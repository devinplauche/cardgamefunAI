from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import random
import time
import uuid
from typing import Any

#: Imported as a module, not `from ... import AGENT_CHOOSES_SACRIFICE`, so the
#: flag is read at call time. hero_ab.paired_experiment flips knobs by setting
#: module globals; a value bound at import would silently ignore the arm.
import hero_engine

from hero_engine import (
    BoardChampion,
    DAGGER,
    FIRE_GEM,
    GOLD,
    HRCard,
    HRMarket,
    HRPlayer,
    RUBY,
    SHORTSWORD,
    auto_expend_all,
    buy_card,
    expend_champion,
    has_ally,
    load_hero_cards,
    play_card,
    remove_stunned_champions,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CARDS_PATH = REPO_ROOT / "data" / "hero_realms_cards.json"
DEFAULT_CARDS = load_hero_cards(str(CARDS_PATH))
#: Legacy fixed-order phases. Retained because tests and older harnesses set
#: `session.phase` explicitly, and because they remain a faithful *subset* of
#: what the real Main Phase permits - useful for reproducing pre-fix baselines.
PHASES = ("play", "champion", "buy", "combat")

#: The printed turn structure is Main -> Discard -> Draw, and within Main the
#: rulebook is explicit: "Any time during your Main Phase, you may perform any
#: of the following, in any order, as many times as you are able: play a card
#: from your hand; use the expend, ally, and/or sacrifice abilities of any of
#: your cards in play; use Gold to acquire new cards from the Market; use
#: Combat to attack an opponent and/or their champions."
#:
#: The old `play -> champion -> buy -> combat` ratchet made whole card effects
#: unreachable: Deception's Guild ally puts an acquired card into hand during
#: the buy phase, by which point the play phase was over, so it could never be
#: played and was discarded unused. Bribe and Rasmus (`top_of_deck`) were
#: degraded the same way.
MAIN_PHASE = "main"

#: New games start in the faithful main phase. Set False to reproduce
#: pre-2026-08 baselines, which were all measured under the ratchet.
FREEFORM_TURN = True

#: Canonical ordering used to sort a main-phase action list. The four
#: categories' `priority` values are on unrelated scales, so they cannot be
#: compared directly; ordering by category first reproduces the legacy phase
#: sequence for a greedy consumer while still offering every legal action.
_ACTION_CATEGORY_ORDER = {
    "play_card": 0,
    "expend_champion": 1,
    "sacrifice_played": 2,
    "buy_card": 3,
    "attack_target": 4,
    "advance_phase": 5,
}

#: Separation between category bands in a main-phase action's `priority`.
#: Raw priorities span roughly -10..40, so 1000 keeps categories from ever
#: overlapping while leaving within-category ordering intact. Main-phase
#: actions also carry `rawPriority` and `categoryRank` for anything that needs
#: the undistorted value.
_CATEGORY_OFFSET = 1000

#: Human labels for the branches of an or_choice card.
_OR_CHOICE_LABEL = {
    "combat": "combat", "gold": "gold", "health": "heal",
    "per_champion_health": "heal per champion",
}


# Action priorities are pure functions of a card, and HRCard is never mutated,
# so they are computed once per distinct card rather than rebuilt on every
# legal_actions() call. legal_actions runs ~25k times per MCTS decision, and
# these lookups were the single largest source of HRCard.get calls (~420k in a
# 12-decision profile). Keyed by card.id, which is unique across the card set
# and the five hardcoded starting/Fire Gem cards (verified: 60 cards, no
# duplicate ids, no id with conflicting stats).
_PLAY_PRIORITY_CACHE: dict[str, int] = {}
_BUY_PRIORITY_CACHE: dict[tuple[str, bool], float] = {}


def _play_priority(card: HRCard) -> int:
    cached = _PLAY_PRIORITY_CACHE.get(card.id)
    if cached is None:
        eff = card.effects
        cached = (card.cost + eff.get("draw", 0) * 3
                  + eff.get("gold", 0) * 2 + eff.get("combat", 0))
        _PLAY_PRIORITY_CACHE[card.id] = cached
    return cached


# Default False reproduces the historical formula exactly - see the note on
# FIX_OR_CHOICE_DOUBLE_COUNT below. Never flip a default here without an A/B;
# this project has repeatedly measured "obviously correct" buy-valuation
# changes as negative (BASELINE.md, "the holistic buy valuation makes the bot
# worse").
FIX_OR_CHOICE_DOUBLE_COUNT = False


def _buy_priority(card: HRCard) -> float:
    # Keyed on the flag too: it is a runtime-togglable knob for A/B testing
    # (hero_buy_priority_ab.py), and the cache must not serve a value computed
    # under the other setting.
    cache_key = (card.id, FIX_OR_CHOICE_DOUBLE_COUNT)
    cached = _BUY_PRIORITY_CACHE.get(cache_key)
    if cached is None:
        eff = card.effects
        import hero_weights as W

        or_choice = eff.get("or_choice", []) if FIX_OR_CHOICE_DOUBLE_COUNT else []
        if or_choice:
            # Branches are mutually exclusive at resolution time (see
            # expend_champion's or_choice handling in hero_engine.py, and the
            # matching fix in _holistic_card_score). Summing every listed
            # field credits value that can never all be realised from one
            # activation - Street Thug and Cult Priest ({gold:1, combat:2/1,
            # or_choice:[gold,combat]}) were unconditionally scored as if they
            # granted both every time. Only combat/gold/draw participate,
            # matching what _buy_priority has ever priced - health was never
            # in this formula (see hero_weights.py's docstring), so a
            # combat/health or_choice like Darian, War Mage's is unaffected.
            branch_weights = {"combat": W.get("buy_combat"), "gold": W.get("buy_gold"),
                              "draw": W.get("buy_draw")}
            resource = max((eff.get(kind, 0) * branch_weights[kind]
                           for kind in or_choice if kind in branch_weights),
                          default=0.0)
        else:
            resource = (eff.get("combat", 0) * W.get("buy_combat")
                       + eff.get("gold", 0) * W.get("buy_gold")
                       + eff.get("draw", 0) * W.get("buy_draw"))
        cached = card.cost * W.get("buy_cost") + resource
        ally = (eff.get("ally_combat", 0) + eff.get("ally_gold", 0)
                + eff.get("ally_health", 0) + eff.get("ally_draw", 0))
        cached += ally * W.get("buy_ally")
        if eff.get("sacrifice_card"):
            cached += W.get("buy_sacrifice")
        _BUY_PRIORITY_CACHE[cache_key] = cached
    return cached


def _copy_champion(champion: BoardChampion) -> BoardChampion:
    clone = BoardChampion.__new__(BoardChampion)
    clone.card = champion.card  # HRCard is never mutated; share the reference
    clone.current_health = champion.current_health
    clone.exhausted = champion.exhausted
    clone.guard = champion.guard
    # Preserved, not regenerated: this clone represents the same logical
    # champion instance across a simulation, and the counter that assigns
    # instance_id is process-global, so re-deriving it here would both
    # diverge from the original and burn extra ids needlessly.
    clone.instance_id = champion.instance_id
    return clone


def _copy_player(player: HRPlayer, rng: random.Random) -> HRPlayer:
    clone = HRPlayer.__new__(HRPlayer)
    clone.name = player.name
    clone._rng = rng
    clone.hp = player.hp
    clone.gold = player.gold
    clone.combat = player.combat
    # Card lists hold shared HRCard references, so the containers need copying
    # but their contents do not. Starting decks are literally [GOLD] * 7 of the
    # same object already.
    clone.deck = player.deck[:]
    clone.hand = player.hand[:]
    clone.discard = player.discard[:]
    clone.banish = player.banish[:]
    clone.board = [_copy_champion(champion) for champion in player.board]
    clone.played_this_turn = player.played_this_turn[:]
    clone.pending_ally = player.pending_ally[:]
    clone.pending_per_champion = [dict(e) for e in player.pending_per_champion]
    clone.pending_stun_targets = player.pending_stun_targets[:]
    clone.pending_prepares = player.pending_prepares
    # Deferred sacrifice/discard targeting. Dicts are copied, not aliased -
    # apply_choice decrements "count" in place, so a shared dict would let a
    # simulated branch consume the real game's pending choice.
    clone.pending_choices = [dict(c) for c in player.pending_choices]
    clone.defer_choices = player.defer_choices
    # Simulation clones are never shown to anyone, and play_card runs ~25k
    # times per MCTS decision, so the narration is switched off rather than
    # built and discarded.
    clone.effect_log = []
    clone.log_effects = False
    clone.actions_played = player.actions_played
    clone.cards_bought = player.cards_bought
    clone.next_buy_to_hand = player.next_buy_to_hand
    clone.next_buy_to_top = player.next_buy_to_top
    clone.next_buy_to_top_action_only = player.next_buy_to_top_action_only
    return clone


def _remap_pending_stun_targets(player: HRPlayer, opponent: HRPlayer) -> None:
    """Point deferred stun effects at champions in the cloned game state.

    ``pending_stun_targets`` is the only player field whose payload can hold a
    mutable game object.  A shallow tuple copy leaves it pointing at the live
    opponent board, which makes a later ally-triggered stun silently fail in a
    simulation because that object is not one of the clone's legal targets.
    """
    cloned_targets = {champion.instance_id: champion for champion in opponent.board}
    remapped: list[tuple[HRCard, BoardChampion | None]] = []
    for card, target in player.pending_stun_targets:
        if target is None:
            remapped.append((card, None))
            continue
        # A target normally remains on the opponent's board until its pending
        # ally fires.  Preserve the engine's "target no longer legal" behavior
        # if a custom state has already removed it, without retaining a live
        # BoardChampion reference in the clone.
        remapped.append((card, cloned_targets.get(target.instance_id, _copy_champion(target))))
    player.pending_stun_targets = remapped


def _copy_market(market: HRMarket, rng: random.Random) -> HRMarket:
    # __new__ rather than __init__: the constructor shuffles the pool.
    clone = HRMarket.__new__(HRMarket)
    clone.pool = market.pool[:]
    clone.fire_gems_remaining = market.fire_gems_remaining
    clone.row = market.row[:]
    return clone


def _card_view(card: HRCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "name": card.name,
        "cost": card.cost,
        "faction": card.faction,
        "cardType": card.card_type,
        "guard": card.guard,
        "health": card.health,
        "effects": card.effects,
        "text": card.text,
    }


def _champion_view(champion) -> dict[str, Any]:
    base = _card_view(champion.card)
    base.update(
        {
            "currentHealth": champion.current_health,
            "exhausted": champion.exhausted,
            "alive": champion.alive,
            # Distinguishes two board champions sharing the same card.id
            # (a card printed in 2-3 copies can appear twice on one board).
            # Matches the championId used in legal_actions/expend/attack.
            "instanceId": str(champion.instance_id),
        }
    )
    return base


def _player_view(player: HRPlayer, reveal_hand: bool) -> dict[str, Any]:
    return {
        "name": player.name,
        "hp": player.hp,
        "gold": player.gold,
        "combat": player.combat,
        "deckCount": len(player.deck),
        "handCount": len(player.hand),
        "discardCount": len(player.discard),
        "banishCount": len(player.banish),
        "nextBuyToHand": player.next_buy_to_hand,
        "nextBuyToTop": player.next_buy_to_top,
        "nextBuyToTopActionOnly": player.next_buy_to_top_action_only,
        "hand": [_card_view(card) for card in player.hand] if reveal_hand else [],
        # Non-champion cards still in play this turn. Needed by the UI to offer
        # a card's own "Sacrifice this card:" bonus, which is optional and the
        # player's to take - Fire Gem gives 2 gold on play and *may then* be
        # sacrificed for 3 combat. Always visible: these are face-up in play.
        "playedThisTurn": [_card_view(card) for card in player.played_this_turn],
        "board": [_champion_view(champion) for champion in player.board if champion.alive],
    }


def _market_view(market: HRMarket) -> dict[str, Any]:
    return {
        "row": [_card_view(card) if card else None for card in market.row_cards()],
        "fireGemsRemaining": market.fire_gems_remaining,
    }


@dataclass(frozen=True)
class PublicOpponentPurchase:
    """A buy observation visible to the bot, with no private-zone identities."""

    gold_before_buy: int
    buy_options: tuple[tuple[int, str], ...]
    chosen_market_index: int


@dataclass
class GameSession:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    seed: int | None = None
    algorithm: str = "mcts"
    budget_ms: int = 60
    cards: list[HRCard] = field(default_factory=lambda: list(DEFAULT_CARDS))
    player: HRPlayer = field(init=False)
    bot: HRPlayer = field(init=False)
    market: HRMarket = field(init=False)
    turn_number: int = field(default=1)
    active_player: str = field(default="player")
    phase: str = field(default="play")
    winner: str | None = field(default=None)
    log: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    history_sequence: int = field(default=0)
    last_bot_insight: dict[str, Any] | None = field(default=None)
    opponent_purchase_observations: tuple[PublicOpponentPurchase, ...] = ()
    record_history: bool = field(default=True)
    rng: random.Random = field(init=False, repr=False)
    _normal_market_cards: tuple[HRCard, ...] = field(init=False, repr=False)
    _full_inventory: tuple[HRCard, ...] = field(init=False, repr=False)
    _inventory_counts: Counter[str] = field(init=False, repr=False)
    _inventory_cards_by_id: dict[str, HRCard] = field(init=False, repr=False)
    _market_card_ids: frozenset[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._normal_market_cards = tuple(
            card for card in self.cards if card.name.lower() != "fire gem"
        )
        self._full_inventory = (
            self._normal_market_cards
            + (FIRE_GEM,) * 16
            + (GOLD,) * 14
            + (SHORTSWORD,) * 2
            + (DAGGER,) * 2
            + (RUBY,) * 2
        )
        self._inventory_counts = Counter(card.id for card in self._full_inventory)
        self._inventory_cards_by_id = {
            card.id: card for card in self._full_inventory
        }
        self._market_card_ids = frozenset(
            card.id for card in self._normal_market_cards
        )
        self.rng = random.Random(self.seed)
        self.player = HRPlayer("Player", self.rng)
        self.bot = HRPlayer("Bot", self.rng)
        self.player.setup_starting_deck()
        self.bot.setup_starting_deck()
        self.player.draw(3)
        self.bot.draw(5)
        self.market = HRMarket(self.cards, self.rng)
        self.phase = MAIN_PHASE if FREEFORM_TURN else "play"
        self._start_turn(self.player)
        self.record_event("system", "Game created")

    def clone(self) -> "GameSession":
        """Simulation copy: only the mutable game state, nothing else.

        This is the MCTS inner loop, so it is hand-written rather than a
        deepcopy. deepcopy walked every HRCard in both decks and the market pool
        - none of which are ever mutated - plus history and log, where each
        history entry holds a full state snapshot.

        history/log/insight are presentation-only and are dropped: clones never
        surface to a user, and record_history=False stops rollouts rebuilding
        state snapshots on every action.

        Covered by test_clone_copies_every_field, which fails if a new field is
        added to GameSession and not handled here.
        """
        clone = GameSession.__new__(GameSession)
        clone.session_id = self.session_id
        clone.seed = self.seed
        clone.algorithm = self.algorithm
        clone.budget_ms = self.budget_ms
        clone.cards = self.cards  # read-only card definitions, shared
        clone.rng = random.Random()
        clone.rng.setstate(self.rng.getstate())
        clone.player = _copy_player(self.player, clone.rng)
        clone.bot = _copy_player(self.bot, clone.rng)
        _remap_pending_stun_targets(clone.player, clone.bot)
        _remap_pending_stun_targets(clone.bot, clone.player)
        clone.market = _copy_market(self.market, clone.rng)
        clone.turn_number = self.turn_number
        clone.active_player = self.active_player
        clone.phase = self.phase
        clone.winner = self.winner
        clone.log = []
        clone.history = []
        clone.history_sequence = self.history_sequence
        clone.last_bot_insight = None
        clone.opponent_purchase_observations = self.opponent_purchase_observations
        clone.record_history = False
        # Immutable card objects plus read-only-by-convention inventory
        # templates are safe to share. Each determinization copies the Counter
        # before subtracting public cards.
        clone._normal_market_cards = self._normal_market_cards
        clone._full_inventory = self._full_inventory
        clone._inventory_counts = self._inventory_counts
        clone._inventory_cards_by_id = self._inventory_cards_by_id
        clone._market_card_ids = self._market_card_ids
        return clone

    def determinize_for_bot(self, rng: random.Random, *,
                            allow_private_test_fallback: bool = False) -> "GameSession":
        """Build one fair, sampled world for bot search.

        The live session deliberately contains both players' complete zones,
        while the UI exposes the human's zone *counts* only. Information-set
        search therefore reconstructs every hidden human zone and the unseen
        market from public inventory constraints. The original session is
        never mutated.
        """
        clone = self.clone()

        # The bot knows its own cards but not its future draw order.
        rng.shuffle(clone.bot.deck)

        # Reconstruct all hidden cards from the public inventory. Market cards
        # come from the configured pool; Fire Gems and both starting decks are
        # separate piles in the engine. Subtract only public zones: bot-owned
        # cards, both boards/in-play cards, the visible market row, and the
        # public Fire Gem side pile. Human hand/deck/discard/banish identities
        # and the unseen market pool are deliberately never read back.
        public_cards = (
            clone.bot.deck + clone.bot.hand + clone.bot.discard + clone.bot.banish
            + clone.bot.played_this_turn
            + [champion.card for champion in clone.bot.board]
            + clone.player.played_this_turn
            + [champion.card for champion in clone.player.board]
            + [card for card in clone.market.row if card is not None]
            + [FIRE_GEM] * clone.market.fire_gems_remaining
        )
        inventory = clone._inventory_counts.copy()
        for card in public_cards:
            if inventory[card.id] <= 0:
                if allow_private_test_fallback:
                    return self._fallback_determinization(clone, rng)
                raise ValueError(
                    "Cannot fairly determinize: public card is absent from "
                    "the configured inventory"
                )
            inventory[card.id] -= 1

        unknown_cards = [
            clone._inventory_cards_by_id[card_id]
            for card_id, count in inventory.items()
            for _ in range(count)
        ]
        human_zone_sizes = (
            len(clone.player.hand), len(clone.player.deck),
            len(clone.player.discard), len(clone.player.banish),
        )
        market_pool_size = len(clone.market.pool)
        if len(unknown_cards) != sum(human_zone_sizes) + market_pool_size:
            if allow_private_test_fallback:
                return self._fallback_determinization(clone, rng)
            raise ValueError(
                "Cannot fairly determinize: public inventory does not match "
                "the hidden-zone sizes"
            )

        # Starting cards and Fire Gems cannot be in the market deck. Choose
        # the hidden market first, then distribute the remaining cards through
        # the human's hidden zones while preserving every visible count.
        market_candidates = [
            card for card in unknown_cards if card.id in clone._market_card_ids
        ]
        if len(market_candidates) < market_pool_size:
            if allow_private_test_fallback:
                return self._fallback_determinization(clone, rng)
            raise ValueError(
                "Cannot fairly determinize: configured market inventory is "
                "too small for the hidden market"
            )
        rng.shuffle(market_candidates)
        clone.market.pool = market_candidates[:market_pool_size]
        selected_market = Counter(card.id for card in clone.market.pool)
        human_unknown = []
        for card in unknown_cards:
            if selected_market[card.id]:
                selected_market[card.id] -= 1
            else:
                human_unknown.append(card)
        rng.shuffle(human_unknown)
        hand_size, deck_size, discard_size, banish_size = human_zone_sizes
        clone.player.hand = human_unknown[:hand_size]
        clone.player.deck = human_unknown[hand_size:hand_size + deck_size]
        clone.player.discard = human_unknown[hand_size + deck_size:hand_size + deck_size + discard_size]
        clone.player.banish = human_unknown[hand_size + deck_size + discard_size:
                                             hand_size + deck_size + discard_size + banish_size]

        # Future reshuffles need an independent sampled RNG as well.  Both
        # players share the game RNG, matching the live session's mechanics.
        clone.rng = random.Random(rng.getrandbits(128))
        clone.player._rng = clone.rng
        clone.bot._rng = clone.rng
        return clone

    @staticmethod
    def _fallback_determinization(clone: "GameSession", rng: random.Random) -> "GameSession":
        """Test-only sampler for synthetic states with no public inventory.

        This reads private-zone composition and must never be selected
        implicitly by production search.
        """
        hand_size = len(clone.player.hand)
        private_cards = clone.player.hand + clone.player.deck
        rng.shuffle(private_cards)
        clone.player.hand = private_cards[:hand_size]
        clone.player.deck = private_cards[hand_size:]
        rng.shuffle(clone.market.pool)
        clone.rng = random.Random(rng.getrandbits(128))
        clone.player._rng = clone.rng
        clone.bot._rng = clone.rng
        return clone

    def _start_turn(self, player: HRPlayer) -> None:
        player.gold = 0
        player.combat = 0
        player.actions_played = 0
        player.discard_played_cards()
        player.pending_ally.clear()
        player.pending_per_champion.clear()
        player.pending_stun_targets.clear()
        player.pending_prepares = 0
        player.pending_choices.clear()
        player.cards_bought = 0
        player.next_buy_to_hand = False
        player.next_buy_to_top = False
        player.next_buy_to_top_action_only = False
        for champion in player.board:
            champion.exhausted = False
            # Damage to champions does not carry over between turns.
            champion.current_health = champion.card.health

    def _current(self) -> HRPlayer:
        return self.player if self.active_player == "player" else self.bot

    def _opponent(self) -> HRPlayer:
        return self.bot if self.active_player == "player" else self.player

    def _attack_targets(self, opponent: HRPlayer) -> list[BoardChampion]:
        """Legal combat/stun targets: guards while any are alive (they block
        both the player and other champions), otherwise every living champion
        - a champion is a legal target once nothing protects it (rulebook:
        "You may use Combat to attack your opponent and/or their Champions")."""
        living = [champion for champion in opponent.board if champion.alive]
        guards = [champion for champion in living if champion.guard]
        return guards or living

    def _stun_target(self, opponent: HRPlayer, target_index: int | None) -> BoardChampion | None:
        targets = self._attack_targets(opponent)
        if not targets:
            return None
        if target_index is None:
            raise ValueError("Choose a champion to stun; guards must be stunned first")
        if not isinstance(target_index, int) or not 0 <= target_index < len(targets):
            raise ValueError("Invalid stun target")
        return targets[target_index]

    def _check_winner(self) -> None:
        if self.player.hp <= 0 and self.bot.hp <= 0:
            self.winner = "draw"
        elif self.player.hp <= 0:
            self.winner = "bot"
        elif self.bot.hp <= 0:
            self.winner = "player"

    def log_event(self, message: str, kind: str = "system", bot_insight: dict[str, Any] | None = None) -> None:
        self.log.append(
            {
                "kind": kind,
                "message": message,
                "turn": self.turn_number,
                "phase": self.phase,
                "activePlayer": self.active_player,
                "at": round(time.time(), 3),
                "botInsight": bot_insight,
            }
        )
        self.log = self.log[-50:]

    def _core_state(self) -> dict[str, Any]:
        self._check_winner()
        return {
            "sessionId": self.session_id,
            "turnNumber": self.turn_number,
            "phase": self.phase,
            "activePlayer": self.active_player,
            "winner": self.winner,
            "player": _player_view(self.player, reveal_hand=True),
            "bot": _player_view(self.bot, reveal_hand=False),
            "market": _market_view(self.market),
            "legalActions": self.legal_actions(),
            "log": self.log[-20:],
            "botInsight": self.last_bot_insight,
        }

    def record_event(self, kind: str, label: str, bot_insight: dict[str, Any] | None = None) -> None:
        # Simulation clones skip this entirely: every call serialises a full
        # state snapshot, which is pure overhead inside an MCTS rollout.
        if not self.record_history:
            return
        insight = bot_insight if bot_insight is not None else self.last_bot_insight
        self.log_event(label, kind, bot_insight=insight)
        self.history_sequence += 1
        self.history.append(
            {
                "id": f"{self.turn_number}-{self.history_sequence}",
                "kind": kind,
                "label": label,
                "turn": self.turn_number,
                "phase": self.phase,
                "activePlayer": self.active_player,
                "botInsight": insight,
                "state": self._core_state(),
            }
        )
        self.history = self.history[-80:]

    def _play_card_actions(self, player, opponent) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for card in player.hand:
            needs_stun_target = card.get("stun", False)
            stun_targets = self._attack_targets(opponent) if needs_stun_target else []
            if stun_targets:
                for target_index, target in enumerate(stun_targets):
                    actions.append({
                        "type": "play_card", "cardId": card.id,
                        "stunTargetIndex": target_index,
                        "label": f"{card.name} → {target.name}",
                        "priority": _play_priority(card),
                    })
            else:
                actions.append({
                    "type": "play_card", "cardId": card.id,
                    "label": card.name, "priority": _play_priority(card),
                })
        return actions

    def _expend_champion_actions(self, player, opponent) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for champion in player.board:
            if not (champion.alive and not champion.exhausted):
                continue
            stun_targets = (self._attack_targets(opponent)
                            if champion.card.get("stun", False) else [])
            if stun_targets:
                for target_index, target in enumerate(stun_targets):
                    actions.append({
                        "type": "expend_champion", "championId": str(champion.instance_id),
                        "stunTargetIndex": target_index,
                        "label": f"{champion.card.name} → {target.name}",
                        "priority": champion.card.cost + champion.card.health,
                    })
                continue
            # "Expend: gain 1 gold *or* gain 1 combat" is the player's choice,
            # so offer one action per branch. Without this the engine's
            # heuristic silently picked - Cult Priest always took gold, even at
            # 5 HP where combat is plainly better - and no caller could ask for
            # the other branch.
            branches = [kind for kind in champion.card.get("or_choice", [])
                        if champion.card.get(kind, 0)]
            if len(branches) > 1:
                for kind in branches:
                    actions.append({
                        "type": "expend_champion",
                        "championId": str(champion.instance_id),
                        "choice": kind,
                        "label": f"{champion.card.name}: {_OR_CHOICE_LABEL.get(kind, kind)}",
                        "priority": champion.card.cost + champion.card.health,
                    })
            else:
                actions.append({
                    "type": "expend_champion", "championId": str(champion.instance_id),
                    "label": champion.card.name,
                    "priority": champion.card.cost + champion.card.health,
                })
            actions.extend(self._expend_sacrifice_actions(player, champion))
        return actions

    def _expend_sacrifice_actions(self, player, champion) -> list[dict[str, Any]]:
        """"You may sacrifice a card... if you do, gain 2 more combat" (Lys,
        Krythos) as one action per candidate.

        Playing the UI by hand found this taking a Gold out of hand with no
        prompt and no log line, so neither a human nor MCTS could decline it or
        pick a different card. Only offered while AGENT_CHOOSES_SACRIFICE is
        set; the plain expend action above is the "decline" branch.
        """
        amount = champion.card.get("sacrifice_for_combat", 0)
        if not amount or not hero_engine.AGENT_CHOOSES_SACRIFICE:
            return []
        zone = "hand" if player.hand else ("discard" if player.discard else None)
        if zone is None:
            return []
        source = player.hand if zone == "hand" else player.discard
        # Identical cards are interchangeable here, so offering one action per
        # duplicate would multiply the branching factor for nothing - and this
        # project has measured a 9-11pp loss from widening a search root.
        seen: set[str] = set()
        actions: list[dict[str, Any]] = []
        for index, card in enumerate(source):
            if card.id in seen:
                continue
            seen.add(card.id)
            actions.append({
                "type": "expend_champion",
                "championId": str(champion.instance_id),
                "sacrificeIndex": index,
                "sacrificeZone": zone,
                "label": f"{champion.card.name} + sacrifice {card.name} "
                         f"(+{amount} combat)",
                "priority": champion.card.cost + champion.card.health + amount,
            })
        return actions

    def _drain_effect_log(self, *players) -> None:
        """Surface effects the engine resolved by itself.

        A sacrifice or forced discard mutates a zone without any action being
        taken for it, so nothing else in this class knows to log it. Playing
        the UI by hand found Lys removing a card from hand and Fire Gem
        banishing itself with no trace in the log either time. Drained for both
        players because forced discards hit the opponent.
        """
        for player in players:
            if not player:
                continue
            for message in player.effect_log:
                self.record_event("effect", f"{player.name}: {message}")
            player.effect_log.clear()

    def _sacrifice_played_actions(self, player) -> list[dict[str, Any]]:
        """Cards in play whose own "Sacrifice this card:" bonus is unclaimed.

        Fire Gem reads "Gain 2 gold. Sacrifice this card: gain 3 combat" - two
        separate things, the second optional and the player's to take. The
        engine decided via `_should_self_sacrifice` and, when it declined, left
        no way to ask, so a human could take the gold and never the combat.
        """
        actions: list[dict[str, Any]] = []
        for card in player.played_this_turn:
            amount = card.get("sacrifice_combat", 0)
            if amount:
                actions.append({
                    "type": "sacrifice_played", "cardId": card.id,
                    "label": f"Sacrifice {card.name}: +{amount} combat",
                    "priority": amount,
                })
        return actions

    def _buy_card_actions(self, player) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for idx, card in enumerate(self.market.row_cards()):
            if card and card.cost <= player.gold:
                actions.append({
                    "type": "buy_card", "marketIndex": idx,
                    "label": card.name, "priority": _buy_priority(card),
                })
        if player.gold >= 2 and self.market.can_buy_fire_gem():
            actions.append({
                "type": "buy_card", "marketIndex": 5,
                "label": "Fire Gem", "priority": 6,
            })
        return actions

    def _attack_actions(self, player, opponent) -> list[dict[str, Any]]:
        # Combat can only be assigned if there is combat to assign. Offering
        # guard targets at 0 combat made attack_target_action raise.
        if player.combat <= 0:
            return []
        actions: list[dict[str, Any]] = []
        targets = self._attack_targets(opponent)
        guards_present = bool(targets) and targets[0].guard
        for champion in targets:
            actions.append({
                "type": "attack_target", "target": "champion",
                "championId": str(champion.instance_id),
                "label": champion.card.name,
                "priority": 10 - champion.current_health,
            })
        # Once no guard is protecting them, the rulebook allows attacking the
        # player and/or any champion freely - a guard blocks both, so this is
        # only offered when none remain.
        if not guards_present:
            actions.append({
                "type": "attack_target", "target": "player",
                "label": opponent.name, "priority": player.combat,
            })
        return actions

    def legal_actions(self) -> list[dict[str, Any]]:
        if self.winner:
            return []

        player = self._current()
        opponent = self._opponent()

        if self.phase == MAIN_PHASE:
            actions = (self._play_card_actions(player, opponent)
                       + self._expend_champion_actions(player, opponent)
                       + self._sacrifice_played_actions(player)
                       + self._buy_card_actions(player)
                       + self._attack_actions(player, opponent))
            actions.append({"type": "advance_phase", "label": "End Turn", "priority": -10})
            # The four groups' raw `priority` values are on unrelated scales
            # (play uses _play_priority, buy uses _buy_priority, combat uses
            # target health), so comparing them directly is meaningless - and
            # every consumer in this repo picks its action with
            # `max(actions, key=priority)`. Rather than change all of them,
            # make the scales comparable: offset each category so category
            # order dominates and the raw priority only breaks ties within a
            # category. `max` by priority then yields exactly the action the
            # legacy phase sequence would have produced, while every legal
            # action is still *offered* - which is what the printed rules
            # require, and what makes a card acquired to hand mid-turn
            # playable again.
            for action in actions:
                rank = _ACTION_CATEGORY_ORDER.get(action["type"], 99)
                action["categoryRank"] = rank
                action["rawPriority"] = action.get("priority", 0)
                action["priority"] = action["rawPriority"] + (5 - rank) * _CATEGORY_OFFSET
            return sorted(actions, key=lambda item: item["priority"], reverse=True)

        actions = []
        if self.phase == "play":
            actions = self._play_card_actions(player, opponent)
        elif self.phase == "champion":
            actions = (self._expend_champion_actions(player, opponent)
                       + self._sacrifice_played_actions(player))
        elif self.phase == "buy":
            actions = self._buy_card_actions(player)
        elif self.phase == "combat":
            actions = self._attack_actions(player, opponent)

        actions.append({"type": "advance_phase", "label": "Next Phase", "priority": -10})
        return sorted(actions, key=lambda item: item.get("priority", 0), reverse=True)

    def play_card(self, card_id: str, stun_target_index: int | None = None) -> dict[str, Any]:
        player = self._current()
        opponent = self._opponent()
        if self.phase not in ("play", MAIN_PHASE):
            raise ValueError("Cards can only be played during the main phase")
        card = next((item for item in player.hand if item.id == card_id), None)
        if card is None:
            raise ValueError("Card not found in hand")

        ally_bonus = has_ally(card, player)
        needs_stun_target = card.get("stun", False)
        stun_target = self._stun_target(opponent, stun_target_index) if needs_stun_target else None
        play_card(player, card, self.market, ally_bonus=ally_bonus, opponent=opponent,
                  stun_target=stun_target)
        self.record_event("play", f"Played {card.name}")
        self._drain_effect_log(player, opponent)
        self._check_winner()
        return self.get_state()

    def expend_champion_action(self, champion_id: str,
                                stun_target_index: int | None = None,
                                choice: str | None = None,
                                sacrifice_index: int | None = None,
                                sacrifice_zone: str = "hand") -> dict[str, Any]:
        player = self._current()
        opponent = self._opponent()
        if self.phase not in ("champion", MAIN_PHASE):
            raise ValueError("Champions can only be expended during the main phase")
        champion = next((item for item in player.board if str(item.instance_id) == champion_id), None)
        if champion is None:
            raise ValueError("Champion not found")
        stun_target = self._stun_target(opponent, stun_target_index) if champion.card.get("stun", False) else None
        # `choice` names an or_choice branch ("gain 1 gold *or* 1 combat").
        # None leaves the engine's heuristic in charge, which is what every
        # simulated game and the bot's rollouts rely on.
        if not expend_champion(player, champion, opponent, stun_target=stun_target,
                               choice=choice, sacrifice_index=sacrifice_index,
                               sacrifice_zone=sacrifice_zone):
            raise ValueError("Champion could not be expended")

        detail = f" ({_OR_CHOICE_LABEL.get(choice, choice)})" if choice else ""
        self.record_event("expend", f"Expended {champion.card.name}{detail}")
        self._drain_effect_log(player, opponent)
        self._check_winner()
        return self.get_state()

    def sacrifice_played_action(self, card_id: str) -> dict[str, Any]:
        """Take a played card's own "Sacrifice this card:" bonus.

        Separate from the card's on-play effect, and optional - Fire Gem gives
        2 gold when played and *may then* be sacrificed for 3 combat. The card
        is banished (removed from the game), matching how the engine already
        resolves a self-sacrifice it decides to take.
        """
        player = self._current()
        if self.phase not in ("champion", MAIN_PHASE):
            raise ValueError("Cards can only be sacrificed during the main phase")
        card = next((item for item in player.played_this_turn if item.id == card_id), None)
        if card is None:
            raise ValueError("Card is not in play")
        amount = card.get("sacrifice_combat", 0)
        if not amount:
            raise ValueError("That card has no sacrifice ability")

        player.combat += amount
        player.played_this_turn.remove(card)
        player.banish.append(card)
        self.record_event("sacrifice", f"Sacrificed {card.name} for {amount} combat")
        self._check_winner()
        return self.get_state()

    def buy_card_action(self, market_index: int) -> dict[str, Any]:
        player = self._current()
        if self.phase not in ("buy", MAIN_PHASE):
            raise ValueError("Cards can only be bought during the main phase")
        if not isinstance(market_index, int) or not 0 <= market_index <= 5:
            raise ValueError("Invalid market index")
        label = "Fire Gem"
        if market_index != 5:
            current_card = self.market.row_cards()[market_index]
            label = current_card.name if current_card else "Market card"

        observation = None
        if self.record_history and self.active_player == "player":
            # Capture the public legal choices before this purchase mutates the
            # row or spends gold. The player is MCTS's opponent; their private
            # zones are deliberately not present in this immutable record.
            buy_options = tuple(
                (int(action["marketIndex"]), str(action["label"]))
                for action in self.legal_actions()
                if action["type"] == "buy_card"
            )
            # Labels are names for presentation, but card ids are needed to
            # replay profile valuation exactly. Resolve them only from the
            # visible row / Fire Gem side pile, never from a private zone.
            visible_ids = {
                index: card.id for index, card in enumerate(self.market.row_cards()) if card is not None
            }
            if self.market.can_buy_fire_gem():
                visible_ids[5] = FIRE_GEM.id
            observation = PublicOpponentPurchase(
                gold_before_buy=player.gold,
                buy_options=tuple(
                    (index, visible_ids[index]) for index, _ in buy_options if index in visible_ids
                ),
                chosen_market_index=market_index,
            )

        if buy_card(player, self.market, market_index):
            if observation is not None:
                self.opponent_purchase_observations += (observation,)
            self.record_event("buy", f"Bought {label}")
        else:
            raise ValueError("Purchase failed")

        self._check_winner()
        return self.get_state()

    def attack_target_action(self, target_kind: str, champion_id: str | None = None) -> dict[str, Any]:
        player = self._current()
        opponent = self._opponent()
        if self.phase not in ("combat", MAIN_PHASE):
            raise ValueError("Combat attacks can only happen during the main phase")
        if player.combat <= 0:
            raise ValueError("No combat remaining")

        targets = self._attack_targets(opponent)
        guards_present = bool(targets) and targets[0].guard
        if target_kind == "player":
            if guards_present:
                raise ValueError("Guards must be attacked before the player")
            dealt = player.combat
            opponent.hp -= dealt
            player.combat = 0
            self.record_event("combat", f"Dealt {dealt} combat to {opponent.name}")
            self._check_winner()
            return self.get_state()

        champion = next((item for item in targets if str(item.instance_id) == champion_id), None)
        if champion is None:
            raise ValueError("Champion not found or not a legal target")

        dealt = min(player.combat, champion.current_health)
        champion.current_health -= dealt
        player.combat -= dealt
        if not champion.alive:
            # Stunned champions go to their owner's discard pile.
            remove_stunned_champions(opponent)
        self.record_event("combat", f"Assigned {dealt} combat to {champion.card.name}")

        # No auto-spill of any leftover combat: once a guard is gone, the
        # player may freely choose to assign the remainder to the opponent's
        # face or to another champion (rulebook: "you may use Combat to
        # attack your opponent and/or their Champions"), so it is left in
        # player.combat for an explicit follow-up attack_target_action call.

        self._check_winner()
        return self.get_state()

    def advance_phase(self) -> dict[str, Any]:
        if self.winner:
            return self.get_state()

        current = self.phase
        if current == MAIN_PHASE:
            # Main is the only phase a player acts in, so "advance" ends the
            # turn (the printed Discard and Draw phases are what end_turn does).
            self.end_turn()
            return self.get_state()
        if current == "play":
            self.phase = "champion"
        elif current == "champion":
            self.phase = "buy"
        elif current == "buy":
            self.phase = "combat"
        elif current == "combat":
            self.end_turn()
            return self.get_state()
        else:
            raise ValueError("Unknown phase")

        self.record_event("phase", f"Advanced to {self.phase} phase")
        return self.get_state()

    def end_turn(self) -> dict[str, Any]:
        if self.winner:
            return self.get_state()

        current = self._current()
        current.discard_played_cards()
        for card in list(current.hand):
            current.discard.append(card)
        current.hand.clear()
        current.draw(5)

        self.active_player = "bot" if self.active_player == "player" else "player"
        self.turn_number += 1
        self.phase = MAIN_PHASE if FREEFORM_TURN else "play"
        self._start_turn(self._current())
        self.record_event("turn", f"{current.name} ended turn")
        self.record_event("turn", f"{self._current().name} started turn")
        self._check_winner()
        return self.get_state()

    def run_bot_turn(self) -> dict[str, Any]:
        from web.bot import run_bot_turn

        if self.active_player != "bot" or self.winner:
            return self.get_state()
        insight = run_bot_turn(self, budget_ms=self.budget_ms, algorithm=self.algorithm)
        self.last_bot_insight = insight
        self._check_winner()
        return self.get_state()

    def get_state(self) -> dict[str, Any]:
        # Every action handler (play_card, buy_card_action, attack_target_action,
        # advance_phase, end_turn) returns self.get_state(), and apply_action
        # discards it. Inside an MCTS rollout that meant serialising both hands,
        # both boards, the market and legal_actions on *every* action, purely to
        # throw it away - measured at ~32% of total rollout time.
        #
        # _check_winner() still has to run: it is the only thing that sets
        # self.winner, which the rollout loop and evaluate_state both depend on.
        if not self.record_history:
            self._check_winner()
            return {}
        state = self._core_state()
        state["history"] = self.history[-40:]
        return state


def create_session(seed: int | None = None, algorithm: str = "mcts", budget_ms: int = 60) -> GameSession:
    return GameSession(seed=seed, algorithm=algorithm, budget_ms=budget_ms)
