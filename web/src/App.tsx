import { BotActionBanner } from './BotActionBanner';
import { AuthScreen } from './AuthScreen';
import { Lobby } from './Lobby';
import { HumanGame } from './HumanGame';
import { GameTable } from './GameTable';
import { logout, me } from './auth';
import { useBotPlayback } from './useBotPlayback';
import { BotStreamError } from './botStream';
import { CardArtwork } from './CardArtwork';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  advancePhase,
  attackTarget,
  buyCard,
  createSession,
  endTurn,
  expendChampion,
  loadSession,
  playCard,
  playAll,
  sacrificePlayed,
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
  LegalAction,
  User,
} from './types';

export type StatusTone = 'idle' | 'busy' | 'error' | 'good';

export const PHASE_COPY: Record<Phase, string> = {
  main: 'Play cards, expend champions, buy, and attack - in any order.',
  play: 'Play cards from your hand.',
  champion: 'Expend ready champions.',
  buy: 'Buy cards from the market.',
  combat: 'Assign combat to guards or the opponent.',
};

export function formatCardTags(card: CardView): string[] {
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

/**
 * Card text in data/hero_realms_cards.json carries three kinds of markup:
 * `{...}` around game terms, `<hr>` between the base ability and the ally
 * ability, and inline emphasis such as `<i>or</i>`. Only the first two were
 * handled, so Cult Priest read literally as
 * "Expend: Gain 1 gold <i>or</i> Gain 1 combat" on its face. `<hr>` stays the
 * section split; every other tag is dropped and the words around it kept.
 */
export function formatCardRules(text: string): string[] {
  return text
    .split(/<hr\s*\/?>/i)
    .map((section) =>
      section
        .trim()
        .split(/(?:\n|<br\s*\/?>)+/i)
        .map((line) =>
          line
            .replace(/<[^>]*>/g, '')
            .replace(/[{}]/g, '')
            .replace(/\s+/g, ' ')
            .trim(),
        )
        .filter(Boolean)
        .join(' ')
    )
    .filter(Boolean);
}

function money(n: number) {
  return n.toLocaleString();
}

export function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value" key={value}>{value}</div>
    </div>
  );
}

