import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type {
  CardView,
  ChampionView,
  GameStateCore,
  LegalAction,
  Phase,
  PlayerView,
} from './types';
import { CardArtwork } from './CardArtwork';
import { playSound, unlockAudio, isMuted, setMuted, buzz } from './juice';
import {
  HistoryInspector,
  LogList,
  OR_CHOICE_LABEL,
  formatCardRules,
  formatCardTags,
  orChoiceBranches,
  phaseAllows,
} from './App';
import type { HistoryFrame } from './types';

export interface TableHandlers {
  onPlay: (cardId: string, stunTargetIndex?: number) => void;
  onPlayAll: () => void;
  onTriggerAlly: (cardId: string, stunTargetIndex?: number) => void;
  onExpend: (
    championId: string,
    stunTargetIndex?: number,
    choice?: string,
    sacrificeIndex?: number,
    sacrificeZone?: string,
  ) => void;
  onSacrifice: (cardId: string) => void;
  onBuy: (index: number) => void;
  onAttack: (target: 'player' | 'champion', championId?: string) => void;
  onResolveChoice: (candidateIndex: number) => void;
  onEndTurn: () => void;
  onAdvance: () => void;
  onExit?: () => void;
  onRefresh: () => void;
  onSignOut?: () => void;
}

interface Props extends TableHandlers {
  /** Live game meta the table needs: history for replay, invite code for the waiting room. */
  game: { history?: HistoryFrame[]; inviteCode?: string; gameId?: string };
  /** What's on screen: the live game or a history replay frame. */
  state: GameStateCore;
  yourSide: 'player' | 'bot';
  opponentName: string;
  seatNames: { player: string; bot: string };
  isMyTurn: boolean;
  canMutate: boolean;
  busy: boolean;
  waiting: boolean;
  winner: 'player' | 'bot' | 'draw' | null;
  winnerCopy: string | null;
  isReplayMode: boolean;
  phase: Phase;
  phaseLabel: string;
  status: { tone: string; message: string };
  actionLabel: string;
  autoPlayCount: number;
  replayFrame: HistoryFrame | null;
  onSelectFrame: (frame: HistoryFrame | null) => void;
  onLive: () => void;
  /** Bot mode only: live action banner shown while the bot streams its turn. */
  botBanner?: ReactNode;
  /** Bot mode only: extra controls (new-match setup, bot insight) in the info sheet. */
  infoExtra?: ReactNode;
  /** Bot mode only: start a fresh match (winner overlay button). */
  onNewGame?: () => void;
}

type ChampionAction = {
  key: string;
  label: string;
  detail?: string;
  disabled?: boolean;
  onAction: () => void;
};

/** Compact card for the table: art, cost pip, name, key stats. Tap = primary action. */
function TableCard({
  card,
  onTap,
  disabled,
  dimmed,
  onInspect,
  footer,
  selected,
}: {
  card: CardView;
  onTap?: () => void;
  disabled?: boolean;
  dimmed?: boolean;
  onInspect: (card: CardView) => void;
  footer?: React.ReactNode;
  selected?: boolean;
}) {
  return (
    <div
      className={`tcard${disabled ? ' is-disabled' : ''}${dimmed ? ' is-dimmed' : ''}${selected ? ' is-selected' : ''}${card.cardType === 'champion' ? ' is-champion' : ''}`}
      onClick={disabled ? undefined : onTap}
      role={onTap && !disabled ? 'button' : undefined}
      aria-label={card.name}
    >
      <span className="tcard-cost">{card.cost}</span>
      <button
        className="tcard-info"
        aria-label={`Inspect ${card.name}`}
        onClick={(e) => {
          e.stopPropagation();
          onInspect(card);
        }}
      >
        ⓘ
      </button>
      <div className="tcard-art">
        <CardArtwork card={card} />
      </div>
      <div className="tcard-name">{card.name}</div>
      {footer}
    </div>
  );
}

function ChampionSpot({
  champion,
  onTap,
  disabled,
  dimmed,
  attackable,
  onInspect,
}: {
  champion: ChampionView;
  onTap?: () => void;
  disabled?: boolean;
  dimmed?: boolean;
  attackable?: boolean;
  onInspect: (card: CardView) => void;
}) {
  return (
    <div className={`champ-spot-wrap${champion.exhausted ? ' is-spent' : ''}`}>
      <TableCard
        card={champion}
        onTap={onTap}
        disabled={disabled}
        dimmed={dimmed}
        onInspect={onInspect}
        footer={
          <div className="tcard-badges">
            {champion.guard ? <span className="tbadge guard">G</span> : null}
            <span className="tbadge hp">♥{champion.currentHealth}</span>
            {champion.exhausted ? <span className="tbadge spent">…</span> : null}
          </div>
        }
      />
      {attackable ? <span className="attack-hint" aria-hidden="true">⚔</span> : null}
    </div>
  );
}

function InspectModal({ card, onClose }: { card: CardView; onClose: () => void }) {
  return (
    <div className="sheet-scrim" onClick={onClose}>
      <div className="inspect-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={card.name}>
        <div className="inspect-art">
          <CardArtwork card={card} />
        </div>
        <h3>{card.name}</h3>
        <div className="inspect-meta">
          <span>{card.cost} gold</span>
          <span>{card.faction || 'Neutral'}</span>
          <span>{card.cardType}</span>
        </div>
        <div className="tag-row">
          {formatCardTags(card).map((tag) => (
            <span key={tag} className="tag">{tag}</span>
          ))}
        </div>
        {formatCardRules(card.text).map((section, i) => (
          <p key={i} className="inspect-rules">{section}</p>
        ))}
        <button className="primary-button" onClick={onClose}>Close</button>
      </div>
    </div>
  );
}

