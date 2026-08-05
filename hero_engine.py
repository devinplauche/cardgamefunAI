"""Hero Realms game engine — deck-building card game simulation."""

from __future__ import annotations
import itertools
import json
import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class HRCard:
    id: str
    name: str
    cost: int
    faction: str
    card_type: str  # champion, action, item
    subtypes: list = field(default_factory=list)
    guard: int = 0
    health: int = 0
    effects: dict = field(default_factory=dict)
    text: str = ""

    def get(self, key: str, default=0):
        return self.effects.get(key, default)


def load_hero_cards(path: str) -> list[HRCard]:
    """Load every card, expanded to the correct number of physical copies.

    The card data used to have exactly one entry per unique card, so a market
    deck built from it had 54 cards where the base set ships 80 (18 of the 55
    cards are printed in 2 or 3 copies - Taxation and Profit at 3x each,
    Man-at-Arms and Wolf Shaman at 2x, and so on). Every simulated game -
    RL training, benchmarks, MCTS, the web app - drew from a market skewed
    toward treating every card as equally rare, when the physical game does
    not: a 3x common should show up roughly 3x as often as a 1x rare.

    Duplicate copies share the same HRCard instance (matching the existing
    convention for GOLD/SHORTSWORD/DAGGER/RUBY, which are already `[GOLD] *
    7` etc.), safe because HRCard is never mutated anywhere in the engine.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cards = []
    for c in data:
        c["card_type"] = c.pop("type", "action")
        c.pop("location", None)
        c.pop("subtypes", None)
        quantity = c.pop("quantity", 1)
        card = HRCard(**c)
        cards.extend([card] * quantity)
    return cards


# --- Starting cards (Hero Realms base set) ---
GOLD = HRCard(id="gold", name="Gold", cost=0, faction="",
              card_type="treasure", effects={"gold": 1})
SHORTSWORD = HRCard(id="shortsword", name="Shortsword", cost=0, faction="",
                    card_type="action", effects={"combat": 2})
DAGGER = HRCard(id="dagger", name="Dagger", cost=0, faction="",
                card_type="action", effects={"combat": 1})
# Ruby is a *treasure worth 2 gold*, not a 1-health action. It was wrong here
# from the start, which cost every player 2 gold per deck cycle - a 29% cut to
# starting economy (7 gold per cycle instead of 9).
#
# How it survived: tools/audit_cards.py compares printed text to the effects
# dict for the 55 cards in data/hero_realms_cards.json, and these five starting
# cards are hardcoded here instead, so they were never in its scope. BASELINE.md
# records that audit concluding "the card data is clean". The QA documents tick
# "Starting deck: 7 Gold + 1 Shortsword + 1 Dagger + 1 Ruby" - which verifies
# the deck's *composition* and never any card's *effects*. The one card checked
# by neither was the one that was wrong. See test_starting_cards.py, which now
# pins all five against the printed rules.
RUBY = HRCard(id="ruby", name="Ruby", cost=0, faction="",
              card_type="treasure", effects={"gold": 2})
FIRE_GEM = HRCard(id="fire_gem", name="Fire Gem", cost=2, faction="",
                  card_type="item", effects={"gold": 2, "sacrifice_combat": 3})


_board_champion_ids = itertools.count()


class BoardChampion:
    def __init__(self, card: HRCard):
        self.card = card
        self.current_health = card.health
        self.exhausted = False  # true if expended this turn
        self.guard = card.guard
        # Some cards are printed in 2-3 copies (see load_hero_cards), so two
        # champions on the same board can share card.id. web/session.py used
        # to identify a BoardChampion by card.id alone; with a duplicate on
        # the board, that lookup always resolved to whichever copy came first
        # in the list, so an already-exhausted first copy made the second,
        # genuinely available copy unreachable - "Champion could not be
        # expended" even with a legal one sitting right there. instance_id
        # disambiguates copies of the same card from each other.
        self.instance_id = next(_board_champion_ids)

    @property
    def name(self):
        return self.card.name

    @property
    def alive(self):
        return self.current_health > 0


class HRPlayer:
    def __init__(self, name: str, rng=None):
        self.name = name
        self._rng = rng if rng is not None else random
        self.hp = 50
        self.gold = 0
        self.combat = 0
        self.deck: list[HRCard] = []
        self.hand: list[HRCard] = []
        self.discard: list[HRCard] = []
        self.banish: list[HRCard] = []  # cards removed from game (sacrificed)
        self.board: list[BoardChampion] = []  # champions in play
        # Non-champion cards in play this turn. Actions, items, and treasures
        # do not enter the discard pile until the Discard Phase, so they cannot
        # be reshuffled and played again during the same turn. Faction cards in
        # this zone can trigger each other's ally abilities. Champions are not
        # tracked here; they live on `board`, which has its own self-exclusion
        # check in has_ally.
        self.played_this_turn: list[HRCard] = []
        # Cards played this turn whose ally ability has not fired yet; allies
        # are retroactive, so these are re-checked whenever a faction card
        # enters play.
        self.pending_ally: list[HRCard] = []
        # Played actions with a per_champion_* bonus, topped up when a
        # champion enters play later the same turn - see
        # _apply_per_champion_bonus / _resolve_pending_per_champion.
        self.pending_per_champion: list[dict] = []
        self.pending_stun_targets: list[tuple[HRCard, Optional[BoardChampion]]] = []
        # The UI/AI phase model plays all actions before champions can be
        # expended. Prepare effects are therefore queued and applied to the
        # first champion the player subsequently chooses to expend.
        self.pending_prepares: int = 0
        # Sacrifice and discard targeting used to be resolved inline by
        # _find_worst_idx the moment the effect fired, which made them
        # unreachable to any agent - they are the decisions a strong player
        # spends the most thought on. With defer_choices set, the effect
        # enqueues here instead and something outside the engine answers it;
        # left False, play_card auto-resolves exactly as before, so every
        # existing caller (heuristics, MCTS, the v1 RL env) is unchanged.
        self.pending_choices: list[dict] = []
        self.defer_choices: bool = False
        self.actions_played: int = 0
        self.cards_bought: int = 0
        self.next_buy_to_hand: bool = False  # Deception ally: next bought card goes to hand
        self.next_buy_to_top: bool = False   # Rasmus ally: next bought card goes on top of deck
        self.next_buy_to_top_action_only: bool = False  # Bribe ally: next ACTION on top

    def setup_starting_deck(self):
        self.deck = [GOLD] * 7 + [SHORTSWORD] + [DAGGER] + [RUBY]
        self._rng.shuffle(self.deck)

    def draw(self, n: int = 1):
        drawn = []
        for _ in range(n):
            if not self.deck:
                self._reshuffle_discard()
                if not self.deck:
                    break
            drawn.append(self.deck.pop(0))
        self.hand.extend(drawn)
        return drawn

    def _reshuffle_discard(self):
        if not self.discard:
            return
        self.deck = self.discard[:]
        self.discard.clear()
        self._rng.shuffle(self.deck)

    def hand_size(self):
        return len(self.hand)

    def discard_played_cards(self) -> None:
        """Move this turn's non-champion cards to discard at the Discard Phase."""
        self.discard.extend(self.played_this_turn)
        self.played_this_turn.clear()

    def allies(self) -> set[str]:
        factions = set()
        for bc in self.board:
            if bc.card.faction:
                factions.add(bc.card.faction)
        return factions