export function Panel({ title, subtitle, children, className = '' }: { title: string; subtitle?: string; children: React.ReactNode; className?: string }) {
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
export function phaseAllows(phase: Phase, category: 'play' | 'champion' | 'buy' | 'combat'): boolean {
  return phase === 'main' || phase === category;
}

/**
 * Branches of an "Expend: gain 1 gold *or* gain 1 combat" card. The rules make
 * this the player's call, so each branch gets its own button; the engine's
 * heuristic only decides when no choice is supplied (i.e. for the bot).
 */
export const OR_CHOICE_LABEL: Record<string, string> = {
  combat: 'combat',
  gold: 'gold',
  health: 'heal',
  per_champion_health: 'heal/champ',
};

export function orChoiceBranches(card: CardView): string[] {
  const branches = (card.effects.or_choice as string[] | undefined) ?? [];
  return branches.filter((kind) => ((card.effects[kind] as number | undefined) ?? 0) > 0);
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
      <div className="card-topline"><span aria-hidden="true">{card.cardType === 'champion' ? '♜' : '✦'}</span><span>{card.cardType === 'champion' ? 'Champion' : 'Action & item'}</span></div>
      <CardArtwork card={card} />
      <div className="card-main">
        <div className="card-title-row">
          <h3>{card.name}</h3>
          <span className="cost-pill" aria-label={`${card.cost} gold cost`}>{card.cost}</span>
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

type ChampionAction = {
  key: string;
  label: string;
  onAction: () => void;
  disabled?: boolean;
};

/**
 * One row per champion on the board, however many things it can do.
 *
 * This used to take a single label/handler, so a champion offering more than
 * one option was rendered by repeating the whole row - an "Expend: gain 1 gold
 * *or* 1 combat" card such as Cult Priest appeared as two champions, each with
 * its own name, Ready badge and HP readout, which reads as 8 health of
 * blockers where there are 4. Lys had the same problem once its per-victim
 * sacrifice actions appeared. The identity of the champion is now rendered
 * once and every action hangs off it.
 */
function ChampionRow({
  champion,
  actions,
  quiet = false,
}: {
  champion: ChampionView;
  actions: ChampionAction[];
  quiet?: boolean;
}) {
  return (
    <div className={`champ-row ${quiet ? 'quiet' : ''}`}>
      <CardArtwork card={champion} compact />
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
      <div className="champ-actions">
        {actions.map((action) => (
          <button
            key={action.key}
            className="ghost-button subtle"
            onClick={action.onAction}
            disabled={action.disabled}
          >
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function LogList({ entries, seatNames }: { entries: LogEntry[]; seatNames?: Record<string, string> }) {
  const seatLabel = (seat: string) => seatNames?.[seat] ?? seat;
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
            Turn {entry.turn} - {seatLabel(entry.activePlayer)}
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

export function PlayerSummary({ player }: { player: PlayerView }) {
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

export function CandidateList({ candidates }: { candidates: NonNullable<NonNullable<GameState['botInsight']>['candidates']> }) {
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

export function HistoryInspector({
  history,
  selectedFrame,
  onSelectFrame,
  onLive,
  disabled = false,
  seatNames,
}: {
  history: HistoryFrame[];
  selectedFrame: HistoryFrame | null;
  onSelectFrame: (frame: HistoryFrame) => void;
  onLive: () => void;
  disabled?: boolean;
  seatNames?: Record<string, string>;
}) {
  const seatLabel = (seat: string) => seatNames?.[seat] ?? seat;
  return (
    <Panel className="history-panel" title="Move history" subtitle="Pick any frame to inspect the board at that moment.">
      <div className="history-toolbar">
        <button className="secondary-button" onClick={onLive} disabled={disabled || !selectedFrame}>
          Back to Live
        </button>
        <span className="history-count">{history.length} frames</span>
      </div>
      <div className="history-list">
        {history.slice().reverse().map((frame) => (
          <button
            key={frame.id}
            disabled={disabled}
            className={`history-item ${selectedFrame?.id === frame.id ? 'selected' : ''}`}
            onClick={() => onSelectFrame(frame)}
          >
            <div className="history-item-top">
              <strong>{frame.label}</strong>
              <span>{frame.kind}</span>
            </div>
            <div className="history-item-meta">
              Turn {frame.turn} - {frame.phase} - {seatLabel(frame.activePlayer)}
            </div>
          </button>
        ))}
      </div>
      {selectedFrame ? (
        <div className="history-detail">
          <div className="history-detail-title">Replay snapshot</div>
          <div className="history-detail-meta">
            Turn {selectedFrame.turn} - {selectedFrame.phase} - {seatLabel(selectedFrame.activePlayer)}
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

export function MarketColumn({
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

export function BoardColumn({
  title,
  player,
  phase,
  activePlayer,
  onPlay,
  onPlayAll,
  autoPlayCount = 0,
  onExpend,
  onSacrifice,
  onAttack,
  stunTargets,
  hiddenHand = false,
  role,
  perspective = 'player',
  attackingCombat,
  legalActions = [],
  live,
}: {
  title: string;
  player: PlayerView;
  phase: Phase;
  activePlayer: 'player' | 'bot';
  legalActions?: LegalAction[];
  /** False while inspecting a history frame, which must never mutate the game. */
  live: boolean;
  onPlayAll?: () => void;
  autoPlayCount?: number;
  onPlay?: (cardId: string, stunTargetIndex?: number) => Promise<void>;
  onExpend?: (
    championId: string,
    stunTargetIndex?: number,
    choice?: string,
    sacrificeIndex?: number,
    sacrificeZone?: string,
  ) => Promise<void>;
  onSacrifice?: (cardId: string) => Promise<void>;
  onAttack?: (target: 'player' | 'champion', championId?: string) => Promise<void>;
  stunTargets: ChampionView[];
  hiddenHand?: boolean;
  role: 'player' | 'bot';
  /** Which engine side the interacting human sits on; defaults to 'player'. */
  perspective?: 'player' | 'bot';
  attackingCombat?: number;
}) {
  const isHumanTurn = activePlayer === perspective;
  const canInteract = isHumanTurn && live;
  const combatAvailable = role === 'bot' ? attackingCombat ?? 0 : player.combat;
  const legalAttackTargets = role === 'bot'
    ? (() => {
        const living = player.board.filter((champion) => champion.alive && champion.currentHealth > 0);
        const guards = living.filter((champion) => champion.guard > 0);
        return guards.length > 0 ? guards : living;
      })()
    : [];
  const legalAttackIds = new Set(legalAttackTargets.map((champion) => champion.instanceId));
  // Whether the face is a legal target, taken from the server's own list
  // rather than re-derived here. Guards must be destroyed before the player
  // can be hit, and this button used to be gated on nothing but "do I have
  // combat", so it happily offered a move the engine answered with a 400.
  const faceAttackLegal = legalActions.some(
    (action) => action.type === 'attack_target' && action.target === 'player',
  );
  const guardsBlocking = !faceAttackLegal && combatAvailable > 0;
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
    <Panel className={`player-panel ${role}`} title={title} subtitle={hiddenHand ? 'Your opponent · hand concealed' : 'Your side of the battlefield'}>
      <PlayerSummary player={player} />
      <div className="subsection">
        <div className="subsection-head">
          <h3>Champions</h3>
        </div>
        <div className="stack">
          {player.board.length === 0 ? <div className="empty-note">No champions in play.</div> : null}
          {player.board.map((champion, index) => {
            const actions: ChampionAction[] = [];

            if (role === 'player') {
              const canExpend = phaseAllows(phase, 'champion') && canInteract && !!onExpend;
              // An "expend: X *or* Y" card gets one button per branch, on this
              // same row - the rules make the branch the player's call.
              const branches = orChoiceBranches(champion);
              if (branches.length > 1 && canExpend) {
                for (const kind of branches) {
                  actions.push({
                    key: `${champion.instanceId}-${kind}`,
                    label: `Expend: ${OR_CHOICE_LABEL[kind] ?? kind}`,
                    disabled: champion.exhausted,
                    onAction: () => void onExpend?.(champion.instanceId, undefined, kind),
                  });
                }
              } else {
                actions.push({
                  key: `${champion.instanceId}-expend`,
                  label: canExpend ? 'Expend' : 'Locked',
                  disabled: !canExpend || champion.exhausted,
                  onAction: () => {
                    // instanceId, not id: the engine matches board champions on
                    // instance_id, and two copies of one card can share an id.
                    const targetIndex = chooseStunTarget(champion);
                    if (targetIndex !== null && onExpend) void onExpend(champion.instanceId, targetIndex);
                  },
                });
              }

              // Sacrifice-on-expend ("you may sacrifice a card... gain 2 more
              // combat") is rendered straight from the server's legal actions
              // rather than re-derived from the card here. Every affordance this
              // panel builds from its own card model is one the engine can add
              // without the UI ever showing it - which is how Lys came to eat a
              // card from hand with no prompt and no log line.
              if (canExpend) {
                for (const action of legalActions) {
                  if (
                    action.type !== 'expend_champion' ||
                    action.championId !== champion.instanceId ||
                    action.sacrificeIndex === undefined ||
                    action.sacrificeIndex === null
                  ) {
                    continue;
                  }
                  actions.push({
                    key: `${champion.instanceId}-sac-${action.sacrificeZone}-${action.sacrificeIndex}`,
                    label: action.label,
                    disabled: champion.exhausted,
                    onAction: () =>
                      void onExpend?.(
                        champion.instanceId,
                        undefined,
                        undefined,
                        action.sacrificeIndex ?? undefined,
                        action.sacrificeZone ?? 'hand',
                      ),
                  });
                }
              }
            } else {
              const canAttack =
                phaseAllows(phase, 'combat') &&
                canInteract &&
                !!onAttack &&
                combatAvailable > 0 &&
                legalAttackIds.has(champion.instanceId);
              actions.push({
                key: `${champion.instanceId}-attack`,
                label: canAttack ? 'Attack' : 'Locked',
                disabled: !canAttack,
                onAction: () => void onAttack?.('champion', champion.instanceId),
              });
            }

            return (
              <ChampionRow
                key={`${champion.instanceId}-${index}`}
                champion={champion}
                actions={actions}
                quiet={hiddenHand}
              />
            );
          })}
        </div>
      </div>
      {player.playedThisTurn.some((card) => ((card.effects.sacrifice_combat as number | undefined) ?? 0) > 0) ? (
        <div className="subsection">
          <div className="subsection-head">
            <h3>In play · optional abilities</h3>
          </div>
          <div className="stack">
            {player.playedThisTurn
              .map((card, index) => ({ card, index }))
              .filter(({ card }) => ((card.effects.sacrifice_combat as number | undefined) ?? 0) > 0)
              .map(({ card, index }) => (
                <div key={`${card.id}-played-${index}`} className="champ-row">
                  <CardArtwork card={card} compact />
                  <div className="champ-copy">
                    <div className="champ-name">{card.name}</div>
                    <div className="champ-sub">
                      Sacrifice: +{card.effects.sacrifice_combat as number} combat
                    </div>
                  </div>
                  <button
                    className="ghost-button subtle"
                    disabled={!canInteract || !onSacrifice || !legalActions.some((action) => action.type === 'sacrifice_played' && action.cardId === card.id)}
                    onClick={() => onSacrifice && void onSacrifice(card.id)}
                  >
                    Sacrifice · +{card.effects.sacrifice_combat as number} combat
                  </button>
                </div>
              ))}
          </div>
        </div>
      ) : null}
      <div className="subsection">
        <div className="subsection-head">
          <h3>{hiddenHand ? 'Hidden hand' : 'Hand'}</h3>
          {!hiddenHand && onPlayAll ? (
            <button className="secondary-button" onClick={onPlayAll}
              disabled={!canInteract || !phaseAllows(phase, 'play') || autoPlayCount === 0}
              title="Play straightforward cards. Draw, targeting, and choice effects stay in hand.">
              Play all{autoPlayCount > 0 ? ` (${autoPlayCount})` : ''}
            </button>
          ) : null}
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
            disabled={player.combat <= 0 || !faceAttackLegal}
            title={guardsBlocking ? 'Guards must be destroyed before the opponent can be attacked.' : undefined}
          >
            Attack Face
          </button>
          {guardsBlocking ? (
            <div className="empty-note subtle-note">
              A guard is blocking - attack it first.
            </div>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}

function BotGame({ onExit, onSignOut }: { onExit: () => void; onSignOut: () => void }) {
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
  const playback = useBotPlayback();
  const attemptedBotTurn = useRef<string | null>(null);

  const displayState = playback.action?.frame.state ?? replayFrame?.state ?? session;
  const phase = displayState?.phase ?? 'play';
  const activePlayer = displayState?.activePlayer ?? 'player';
  const isBotTurn = activePlayer === 'bot';
  const isReplayMode = replayFrame !== null;
  const canMutate = !!session && !isReplayMode && !busy && !playback.running;

  // The live game's outcome, which is what "the match is over" means even
  // while a history frame from the middle of the game is on screen.
  const winner = session?.winner ?? null;
  const winnerCopy = winner
    ? winner === 'draw'
      ? 'The game ended in a draw.'
      : `${winner === 'player' ? 'You' : 'Bot'} won the match.`
    : null;

  const phaseLabel = useMemo(() => {
    if (!displayState) return 'Waiting for match';
    if (winner && !isReplayMode) return 'Match over';
    return `${displayState.activePlayer === 'player' ? 'Your' : 'Bot'} turn - ${displayState.phase}`;
  }, [displayState, winner, isReplayMode]);

  /**
   * Runs a mutation and folds the result into state, returning null if the
   * server refused it.
   *
   * It used to re-throw after setting the error status. Every caller is
   * invoked as `void handler(...)` with no `.catch`, so a refusal the UI had
   * already handled and displayed - "Guards must be attacked before the
   * player", say - still surfaced as an `Uncaught (in promise)` and tripped
   * any error reporter or break-on-exception watching the page. The status
   * chip is the report; there is no second consumer to re-throw for.
   */
  async function refreshFrom<T>(work: Promise<T>): Promise<GameState | null> {
    setBusy(true);
    try {
      const next = await work;
      setSession(next as GameState);
      setStatus({ tone: 'good', message: 'State updated.' });
      return next as GameState;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      setStatus({ tone: 'error', message });
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function startNewMatch() {
    const parsedSeed = Number.parseInt(seedText, 10);
    const seed = Number.isFinite(parsedSeed) ? parsedSeed : 7;
    setReplayFrame(null);
    const next = await refreshFrom(createSession({ seed, algorithm, budgetMs }));
    if (next) setStatus({ tone: 'good', message: `Match started with seed ${seed}.` });
    return next;
  }

  async function handlePlayAll() {
    if (!canMutate || !session || session.activePlayer !== 'player') return;
    const next = await refreshFrom(playAll(session.sessionId));
    if (next) setStatus({ tone: 'good', message: 'Straightforward cards played. Optional abilities remain yours to use.' });
  }

  async function handlePlay(cardId: string, stunTargetIndex?: number) {
    if (!canMutate || !session) return;
    await refreshFrom(playCard(session.sessionId, cardId, stunTargetIndex));
  }

  async function handleExpend(
    championId: string,
    stunTargetIndex?: number,
    choice?: string,
    sacrificeIndex?: number,
    sacrificeZone?: string,
  ) {
    if (!canMutate || !session) return;
    await refreshFrom(
      expendChampion(session.sessionId, championId, stunTargetIndex, choice, sacrificeIndex, sacrificeZone),
    );
  }

  async function handleBuy(index: number) {
    if (!canMutate || !session) return;
    await refreshFrom(buyCard(session.sessionId, index));
  }

  async function handleSacrifice(cardId: string) {
    // isReplayMode, like every other mutating handler: without it, clicking
    // Sacrifice while inspecting a history frame banished a card in the *live*
    // game, since the button is enabled off the replayed frame's active player.
    if (!canMutate || !session) return;
    await refreshFrom(sacrificePlayed(session.sessionId, cardId));
  }

  async function handleAttack(target: 'player' | 'champion', championId?: string) {
    if (!canMutate || !session) return;
    await refreshFrom(attackTarget(session.sessionId, target, championId));
  }

  async function handleAdvance() {
    if (!canMutate || !session) return;
    await refreshFrom(phase === 'combat' ? endTurn(session.sessionId) : advancePhase(session.sessionId));
  }

  async function handleBotTurn() {
    if (!canMutate || !session) return;
    if (session.activePlayer !== 'bot' || session.winner) return;
    attemptedBotTurn.current = `${session.sessionId}:${session.turnNumber}`;
    setBusy(true);
    setStatus({ tone: 'busy', message: 'The challenger is taking its turn…' });
    try {
      const next = await playback.run(session, algorithm, budgetMs);
      setSession(next);
      setStatus({ tone: 'good', message: next.winner ? 'Match complete.' : 'Bot turn complete. Your move.' });
    } catch (error) {
      // Preserve the latest authoritative board on interruption; never rerun a
      // partially completed turn automatically. Refresh can recover a dropped stream.
      if (error instanceof BotStreamError && error.state) setSession(error.state);
      else if (playback.latest.current) setSession({ ...session, ...playback.latest.current });
      setStatus({ tone: 'error', message: `${error instanceof Error ? error.message : 'Bot turn failed.'} Refresh to check the board.` });
    } finally {
      setBusy(false);
    }
  }

  async function handleRefresh() {
    if (!session) return;
    setReplayFrame(null);
    await refreshFrom(loadSession(session.sessionId));
  }

  // The table layout has no page scroll, so no scroll-into-view is needed
  // when the match ends - the winner overlay covers the table instead.
  useEffect(() => {
    if (session || busy) return;
    void startNewMatch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!session || busy || playback.running || session.activePlayer !== 'bot' || session.winner || isReplayMode) return;
    const turnKey = `${session.sessionId}:${session.turnNumber}`;
    if (attemptedBotTurn.current === turnKey) return;
    const timer = window.setTimeout(() => {
      attemptedBotTurn.current = turnKey;
      void handleBotTurn();
    }, 350);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.sessionId, session?.activePlayer, session?.turnNumber, busy, isReplayMode, playback.running]);

  // Under the main phase, advancing IS ending the turn.
  const actionLabel = (phase === 'combat' || phase === 'main') ? 'End Turn' : 'Next Phase';

  // --- bot-only extras for the table: match setup + bot insight in the info sheet ---
  const botInfoExtra = (
    <>
      <h4>New match</h4>
      <div className="bot-setup">
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
          <span>Budget · ms</span>
          <input value={budgetMs} onChange={(event) => setBudgetMs(Number(event.target.value || 0))} inputMode="numeric" />
        </label>
        <button className="primary-button" onClick={() => void startNewMatch()} disabled={busy}>
          New Match
        </button>
      </div>
      {displayState?.botInsight ? (
        <>
          <h4>Bot insight</h4>
          <p className="phase-copy">
            {displayState.botInsight.algorithm} · {displayState.botInsight.iterations ?? 0} rollouts · {displayState.botInsight.elapsedMs ?? 0} ms
          </p>
          {displayState.botInsight.candidates?.length ? (
            <CandidateList candidates={displayState.botInsight.candidates} />
          ) : null}
        </>
      ) : null}
    </>
  );

  if (!displayState) {
    return (
      <div className="game-table">
        <header className="table-topbar">
          <span className="icon-button-spacer" aria-hidden="true" />
          <span className="table-title"><span aria-hidden="true">♜</span> Hero Realms</span>
          <span className="icon-button-spacer" aria-hidden="true" />
        </header>
        <div className="center-overlay">
          <div className="overlay-card"><h3>Starting match…</h3></div>
        </div>
      </div>
    );
  }

  return (
    <GameTable
      game={{ history: session?.history }}
      state={displayState}
      yourSide="player"
      opponentName="Bot"
      seatNames={{ player: 'You', bot: 'Bot' }}
      isMyTurn={!isBotTurn && !isReplayMode && !playback.running}
      canMutate={canMutate}
      busy={busy}
      waiting={false}
      winner={winner}
      winnerCopy={winnerCopy}
      isReplayMode={isReplayMode}
      phase={phase}
      phaseLabel={phaseLabel}
      status={status}
      actionLabel={actionLabel}
      autoPlayCount={displayState.autoPlayCount ?? 0}
      replayFrame={playback.action?.frame ?? replayFrame}
      onSelectFrame={(frame) => setReplayFrame(frame)}
      onLive={() => setReplayFrame(null)}
      onPlay={(cardId, stunTargetIndex) => void handlePlay(cardId, stunTargetIndex)}
      onPlayAll={() => void handlePlayAll()}
      onExpend={(championId, stunTargetIndex, choice, sacrificeIndex, sacrificeZone) =>
        void handleExpend(championId, stunTargetIndex, choice, sacrificeIndex, sacrificeZone)}
      onSacrifice={(cardId) => void handleSacrifice(cardId)}
      onBuy={(index) => void handleBuy(index)}
      onAttack={(target, championId) => void handleAttack(target, championId)}
      onEndTurn={() => void handleAdvance()}
      onAdvance={() => void handleAdvance()}
      onExit={onExit}
      onRefresh={() => void handleRefresh()}
      onSignOut={onSignOut}
      onNewGame={() => void startNewMatch()}
      botBanner={
        playback.running ? (
          <BotActionBanner action={playback.action} skipping={playback.skipping} onSkip={playback.skip} />
        ) : undefined
      }
      infoExtra={botInfoExtra}
    />
  );
}

type Mode = 'bot' | 'lobby' | 'human';

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [mode, setMode] = useState<Mode>('lobby');
  const [humanGameId, setHumanGameId] = useState<string | null>(null);

  useEffect(() => {
    me().then((u) => {
      setUser(u);
      setAuthChecked(true);
    }).catch(() => setAuthChecked(true));
  }, []);

  async function handleLogout() {
    await logout();
    setUser(null);
    setMode('lobby');
    setHumanGameId(null);
  }

  function openGame(gameId: string) {
    setHumanGameId(gameId);
    setMode('human');
  }

  if (!authChecked) {
    return (
      <div className="app-shell">
        <main className="auth-main">
          <p className="auth-sub">Loading…</p>
        </main>
      </div>
    );
  }

  if (!user) {
    return <AuthScreen onAuth={(u) => { setUser(u); setMode('lobby'); }} />;
  }

  return (
    <div className="app-mode-shell">
      {mode !== 'human' && mode !== 'bot' ? (
        <nav className="mode-tabs">
          <div className="mode-tabs-left">
            <button
              className="mode-tab active"
              onClick={() => setMode('lobby')}
            >
              Vs Human
            </button>
            <button
              className="mode-tab"
              onClick={() => setMode('bot')}
            >
              Vs Bot
            </button>
          </div>
          <div className="mode-tabs-right">
            <span className="mode-user">{user.username}</span>
            <button className="secondary-button" onClick={() => void handleLogout()}>
              Sign out
            </button>
          </div>
        </nav>
      ) : null}
      {mode === 'bot' ? (
        <BotGame onExit={() => setMode('lobby')} onSignOut={() => void handleLogout()} />
      ) : mode === 'human' && humanGameId ? (
        <HumanGame gameId={humanGameId} user={user} onSignOut={() => void handleLogout()} onExit={() => { setHumanGameId(null); setMode('lobby'); }} />
      ) : (
        <Lobby user={user} onOpenGame={openGame} />
      )}
    </div>
  );
}

export default App;