function ActionSheet({
  title,
  subtitle,
  art,
  actions,
  onClose,
  cancelLabel,
  hideCancel,
}: {
  title: string;
  subtitle?: string;
  art?: CardView;
  actions: ChampionAction[];
  onClose: () => void;
  cancelLabel?: string;
  hideCancel?: boolean;
}) {
  return (
    <div className="sheet-scrim" onClick={onClose}>
      <div className="action-sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div className="sheet-handle" aria-hidden="true" />
        <div className="action-sheet-head">
          {art ? (
            <div className="action-sheet-art"><CardArtwork card={art} compact /></div>
          ) : null}
          <div>
            <h3>{title}</h3>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
        </div>
        <div className="action-list">
          {actions.map((action) => (
            <button
              key={action.key}
              className="action-row"
              disabled={action.disabled}
              onClick={() => {
                action.onAction();
                onClose();
              }}
            >
              <span>{action.label}</span>
              {action.detail ? <small>{action.detail}</small> : null}
            </button>
          ))}
        </div>
        {hideCancel ? null : (
          <button className="secondary-button" onClick={onClose}>{cancelLabel ?? 'Cancel'}</button>
        )}
      </div>
    </div>
  );
}

const CONFETTI_COLORS = ['#ffd166', '#ef476f', '#06d6a0', '#118ab2', '#f78c6b', '#c39bd3'];

function Confetti() {
  const pieces = useMemo(
    () =>
      Array.from({ length: 42 }, (_, i) => ({
        id: i,
        left: Math.random() * 100,
        delay: Math.random() * 0.9,
        duration: 2.2 + Math.random() * 1.8,
        color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
        width: 6 + Math.random() * 6,
      })),
    [],
  );
  return (
    <div className="confetti" aria-hidden="true">
      {pieces.map((p) => (
        <span
          key={p.id}
          className="confetti-piece"
          style={{
            left: `${p.left}%`,
            width: p.width,
            background: p.color,
            animationDelay: `${p.delay}s`,
            animationDuration: `${p.duration}s`,
          }}
        />
      ))}
    </div>
  );
}

function DiscardSheet({ title, cards, onInspect, onClose }: {
  title: string;
  cards: CardView[];
  onInspect: (card: CardView) => void;
  onClose: () => void;
}) {
  // Most recently discarded first - the top of the pile is what matters.
  const ordered = [...cards].reverse();
  return (
    <div className="sheet-scrim" onClick={onClose}>
      <div className="discard-sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div className="sheet-handle" aria-hidden="true" />
        <h3>{title} ({cards.length})</h3>
        {ordered.length === 0 ? (
          <div className="empty-note">Nothing discarded yet.</div>
        ) : (
          <div className="discard-list">
            {ordered.map((card) => (
              <button
                key={card.id}
                className="discard-row"
                onClick={() => onInspect(card)}
                aria-label={`Inspect ${card.name}`}
              >
                <span className="discard-row-art"><CardArtwork card={card} compact /></span>
                <span className="discard-row-name">{card.name}</span>
                <span className="discard-row-cost">{card.cost}●</span>
              </button>
            ))}
          </div>
        )}
        <button className="secondary-button" onClick={onClose}>Close</button>
      </div>
    </div>
  );
}

function ChoiceSheet({ actions, kind, source, remaining, onResolve }: {
  actions: LegalAction[];
  kind: string;
  source?: string | null;
  remaining?: number;
  onResolve: (candidateIndex: number) => void;
}) {
  // A pending card-effect choice must be answered before anything else can
  // happen: no scrim dismiss, no cancel button. The backend enforces the
  // same lock, so there is no path that silently swallows the choice.
  const title =
    kind === 'discard' ? 'Discard a card'
    : kind === 'reanimate' ? 'Reanimate a champion'
    : kind === 'recycle' ? 'Recycle a card'
    : 'Sacrifice a card';
  // Multi-pick choices (Tyrannor's "up to two") reopen this sheet after each
  // pick, so say how many are left; declining stops early.
  const picksLeft = typeof remaining === 'number' ? remaining : 1;
  const hint =
    kind === 'discard' ? 'choose a card from your hand to discard.'
    : kind === 'reanimate'
      ? 'choose a champion from your discard pile to put on top of your deck.'
    : kind === 'recycle'
      ? 'you may put a card from your discard pile on top of your deck.'
    : picksLeft > 1
      ? `you may sacrifice up to ${picksLeft} cards from your hand or discard pile.`
      : 'you may sacrifice a card from your hand or discard pile.';
  return (
    <ActionSheet
      title={title}
      subtitle={`${source ? `${source}: ` : ''}${hint}`}
      actions={actions.map((action) => ({
        key: `choice-${String(action.candidateIndex)}`,
        label: action.label,
        detail: action.candidateIndex === -1
          ? (picksLeft > 1 ? 'Stop here' : 'Keep everything')
          : undefined,
        onAction: () => onResolve(Number(action.candidateIndex)),
      }))}
      onClose={() => {}}
      hideCancel
    />
  );
}