# --- Effect helper functions ---

def _card_score(card: HRCard) -> float:
    """Score a card's overall value (higher = more valuable to keep)."""
    if card.id == "gold":
        return -100
    if card.id == "shortsword":
        return -75
    if card.id == "dagger":
        return -60
    if card.id == "ruby":
        return -50
    import hero_weights as W

    e = card.effects
    score = (card.cost * W.get("cost")
             + card.get("combat", 0) * W.get("combat")
             + card.get("gold", 0) * W.get("gold")
             + card.get("health", 0) * W.get("health")
             + card.get("draw", 0) * W.get("draw")
             + (card.health if card.card_type == "champion" else 0) * W.get("champion_health"))
    # Ally effects and sacrifice access were worth zero here, which is what
    # DEFAULTS still encode - see hero_weights for the play data that says
    # they should not be.
    score += (e.get("ally_combat", 0) * W.get("ally_combat")
              + e.get("ally_gold", 0) * W.get("ally_gold")
              + e.get("ally_health", 0) * W.get("ally_health")
              + e.get("ally_draw", 0) * W.get("ally_draw"))
    if e.get("sacrifice_card"):
        score += W.get("sacrifice_card")
    return score


def remove_stunned_champions(player: HRPlayer) -> list[HRCard]:
    """Move stunned (destroyed) champions off the board into their owner's
    discard pile, and return the cards moved.

    Per the official rules: "Once stunned, a Champion is placed in its owner's
    discard pile." Every combat site used to just filter dead champions off
    the board with a list comprehension, so the card vanished from the game
    entirely - effectively banishing it. That made every champion a one-use
    card once attacked, and champion-focused strategies far weaker than the
    rules allow.
    """
    stunned = [bc for bc in player.board if not bc.alive]
    if not stunned:
        return []
    player.board = [bc for bc in player.board if bc.alive]
    for bc in stunned:
        player.discard.append(bc.card)
    return [bc.card for bc in stunned]


def _deck_gold_density(player: HRPlayer) -> float:
    """Average gold produced per card the player already owns.

    Has to measure gold specifically, not overall card quality. A deck
    flooded with plain Gold actually *lowers* mean card value (Gold scores
    below a typical deck's own average), which would make a quality-based
    discount reward keeping still more Gold - the opposite of the diminishing
    returns it is meant to express.
    """
    cards = player.deck + player.hand + player.discard
    if not cards:
        return 0.0
    return sum(card.get("gold", 0) for card in cards) / len(cards)


# Reference scale for the gold-diminishing-returns discount below: the
# starting deck's own gold density. 7 Gold at 1 each plus Ruby at 2, over 10
# cards, is 0.9 - it read 0.7 while Ruby was mis-encoded as a 1-health action,
# so this constant was derived from the bug. 4x that so a fresh deck sits at a
# mild discount rather than a severe one - matches GOLD_DISCOUNT_SCALE in
# web/bot.py, which discounts the *buying* side of this same tradeoff.
_GOLD_DENSITY_DISCOUNT_SCALE = 0.9 * 4.0


def _contextual_card_value(card: HRCard, player: HRPlayer,
                           opponent: Optional[HRPlayer] = None) -> float:
    """Value of a card the player already owns, for deciding which to keep
    when the engine has to discard or sacrifice one.

    _card_score alone is a fixed per-card number - cost and raw stats, with
    no idea whether the player is racing for lethal, needs healing, already
    has plenty of gold, or has an ally on board that makes this specific
    card's ally_* fields real rather than dead text. That is the same kind
    of blind spot _holistic_card_score (web/bot.py) fixes for buy decisions.
    This is the discard/sacrifice-side counterpart, and it lives in the
    engine itself rather than the bot layer, because _find_worst_idx and
    _find_best_idx are called from every simulated game - RL training,
    heuristic AI opponents, and the MCTS bot alike - not just the MCTS bot's
    own purchases.

    The four starting cards are deliberately exempt from every adjustment
    below: they are junk under any circumstances and must stay the default
    discard/sacrifice target regardless of context, exactly as
    _worth_sacrificing already assumes.
    """
    score = float(_card_score(card))
    if card.id in _STARTER_IDS:
        # Still exempt from every situational adjustment below - these are junk
        # in any context. Only their ordering among themselves is in question,
        # and that is what _starter_value decides.
        return _starter_value(card, player, opponent)

    if opponent is not None:
        opp_hp_ratio = min(max(opponent.hp, 0), HRGame.STARTING_HP) / HRGame.STARTING_HP
        # Combat is worth more to keep the closer the opponent is to dead -
        # closing out a game beats incremental damage at full health. Same
        # shape as the combat weight _holistic_card_score uses for buying.
        score += card.get("combat", 0) * (1.0 - opp_hp_ratio) * 3.0

    own_hp_ratio = min(max(player.hp, 0), HRGame.STARTING_HP) / HRGame.STARTING_HP
    # A heal is worth more to keep the more urgently the player needs it.
    score += card.get("health", 0) * (1.0 - own_hp_ratio) * 4.0

    ally_faction = card.effects.get("ally_faction", "")
    if ally_faction:
        ally_value = (
            card.get("ally_combat", 0) * 4
            + card.get("ally_gold", 0) * 3
            + card.get("ally_draw", 0) * 5
            + card.get("ally_health", 0) * 3
        )
        if ally_value:
            # Full credit once the matching faction is actually on board (the
            # bonus is real right now); a small, non-zero credit otherwise,
            # since ally_faction is common enough that ignoring it outright
            # would systematically undervalue these cards even when the ally
            # is one purchase away.
            score += ally_value if ally_faction in player.allies() else ally_value * 0.2

    if card.get("gold", 0) > 0:
        # Diminishing returns on gold specifically, mirroring the buy-side
        # discount: another gold card is worth less to keep once the deck
        # already produces plenty of it.
        discount = 1.0 / (1.0 + _deck_gold_density(player) / _GOLD_DENSITY_DISCOUNT_SCALE)
        score -= card.get("gold", 0) * 3 * (1.0 - discount)

    return score


