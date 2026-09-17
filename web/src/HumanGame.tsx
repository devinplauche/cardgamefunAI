import { useCallback, useEffect, useMemo, useState } from 'react';
import type { HistoryFrame, HumanGameState, User } from './types';
import { gameAction, loadGame } from './api';
import { GameTable } from './GameTable';

const POLL_MS = 2500;

interface Props {
  gameId: string;
  user: User;
  onExit: () => void;
  onSignOut: () => void;
}

export function HumanGame({ gameId, user, onExit, onSignOut }: Props) {
  const [game, setGame] = useState<HumanGameState | null>(null);
  const [replayFrame, setReplayFrame] = useState<HistoryFrame | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ tone: string; message: string }>({
    tone: 'idle',
    message: 'Connecting to match…',
  });

  const yourSide = game?.yourSide ?? 'player';
  const opponentName = yourSide === 'player' ? game?.guestName : game?.hostName;
  // The engine keys the guest off the "bot" seat; show real names instead.
  const seatNames = useMemo(
    () => ({
      player: game?.hostName ?? 'Host',
      bot: game?.guestName ?? 'Guest',
    }),
    [game?.hostName, game?.guestName],
  );
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

  // Poll while waiting for the opponent (or for them to join at all) - and
  // while waiting for them to answer a forced discard on your turn, so the
  // board refreshes the moment they choose.
  useEffect(() => {
    if (!game || winner || (!waiting && isMyTurn && !game.choicePending)) return;
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
    if (!canMutate || !game) return;
    // A forced discard is answered out of turn, from the victim's seat; the
    // server only accepts resolve-choice for the choice's owner.
    if (action !== 'resolve-choice' && game.activePlayer !== yourSide) return;
    await refreshFrom(gameAction(gameId, action, params), okMessage);
  }

  async function handlePlay(cardId: string, stunTargetIndex?: number) {
    await act('play-card', { cardId, stunTargetIndex });
  }
  async function handlePlayAll() {
    await act('play-all', {}, 'Straightforward cards played. Optional abilities remain yours to use.');
  }
  async function handleTriggerAlly(cardId: string, stunTargetIndex?: number) {
    await act('trigger-ally', { cardId, stunTargetIndex });
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
  async function handleResolveChoice(candidateIndex: number) {
    await act('resolve-choice', { candidateIndex });
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
    <div className="game-table-loading">
      {displayState && game ? (
        <GameTable
          game={game}
          state={displayState}
          yourSide={yourSide}
          opponentName={opponentName ?? 'Opponent'}
          seatNames={seatNames}
          isMyTurn={isMyTurn}
          canMutate={canMutate}
          busy={busy}
          waiting={waiting}
          winner={winner}
          winnerCopy={winnerCopy}
          isReplayMode={isReplayMode}
          phase={phase}
          phaseLabel={phaseLabel}
          status={status}
          actionLabel={actionLabel}
          autoPlayCount={displayState.autoPlayCount ?? 0}
          replayFrame={replayFrame}
          onSelectFrame={setReplayFrame}
          onLive={() => setReplayFrame(null)}
          onPlay={handlePlay}
          onPlayAll={handlePlayAll}
          onTriggerAlly={handleTriggerAlly}
          onExpend={handleExpend}
          onSacrifice={handleSacrifice}
          onBuy={handleBuy}
          onAttack={handleAttack}
          onResolveChoice={handleResolveChoice}
          onEndTurn={handleEndTurn}
          onAdvance={handleAdvance}
          onExit={onExit}
          onRefresh={handleRefresh}
          onSignOut={onSignOut}
        />
      ) : (
        <div className="center-overlay">
          <div className="overlay-card">
            <h3>{status.message}</h3>
          </div>
        </div>
      )}
    </div>
  );
}