export function GameTable(props: Props) {
  const {
    game, state, yourSide, opponentName, seatNames,
    isMyTurn, canMutate, busy, waiting, winner, winnerCopy,
    isReplayMode, phase, phaseLabel, status, actionLabel, autoPlayCount,
    replayFrame, onSelectFrame, onLive,
  } = props;

  const [inspectCard, setInspectCard] = useState<CardView | null>(null);
  const [sheetChampion, setSheetChampion] = useState<ChampionView | null>(null);
  const [infoOpen, setInfoOpen] = useState(false);
  // Discard pile viewer: { title, cards } for your pile or the opponent's.
  const [discardView, setDiscardView] = useState<{ title: string; cards: CardView[] } | null>(null);

  // Juice: rewarding-moment banners, screen shake, floating damage numbers.
  const [moment, setMoment] = useState<{ id: number; kind: string; title: string; sub?: string } | null>(null);
  const [shake, setShake] = useState<'hard' | 'soft' | null>(null);
  const [floaters, setFloaters] = useState<{ id: number; text: string }[]>([]);
  const [mutedUi, setMutedUi] = useState(isMuted());
  const juiceId = useRef(0);
  const momentTimer = useRef<number | null>(null);

  const fireMoment = (kind: string, title: string, sub?: string) => {
    if (momentTimer.current !== null) window.clearTimeout(momentTimer.current);
    juiceId.current += 1;
    setMoment({ id: juiceId.current, kind, title, sub });
    momentTimer.current = window.setTimeout(() => setMoment(null), 1500);
  };
  useEffect(
    () => () => {
      if (momentTimer.current !== null) window.clearTimeout(momentTimer.current);
    },
    [],
  );

  const addFloater = (text: string) => {
    juiceId.current += 1;
    const id = juiceId.current;
    setFloaters((prev) => [...prev.slice(-2), { id, text }]);
    window.setTimeout(() => {
      setFloaters((prev) => prev.filter((f) => f.id !== id));
    }, 1150);
  };

  // Screen shake is a one-shot CSS animation: clear the class after it
  // finishes so the next hit re-triggers it.
  useEffect(() => {
    if (!shake) return;
    const t = window.setTimeout(() => setShake(null), 450);
    return () => window.clearTimeout(t);
  }, [shake]);

  // iOS Safari only allows audio after a user gesture - prime it on the
  // first tap anywhere.
  useEffect(() => {
    const unlock = () => unlockAudio();
    window.addEventListener('pointerdown', unlock, { once: true });
    return () => window.removeEventListener('pointerdown', unlock);
  }, []);
  // End-turn confirmation: warnings shown once per turn, then it goes through.
  const [confirmEndTurn, setConfirmEndTurn] = useState<string[] | null>(null);
  const [warnedTurn, setWarnedTurn] = useState<string | null>(null);
  // Stun target picker: { kind, id, name } of the card/champion being
  // played/expended, or of the ally trigger being fired. Replaces the old
  // window.prompt number entry, which didn't work on mobile and forced a
  // number nobody wants to type. Ally-gated stuns (Death Threat, Hit Job)
  // pick their target when the ally is triggered, not when the card is
  // played - only base-effect stuns (Fire Bomb) open this at play time.
  const [stunPicker, setStunPicker] = useState<{
    kind: 'card' | 'champion' | 'trigger';
    id: string;
    name: string;
  } | null>(null);
  // Attack target picker: opened by the Attack button when face isn't legal
  // and more than one guard can be killed (single guard / face = one tap).
  const [attackPicker, setAttackPicker] = useState(false);

  // Escape dismisses the topmost overlay (action sheet, then card inspect,
  // then the discard viewer, then the info sheet) - the scrims otherwise
  // leave no keyboard path out.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (sheetChampion) setSheetChampion(null);
      else if (inspectCard) setInspectCard(null);
      else if (discardView) setDiscardView(null);
      else if (infoOpen) setInfoOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sheetChampion, inspectCard, discardView, infoOpen]);

  // Backend contract: state["player"] is ALWAYS your own seat and
  // state["bot"] is ALWAYS the opponent, for both host and guest
  // (session._core_state swaps the views for the guest's for_side).
  const me = state.player;
  const foe = state.bot;

  // Kill detection: a foe champion that was on the board and is now gone was
  // destroyed (attack or stun) - celebrate it. Your own losses get a soft
  // shake, not a party. Board identity resets on a new match so the fresh
  // board isn't read as a massacre.
  const prevBoards = useRef<{ sessionId: string | null; foe: Map<string, ChampionView>; me: Map<string, ChampionView> }>({
    sessionId: null,
    foe: new Map(),
    me: new Map(),
  });
  useEffect(() => {
    const prev = prevBoards.current;
    if (prev.sessionId !== state.sessionId) {
      prev.sessionId = state.sessionId;
      prev.foe = new Map(foe.board.map((c) => [c.instanceId, c]));
      prev.me = new Map(me.board.map((c) => [c.instanceId, c]));
      return;
    }
    for (const [id, champ] of prev.foe) {
      if (!foe.board.some((c) => c.instanceId === id)) {
        fireMoment('kill', `💥 ${champ.name} destroyed!`, champ.guard > 0 ? 'Guard down — the way is open' : 'One less blocker');
        playSound('kill');
        setShake('hard');
      }
    }
    for (const [id, champ] of prev.me) {
      if (!me.board.some((c) => c.instanceId === id)) {
        setShake('soft');
        playSound('damage');
      }
    }
    prev.foe = new Map(foe.board.map((c) => [c.instanceId, c]));
    prev.me = new Map(me.board.map((c) => [c.instanceId, c]));
    // fireMoment/playSound are stable enough; boards drive this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [foe.board, me.board, state.sessionId]);

  // Faction combo: playing 2+ non-wild cards of one faction in a turn is the
  // core synergy loop - count it up out loud. Wilds don't build combos.
  const combo = useMemo(() => {
    const counts = new Map<string, number>();
    for (const card of me.playedThisTurn) {
      if (!card.faction || card.faction === 'Wild') continue;
      counts.set(card.faction, (counts.get(card.faction) ?? 0) + 1);
    }
    let best: { faction: string; count: number } | null = null;
    for (const [faction, count] of counts) {
      if (count >= 2 && (!best || count > best.count)) best = { faction, count };
    }
    return best;
  }, [me.playedThisTurn]);
  const prevComboCount = useRef(0);
  useEffect(() => {
    // playedThisTurn empties each turn, which naturally resets the count.
    const n = combo?.count ?? 0;
    if (n > prevComboCount.current && n >= 2 && isMyTurn && !winner) {
      fireMoment('combo', `⚡ ${combo!.faction} synergy ×${n}!`, 'Same-faction cards played this turn');
      playSound('combo', { combo: n });
    }
    prevComboCount.current = n;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [combo, isMyTurn, winner]);

  // Soft whoosh when your turn starts; fanfare when you win.
  const prevMyTurn = useRef(isMyTurn);
  const prevWinnerRef = useRef(winner);
  useEffect(() => {
    if (isMyTurn && !prevMyTurn.current && !winner) playSound('turn');
    prevMyTurn.current = isMyTurn;
    if (winner && !prevWinnerRef.current && winner === yourSide) {
      playSound('win');
      buzz([70, 90, 70, 90, 140]);
    }
    prevWinnerRef.current = winner;
  }, [isMyTurn, winner, yourSide]);
  // Connectivity: the net module dispatches `hr:net` with
  // { online: boolean }; the top-bar dot mirrors it. Taps that need the
  // network check needOnline() first so a dead radio surfaces a plain-words
  // notice instead of spinning until the request times out.
  const [online, setOnline] = useState(
    () => typeof navigator === 'undefined' || navigator.onLine,
  );
  const onlineRef = useRef(online);
  useEffect(() => {
    const onNet = (event: Event) => {
      const detail = (event as CustomEvent<{ online?: boolean }>).detail;
      const next = typeof detail?.online === 'boolean' ? detail.online : true;
      onlineRef.current = next;
      setOnline(next);
    };
    window.addEventListener('hr:net', onNet);
    return () => window.removeEventListener('hr:net', onNet);
  }, []);
  const offlineNotice = () => {
    fireMoment('notice', "You're offline", 'Check your connection — nothing was sent');
  };
  const needOnline = (): boolean => {
    if (!onlineRef.current) {
      offlineNotice();
      return false;
    }
    return true;
  };

  // Loading skeleton: a refresh that takes longer than ~1s shouldn't read
  // as a frozen board. Cover the table with pulsing placeholders until the
  // new state lands. Skipped while the bot streams its turn - the action
  // banners already narrate that busy state.
  const skeletonArmed = busy && !props.botBanner;
  const [showSkeleton, setShowSkeleton] = useState(false);
  useEffect(() => {
    if (!skeletonArmed) {
      setShowSkeleton(false);
      return;
    }
    const t = window.setTimeout(() => setShowSkeleton(true), 1000);
    return () => window.clearTimeout(t);
  }, [skeletonArmed]);

  // Undo is multiplayer-only: POST /api/games/{gameId}/undo. The game prop
  // carries gameId for human games; bot mode passes a bare { history },
  // so the button hides there.
  const gameId = game.gameId ?? null;
  const [undoing, setUndoing] = useState(false);

  const canInteract = canMutate && isMyTurn && !winner && !busy;

  const handlePlayCard = (card: CardView) => {
    if (!needOnline()) return;
    if (!canInteract || !phaseAllows(phase, 'play')) return;
    // Base-effect stuns (Fire Bomb) pick a target at play time. Ally-gated
    // stuns (Death Threat, Hit Job) carry ally_faction - their target is
    // chosen when the ally ability itself is triggered, not here.
    if (card.effects.stun && !card.effects.ally_faction && stunCandidates.length > 0) {
      setStunPicker({ kind: 'card', id: card.id, name: card.name });
      return;
    }
    props.onPlay(card.id, undefined);
  };

  const handleBuyCard = (index: number, cost: number) => {
    if (!needOnline()) return;
    if (!canInteract || !phaseAllows(phase, 'buy') || cost > me.gold) return;
    // Optimistic juice: the tap is the reward. Legality is already gated
    // above, so a false fanfare is all but impossible.
    const card = state.market.row[index];
    if (card && cost >= 5) {
      fireMoment('bigbuy', `🔥 ${card.name} recruited!`, `${cost} gold of pure power`);
      playSound('bigbuy');
      buzz([20, 60, 40]);
      setShake('soft');
    } else {
      playSound('buy');
    }
    props.onBuy(index);
  };

  // --- end-turn warnings: what the player could still do before ending ---
  const endTurnWarnings = (): string[] => {
    const warnings: string[] = [];
    if (!isMyTurn || isReplayMode || winner) return warnings;
    if (phaseAllows(phase, 'buy')) {
      const affordable = state.market.row.filter(
        (card): card is CardView => !!card && card.cost <= me.gold,
      );
      if (affordable.length > 0) {
        const names = affordable.slice(0, 3).map((card) => card.name).join(', ');
        const more = affordable.length > 3 ? ` (+${affordable.length - 3} more)` : '';
        warnings.push(`Buy ${names}${more} (${me.gold}●)`);
      } else if (me.gold >= 2 && state.market.fireGemsRemaining > 0) {
        warnings.push(`Buy a Fire Gem (${me.gold}●)`);
      }
    }
    if (phaseAllows(phase, 'combat') && me.combat > 0 && attackInfo.canAttack) {
      warnings.push(`Attack for ${me.combat}⚔`);
    }
    if (phaseAllows(phase, 'champion')) {
      const stunners = me.board.filter(
        (champion) => champion.alive && !champion.exhausted && champion.effects.stun,
      );
      const targets = foe.board.filter((champion) => champion.alive && champion.currentHealth > 0);
      if (stunners.length > 0 && targets.length > 0) {
        warnings.push(`Stun with ${stunners.map((champion) => champion.name).join(', ')}`);
      }
    }
    if (triggerActions.length > 0) {
      const seen = new Set<string>();
      const names: string[] = [];
      for (const action of triggerActions) {
        const champ = action.championId
          ? me.board.find((c) => c.instanceId === action.championId)
          : undefined;
        const played = champ ?? me.playedThisTurn.find((c) => c.id === action.cardId);
        const name = played?.name ?? (typeof action.cardId === 'string' ? action.cardId : 'ally');
        if (!seen.has(name)) {
          seen.add(name);
          names.push(name);
        }
        if (names.length >= 3) break;
      }
      warnings.push(`Trigger ally: ${names.join(', ')}`);
    }
    return warnings;
  };

  const handlePrimary = () => {
    if (!needOnline()) return;
    if (!(phase === 'combat' || phase === 'main')) {
      props.onAdvance();
      return;
    }
    const turnKey = `${state.turnNumber}:${yourSide}`;
    const warnings = endTurnWarnings();
    if (warnings.length > 0 && warnedTurn !== turnKey) {
      setConfirmEndTurn(warnings);
      return;
    }
    setConfirmEndTurn(null);
    props.onEndTurn();
  };

  // api.undo is the sibling agent's contract: POST /api/games/{gameId}/undo,
  // resolving to the post-undo game state. Dynamically imported so this
  // module also compiles before that export lands; a missing export
  // degrades to the same plain-words notice as any other undo failure.
  async function undoGame(gid: string): Promise<GameStateCore> {
    const api = await import('./api');
    const undo = (api as unknown as { undo?: (gameId: string) => Promise<GameStateCore> }).undo;
    if (typeof undo !== 'function') throw new Error('Undo is not available in this build.');
    return undo(gid);
  }

  const handleUndo = () => {
    if (!gameId || undoing) return;
    if (!needOnline()) return;
    setUndoing(true);
    void undoGame(gameId)
      .then(() => {
        // The undo response is the post-undo state; pull it through the
        // standard refresh path so the owner applies it authoritatively.
        props.onRefresh();
      })
      .catch((error: unknown) => {
        fireMoment('notice', 'Undo failed', error instanceof Error ? error.message : 'Nothing to undo.');
      })
      .finally(() => setUndoing(false));
  };

  // --- champion actions for the player's own board (mirrors BoardColumn) ---
  // Ally triggers offered by the backend: one legal action per card whose
  // ally ability is live this turn. The player fires them on their own
  // timing - they never auto-fire on play/expend.
  const triggerActions = useMemo(
    () => state.legalActions.filter((a) => a.type === 'trigger_ally'),
    [state.legalActions],
  );
  const championActions = (champion: ChampionView): ChampionAction[] => {
    const actions: ChampionAction[] = [];
    // Ally ability, user-triggered: the official app lets the player fire it
    // on their own timing. Offered while legalActions carries it (main phase
    // and all legacy phases), whether or not the champion is exhausted.
    if (canInteract) {
      const allyActs = triggerActions.filter(
        (action) => action.championId === champion.instanceId,
      );
      if (allyActs.length > 0) {
        const first = allyActs[0];
        const desc = (first.label.split(' - ally: ')[1] ?? first.label).trim();
        const needsPick = allyActs.some(
          (action) => action.stunTargetIndex !== undefined && action.stunTargetIndex !== null,
        );
        actions.push({
          key: `${champion.instanceId}-ally`,
          label: `⚡ Ally: ${desc}`,
          onAction: () => {
            setSheetChampion(null);
            if (needsPick && stunCandidates.length > 0) {
              setStunPicker({ kind: 'trigger', id: first.cardId ?? '', name: champion.name });
            } else {
              juicyTriggerAlly(first.cardId ?? '');
            }
          },
        });
      }
    }
    const canExpend = phaseAllows(phase, 'champion') && canInteract;
    const branches = orChoiceBranches(champion);
    if (branches.length > 1 && canExpend) {
      for (const kind of branches) {
        actions.push({
          key: `${champion.instanceId}-${kind}`,
          label: `Expend: ${OR_CHOICE_LABEL[kind] ?? kind}`,
          disabled: champion.exhausted,
          onAction: () => {
            if (!needOnline()) return;
            props.onExpend(champion.instanceId, undefined, kind);
          },
        });
      }
    } else {
      actions.push({
        key: `${champion.instanceId}-expend`,
        label: canExpend ? 'Expend' : 'Locked',
        detail: !canExpend ? 'Not your turn or wrong phase' : champion.exhausted ? 'Already spent' : undefined,
        disabled: !canExpend || champion.exhausted,
        onAction: () => {
          if (!needOnline()) return;
          // Only base-effect stuns pick a target when expended; ally-gated
          // stuns wait for the Ally button above.
          if (champion.effects.stun && !champion.effects.ally_faction && stunCandidates.length > 0) {
            setSheetChampion(null);
            setStunPicker({ kind: 'champion', id: champion.instanceId, name: champion.name });
            return;
          }
          props.onExpend(champion.instanceId, undefined);
        },
      });
    }
    if (canExpend) {
      for (const action of state.legalActions) {
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
          onAction: () => {
            if (!needOnline()) return;
            props.onExpend(
              champion.instanceId,
              undefined,
              undefined,
              (action.sacrificeIndex as number | undefined) ?? undefined,
              (action.sacrificeZone as string | undefined) ?? 'hand',
            );
          },
        });
      }
    }
    return actions;
  };

  // --- attack legality for the opponent's board (mirrors BoardColumn) ---
  // Chip damage is pointless: a champion is only offered as a target when the
  // attack stuns (kills) it. Otherwise the player attacks face.
  const attackInfo = useMemo(() => {
    const living = foe.board.filter((c) => c.alive && c.currentHealth > 0);
    const guards = living.filter((c) => c.guard > 0 && !c.exhausted);
    const targets = guards.length > 0 ? guards : living;
    const killable = targets.filter((c) => c.currentHealth <= me.combat);
    const ids = new Set(killable.map((c) => c.instanceId));
    const faceLegal = state.legalActions.some(
      (a: LegalAction) => a.type === 'attack_target' && a.target === 'player',
    );
    return {
      ids,
      faceLegal,
      guardsBlocking: !faceLegal && me.combat > 0,
      canAttack: faceLegal || killable.length > 0,
    };
  }, [foe.board, state.legalActions, me.combat]);

  // Stun targets mirror the backend's _attack_targets exactly (living
  // champions; prepared guards take priority). The picker's index is the
  // candidate's position in this list, which is what the backend resolves.
  const stunCandidates = useMemo(() => {
    const living = foe.board.filter((c) => c.alive);
    const guards = living.filter((c) => c.guard > 0 && !c.exhausted);
    return guards.length > 0 ? guards : living;
  }, [foe.board]);

  const canAttackNow = canInteract && phaseAllows(phase, 'combat') && me.combat > 0;

  // Pending card-effect choice (Elven Gift's discard, The Rot's sacrifice,
  // ...): the backend answers legalActions with ONLY these while one pends,
  // so this sheet is the whole UI until it's resolved. Gated on canInteract
  // so it only ever prompts the human whose turn it is.
  const choiceActions = useMemo(
    () => state.legalActions.filter((a) => a.type === 'resolve_choice'),
    [state.legalActions],
  );
  const pendingChoice = canInteract && choiceActions.length > 0 ? choiceActions[0] : null;

  // Attack with impact: face hits get a damage floater, shake and thud;
  // champion kills are celebrated by the board-diff effect above.
  const juicyAttack = (target: 'player' | 'champion', championId?: string) => {
    if (!needOnline()) return;
    if (target === 'player') {
      addFloater(`−${me.combat}`);
      setShake('soft');
      playSound('damage');
    } else {
      playSound('click');
    }
    props.onAttack(target, championId);
  };

  // Attack button: face when legal, otherwise the guard. One tap for the
  // common cases; a picker only when several guards could be killed.
  const canAttackButton = canAttackNow && attackInfo.canAttack;
  const handleAttackButton = () => {
    if (!canAttackButton) return;
    if (attackInfo.faceLegal) {
      juicyAttack('player');
      return;
    }
    const killable = foe.board.filter((c) => attackInfo.ids.has(c.instanceId));
    if (killable.length === 1) {
      juicyAttack('champion', killable[0].instanceId);
      return;
    }
    setAttackPicker(true);
  };

  const sacrificeables = useMemo(
    () =>
      me.playedThisTurn.filter(
        (card) => ((card.effects.sacrifice_combat as number | undefined) ?? 0) > 0,
      ),
    [me.playedThisTurn],
  );

  // Ally trigger for a card in the played strip (board champions get theirs
  // in the champion sheet). Stun allies open the target picker; the rest
  // fire immediately.
  // Ally trigger with the dopamine hit: banner + zap sound, then the action.
  const juicyTriggerAlly = (cardId: string, stunTargetIndex?: number) => {
    if (!needOnline()) return;
    const card =
      me.playedThisTurn.find((c) => c.id === cardId) ??
      me.board.find((c) => c.id === cardId) ??
      foe.board.find((c) => c.id === cardId);
    const name = card?.name ?? 'Ally';
    fireMoment('ally', `⚡ ${name}!`, 'Ally ability triggered');
    playSound('ally');
    buzz([25, 40, 25]);
    props.onTriggerAlly(cardId, stunTargetIndex);
  };

  const handleTriggerPlayed = (cardId: string) => {
    const acts = triggerActions.filter(
      (action) => action.cardId === cardId && !action.championId,
    );
    if (acts.length === 0) return;
    const needsPick =
      acts.some(
        (action) => action.stunTargetIndex !== undefined && action.stunTargetIndex !== null,
      ) && stunCandidates.length > 0;
    if (needsPick) {
      const card = me.playedThisTurn.find((c) => c.id === cardId);
      setStunPicker({ kind: 'trigger', id: cardId, name: card?.name ?? 'Ally' });
    } else {
      juicyTriggerAlly(cardId);
    }
  };

  const bannerText = waiting
    ? 'Waiting for opponent'
    : winner
      ? 'Match over'
      : isMyTurn
        ? `Your turn · Turn ${state.turnNumber}`
        : `${opponentName}'s turn · Turn ${state.turnNumber}`;

  return (
    <div className={`game-table${shake ? ` shake-${shake}` : ''}`}>
      {/* slim top bar */}
      <header className="table-topbar">
        {props.onExit ? (
          <button className="icon-button" onClick={props.onExit} aria-label="Back to lobby">‹</button>
        ) : (
          <span className="icon-button-spacer" aria-hidden="true" />
        )}
        <span className="table-title"><span aria-hidden="true">♜</span> Hero Realms</span>
        <div className="table-top-actions">
          <span
            className={`net-dot${online ? ' is-online' : ' is-offline'}`}
            role="status"
            aria-label={online ? 'Connected' : 'Offline'}
            title={online ? 'Connected' : 'Offline — game actions need a connection'}
          />
          <button
            className="icon-button"
            onClick={() => {
              const next = !mutedUi;
              setMuted(next);
              setMutedUi(next);
              if (!next) playSound('click');
            }}
            aria-label={mutedUi ? 'Unmute sound effects' : 'Mute sound effects'}
            title={mutedUi ? 'Unmute sound effects' : 'Mute sound effects'}
          >
            {mutedUi ? '🔇' : '🔊'}
          </button>
          <button
            className="icon-button"
            onClick={() => setInfoOpen(true)}
            aria-label="Match info"
          >
            ≡
          </button>
        </div>
      </header>

      {/* opponent zone */}
      <section className="opp-zone" aria-label="Opponent">
        <div className="player-strip">
          <span className="avatar" aria-hidden="true">{opponentName.slice(0, 1).toUpperCase()}</span>
          <span className="player-strip-name">{opponentName}</span>
          <span className="hp-wrap">
            <button
              className={`hp-pill foe${attackInfo.faceLegal && canAttackNow ? ' attackable' : ''}`}
              disabled={!(attackInfo.faceLegal && canAttackNow)}
              onClick={() => juicyAttack('player')}
              title={attackInfo.guardsBlocking ? 'Guards must be destroyed first' : attackInfo.faceLegal && canAttackNow ? 'Attack!' : undefined}
            >
              ♥ {foe.hp}
            </button>
            {floaters.map((f) => (
              <span key={f.id} className="floater" aria-hidden="true">{f.text}</span>
            ))}
          </span>
          <span className="deck-pip" title="Deck">🂠 {foe.deckCount}</span>
          <span className="deck-pip" title="Hand">🂡 {foe.handCount}</span>
          <button
            className="deck-pip as-button"
            title="View discard pile"
            aria-label={`View ${opponentName}'s discard pile (${foe.discardCount} cards)`}
            onClick={() => setDiscardView({ title: `${opponentName}'s discard pile`, cards: foe.discard })}
          >
            🗑 {foe.discardCount}
          </button>
        </div>
        <div className="champ-strip">
          {foe.board.length === 0 ? (
            <span className="strip-empty">No champions</span>
          ) : (
            foe.board.map((champion) => (
              <ChampionSpot
                key={champion.instanceId}
                champion={champion}
                attackable={canAttackNow && attackInfo.ids.has(champion.instanceId)}
                dimmed={!canAttackNow}
                onInspect={setInspectCard}
                onTap={
                  canAttackNow && attackInfo.ids.has(champion.instanceId)
                    ? () => juicyAttack('champion', champion.instanceId)
                    : undefined
                }
              />
            ))
          )}
        </div>
      </section>

      {/* market */}
      <section className="market-zone" aria-label="Market">
        <div className="zone-label">
          <span>Market</span>
          {me.nextBuyToHand ? (
            <span className="ally-badge" title="An ally ability is armed: the next card you acquire goes into your hand.">Next buy → hand</span>
          ) : me.nextBuyToTop ? (
            <span className="ally-badge" title="An ally ability is armed: the next card you acquire goes on top of your deck.">
              Next buy → top{me.nextBuyToTopActionOnly ? ' (action)' : ''}
            </span>
          ) : null}
          <span className="gold-inline">● {me.gold} gold</span>
        </div>
        <div className="market-row">
          {state.market.row.map((card, index) =>
            card ? (
              <TableCard
                key={`${card.id}-${index}`}
                card={card}
                dimmed={!canInteract || card.cost > me.gold}
                disabled={!canInteract || !phaseAllows(phase, 'buy') || card.cost > me.gold}
                onInspect={setInspectCard}
                onTap={() => handleBuyCard(index, card.cost)}
              />
            ) : (
              <div key={`empty-${index}`} className="tcard is-empty">
                <span className="empty-note">—</span>
              </div>
            ),
          )}
          {state.market.fireGemsRemaining > 0 ? (
            <TableCard
              key="fire-gem"
              card={{
                id: 'fire_gem', name: 'Fire Gem', cost: 2, faction: '', cardType: 'item',
                guard: 0, health: 0, effects: {}, text: 'Gain 2 gold. Sacrifice: gain 3 combat.',
              }}
              dimmed={!canInteract || me.gold < 2}
              disabled={!canInteract || !phaseAllows(phase, 'buy') || me.gold < 2}
              onInspect={setInspectCard}
              onTap={() => handleBuyCard(5, 2)}
            />
          ) : null}
        </div>
      </section>

      {/* turn banner + pools */}
      <div className={`turn-banner${isMyTurn && !winner && !waiting ? ' mine' : ''}`}>
        <span className="turn-text">{isReplayMode ? 'Replay' : bannerText}</span>
        {combo ? (
          <span className="combo-badge" title={`${combo.count} ${combo.faction} cards played this turn`}>
            ⚡ {combo.faction} ×{combo.count}
          </span>
        ) : null}
        <span className="pools">
          <span className="pool combat" title="Combat">⚔ {me.combat}</span>
          <span className="pool gold" title="Gold">● {me.gold}</span>
        </span>
      </div>
      {moment ? (
        <div key={moment.id} className={`juice-banner juice-${moment.kind}`} aria-live="polite">
          <div className="juice-title">{moment.title}</div>
          {moment.sub ? <div className="juice-sub">{moment.sub}</div> : null}
        </div>
      ) : null}
      {props.botBanner}

      {/* slow-refresh skeleton: pulsing placeholders so a >1s load never
          reads as a frozen board */}
      {showSkeleton ? (
        <div className="skeleton-overlay" aria-hidden="true">
          <div className="skel skel-bar" />
          <div className="skel-row">
            <span className="skel skel-card" />
            <span className="skel skel-card" />
            <span className="skel skel-card" />
            <span className="skel skel-card" />
            <span className="skel skel-card" />
          </div>
          <div className="skel skel-banner" />
          <div className="skel-row">
            <span className="skel skel-card" />
            <span className="skel skel-card" />
            <span className="skel skel-card" />
            <span className="skel skel-card" />
          </div>
          <div className="skel skel-bar" />
        </div>
      ) : null}

      {/* player champions */}
      <section className="player-champs" aria-label="Your champions">
        <div className="champ-strip">
          {me.board.length === 0 ? (
            <span className="strip-empty">No champions in play — buy red cards to recruit them</span>
          ) : (
            me.board.map((champion) => (
              <ChampionSpot
                key={champion.instanceId}
                champion={champion}
                dimmed={!canInteract}
                onInspect={setInspectCard}
                onTap={canInteract ? () => setSheetChampion(champion) : undefined}
              />
            ))
          )}
        </div>
        {sacrificeables.length > 0 ? (
          <div className="sac-row">
            {sacrificeables.map((card, i) => (
              <button
                key={`${card.id}-sac-${i}`}
                className="sac-chip"
                disabled={!canInteract}
                onClick={() => {
                  if (needOnline()) props.onSacrifice(card.id);
                }}
              >
                Sac {card.name} +{card.effects.sacrifice_combat as number}⚔
              </button>
            ))}
          </div>
        ) : null}
      </section>

      {/* cards played this turn: kept visible so the player can see
          what's already been committed (tapping one inspects it) */}
      {me.playedThisTurn.length > 0 ? (
        <section className="played-zone" aria-label="Cards you have played">
          <div className="zone-label">
            <span>Played</span>
          </div>
          <div className="played-row">
            {me.playedThisTurn.map((card, index) => {
              const hasAlly = triggerActions.some(
                (action) => action.cardId === card.id && !action.championId,
              );
              return (
                <div key={`${card.id}-played-${index}`} className="played-chip-wrap">
                  <button
                    className="played-chip"
                    onClick={() => setInspectCard(card)}
                    title={card.name}
                    aria-label={`Inspect ${card.name}`}
                  >
                    <span className="played-chip-art">
                      <CardArtwork card={card} />
                    </span>
                    <span className="played-chip-name">{card.name}</span>
                  </button>
                  {hasAlly && canInteract ? (
                    <button
                      className="played-chip-ally"
                      onClick={() => handleTriggerPlayed(card.id)}
                      aria-label={`Trigger ${card.name} ally ability`}
                    >
                      ⚡ Ally
                    </button>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {/* hand */}
      <section className="hand-zone" aria-label="Your hand">
        <div className="hand-fan">
          {me.hand.length === 0 ? (
            <span className="strip-empty">Hand empty</span>
          ) : (
            me.hand.map((card, index) => (
              <div key={`${card.id}-${index}`} className="fan-slot">
                <TableCard
                  card={card}
                  dimmed={!canInteract || !phaseAllows(phase, 'play')}
                  disabled={!canInteract || !phaseAllows(phase, 'play')}
                  onInspect={setInspectCard}
                  onTap={() => handlePlayCard(card)}
                />
              </div>
            ))
          )}
        </div>
      </section>

      {/* player bar */}
      <footer className="player-bar">
        <span className="avatar" aria-hidden="true">{me.name.slice(0, 1).toUpperCase()}</span>
        <span className="hp-pill mine">♥ {me.hp}</span>
        <span className="deck-pip" title="Deck">🂠 {me.deckCount}</span>
        <button
          className="deck-pip as-button"
          title="View your discard pile"
          aria-label={`View your discard pile (${me.discardCount} cards)`}
          onClick={() => setDiscardView({ title: 'Your discard pile', cards: me.discard })}
        >
          🗑 {me.discardCount}
        </button>
        <div className="player-bar-actions">
          {gameId ? (
            <button
              className="table-button undo-button"
              disabled={!canInteract || undoing}
              onClick={handleUndo}
              title="Undo your last action"
              aria-label="Undo your last action"
            >
              ↩ Undo
            </button>
          ) : null}
          <button
            className="table-button"
            disabled={!canAttackButton}
            onClick={handleAttackButton}
            title={
              canAttackButton
                ? `Attack for ${me.combat}⚔`
                : 'No attacks available'
            }
          >
            ⚔ Attack
          </button>
          {autoPlayCount > 0 ? (
            <button
              className="table-button"
              disabled={!canInteract || !phaseAllows(phase, 'play')}
              onClick={() => {
                if (needOnline()) props.onPlayAll();
              }}
            >
              Play all ({autoPlayCount})
            </button>
          ) : null}
          <button
            className="table-button primary"
            disabled={!canMutate || busy || winner !== null || !isMyTurn}
            onClick={handlePrimary}
          >
            {actionLabel}
          </button>
        </div>
      </footer>

      {/* overlays */}
      {pendingChoice ? (
        <ChoiceSheet
          actions={choiceActions}
          kind={pendingChoice.kind ?? ''}
          source={pendingChoice.source}
          remaining={typeof pendingChoice.remaining === 'number' ? pendingChoice.remaining : 1}
          onResolve={(candidateIndex) => {
            if (needOnline()) props.onResolveChoice(candidateIndex);
          }}
        />
      ) : null}

      {attackPicker ? (
        <ActionSheet
          title="Attack which guard?"
          subtitle="Guards must be destroyed before you can attack face:"
          actions={foe.board
            .filter((c) => attackInfo.ids.has(c.instanceId))
            .map((c) => ({
              key: c.instanceId,
              label: `Attack ${c.name}`,
              detail: `${c.currentHealth}❤ · your ${me.combat}⚔ is lethal`,
              onAction: () => {
                setAttackPicker(false);
                juicyAttack('champion', c.instanceId);
              },
            }))}
          onClose={() => setAttackPicker(false)}
        />
      ) : null}

      {stunPicker ? (
        <ActionSheet
          title={`Stun with ${stunPicker.name}`}
          subtitle="Choose a champion to stun:"
          actions={stunCandidates.map((candidate, index) => ({
            key: candidate.instanceId,
            label: `Stun ${candidate.name}`,
            detail: `${candidate.guard > 0 ? 'Guard · ' : ''}${candidate.currentHealth}❤`,
            onAction: () => {
              const target = stunPicker;
              setStunPicker(null);
              if (!needOnline()) return;
              if (target.kind === 'card') props.onPlay(target.id, index);
              else if (target.kind === 'champion') props.onExpend(target.id, index);
              else juicyTriggerAlly(target.id, index);
            },
          }))}
          onClose={() => setStunPicker(null)}
        />
      ) : null}

      {confirmEndTurn ? (
        <ActionSheet
          title="End turn?"
          subtitle="You can still act:"
          actions={[
            ...confirmEndTurn.map((warning, index) => ({
              key: `warn-${index}`,
              label: `• ${warning}`,
              disabled: true,
              onAction: () => {},
            })),
            {
              key: 'end-anyway',
              label: 'End turn anyway',
              onAction: () => {
                if (!needOnline()) return;
                setWarnedTurn(`${state.turnNumber}:${yourSide}`);
                props.onEndTurn();
              },
            },
          ]}
          onClose={() => setConfirmEndTurn(null)}
          cancelLabel="Keep playing"
        />
      ) : null}

      {sheetChampion ? (
        <ActionSheet
          title={sheetChampion.name}
          subtitle={formatCardRules(sheetChampion.text)[0]}
          art={sheetChampion}
          actions={championActions(sheetChampion)}
          onClose={() => setSheetChampion(null)}
        />
      ) : null}

      {discardView ? (
        <DiscardSheet
          title={discardView.title}
          cards={discardView.cards}
          onInspect={(card) => setInspectCard(card)}
          onClose={() => setDiscardView(null)}
        />
      ) : null}

      {inspectCard ? (
        <InspectModal card={inspectCard} onClose={() => setInspectCard(null)} />
      ) : null}

      {infoOpen ? (
        <div className="sheet-scrim" onClick={() => setInfoOpen(false)}>
          <div className="info-sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Match info">
            <div className="sheet-handle" aria-hidden="true" />
            <h3>Match info</h3>
            <p className={`status-chip ${status.tone}`}>{isReplayMode ? 'Replay mode' : status.message}</p>
            <p className="phase-copy">{phaseLabel}</p>
            <div className="info-actions">
              <button className="secondary-button" onClick={() => { if (!needOnline()) return; setInfoOpen(false); props.onRefresh(); }} disabled={busy}>Refresh</button>
              {props.onExit ? (
                <button className="secondary-button" onClick={() => { setInfoOpen(false); props.onExit?.(); }}>Lobby</button>
              ) : null}
              {props.onSignOut ? (
                <button className="secondary-button" onClick={() => void props.onSignOut?.()}>Sign out</button>
              ) : null}
            </div>
            {props.infoExtra}
            <h4>Decision log</h4>
            <div className="info-scroll">
              <LogList entries={state.log} seatNames={seatNames} />
            </div>
            <h4>Move history</h4>
            <HistoryInspector
              disabled={busy}
              history={game.history ?? []}
              selectedFrame={replayFrame}
              onSelectFrame={(frame) => { setInfoOpen(false); onSelectFrame(frame); }}
              onLive={() => { setInfoOpen(false); onLive(); }}
              seatNames={seatNames}
            />
          </div>
        </div>
      ) : null}

      {waiting && game.inviteCode ? (
        <div className="center-overlay">
          <div className="overlay-card">
            <h3>Waiting for opponent</h3>
            <p>Share this invite code:</p>
            <div className="invite-big">{game.inviteCode}</div>
            <p className="phase-copy">Your opponent joins from the lobby with this code.</p>
            {props.onExit ? (
              <button className="secondary-button" onClick={props.onExit}>Back to Lobby</button>
            ) : null}
          </div>
        </div>
      ) : null}

      {winnerCopy ? (
        <div className="center-overlay">
          {winner === yourSide ? <Confetti /> : null}
          <div className={`overlay-card${winner === yourSide ? ' won' : ''}`}>
            <h3>{winnerCopy}</h3>
            {props.onNewGame ? (
              <button className="primary-button" onClick={props.onNewGame}>New Match</button>
            ) : props.onExit ? (
              <button className="primary-button" onClick={props.onExit}>Back to Lobby</button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