_STARTER_IDS = ("gold", "shortsword", "dagger", "ruby")

# "fixed" keeps _card_score's constants (gold -100, shortsword -75, dagger -60,
# ruby -50) and is byte-identical to the previous behaviour. "phased" orders the
# four starting cards by what they are worth *now*.
#
# Why this is worth a knob at all: _find_worst_idx fires 14.1 times per game and
# lands on one of these four cards 95.9% of the time (measured over 24 games).
# So the great majority of every discard and sacrifice decision in this engine -
# for the MCTS bot, the heuristic profiles, and RL training alike - is resolved
# by a four-entry lookup table, while the rich situational model in
# _contextual_card_value applies only to the remaining 4%.
#
# The constants also disagree with every strategy source consulted. They dump
# Gold first unconditionally, stripping early economy, and hold Dagger (1
# combat, nearly worthless early) until third. Sources are consistent that gold
# matters early and much less late, and that non-economy cards should go first.
STARTER_ORDER_MODE = "fixed"  # "fixed" or "phased"

# Which seat the phased ordering applies to. This is a *measurement device*
# first: _find_worst_idx is engine-level, so improving it symmetrically improves
# the benchmark opponents too and the win rate can stay flat while play genuinely
# improves. "bot" isolates the effect - and happens also to be the honest
# shipping configuration, since it is the bot's decision policy that is being
# changed, not the game's rules.
STARTER_ORDER_SEATS = "bot"  # "bot" or "all"


def _starter_value(card: HRCard, player: Optional[HRPlayer],
                   opponent: Optional[HRPlayer]) -> float:
    """Context-aware junk ordering for the four starting cards.

    Both terms are anchored at the same -100 floor so these stay far below any
    purchased card and remain the default target, exactly as _worth_sacrificing
    assumes. Only their order relative to *each other* changes.

    The four starters in *this* engine are gold (1 gold), shortsword (2 combat),
    dagger (1 combat) and ruby (1 health) - note ruby is a heal here, not the
    2-gold treasure of the printed base set, so it needs the healing axis rather
    than the economy one. Getting that wrong ranks it worst in every state.

    Each axis is priced by when it is actually worth something:

      gold    decays as the game progresses - nothing left worth buying;
      combat  rises as the game progresses - damage is how the game ends;
      health  rises as the *player's own* HP falls, matching the shape
              _contextual_card_value already uses for healing on real cards.

    Early at full health this ranks dagger ~ ruby < shortsword < gold: thin the
    near-useless combat and heal starters while gold is still buying cards. Late
    and hurt it becomes gold < dagger ~ ruby < shortsword. The shipped constants
    (gold < shortsword < dagger < ruby) match neither end.

    Progress is read from total HP depleted rather than turn count because that
    is what this function has access to - it takes players, not a session.
    """
    if (STARTER_ORDER_MODE != "phased" or player is None or opponent is None
            or (STARTER_ORDER_SEATS == "bot" and player.name != "Bot")):
        return float(_card_score(card))
    remaining = max(player.hp, 0) + max(opponent.hp, 0)
    progress = min(1.0, max(0.0, 1.0 - remaining / (2.0 * HRGame.STARTING_HP)))
    own_hp_ratio = min(max(player.hp, 0), HRGame.STARTING_HP) / HRGame.STARTING_HP
    gold = card.get("gold", 0)
    combat = card.get("combat", 0)
    health = card.get("health", 0)
    return (
        -100.0
        + gold * 25.0 * (1.0 - progress)
        + combat * 25.0 * progress
        + health * 25.0 * (1.0 - own_hp_ratio)
        # Breaks ties between starters carrying the same amount of a currently
        # worthless resource, by raw printed power.
        + (gold + combat + health) * 1.0
    )


def _find_worst_idx(cards: list, player: Optional[HRPlayer] = None,
                    opponent: Optional[HRPlayer] = None) -> int:
    """Index of the lowest-value card (for sacrificing/discarding).

    Uses the situational _contextual_card_value when the owning player is
    known, falling back to the fixed _card_score otherwise.
    """
    best_i, best_s = 0, float("inf")
    for i, c in enumerate(cards):
        s = _contextual_card_value(c, player, opponent) if player is not None else _card_score(c)
        if s < best_s:
            best_s = s
            best_i = i
    return best_i


def _find_best_idx(cards: list, player: Optional[HRPlayer] = None,
                   opponent: Optional[HRPlayer] = None) -> int:
    """Index of the highest-value card (for returning from discard)."""
    best_i, best_s = 0, float("-inf")
    for i, c in enumerate(cards):
        s = _contextual_card_value(c, player, opponent) if player is not None else _card_score(c)
        if s > best_s:
            best_s = s
            best_i = i
    return best_i


def _worth_sacrificing(card: HRCard, player: Optional[HRPlayer] = None,
                       opponent: Optional[HRPlayer] = None) -> bool:
    """Whether a hand/discard card is worth an optional sacrifice.

    Every printed sacrifice effect in this card set reads "you may sacrifice"
    (or uses the {Sacrifice}: keyword, which means the same thing) - it is
    never mandatory. The engine used to apply these unconditionally, which
    meant a lean, thinned deck (exactly what a sacrifice-focused strategy
    builds toward) had no bad cards left to decline sacrificing, and was
    forced to burn a genuinely useful card instead.

    With player context, uses _contextual_card_value instead of the fixed
    _card_score, so a redundant purchased card can also become worth
    sacrificing once the deck already has plenty of what it offers (e.g. a
    cheap economy card once gold density is high) - not only the four
    starting cards. Without context (or for those four, which
    _contextual_card_value always scores identically to _card_score), the
    original -50 to -100 vs. cost*10+ split still applies.
    """
    if player is not None:
        return _contextual_card_value(card, player, opponent) < 0
    return _card_score(card) < 0


