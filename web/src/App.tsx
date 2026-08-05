import { useEffect, useMemo, useState } from 'react';
import {
  advancePhase,
  attackTarget,
  buyCard,
  createSession,
  endTurn,
  expendChampion,
  loadSession,
  playCard,
  runBotTurn,
} from './api';
import type {
  CardView,
  ChampionView,
  GameState,
  HistoryFrame,
  LogEntry,
  MarketView,
  Phase,
  PlayerView,
} from './types';

type StatusTone = 'idle' | 'busy' | 'error' | 'good';

const PHASE_COPY: Record<Phase, string> = {
  main: 'Play cards, expend champions, buy, and attack - in any order.',
  play: 'Play cards from your hand.',
  champion: 'Expend ready champions.',
  buy: 'Buy cards from the market.',
  combat: 'Assign combat to guards or the opponent.',
};

function formatCardTags(card: CardView): string[] {
  const tags: string[] = [];
  if ((card.effects.gold as number | undefined) ?? 0) tags.push(`+${card.effects.gold as number} Gold`);
  if ((card.effects.combat as number | undefined) ?? 0) tags.push(`+${card.effects.combat as number} Combat`);
  if ((card.effects.draw as number | undefined) ?? 0) tags.push(`Draw ${(card.effects.draw as number)}`);
  if ((card.effects.health as number | undefined) ?? 0) tags.push(`+${card.effects.health as number} HP`);
  if ((card.effects.opponent_discard as number | undefined) ?? 0) tags.push(`Discard ${(card.effects.opponent_discard as number)} Opp`);
  if ((card.effects.stun as boolean | undefined) ?? false) tags.push('Stun');
  if (card.cardType === 'champion') {
    tags.push(`Champion ${card.health}`);
    if (card.guard) tags.push('Guard');
  }
  return tags;
}

function formatCardRules(text: string): string[] {
  return text
    .split(/<hr\s*\/?>/i)
    .map((section) =>
      section
        .trim()
        .split(/\n+/)
        .map((line) => line.replace(/[{}]/g, '').trim())
        .filter(Boolean)
        .join(' ')
    )
    .filter(Boolean);
}

function money(n: number) {
  return n.toLocaleString();
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}

function Panel({ title, subtitle, children, className = '' }: { title: string; subtitle?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-head">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
      </div>
      {children}
    </section>
  );
}

/**
 * The engine now runs a single faithful Main phase in which playing, expending,
 * buying and attacking are all simultaneously legal (see web/session.py:
 * MAIN_PHASE). The legacy fixed phases are still reachable for baseline
 * reproduction, so the UI accepts either: under 'main' everything is enabled,
 * otherwise the old per-phase gating applies.
 */
function phaseAllows(phase: Phase, category: 'play' | 'champion' | 'buy' | 'combat'): boolean {
  return phase === 'main' || phase === category;
}

