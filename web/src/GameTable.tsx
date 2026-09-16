import { useEffect, useMemo, useState } from 'react';
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
  game: { history?: HistoryFrame[]; inviteCode?: string };
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
  const isDiscard = kind === 'discard';
  // Multi-pick choices (Tyrannor's "up to two") reopen this sheet after each
  // pick, so say how many are left; declining stops early.
  const picksLeft = typeof remaining === 'number' ? remaining : 1;
  return (
    <ActionSheet
      title={isDiscard ? 'Discard a card' : 'Sacrifice a card'}
      subtitle={
        isDiscard
          ? `${source ? `${source}: ` : ''}choose a card from your hand to discard.`
          : `${source ? `${source}: ` : ''}${
              picksLeft > 1
                ? `you may sacrifice up to ${picksLeft} cards from your hand or discard pile.`
                : 'you may sacrifice a card from your hand or discard pile.'
            }`
      }
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
  // then the info sheet) - the scrims otherwise leave no keyboard path out.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (sheetChampion) setSheetChampion(null);
      else if (inspectCard) setInspectCard(null);
      else if (infoOpen) setInfoOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sheetChampion, inspectCard, infoOpen]);

  // Backend contract: state["player"] is ALWAYS your own seat and
  // state["bot"] is ALWAYS the opponent, for both host and guest
  // (session._core_state swaps the views for the guest's for_side).
  const me = state.player;
  const foe = state.bot;
  const canInteract = canMutate && isMyTurn && !winner && !busy;

  const handlePlayCard = (card: CardView) => {
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
    if (!canInteract || !phaseAllows(phase, 'buy') || cost > me.gold) return;
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
              props.onTriggerAlly(first.cardId ?? '');
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
          onAction: () => props.onExpend(champion.instanceId, undefined, kind),
        });
      }
    } else {
      actions.push({
        key: `${champion.instanceId}-expend`,
        label: canExpend ? 'Expend' : 'Locked',
        detail: !canExpend ? 'Not your turn or wrong phase' : champion.exhausted ? 'Already spent' : undefined,
        disabled: !canExpend || champion.exhausted,
        onAction: () => {
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
          onAction: () =>
            props.onExpend(
              champion.instanceId,
              undefined,
              undefined,
              (action.sacrificeIndex as number | undefined) ?? undefined,
              (action.sacrificeZone as string | undefined) ?? 'hand',
            ),
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

  // Attack button: face when legal, otherwise the guard. One tap for the
  // common cases; a picker only when several guards could be killed.
  const canAttackButton = canAttackNow && attackInfo.canAttack;
  const handleAttackButton = () => {
    if (!canAttackButton) return;
    if (attackInfo.faceLegal) {
      props.onAttack('player');
      return;
    }
    const killable = foe.board.filter((c) => attackInfo.ids.has(c.instanceId));
    if (killable.length === 1) {
      props.onAttack('champion', killable[0].instanceId);
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
      props.onTriggerAlly(cardId);
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
    <div className="game-table">
      {/* slim top bar */}
      <header className="table-topbar">
        {props.onExit ? (
          <button className="icon-button" onClick={props.onExit} aria-label="Back to lobby">‹</button>
        ) : (
          <span className="icon-button-spacer" aria-hidden="true" />
        )}
        <span className="table-title"><span aria-hidden="true">♜</span> Hero Realms</span>
        <div className="table-top-actions">
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
          <button
            className={`hp-pill foe${attackInfo.faceLegal && canAttackNow ? ' attackable' : ''}`}
            disabled={!(attackInfo.faceLegal && canAttackNow)}
            onClick={() => props.onAttack('player')}
            title={attackInfo.guardsBlocking ? 'Guards must be destroyed first' : attackInfo.faceLegal && canAttackNow ? 'Attack!' : undefined}
          >
            ♥ {foe.hp}
          </button>
          <span className="deck-pip" title="Deck">🂠 {foe.deckCount}</span>
          <span className="deck-pip" title="Hand">🂡 {foe.handCount}</span>
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
                    ? () => props.onAttack('champion', champion.instanceId)
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
        <span className="pools">
          <span className="pool combat" title="Combat">⚔ {me.combat}</span>
          <span className="pool gold" title="Gold">● {me.gold}</span>
        </span>
      </div>
      {props.botBanner}

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
                onClick={() => props.onSacrifice(card.id)}
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
        <div className="player-bar-actions">
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
              onClick={props.onPlayAll}
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
          onResolve={(candidateIndex) => props.onResolveChoice(candidateIndex)}
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
                props.onAttack('champion', c.instanceId);
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
              if (target.kind === 'card') props.onPlay(target.id, index);
              else if (target.kind === 'champion') props.onExpend(target.id, index);
              else props.onTriggerAlly(target.id, index);
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
              <button className="secondary-button" onClick={() => { setInfoOpen(false); props.onRefresh(); }} disabled={busy}>Refresh</button>
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