def _should_self_sacrifice(player: HRPlayer, opponent: Optional[HRPlayer] = None,
                           requires_open_combat: bool = False) -> bool:
    """Whether to take an optional self-sacrifice (Fire Gem's "{Sacrifice}:
    gain 3 combat" and similar): burn the just-played card itself for a
    one-time bonus, trading away its own future recurring value.

    Declines when the bonus is combat and a guard would absorb it for
    nothing (the same reasoning the or_choice combat branch below already
    uses), and otherwise takes it once the player already owns a couple of
    non-starting economy cards: keeping the first copies of a gold source is
    usually worth more than one early burst of combat, but by the time a
    further copy would arrive the marginal card is worth less than a
    guaranteed bonus now.
    """
    if requires_open_combat and opponent:
        # Exhausting a guard uses its ability; it remains in play and continues
        # to block combat until stunned.
        guards = [bc for bc in opponent.board if bc.guard and bc.alive]
        if guards:
            return False
    owned_economy = sum(
        1 for c in player.deck + player.hand + player.discard
        if c.get("gold", 0) > 0 and c.id != "gold"
    )
    return owned_economy >= 2


def _discard_from_hand(player: HRPlayer, n: int, opponent: Optional[HRPlayer] = None):
    """Discard n lowest-value cards from hand (self-discard: keep best)."""
    n = min(n, len(player.hand))
    if n <= 0:
        return
    if player.defer_choices:
        _enqueue_choice(player, "discard", n)
        return
    for _ in range(n):
        idx = _find_worst_idx(player.hand, player, opponent)
        player.discard.append(player.hand.pop(idx))


def _enqueue_choice(player: HRPlayer, kind: str, count: int, zone: str = "hand"):
    """Record a targeting decision for later instead of resolving it now."""
    if count > 0:
        player.pending_choices.append({"kind": kind, "count": count, "zone": zone})


def choice_candidates(player: HRPlayer, choice: dict) -> list[HRCard]:
    """The cards a pending choice may legally select from."""
    if choice["kind"] == "discard":
        return list(player.hand)
    # Sacrifice reads "a card in your hand or discard pile"; hand is offered
    # first only when non-empty, matching the original inline resolution.
    if choice["zone"] == "hand":
        return list(player.hand)
    return list(player.discard)


def apply_choice(player: HRPlayer, choice: dict, index: int) -> Optional[HRCard]:
    """Resolve one unit of a pending choice by selecting candidate `index`."""
    candidates = choice_candidates(player, choice)
    if not candidates or not (0 <= index < len(candidates)):
        return None
    card = candidates[index]
    if choice["kind"] == "discard":
        player.hand.remove(card)
        player.discard.append(card)
    else:
        source = player.hand if choice["zone"] == "hand" else player.discard
        source.remove(card)
        player.banish.append(card)
    choice["count"] -= 1
    if choice["count"] <= 0 and choice in player.pending_choices:
        player.pending_choices.remove(choice)
    return card


def auto_resolve_choices(player: HRPlayer, opponent: Optional[HRPlayer] = None):
    """Answer every pending choice with the heuristic the engine used inline.

    Keeps deferred and non-deferred play byte-identical when nobody else
    answers, so enabling deferral cannot silently change existing agents.
    """
    while player.pending_choices:
        choice = player.pending_choices[0]
        candidates = choice_candidates(player, choice)
        if not candidates:
            player.pending_choices.remove(choice)
            continue
        idx = _find_worst_idx(candidates, player, opponent)
        if choice["kind"] == "sacrifice" and not _worth_sacrificing(
                candidates[idx], player, opponent):
            player.pending_choices.remove(choice)
            continue
        if apply_choice(player, choice, idx) is None:
            player.pending_choices.remove(choice)


def _force_opponent_discard(opponent: HRPlayer, n: int = 1, forcing_player: Optional[HRPlayer] = None):
    """Opponent discards n of their worst cards (opponent chooses to minimize
    harm to themselves - from their own perspective, `forcing_player` is
    their opponent)."""
    n = min(n, len(opponent.hand))
    for _ in range(n):
        idx = _find_worst_idx(opponent.hand, opponent, forcing_player)
        opponent.discard.append(opponent.hand.pop(idx))


class HRMarket:
    def __init__(self, cards: list[HRCard], rng=None):
        # Fire Gems are always in a separate side pile, not shuffled into market row.
        self.pool = [c for c in cards if c.name.lower() != "fire gem"]
        self.fire_gems_remaining = 16  # base set ships 16 Fire Gem cards
        (rng if rng is not None else random).shuffle(self.pool)
        self.row: list[Optional[HRCard]] = [None] * 5
        self._fill_row()

    def _fill_row(self):
        for i in range(5):
            if self.row[i] is None and self.pool:
                self.row[i] = self.pool.pop(0)

    def buy(self, index: int) -> Optional[HRCard]:
        if index < 0 or index >= 5 or self.row[index] is None:
            return None
        card = self.row[index]
        self.row[index] = None
        self._fill_row()
        return card

    def row_cards(self) -> list[Optional[HRCard]]:
        return self.row[:]

    def can_buy_fire_gem(self) -> bool:
        return self.fire_gems_remaining > 0

    def buy_fire_gem(self) -> Optional[HRCard]:
        if self.fire_gems_remaining <= 0:
            return None
        self.fire_gems_remaining -= 1
        return FIRE_GEM