function CardTile({
  card,
  actionLabel,
  actionDisabled,
  onAction,
}: {
  card: CardView;
  actionLabel: string;
  actionDisabled?: boolean;
  onAction: () => void;
}) {
  return (
    <article className={`card-tile ${card.cardType === 'champion' ? 'champion' : ''}`}>
      <div className="card-topline" />
      <div className="card-main">
        <div className="card-title-row">
          <h3>{card.name}</h3>
          <span className="cost-pill">{card.cost}</span>
        </div>
        <div className="card-meta">
          <span>{card.faction || 'Neutral'}</span>
          <span>{card.cardType}</span>
        </div>
        <div className="tag-row">
          {formatCardTags(card).map((tag) => (
            <span key={tag} className="tag">
              {tag}
            </span>
          ))}
        </div>
        {card.text ? (
          <div className="card-rules">
            {formatCardRules(card.text).map((section, index) => (
              <div key={`${card.id}-rule-${index}`} className="card-rule-section">
                <p>{section}</p>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      <button className="ghost-button" onClick={onAction} disabled={actionDisabled}>
        {actionLabel}
      </button>
    </article>
  );
}

function ChampionRow({
  champion,
  onAction,
  actionLabel,
  disabled,
  quiet = false,
}: {
  champion: ChampionView;
  onAction: () => void;
  actionLabel: string;
  disabled?: boolean;
  quiet?: boolean;
}) {
  return (
    <div className={`champ-row ${quiet ? 'quiet' : ''}`}>
      <div className="champ-copy">
        <div className="champ-name">
          {champion.name}
          {champion.guard ? <span className="tiny-pill">Guard</span> : null}
          {champion.exhausted ? <span className="tiny-pill muted">Spent</span> : <span className="tiny-pill">Ready</span>}
        </div>
        <div className="champ-sub">
          HP {champion.currentHealth}/{champion.health}
        </div>
      </div>
      <button className="ghost-button subtle" onClick={onAction} disabled={disabled}>
        {actionLabel}
      </button>
    </div>
  );
}

function LogList({ entries }: { entries: LogEntry[] }) {
  return (
    <div className="log-list">
      {entries.length === 0 ? <div className="empty-note">No actions yet.</div> : null}
      {entries.slice().reverse().map((entry, index) => (
        <div key={`${entry.at}-${index}`} className={`log-item log-${entry.kind}`}>
          <div className="log-topline">
            <span>{entry.message}</span>
            <span>{entry.phase}</span>
          </div>
          <div className="log-meta">
            Turn {entry.turn} - {entry.activePlayer}
          </div>
          {entry.botInsight?.candidates?.length ? (
            <div className="log-candidates">
              {entry.botInsight.candidates.slice(0, 3).map((candidate, candidateIndex) => (
                <span key={`${entry.at}-${candidateIndex}`} className="log-candidate">
                  {candidate.label ?? candidate.type ?? 'Action'}
                  {typeof candidate.averageScore === 'number' ? ` ${candidate.averageScore.toFixed(2)}` : ''}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function PlayerSummary({ player }: { player: PlayerView }) {
  return (
    <div className="summary-grid">
      <Stat label="HP" value={player.hp} />
      <Stat label="Gold" value={player.gold} />
      <Stat label="Combat" value={player.combat} />
      <Stat label="Deck" value={player.deckCount} />
      <Stat label="Hand" value={player.handCount} />
      <Stat label="Discard" value={player.discardCount} />
    </div>
  );
}

function CandidateList({ candidates }: { candidates: NonNullable<NonNullable<GameState['botInsight']>['candidates']> }) {
  if (!candidates.length) {
    return <div className="empty-note">No ranked candidates recorded.</div>;
  }

  return (
    <div className="candidate-list">
      {candidates.slice(0, 3).map((candidate, index) => (
        <div key={`${candidate.label ?? candidate.type}-${index}`} className="candidate-row">
          <div>
            <div className="candidate-rank">#{index + 1}</div>
            <div className="candidate-label">{candidate.label ?? candidate.type ?? 'Action'}</div>
          </div>
          <div className="candidate-score">
            {typeof candidate.averageScore === 'number'
              ? candidate.averageScore.toFixed(2)
              : typeof candidate.score === 'number'
                ? candidate.score.toFixed(2)
                : '0.00'}
          </div>
        </div>
      ))}
    </div>
  );
}

function HistoryInspector({
  history,
  selectedFrame,
  onSelectFrame,
  onLive,
}: {
  history: HistoryFrame[];
  selectedFrame: HistoryFrame | null;
  onSelectFrame: (frame: HistoryFrame) => void;
  onLive: () => void;
}) {
  return (
    <Panel title="Move history" subtitle="Pick any frame to inspect the board at that moment.">
      <div className="history-toolbar">
        <button className="secondary-button" onClick={onLive} disabled={!selectedFrame}>
          Back to Live
        </button>
        <span className="history-count">{history.length} frames</span>
      </div>
      <div className="history-list">
        {history.slice().reverse().map((frame) => (
          <button
            key={frame.id}
            className={`history-item ${selectedFrame?.id === frame.id ? 'selected' : ''}`}
            onClick={() => onSelectFrame(frame)}
          >
            <div className="history-item-top">
              <strong>{frame.label}</strong>
              <span>{frame.kind}</span>
            </div>
            <div className="history-item-meta">
              Turn {frame.turn} - {frame.phase} - {frame.activePlayer}
            </div>
          </button>
        ))}
      </div>
      {selectedFrame ? (
        <div className="history-detail">
          <div className="history-detail-title">Replay snapshot</div>
          <div className="history-detail-meta">
            Turn {selectedFrame.turn} - {selectedFrame.phase} - {selectedFrame.activePlayer}
          </div>
          {selectedFrame.botInsight?.candidates?.length ? (
            <div className="history-detail-candidates">
              <div className="subsection-head compact">
                <h3>Top candidates</h3>
              </div>
              <CandidateList candidates={selectedFrame.botInsight.candidates} />
            </div>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}

function MarketColumn({
  market,
  phase,
  canInteract,
  playerGold,
  onBuy,
}: {
  market: MarketView;
  phase: Phase;
  canInteract: boolean;
  playerGold: number;
  onBuy: (marketIndex: number) => Promise<void>;
}) {
  return (
    <Panel title="Market" subtitle="Buy any card you can afford, any time during your turn.">
      <div className="market-grid">
        {market.row.map((card, index) => {
          if (!card) {
            return (
              <div key={`empty-${index}`} className="card-tile empty">
                <div className="empty-note">Empty</div>
              </div>
            );
          }

          return (
            <CardTile
              key={`${card.id}-${index}`}
              card={card}
              actionLabel="Buy"
              actionDisabled={!phaseAllows(phase, 'buy') || !canInteract || card.cost > playerGold}
              onAction={() => void onBuy(index)}
            />
          );
        })}
        {/*
          Fire Gem is marketIndex 5 in the engine but is NOT part of
          market.row, which only ever holds the 5 visible slots (0-4). The old
          `index === 5 ? 'Buy Fire Gem'` branch above could therefore never
          fire, and the human had no way to buy a Fire Gem at all - while the
          bot buys ~2.9 per game through the engine API. Rendered explicitly as
          a sixth tile.
        */}
        {market.fireGemsRemaining > 0 ? (
          <CardTile
            key="fire-gem"
            card={{
              id: 'fire_gem',
              name: 'Fire Gem',
              cost: 2,
              faction: '',
              cardType: 'item',
              guard: 0,
              health: 0,
              effects: {},
              text: 'Gain 2 gold. Sacrifice this card: gain 3 combat.',
            }}
            actionLabel="Buy Fire Gem"
            actionDisabled={!phaseAllows(phase, 'buy') || !canInteract || 2 > playerGold}
            onAction={() => void onBuy(5)}
          />
        ) : null}
      </div>
      <div className="market-foot">
        Fire Gems remaining: <strong>{market.fireGemsRemaining}</strong>
      </div>
    </Panel>
  );
}

function BoardColumn({
  title,
  player,
  phase,
  activePlayer,
  onPlay,
  onExpend,
  onAttack,
  stunTargets,
  hiddenHand = false,
  role,
}: {
  title: string;
  player: PlayerView;
  phase: Phase;
  activePlayer: 'player' | 'bot';
  onPlay?: (cardId: string, stunTargetIndex?: number) => Promise<void>;
  onExpend?: (championId: string, stunTargetIndex?: number) => Promise<void>;
  onAttack?: (target: 'player' | 'champion', championId?: string) => Promise<void>;
  stunTargets: ChampionView[];
  hiddenHand?: boolean;
  role: 'player' | 'bot';
}) {
  const isHumanTurn = activePlayer === 'player';
  const canInteract = isHumanTurn;
  const chooseStunTarget = (card: CardView): number | null | undefined => {
    if (!card.effects.stun || stunTargets.length === 0) return undefined;
    const guards = stunTargets.filter((champion) => champion.guard > 0);
    const candidates = guards.length > 0 ? guards : stunTargets;
    const options = candidates.map((champion, index) => `${index + 1}: ${champion.name}`).join('\n');
    const answer = window.prompt(`Choose a champion to stun${guards.length ? ' (a guard must be chosen)' : ''}:\n${options}`, '1');
    if (answer === null) return null;
    const choice = Number.parseInt(answer, 10) - 1;
    if (!Number.isInteger(choice) || choice < 0 || choice >= candidates.length) {
      window.alert('Choose one of the listed champions.');
      return null;
    }
    return choice;
  };

  return (
    <Panel title={title} subtitle={hiddenHand ? 'Hand hidden, board visible.' : 'Your cards and board.'}>
      <PlayerSummary player={player} />
      <div className="subsection">
        <div className="subsection-head">
          <h3>Champions</h3>
        </div>
        <div className="stack">
          {player.board.length === 0 ? <div className="empty-note">No champions in play.</div> : null}
          {player.board.map((champion, index) => (
            <ChampionRow
              key={`${champion.id}-${index}`}
              champion={champion}
              actionLabel={
                role === 'player'
                  ? phaseAllows(phase, 'champion') && canInteract && onExpend
                    ? 'Expend'
                    : 'Locked'
                  : phaseAllows(phase, 'combat') && canInteract && onAttack
                    ? 'Attack'
                    : 'Locked'
              }
              disabled={
                role === 'player'
                  ? !phaseAllows(phase, 'champion') || !canInteract || champion.exhausted || !onExpend
                  : !phaseAllows(phase, 'combat') || !canInteract || !onAttack
              }
              onAction={() => {
                // instanceId, not id: the engine matches board champions on
                // instance_id, and two copies of one card can share an id.
                if (role === 'player') {
                  const targetIndex = chooseStunTarget(champion);
                  if (targetIndex !== null && onExpend) void onExpend(champion.instanceId, targetIndex);
                } else if (onAttack) {
                  void onAttack('champion', champion.instanceId);
                }
              }}
              quiet={hiddenHand}
            />
          ))}
        </div>
      </div>
      <div className="subsection">
        <div className="subsection-head">
          <h3>{hiddenHand ? 'Hidden hand' : 'Hand'}</h3>
        </div>
        <div className="stack">
          {hiddenHand ? (
            <div className="hand-backs">
              {Array.from({ length: player.handCount }).map((_, index) => (
                <div key={index} className="card-back" />
              ))}
            </div>
          ) : player.hand.length === 0 ? (
            <div className="empty-note">No cards in hand.</div>
          ) : (
            player.hand.map((card, index) => (
              <CardTile
                key={`${card.id}-${index}`}
                card={card}
                actionLabel={phaseAllows(phase, 'play') && canInteract && onPlay ? 'Play' : 'Locked'}
                actionDisabled={!phaseAllows(phase, 'play') || !canInteract || !onPlay}
                onAction={() => {
                  const targetIndex = chooseStunTarget(card);
                  if (targetIndex !== null && onPlay) void onPlay(card.id, targetIndex);
                }}
              />
            ))
          )}
        </div>
      </div>
      {phaseAllows(phase, 'combat') && canInteract && onAttack && role === 'player' ? (
        <div className="subsection">
          <div className="subsection-head">
            <h3>Combat</h3>
          </div>
          <button
            className="primary-button"
            onClick={() => void onAttack('player')}
            disabled={player.combat <= 0}
          >
            Attack Face
          </button>
        </div>
      ) : null}
    </Panel>
  );
}

function App() {
  const [session, setSession] = useState<GameState | null>(null);
  const [replayFrame, setReplayFrame] = useState<HistoryFrame | null>(null);
  const [seedText, setSeedText] = useState('7');
  const [algorithm, setAlgorithm] = useState('mcts');
  const [budgetMs, setBudgetMs] = useState(60);
  const [status, setStatus] = useState<{ tone: StatusTone; message: string }>({
    tone: 'idle',
    message: 'Ready to start a match.',
  });
  const [busy, setBusy] = useState(false);

  const displayState = replayFrame?.state ?? session;
  const phase = displayState?.phase ?? 'play';
  const activePlayer = displayState?.activePlayer ?? 'player';
  const isBotTurn = activePlayer === 'bot';
  const isReplayMode = replayFrame !== null;
  const canMutate = !!session && !isReplayMode;

  const phaseLabel = useMemo(() => {
    if (!displayState) return 'Waiting for match';
    return `${displayState.activePlayer === 'player' ? 'Your' : 'Bot'} turn - ${displayState.phase}`;
  }, [displayState]);

  async function refreshFrom<T>(work: Promise<T>) {
    setBusy(true);
    try {
      const next = await work;
      setSession(next as GameState);
      setStatus({ tone: 'good', message: 'State updated.' });
      return next as GameState;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      setStatus({ tone: 'error', message });
      throw error;
    } finally {
      setBusy(false);
    }
  }

  async function startNewMatch() {
    const parsedSeed = Number.parseInt(seedText, 10);
    const seed = Number.isFinite(parsedSeed) ? parsedSeed : 7;
    setReplayFrame(null);
    const next = await refreshFrom(createSession({ seed, algorithm, budgetMs }));
    setStatus({ tone: 'good', message: `Match started with seed ${seed}.` });
    return next;
  }

  async function handlePlay(cardId: string, stunTargetIndex?: number) {
    if (!session || isReplayMode) return;
    await refreshFrom(playCard(session.sessionId, cardId, stunTargetIndex));
  }

  async function handleExpend(championId: string, stunTargetIndex?: number) {
    if (!session || isReplayMode) return;
    await refreshFrom(expendChampion(session.sessionId, championId, stunTargetIndex));
  }

  async function handleBuy(index: number) {
    if (!session || isReplayMode) return;
    await refreshFrom(buyCard(session.sessionId, index));
  }

  async function handleAttack(target: 'player' | 'champion', championId?: string) {
    if (!session || isReplayMode) return;
    await refreshFrom(attackTarget(session.sessionId, target, championId));
  }

  async function handleAdvance() {
    if (!session || isReplayMode) return;
    await refreshFrom(phase === 'combat' ? endTurn(session.sessionId) : advancePhase(session.sessionId));
  }

  async function handleBotTurn() {
    if (!session || isReplayMode) return;
    const next = await refreshFrom(runBotTurn(session.sessionId, algorithm, budgetMs));
    setStatus({ tone: 'good', message: `Bot turn complete in ${next.botInsight?.elapsedMs ?? 0} ms.` });
  }

  async function handleRefresh() {
    if (!session) return;
    setReplayFrame(null);
    await refreshFrom(loadSession(session.sessionId));
  }

  useEffect(() => {
    if (session || busy) return;
    void startNewMatch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!session || busy || !isBotTurn || session.winner || isReplayMode) return;
    const timer = window.setTimeout(() => {
      void handleBotTurn();
    }, 350);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.sessionId, session?.activePlayer, session?.phase, busy, isReplayMode]);

  // Under the main phase, advancing IS ending the turn.
  const actionLabel = (phase === 'combat' || phase === 'main') ? 'End Turn' : 'Next Phase';

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">Hero Realms ML Lab</div>
          <h1>Browser-based bot testing with a clean, readable battlefield.</h1>
          <p>Play manually, let the model choose its turn, and inspect each move as it happens.</p>
        </div>
        <div className="topbar-controls">
          <label className="field">
            <span>Seed</span>
            <input value={seedText} onChange={(event) => setSeedText(event.target.value)} inputMode="numeric" />
          </label>
          <label className="field">
            <span>Algorithm</span>
            <select value={algorithm} onChange={(event) => setAlgorithm(event.target.value)}>
              <option value="mcts">MCTS</option>
              <option value="heuristic">Heuristic</option>
            </select>
          </label>
          <label className="field compact">
            <span>Budget</span>
            <input value={budgetMs} onChange={(event) => setBudgetMs(Number(event.target.value || 0))} inputMode="numeric" />
          </label>
          <button className="secondary-button" onClick={() => void startNewMatch()} disabled={busy}>
            New Game
          </button>
          <button className="primary-button" onClick={() => void handleAdvance()} disabled={!canMutate || busy || displayState?.winner !== null || isBotTurn}>
            {actionLabel}
          </button>
        </div>
      </header>

      <main className="layout">
        <section className="hero-strip">
          <div className={`status-chip ${status.tone}`}>{isReplayMode ? 'Replay mode' : status.message}</div>
          <div className="phase-block">
            <span className="phase-label">{phaseLabel}</span>
            <span className="phase-copy">{displayState ? PHASE_COPY[phase] : 'Create a match to begin.'}</span>
          </div>
          <div className="insight">
            <span>Bot insight</span>
            <strong>
              {displayState?.botInsight
                ? `${displayState.botInsight.algorithm} - ${displayState.botInsight.iterations ?? 0} rollouts - ${displayState.botInsight.elapsedMs ?? 0} ms`
                : 'No decision yet'}
            </strong>
            {displayState?.botInsight?.candidates?.length ? <CandidateList candidates={displayState.botInsight.candidates} /> : null}
          </div>
        </section>

        <div className="board-grid">
          <div className="side-stack">
            {displayState ? (
              <BoardColumn
                title="You"
                player={displayState.player}
                phase={phase}
                activePlayer={activePlayer}
                onPlay={handlePlay}
                onExpend={handleExpend}
                onAttack={handleAttack}
                stunTargets={displayState.bot.board}
                role="player"
              />
            ) : null}
          </div>

          <div className="center-stack">
            {displayState ? (
              <>
                <MarketColumn
                  market={displayState.market}
                  phase={phase}
                  canInteract={canMutate && activePlayer === 'player'}
                  playerGold={displayState.player.gold}
                  onBuy={handleBuy}
                />
                <Panel title="Battle notes" subtitle="Recent actions and search results.">
                  <div className="battle-summary">
                    <Stat label="Turn" value={displayState.turnNumber} />
                    <Stat label="Active" value={displayState.activePlayer} />
                    <Stat label="Winner" value={displayState.winner ?? 'None'} />
                  </div>
                  <div className="bot-actions">
                    <button className="secondary-button" onClick={() => void handleBotTurn()} disabled={!canMutate || !isBotTurn || busy || displayState.winner !== null}>
                      Run Bot Turn
                    </button>
                    <button className="secondary-button" onClick={() => void handleRefresh()} disabled={!session || busy}>
                      Refresh
                    </button>
                  </div>
                </Panel>
              </>
            ) : null}
          </div>

          <div className="side-stack">
            {displayState ? (
              <BoardColumn
                title="Bot"
                player={displayState.bot}
                phase={phase}
                activePlayer={activePlayer}
                hiddenHand
                onAttack={handleAttack}
                stunTargets={[]}
                role="bot"
              />
            ) : null}

            {displayState ? (
              <Panel title="Decision log" subtitle="Latest moves from both sides.">
                <LogList entries={displayState.log} />
              </Panel>
            ) : null}

            {session ? (
              <HistoryInspector
                history={session.history ?? []}
                selectedFrame={replayFrame}
                onSelectFrame={setReplayFrame}
                onLive={() => setReplayFrame(null)}
              />
            ) : null}
          </div>
        </div>

        {displayState?.winner ? (
          <section className="winner-banner">
            {displayState.winner === 'draw' ? 'The game ended in a draw.' : `${displayState.winner === 'player' ? 'You' : 'Bot'} won the match.`}
          </section>
        ) : null}
      </main>
    </div>
  );
}

export default App;
