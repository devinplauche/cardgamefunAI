import { useCallback, useEffect, useMemo, useState } from 'react';
import type { HistoryFrame, HumanGameState, User } from './types';
import { gameAction, loadGame } from './api';
import {
  BoardColumn,
  HistoryInspector,
  LogList,
  MarketColumn,
  PHASE_COPY,
  Panel,
  Stat,
} from './App';

const POLL_MS = 2500;

interface Props {
  gameId: string;
  user: User;
  onExit: () => void;
}

export function HumanGame({ gameId, user, onExit }: Props) {
  const [game, setGame] = useState<HumanGameState | null>(null);
  const [replayFrame, setReplayFrame] = useState<HistoryFrame | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ tone: string; message: string }>({
    tone: 'idle',
    message: 'Connecting to match…',
  });

  const yourSide = game?.yourSide ?? 'player';
  const opponentName = yourSide === 'player' ? game?.guestName : game?.hostName;
  const waiting = game?.gameStatus === 'waiting';
  const winner = game?.winner ?? null;
  const isMyTurn = !!game && !waiting && !winner && game.activePlayer === yourSide;
  const isReplayMode = replayFrame !== null;
  const canMutate = !!game && !isReplayMode && !busy && !waiting && game.gameStatus === 'playing';

  const displayState = replayFrame?.state ?? game;
  const phase = displayState?.phase ?? 'play';
  const activePlayer = displayState?.activePlayer ?? 'player';

  const phaseLabel = useMemo(() => {
    if (!game) return 'Connecting';
    if (waiting) return 'Waiting for opponent';
    if (winner && !isReplayMode) return 'Match over';
    const who = game.activePlayer === yourSide ? 'Your' : `${opponentName ?? 'Opponent'}'s`;
    return `${who} turn - ${game.phase}`;
  }, [game, waiting, winner, isReplayMode, yourSide, opponentName]);

  const winnerCopy = useMemo(() => {
    if (!winner || winner === 'draw') return winner === 'draw' ? 'The game ended in a draw.' : null;
    return winner === yourSide ? `${user.username} won the match!` : `${opponentName ?? 'Opponent'} won the match.`;
  }, [winner, yourSide, user.username, opponentName]);

  const refreshFrom = useCallback(
    async (work: Promise<HumanGameState>, okMessage?: string): Promise<HumanGameState | null> => {
      setBusy(true);
      try {
        const next = await work;
        setGame(next);
        setReplayFrame(null);
        setStatus({ tone: 'good', message: okMessage ?? 'State updated.' });
        return next;
      } catch (error) {
        setStatus({ tone: 'error', message: error instanceof Error ? error.message : 'Unknown error' });
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  // Initial load.
  useEffect(() => {
    let cancelled = false;
    setStatus({ tone: 'busy', message: 'Connecting to match…' });
    loadGame(gameId)
      .then((res) => {
        if (cancelled || 'changed' in res) return;
        setGame(res as HumanGameState);
        setStatus({ tone: 'good', message: 'Connected.' });
      })
      .catch((error: Error) => {
        if (!cancelled) setStatus({ tone: 'error', message: error.message });
      });
    return () => {
      cancelled = true;
    };
  }, [gameId]);

  // Poll while waiting for the opponent (or for them to join at all).
  useEffect(() => {
    if (!game || winner || (!waiting && isMyTurn)) return;
    const timer = setInterval(async () => {
      try {
        const res = await loadGame(gameId, game.turnCount);
        if ('changed' in res && res.changed === false) return;
        setGame(res as HumanGameState);
      } catch {
        /* transient; next poll retries */
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [gameId, game, winner, waiting, isMyTurn]);

  async function act(action: string, params: Record<string, unknown> = {}, okMessage?: string) {
    if (!canMutate || !game || game.activePlayer !== yourSide) return;
    await refreshFrom(gameAction(gameId, action, params), okMessage);
  }

  async function handlePlay(cardId: string, stunTargetIndex?: number) {
    await act('play-card', { cardId, stunTargetIndex });
  }
  async function handlePlayAll() {
    await act('play-all', {}, 'Straightforward cards played. Optional abilities remain yours to use.');
  }
  async function handleExpend(
    championId: string,
    stunTargetIndex?: number,
    choice?: string,
    sacrificeIndex?: number,
    sacrificeZone?: string,
  ) {
    await act('expend-champion', { championId, stunTargetIndex, choice, sacrificeIndex, sacrificeZone });
  }
  async function handleBuy(index: number) {
    await act('buy-card', { marketIndex: index });
  }
  async function handleSacrifice(cardId: string) {
    await act('sacrifice-played', { cardId });
  }
  async function handleAttack(target: 'player' | 'champion', championId?: string) {
    await act('attack', { target, championId });
  }
  const handleAdvance = () => void act('advance-phase');
  const handleEndTurn = () => void act('end-turn');
  const handleRefresh = () =>
    void refreshFrom(loadGame(gameId).then((res) => {
      if ('changed' in res) throw new Error('Unexpected poll response');
      return res as HumanGameState;
    }), 'Refreshed.');

  const actionLabel = phase === 'combat' || phase === 'main' ? 'End Turn' : 'Next Phase';

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">
            <span className="brand-mark" aria-hidden="true">♜</span> HERO REALMS{' '}
            <span className="lab-badge">VS HUMAN</span>
          </div>
          <h1>{waiting ? 'Waiting for your opponent.' : isMyTurn ? 'Your move.' : `Waiting on ${opponentName ?? 'opponent'}.`}</h1>
        </div>
        <div className="topbar-controls">
          <button className="secondary-button" onClick={onExit}>
            Lobby
          </button>
          <button className="secondary-button" onClick={handleRefresh} disabled={busy}>
            Refresh
          </button>
          <button
            className="primary-button"
            onClick={() => (phase === 'combat' || phase === 'main' ? void handleEndTurn() : void handleAdvance())}
            disabled={!canMutate || busy || winner !== null || !isMyTurn}
          >
            {actionLabel}
          </button>
        </div>
      </header>

      <main className="layout" id="battlefield">
        <div className="arena-heading">
          <span>BATTLEFIELD</span>
          <span>
            {isReplayMode ? 'REPLAY' : 'LIVE MATCH'}
            <i aria-hidden="true" />
            {displayState ? `TURN ${displayState.turnNumber}` : 'CONNECTING'}
          </span>
        </div>

        {winnerCopy ? (
          <section className={`winner-banner ${winner === yourSide ? 'won' : 'lost'}`}>
            <strong>{winnerCopy}</strong>
            <button className="secondary-button" onClick={onExit}>
              Back to Lobby
            </button>
          </section>
        ) : null}

        {waiting && game ? (
          <section className="winner-banner">
            <strong>Share this invite code: {game.inviteCode}</strong>
            <span className="phase-copy">Your opponent joins from the lobby with this code.</span>
          </section>
        ) : null}

        <section className="hero-strip">
          <div role="status" aria-live="polite" className={`status-chip ${status.tone}`}>
            {isReplayMode ? 'Replay mode' : status.message}
          </div>
          <div className="phase-block">
            <span className="phase-label">{phaseLabel}</span>
            <span className="phase-copy">
              {!displayState
                ? 'Connecting to the match.'
                : winner && !isReplayMode
                  ? 'The match is over.'
                  : waiting
                    ? 'The game starts when your opponent joins.'
                    : PHASE_COPY[phase]}
            </span>
          </div>
          <div className="insight">
            <span>Opponent</span>
            <strong>{opponentName ?? '—'}</strong>
          </div>
        </section>

        <div className="board-grid">
          <div className="side-stack">
            {displayState ? (
              <BoardColumn
                title="Your realm"
                player={displayState.player}
                phase={phase}
                activePlayer={activePlayer}
                perspective={yourSide}
                onPlay={handlePlay}
                onPlayAll={handlePlayAll}
                autoPlayCount={displayState.autoPlayCount ?? 0}
                onExpend={handleExpend}
                onSacrifice={handleSacrifice}
                onAttack={handleAttack}
                stunTargets={displayState.bot.board}
                legalActions={displayState.legalActions}
                role="player"
                live={canMutate && !winner}
              />
            ) : null}
          </div>

          <div className="center-stack">
            {displayState ? (
              <>
                <MarketColumn
                  market={displayState.market}
                  phase={phase}
                  canInteract={canMutate && isMyTurn && !winner}
                  playerGold={displayState.player.gold}
                  onBuy={handleBuy}
                />
                <Panel title="Battle notes" subtitle="Match info.">
                  <div className="battle-summary">
                    <Stat label="Turn" value={displayState.turnNumber} />
                    <Stat label="Active" value={isMyTurn ? 'You' : opponentName ?? 'Opponent'} />
                    <Stat label="Winner" value={displayState.winner ?? 'None'} />
                  </div>
                </Panel>
              </>
            ) : null}
          </div>

          <div className="side-stack">
            {displayState ? (
              <BoardColumn
                title={opponentName ?? 'Opponent'}
                player={displayState.bot}
                phase={phase}
                activePlayer={activePlayer}
                perspective={yourSide}
                hiddenHand
                onAttack={handleAttack}
                stunTargets={[]}
                role="bot"
                attackingCombat={displayState.player.combat}
                legalActions={displayState.legalActions}
                live={canMutate && !winner}
              />
            ) : null}

            {displayState ? (
              <Panel className="log-panel" title="Decision log" subtitle="Latest moves from both sides.">
                <LogList entries={displayState.log} />
              </Panel>
            ) : null}

            {game ? (
              <HistoryInspector
                disabled={busy}
                history={game.history ?? []}
                selectedFrame={replayFrame}
                onSelectFrame={setReplayFrame}
                onLive={() => setReplayFrame(null)}
              />
            ) : null}
          </div>
        </div>
      </main>
      <footer className="app-footer">
        <span>HERO REALMS / ML LAB</span>
        <a href="https://www.herorealms.com/card-gallery/" target="_blank" rel="noreferrer">
          Card artwork © Wise Wizard Games
        </a>
      </footer>
    </div>
  );
}