class HRGame:
    STARTING_HP = 50

    def __init__(self, player1: HRPlayer, player2: HRPlayer, market_cards: list[HRCard]):
        self.p1 = player1
        self.p2 = player2
        self.market = HRMarket(market_cards)
        self.turn_number = 0
        self.active_player: HRPlayer = self.p1
        self.opponent: HRPlayer = self.p2
        self.winner: Optional[str] = None
        self.turn_log: list[str] = []

    def run_game(self, ai_buy, ai_play, ai_attack, ai_expend=None, max_turns=100):
        self.p1.setup_starting_deck()
        self.p2.setup_starting_deck()
        # Per official rules: first player draws 3, second player draws 5
        self.p1.draw(3)
        self.p2.draw(5)

        for turn in range(1, max_turns + 1):
            self.turn_number = turn
            self.take_turn(self.active_player, self.opponent, ai_buy, ai_play, ai_attack, ai_expend)

            if self.opponent.hp <= 0:
                self.winner = self.active_player.name
                break

            self.active_player, self.opponent = self.opponent, self.active_player

        if self.winner is None:
            self.winner = self.active_player.name if self.p2.hp <= self.p1.hp else self.opponent.name

        return self.winner, self.turn_number, self.turn_log

    def take_turn(self, player: HRPlayer, opponent: HRPlayer, ai_buy, ai_play, ai_attack, ai_expend=None):
        player.gold = 0
        player.combat = 0
        player.actions_played = 0
        player.discard_played_cards()
        player.pending_ally.clear()
        player.pending_per_champion.clear()
        player.pending_stun_targets.clear()
        player.pending_prepares = 0
        player.cards_bought = 0
        player.next_buy_to_hand = False
        player.next_buy_to_top = False
        player.next_buy_to_top_action_only = False
        for bc in player.board:
            bc.exhausted = False
            bc.current_health = bc.card.health  # damage does not carry over between turns

        phase = "play"
        while phase:
            if phase == "play":
                ai_play(player, opponent, self.market)
                phase = "champion"
            elif phase == "champion":
                if ai_expend:
                    ai_expend(player, opponent)
                phase = "buy"
            elif phase == "buy":
                ai_buy(player, opponent, self.market)
                phase = "combat"
            elif phase == "combat":
                self._resolve_combat(player, opponent, ai_attack)
                phase = "cleanup"
            elif phase == "cleanup":
                self._cleanup(player)
                phase = None

    def _resolve_combat(self, player: HRPlayer, opponent: HRPlayer, ai_attack):
        if player.combat <= 0:
            return

        # AI decides which guard champions to attack (if multiple), and - once
        # no guard remains, including when there was never one - may snipe a
        # non-guard champion with any leftover combat instead of it all going
        # to face. Called unconditionally: gating this behind `if guards`
        # meant a board with zero guards never got a chance to snipe at all.
        guards = [bc for bc in opponent.board if bc.guard and bc.alive]
        ai_attack(player, opponent, guards)

        dmg = player.combat
        if dmg <= 0:
            return

        # Remaining damage hits the player
        opponent.hp -= dmg

    def _cleanup(self, player: HRPlayer):
        player.discard_played_cards()
        for c in player.hand:
            player.discard.append(c)
        player.hand.clear()
        player.draw(5)


def _stun_champion(opponent: HRPlayer, target: Optional[BoardChampion] = None) -> bool:
    """Stun a selected opposing champion, prioritising guards when present."""
    living = [champion for champion in opponent.board if champion.alive]
    guards = [champion for champion in living if champion.guard]
    candidates = guards or living
    if not candidates:
        return False
    target = target or candidates[0]  # Non-interactive engine callers use the first legal target.
    if target not in candidates:
        return False
    target.current_health = 0
    remove_stunned_champions(opponent)
    return True


def play_card(player: HRPlayer, card: HRCard, market: HRMarket,
              ally_bonus: bool = False, opponent: HRPlayer = None,
              stun_target: Optional[BoardChampion] = None):
    """Play a card from hand, applying all its effects.

    Champions: effects are from their {Expend} ability, NOT on-play.
    They just go to the board; expend them later via expend_champion().
    """
    if card not in player.hand:
        return False
    player.hand.remove(card)

    # Champions go to board without applying effects (those are expend-only)
    if card.card_type == "champion":
        bc = BoardChampion(card)
        player.board.append(bc)
        # A champion entering play can complete a faction pair for an action
        # played earlier this turn, and tops up any queued per-champion bonus.
        _resolve_pending_allies(player, opponent)
        _resolve_pending_per_champion(player)
        return True

    # Non-champions remain in play until the Discard Phase. Keeping every such
    # card out of `discard` prevents a draw effect from reshuffling and
    # replaying a card during the same turn.
    player.played_this_turn.append(card)
    if card.faction:
        _resolve_pending_allies(player, opponent)

    # ---- Base effects (non-champion cards only) ----
    player.gold += card.get("gold", 0)
    player.combat += card.get("combat", 0)

    heal = card.get("health", 0)
    if heal:
        player.hp = min(player.hp + heal, HRGame.STARTING_HP)

    draws = card.get("draw", 0)
    if draws:
        player.draw(draws)

    draw_up_to = card.get("draw_up_to", 0)
    actual_draw_up_to = 0
    if draw_up_to:
        actual_draw_up_to = draw_up_to  # AI draws max
        player.draw(actual_draw_up_to)

    # ---- Per-champion effects for actions ----
    # Priced at the current champion count and queued: per the table
    # experience behind this fix, "for each champion you have in play" on a
    # played action (Close Ranks, Recruit) tops up retroactively if a champion
    # enters play later the same turn, the same way ally abilities do for the
    # action itself staying in play until the Discard Phase.
    _apply_per_champion_bonus(player, card, "per_champion_combat", "combat")
    _apply_per_champion_bonus(player, card, "per_champion_health", "health")

    # ---- Ally bonus ----
    # Applied now if a partner is already in play, otherwise queued: the ally
    # fires retroactively the moment a second card of the faction arrives.
    if ally_bonus:
        _apply_ally_effects(player, card, opponent, stun_target=stun_target)
    elif _has_ally_payload(card):
        player.pending_ally.append(card)
        if card.get("stun", False):
            player.pending_stun_targets.append((card, stun_target))

    total_base_draws = draws + actual_draw_up_to + (card.get("ally_draw", 0) if ally_bonus else 0)

    # ---- Self-discard (draw then discard) ----
    discard_n = card.get("discard", 0)
    if discard_n > 0:
        if total_base_draws == 0:
            player.draw(discard_n)
        _discard_from_hand(player, discard_n, opponent)

    # ---- Filter-draw (discard_drawn: draw X then discard X) ----
    if card.get("discard_drawn", False) and total_base_draws > 0:
        _discard_from_hand(player, total_base_draws, opponent)

    # ---- Self-sacrifice (sacrifice THIS card for bonus effects) ----
    # Optional per the printed text ("{Sacrifice}:" / "you may sacrifice") -
    # see _should_self_sacrifice's docstring for why this can no longer be
    # unconditional.
    sacrificed = False
    sac_combat = card.get("sacrifice_combat", 0)
    guard_hp = sum(
        champion.current_health
        for champion in opponent.board
        if champion.alive and champion.guard
    ) if opponent else 0
    guaranteed_lethal = bool(
        opponent
        and sac_combat > 0
        and player.combat + sac_combat >= guard_hp + opponent.hp
    )
    if sac_combat > 0 and (
        guaranteed_lethal
        or _should_self_sacrifice(player, opponent, requires_open_combat=True)
    ):
        player.combat += sac_combat
        sacrificed = True
    sac_od = card.get("sacrifice_opponent_discard", 0)
    if sac_od > 0 and opponent and _should_self_sacrifice(player, opponent):
        _force_opponent_discard(opponent, sac_od, player)
        sacrificed = True

    # ---- Opponent discard (always, if card has it) ----
    od = card.get("opponent_discard", 0)
    if od > 0 and opponent:
        _force_opponent_discard(opponent, od, player)

    # ---- Generic sacrifice from hand/discard (Dark Reward, Death Touch, etc.) ----
    # Optional ("you may sacrifice a card in your hand or discard pile") -
    # only take it if the worst available card is actually junk; see
    # _worth_sacrificing.
    if card.effects.get("sacrifice_card", False):
        zone = "hand" if player.hand else ("discard" if player.discard else None)
        if zone:
            if player.defer_choices:
                _enqueue_choice(player, "sacrifice", 1, zone)
            else:
                source = player.hand if zone == "hand" else player.discard
                idx = _find_worst_idx(source, player, opponent)
                if _worth_sacrificing(source[idx], player, opponent):
                    player.banish.append(source.pop(idx))

    # ---- Stun (primary for non-ally cards like Fire Bomb; ally-only if ally_faction set) ----
    if card.get("stun", False) and opponent and not card.get("ally_faction", ""):
        _stun_champion(opponent, stun_target)

    # (prepare / to_hand / top_of_deck / ally_opponent_discard are applied by
    # _apply_ally_effects, so they fire retroactively too.)

    # ---- Non-ally effects (always apply) ----

    # Recycle (discard to top of deck) (Smash and Grab - no ally needed)
    if card.get("recycle", False) and player.discard:
        idx = _find_best_idx(player.discard, player, opponent)
        player.deck.insert(0, player.discard.pop(idx))

    # ---- A self-sacrificed card leaves play immediately; every other
    # non-champion remains in played_this_turn until the Discard Phase. ----
    if sacrificed:
        player.played_this_turn.remove(card)
        player.banish.append(card)

    return True


def expend_champion(player: HRPlayer, bc: BoardChampion, opponent: HRPlayer = None,
                    stun_target: Optional[BoardChampion] = None,
                    choice: Optional[str] = None) -> bool:
    """Use a champion's expend ability. Applies the card's effects again.

    `choice` names which branch of an `or_choice` card to take ("combat",
    "gold", "health", "per_champion_health"). The rules make this the player's
    decision - Cult Priest reads "gain 1 gold *or* gain 1 combat" - so when a
    caller supplies one it is honoured verbatim. Left None, the heuristic below
    picks, which is what every simulated game and the bot's own rollouts rely
    on; only a real player needs to override it.
    """
    if bc.exhausted or not bc.alive:
        return False
    bc.exhausted = True

    card = bc.card

    # ---- "Or" choice: apply only the best option ----
    or_choice = card.get("or_choice", [])
    if or_choice:
        options = []
        force_lethal_combat = False
        if "combat" in or_choice:
            val = card.get("combat", 0)
            if val:
                # Guards block face damage whether or not they have already
                # been expended. If this branch creates an immediate open-face
                # lethal, no economic/healing score can rationally beat it.
                guards = [
                    champion for champion in opponent.board
                    if champion.guard and champion.alive
                ] if opponent else []
                force_lethal_combat = bool(
                    opponent
                    and not guards
                    and player.combat + val >= opponent.hp
                )
                if guards:
                    # A veto regardless of magnitude was wrong: combat that
                    # kills the weakest guard is still worth taking (removes a
                    # persistent threat, and any excess spills over once no
                    # guard remains), not merely wasted chip damage.
                    weakest_guard_hp = min(g.current_health for g in guards)
                    score = val if val >= weakest_guard_hp else -10
                else:
                    score = val
                options.append(("combat", val, score))
        if "gold" in or_choice:
            val = card.get("gold", 0)
            if val:
                score = val + (3 if player.gold < 3 else 0)
                options.append(("gold", val, score))
        if "health" in or_choice:
            val = card.get("health", 0)
            if val:
                # A flat hp>=45 threshold didn't reflect how much of the heal
                # actually lands once close to the cap. Score the real amount
                # gained instead, so a heal already mostly wasted competes on
                # its true value rather than an arbitrary cutoff.
                actual_heal = min(val, HRGame.STARTING_HP - player.hp)
                score = actual_heal + (3 if player.hp <= 25 else 0)
                options.append(("health", val, score))
        if "per_champion_health" in or_choice:
            val = card.get("per_champion_health", 0)
            if val:
                count = len([c for c in player.board if c.alive])
                total = val * count
                actual_heal = min(total, HRGame.STARTING_HP - player.hp)
                score = actual_heal + (3 if player.hp <= 25 else 0)
                options.append(("health", total, score))
        if options:
            chosen = next((option for option in options if option[0] == choice), None)
            best = (
                chosen if chosen is not None
                else next(option for option in options if option[0] == "combat")
                if force_lethal_combat
                else max(options, key=lambda x: x[2])
            )
            if best[0] == "combat":
                player.combat += best[1]
            elif best[0] == "gold":
                player.gold += best[1]
            elif best[0] == "health":
                player.hp = min(player.hp + best[1], HRGame.STARTING_HP)
    else:
        # ---- Base expend effects ----
        player.combat += card.get("combat", 0)
        player.gold += card.get("gold", 0)
        heal = card.get("health", 0)
        if heal:
            player.hp = min(player.hp + heal, HRGame.STARTING_HP)

    # ---- Per-other-X effects on expend ----
    other_champions = len([c for c in player.board if c.alive and c != bc])
    per_other_champion_combat = card.get("per_other_champion_combat", 0)
    if per_other_champion_combat:
        player.combat += per_other_champion_combat * other_champions
    per_other_guard_combat = card.get("per_other_guard_combat", 0)
    if per_other_guard_combat:
        other_guards = len([c for c in player.board if c.alive and c.guard and c != bc])
        player.combat += per_other_guard_combat * other_guards
    per_other_wild_combat = card.get("per_other_wild_combat", 0)
    if per_other_wild_combat:
        # "for each other {Wild} CARD you have in play" - not "champion". The
        # other per_* effects on nearby cards all say champion or guard, so
        # board-only is right for them; this one is not. Actions played this
        # turn are in play until the Discard Phase, so a Wild action counts.
        other_wild = len([c for c in player.board if c.alive and c.card.faction == "Wild" and c != bc])
        other_wild += sum(1 for c in player.played_this_turn if c.faction == "Wild")
        player.combat += per_other_wild_combat * other_wild
    draws = card.get("draw", 0)
    if draws:
        player.draw(draws)

    discard_n = card.get("discard", 0)
    if discard_n > 0:
        if draws == 0:
            player.draw(discard_n)
        _discard_from_hand(player, discard_n, opponent)

    if card.get("discard_drawn", False) and draws > 0:
        _discard_from_hand(player, draws, opponent)

    # ---- Sacrifice a card from hand/discard for bonus combat (Krythos, Lys) ----
    # "You may sacrifice a card... If you do, gain an additional combat" - the
    # bonus is conditional on actually sacrificing, so both are skipped
    # together once the worst available card isn't junk (_worth_sacrificing).
    sac_for_combat = card.get("sacrifice_for_combat", 0)
    if sac_for_combat > 0:
        source = None
        if player.hand:
            source = player.hand
        elif player.discard:
            source = player.discard
        if source:
            idx = _find_worst_idx(source, player, opponent)
            if _worth_sacrificing(source[idx], player, opponent):
                player.banish.append(source.pop(idx))
                player.combat += sac_for_combat

    # ---- Sacrifice up to X cards from hand/discard (Tyrannor) ----
    # "You may sacrifice up to two cards" - stops as soon as nothing left
    # qualifies as junk, rather than always forcing all X.
    sacrifice_up_to = card.get("sacrifice_up_to", 0)
    if sacrifice_up_to > 0:
        for _ in range(sacrifice_up_to):
            source = None
            if player.hand:
                source = player.hand
            elif player.discard:
                source = player.discard
            if not source:
                break
            idx = _find_worst_idx(source, player, opponent)
            if not _worth_sacrificing(source[idx], player, opponent):
                break
            player.banish.append(source.pop(idx))

    # ---- Stun on expend (Rake, Master Assassin) ----
    if card.get("stun", False) and opponent:
        for c in opponent.board:
            if c.alive:
                _stun_champion(opponent, stun_target)
                break

    # ---- Opponent discard on expend (Torgen Rocksplitter) ----
    od = card.get("opponent_discard", 0)
    if od > 0 and opponent:
        _force_opponent_discard(opponent, od, player)

    # ---- Reanimate on expend (Varrick): take a champion from discard to the
    # top of the deck. This effect only exists on a champion (Varrick himself,
    # per "reanimate" only appearing on his card), and used to live inside
    # play_card - which returns immediately for any card_type == "champion"
    # before reaching that code. It had never fired in any game this engine
    # has simulated. Picks the best champion via the same contextual
    # valuation recycle already uses, not the first one in discard order. ----
    if card.get("reanimate", False):
        champions = [c for c in player.discard if c.card_type == "champion"]
        if champions:
            best = max(champions, key=lambda c: _contextual_card_value(c, player, opponent))
            player.discard.remove(best)
            player.deck.insert(0, best)

    # ---- Ally effects on expend ----
    if has_ally(card, player):
        player.combat += card.get("ally_combat", 0)
        player.gold += card.get("ally_gold", 0)
        ally_heal = card.get("ally_health", 0)
        if ally_heal:
            player.hp = min(player.hp + ally_heal, HRGame.STARTING_HP)
        ally_per_champion_health = card.get("ally_per_champion_health", 0)
        if ally_per_champion_health:
            champion_count = len([c for c in player.board if c.alive])
            heal = ally_per_champion_health * champion_count
            if heal:
                player.hp = min(player.hp + heal, HRGame.STARTING_HP)
        ally_draw = card.get("ally_draw", 0)
        if ally_draw:
            player.draw(ally_draw)
            if card.get("ally_discard_drawn", False):
                _discard_from_hand(player, ally_draw, opponent)

        # Champion ally top_of_deck (Rasmus: next bought card goes on top; Bribe: action only)
        if card.get("top_of_deck", False):
            player.next_buy_to_top = True
            if card.get("top_of_deck_action_only", False):
                player.next_buy_to_top_action_only = True

        # Champion ally opponent discard (Broelyn)
        ally_od = card.get("ally_opponent_discard", 0)
        if ally_od > 0 and opponent:
            _force_opponent_discard(opponent, ally_od, player)

    if player.pending_prepares > 0 and bc.alive and bc.exhausted:
        bc.exhausted = False
        player.pending_prepares -= 1

    return True


def auto_expend_all(player: HRPlayer, opponent: HRPlayer = None):
    """Expend every ready champion on the board."""
    while True:
        ready = next(
            (bc for bc in player.board if bc.alive and not bc.exhausted),
            None,
        )
        if ready is None:
            break
        expend_champion(player, ready, opponent)


def buy_card(player: HRPlayer, market: HRMarket, index: int) -> bool:
    """Try to buy a market-row card (0-4) or Fire Gem side-pile card (5)."""
    if index == 5:
        if player.gold < FIRE_GEM.cost:
            return False
        bought = market.buy_fire_gem()
        if bought is None:
            return False
        player.gold -= FIRE_GEM.cost
    elif 0 <= index < 5:
        card = market.row[index]
        if card is None:
            return False
        if player.gold < card.cost:
            return False
        player.gold -= card.cost
        bought = market.buy(index)
    else:
        return False

    if bought:
        if player.next_buy_to_hand:
            player.hand.append(bought)
            player.next_buy_to_hand = False
        elif player.next_buy_to_top or player.next_buy_to_top_action_only:
            qualifies_for_action_effect = (
                player.next_buy_to_top_action_only
                and bought.card_type == "action"
            )
            if player.next_buy_to_top or qualifies_for_action_effect:
                player.deck.insert(0, bought)
            else:
                # Bribe says "the next action you acquire this turn." A
                # non-action neither qualifies nor consumes that effect.
                player.discard.append(bought)
            if player.next_buy_to_top:
                player.next_buy_to_top = False
            if qualifies_for_action_effect:
                player.next_buy_to_top_action_only = False
        else:
            player.discard.append(bought)
        player.cards_bought += 1
        return True
    return False


_ALLY_EFFECT_KEYS = ("ally_combat", "ally_gold", "ally_health", "ally_draw",
                     "ally_opponent_discard", "prepare", "to_hand", "top_of_deck", "stun")


def _has_ally_payload(card: HRCard) -> bool:
    """Whether a card's ally ability actually does anything."""
    if not card.effects.get("ally_faction", ""):
        return False
    return any(card.effects.get(k) for k in _ALLY_EFFECT_KEYS)


def _apply_ally_effects(player: HRPlayer, card: HRCard, opponent: Optional[HRPlayer] = None,
                        stun_target: Optional[BoardChampion] = None):
    """Apply a card's ally-gated effects. Split out of play_card so it can also
    fire retroactively - see _resolve_pending_allies."""
    player.combat += card.get("ally_combat", 0)
    player.gold += card.get("ally_gold", 0)
    ally_heal = card.get("ally_health", 0)
    if ally_heal:
        player.hp = min(player.hp + ally_heal, HRGame.STARTING_HP)
    ally_draw = card.get("ally_draw", 0)
    if ally_draw:
        player.draw(ally_draw)
        if card.get("ally_discard_drawn", False):
            _discard_from_hand(player, ally_draw, opponent)

    if card.get("prepare", False):
        prepared = False
        for bc in player.board:
            if bc.alive and bc.exhausted:
                bc.exhausted = False
                prepared = True
                break
        if not prepared:
            player.pending_prepares += 1
    if card.get("to_hand", False):
        player.next_buy_to_hand = True
    if card.get("top_of_deck", False):
        if card.get("top_of_deck_action_only", False):
            player.next_buy_to_top_action_only = True
        else:
            player.next_buy_to_top = True
    ally_od = card.get("ally_opponent_discard", 0)
    if ally_od > 0 and opponent:
        _force_opponent_discard(opponent, ally_od, player)
    if card.get("stun", False) and opponent:
        _stun_champion(opponent, stun_target)


def _apply_per_champion_bonus(player: HRPlayer, card: HRCard, effect_key: str, resource: str):
    """Apply a "for each champion you have in play" bonus on a played action
    card (per_champion_combat / per_champion_health), and queue it to keep
    growing if more champions enter play later the same turn.

    Scoped to played actions only, not champion expend abilities
    (per_other_champion_combat and friends) - an expend is a discrete,
    one-time triggered action rather than a card that stays in a zone the way
    ally-bearing actions do, so there is nothing for a later champion to
    retroactively add to. If that scoping turns out to be too narrow, this is
    the function to widen.
    """
    per_unit = card.get(effect_key, 0)
    if not per_unit:
        return
    count = len([bc for bc in player.board if bc.alive])
    _grant_resource(player, resource, per_unit * count)
    player.pending_per_champion.append({"card": card, "resource": resource,
                                        "per_unit": per_unit, "credited": count})


def _grant_resource(player: HRPlayer, resource: str, amount: int):
    if not amount:
        return
    if resource == "combat":
        player.combat += amount
    elif resource == "health":
        player.hp = min(player.hp + amount, HRGame.STARTING_HP)


def _resolve_pending_per_champion(player: HRPlayer):
    """Top up every queued per-champion bonus to the current champion count.
    Called whenever a champion enters play."""
    if not player.pending_per_champion:
        return
    count = len([bc for bc in player.board if bc.alive])
    for entry in player.pending_per_champion:
        delta = count - entry["credited"]
        if delta > 0:
            _grant_resource(player, entry["resource"], entry["per_unit"] * delta)
            entry["credited"] = count


def _resolve_pending_allies(player: HRPlayer, opponent: Optional[HRPlayer] = None):
    """Fire the ally abilities of cards played earlier this turn that did not
    have a partner at the time but do now.

    Per the official rules: "The order in which you play your cards does not
    matter. As soon as you have two or more cards of the same faction in play,
    you may trigger all relevant Ally Abilities." The engine used to evaluate
    ally_bonus once, at play time, and never revisit it - so playing a lone
    Guild card and then a second Guild card fired only the second one's ally.
    """
    if not player.pending_ally:
        return
    still_pending = []
    for pending in player.pending_ally:
        if has_ally(pending, player):
            stun_target = next((target for card, target in player.pending_stun_targets
                                if card is pending), None)
            _apply_ally_effects(player, pending, opponent, stun_target=stun_target)
            player.pending_stun_targets = [
                (card, target) for card, target in player.pending_stun_targets if card is not pending
            ]
        else:
            still_pending.append(pending)
    player.pending_ally = still_pending


def has_ally(card: HRCard, player: HRPlayer) -> bool:
    """Check if player gets ally bonus for this card.

    The card itself does NOT count — you need ANOTHER card of the same faction
    in play (per official rules: 'as soon as you have another card of that faction').

    "In play" covers champions on the board *and* Actions/Items played earlier
    this turn, which stay in play until the Discard Phase. Checking only the
    board meant 21 of the 36 ally cards - every non-champion one - could never
    trigger each other, so faction-stacking with actions (playing two Guild
    actions in a turn) silently did nothing.
    """
    ally_faction = card.effects.get("ally_faction", "")
    if not ally_faction:
        return False
    if any(bc.card.faction == ally_faction and bc.card is not card
           for bc in player.board):
        return True
    return any(c.faction == ally_faction and c is not card
               for c in player.played_this_turn)
