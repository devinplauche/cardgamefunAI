"""Hero Realms game engine — deck-building card game simulation."""

from __future__ import annotations
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
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cards = []
    for c in data:
        c["card_type"] = c.pop("type", "action")
        c.pop("location", None)
        c.pop("subtypes", None)
        cards.append(HRCard(**c))
    return cards


# --- Starting cards (Hero Realms base set) ---
GOLD = HRCard(id="gold", name="Gold", cost=0, faction="",
              card_type="treasure", effects={"gold": 1})
SHORTSWORD = HRCard(id="shortsword", name="Shortsword", cost=0, faction="",
                    card_type="action", effects={"combat": 2})
DAGGER = HRCard(id="dagger", name="Dagger", cost=0, faction="",
                card_type="action", effects={"combat": 1})
RUBY = HRCard(id="ruby", name="Ruby", cost=0, faction="",
              card_type="action", effects={"health": 1})
FIRE_GEM = HRCard(id="fire_gem", name="Fire Gem", cost=2, faction="",
                  card_type="item", effects={"gold": 2, "sacrifice_combat": 3})


class BoardChampion:
    def __init__(self, card: HRCard):
        self.card = card
        self.current_health = card.health
        self.exhausted = False  # true if expended this turn
        self.guard = card.guard

    @property
    def name(self):
        return self.card.name

    @property
    def alive(self):
        return self.current_health > 0


class HRPlayer:
    def __init__(self, name: str):
        self.name = name
        self.hp = 50
        self.gold = 0
        self.combat = 0
        self.deck: list[HRCard] = []
        self.hand: list[HRCard] = []
        self.discard: list[HRCard] = []
        self.banish: list[HRCard] = []  # cards removed from game (sacrificed)
        self.board: list[BoardChampion] = []  # champions in play
        self.actions_played: int = 0
        self.cards_bought: int = 0
        self.next_buy_to_hand: bool = False  # Deception ally: next bought card goes to hand
        self.next_buy_to_top: bool = False   # Rasmus ally: next bought card goes on top of deck
        self.next_buy_to_top_action_only: bool = False  # Bribe ally: next ACTION on top

    def setup_starting_deck(self):
        self.deck = [GOLD] * 7 + [SHORTSWORD] + [DAGGER] + [RUBY]
        random.shuffle(self.deck)

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
        random.shuffle(self.deck)

    def hand_size(self):
        return len(self.hand)

    def allies(self) -> set[str]:
        factions = set()
        for bc in self.board:
            if bc.card.faction:
                factions.add(bc.card.faction)
        return factions


# --- Effect helper functions ---

def _card_score(card: HRCard) -> int:
    """Score a card's overall value (higher = more valuable to keep)."""
    if card.id == "gold":
        return -100
    if card.id == "shortsword":
        return -75
    if card.id == "dagger":
        return -60
    if card.id == "ruby":
        return -50
    return (card.cost * 10 + card.get("combat", 0) * 4 + card.get("gold", 0) * 3 +
            card.get("health", 0) * 3 + card.get("draw", 0) * 5 +
            (card.health if card.card_type == "champion" else 0) * 2)


def _find_worst_idx(cards: list) -> int:
    """Index of the lowest-value card (for sacrificing/discarding)."""
    best_i, best_s = 0, float("inf")
    for i, c in enumerate(cards):
        s = _card_score(c)
        if s < best_s:
            best_s = s
            best_i = i
    return best_i


def _find_best_idx(cards: list) -> int:
    """Index of the highest-value card (for returning from discard)."""
    best_i, best_s = 0, float("-inf")
    for i, c in enumerate(cards):
        s = _card_score(c)
        if s > best_s:
            best_s = s
            best_i = i
    return best_i


def _worth_sacrificing(card: HRCard) -> bool:
    """Whether a hand/discard card is worth an optional sacrifice.

    Every printed sacrifice effect in this card set reads "you may sacrifice"
    (or uses the {Sacrifice}: keyword, which means the same thing) - it is
    never mandatory. The engine used to apply these unconditionally, which
    meant a lean, thinned deck (exactly what a sacrifice-focused strategy
    builds toward) had no bad cards left to decline sacrificing, and was
    forced to burn a genuinely useful card instead.

    Reuses _card_score's own scale: the four starting cards score strongly
    negative (-50 to -100) and every real market card scores positive
    (cost*10 alone is already >=10 for any purchased card), so this cleanly
    separates "starting junk" from "anything actually worth keeping."
    """
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
        # Matches the guard check the neighbouring or_choice combat branch
        # uses below, for the same "is this guard currently a threat"
        # question. Note _resolve_combat's own guard check (used for real
        # combat resolution) does not filter by exhausted at all, so whether
        # exhaustion should affect guard-blocking here is itself an open
        # question - out of scope for this fix, which is only about the two
        # call sites agreeing with each other.
        guards = [bc for bc in opponent.board if bc.guard and bc.alive and not bc.exhausted]
        if guards:
            return False
    owned_economy = sum(
        1 for c in player.deck + player.hand + player.discard
        if c.get("gold", 0) > 0 and c.id != "gold"
    )
    return owned_economy >= 2


def _discard_from_hand(player: HRPlayer, n: int):
    """Discard n lowest-value cards from hand (self-discard: keep best)."""
    n = min(n, len(player.hand))
    for _ in range(n):
        idx = _find_worst_idx(player.hand)
        player.discard.append(player.hand.pop(idx))


def _force_opponent_discard(opponent: HRPlayer, n: int = 1):
    """Opponent discards n of their worst cards (opponent chooses to minimize harm)."""
    n = min(n, len(opponent.hand))
    for _ in range(n):
        idx = _find_worst_idx(opponent.hand)
        opponent.discard.append(opponent.hand.pop(idx))


class HRMarket:
    def __init__(self, cards: list[HRCard]):
        # Fire Gems are always in a separate side pile, not shuffled into market row.
        self.pool = [c for c in cards if c.name.lower() != "fire gem"]
        self.fire_gems_remaining = 16  # base set ships 16 Fire Gem cards
        random.shuffle(self.pool)
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
        player.cards_bought = 0
        player.next_buy_to_hand = False
        player.next_buy_to_top = False
        player.next_buy_to_top_action_only = False
        for bc in player.board:
            bc.exhausted = False

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

        # AI decides which guard champions to attack (if multiple)
        guards = [bc for bc in opponent.board if bc.guard and bc.alive]
        if guards:
            ai_attack(player, opponent, guards)

        dmg = player.combat
        if dmg <= 0:
            return

        # Remaining damage hits the player
        opponent.hp -= dmg

    def _cleanup(self, player: HRPlayer):
        for c in player.hand:
            player.discard.append(c)
        player.hand.clear()
        player.draw(5)


def play_card(player: HRPlayer, card: HRCard, market: HRMarket,
              ally_bonus: bool = False, opponent: HRPlayer = None):
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
        return True

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
    champion_count = len([bc for bc in player.board if bc.alive])
    per_champion_combat = card.get("per_champion_combat", 0)
    if per_champion_combat:
        player.combat += per_champion_combat * champion_count
    per_champion_health = card.get("per_champion_health", 0)
    if per_champion_health:
        heal = per_champion_health * champion_count
        if heal:
            player.hp = min(player.hp + heal, HRGame.STARTING_HP)

    # ---- Ally bonus ----
    if ally_bonus:
        player.combat += card.get("ally_combat", 0)
        player.gold += card.get("ally_gold", 0)
        ally_heal = card.get("ally_health", 0)
        if ally_heal:
            player.hp = min(player.hp + ally_heal, HRGame.STARTING_HP)
        ally_draw = card.get("ally_draw", 0)
        if ally_draw:
            player.draw(ally_draw)
            if card.get("ally_discard_drawn", False):
                _discard_from_hand(player, ally_draw)

    total_base_draws = draws + actual_draw_up_to + (card.get("ally_draw", 0) if ally_bonus else 0)

    # ---- Self-discard (draw then discard) ----
    discard_n = card.get("discard", 0)
    if discard_n > 0:
        if total_base_draws == 0:
            player.draw(discard_n)
        _discard_from_hand(player, discard_n)

    # ---- Filter-draw (discard_drawn: draw X then discard X) ----
    if card.get("discard_drawn", False) and total_base_draws > 0:
        _discard_from_hand(player, total_base_draws)

    # ---- Self-sacrifice (sacrifice THIS card for bonus effects) ----
    # Optional per the printed text ("{Sacrifice}:" / "you may sacrifice") -
    # see _should_self_sacrifice's docstring for why this can no longer be
    # unconditional.
    sacrificed = False
    sac_combat = card.get("sacrifice_combat", 0)
    if sac_combat > 0 and _should_self_sacrifice(player, opponent, requires_open_combat=True):
        player.combat += sac_combat
        sacrificed = True
    sac_od = card.get("sacrifice_opponent_discard", 0)
    if sac_od > 0 and opponent and _should_self_sacrifice(player, opponent):
        _force_opponent_discard(opponent, sac_od)
        sacrificed = True

    # ---- Opponent discard (always, if card has it) ----
    od = card.get("opponent_discard", 0)
    if od > 0 and opponent:
        _force_opponent_discard(opponent, od)

    # ---- Generic sacrifice from hand/discard (Dark Reward, Death Touch, etc.) ----
    # Optional ("you may sacrifice a card in your hand or discard pile") -
    # only take it if the worst available card is actually junk; see
    # _worth_sacrificing.
    if card.effects.get("sacrifice_card", False):
        source = None
        if player.hand:
            source = player.hand
        elif player.discard:
            source = player.discard
        if source:
            idx = _find_worst_idx(source)
            if _worth_sacrificing(source[idx]):
                player.banish.append(source.pop(idx))

    # ---- Stun (primary for non-ally cards like Fire Bomb; ally-only if ally_faction set) ----
    if card.get("stun", False) and opponent:
        ally_faction = card.get("ally_faction", "")
        if not ally_faction or ally_bonus:
            for bc in opponent.board:
                if bc.alive:
                    bc.exhausted = True
                    break

    # ---- Ally-only effects ----
    if ally_bonus:
        # Prepare (ready own champion) (Domination, Rally the Troops)
        if card.get("prepare", False):
            for bc in player.board:
                if bc.alive and bc.exhausted:
                    bc.exhausted = False
                    break

        # Deception ally: next bought card goes to hand (not discard)
        if card.get("to_hand", False):
            player.next_buy_to_hand = True

        # Bribe ally: next bought card goes on top of deck
        if card.get("top_of_deck", False):
            player.next_buy_to_top = True
            if card.get("top_of_deck_action_only", False):
                player.next_buy_to_top_action_only = True

        # Ally opponent discard (Broelyn, Nature's Bounty)
        ally_od = card.get("ally_opponent_discard", 0)
        if ally_od > 0 and opponent:
            _force_opponent_discard(opponent, ally_od)

    # ---- Non-ally effects (always apply) ----

    # Recycle (discard to top of deck) (Smash and Grab - no ally needed)
    if card.get("recycle", False) and player.discard:
        idx = _find_best_idx(player.discard)
        player.deck.insert(0, player.discard.pop(idx))

    # Reanimate (champion from discard to top of deck) (Varrick)
    if card.get("reanimate", False):
        for i, c in enumerate(player.discard):
            if c.card_type == "champion":
                player.deck.insert(0, player.discard.pop(i))
                break

    # ---- Non-champion cards go to banish (if sacrificed) or discard ----
    if sacrificed:
        player.banish.append(card)
    else:
        player.discard.append(card)

    return True


def expend_champion(player: HRPlayer, bc: BoardChampion, opponent: HRPlayer = None) -> bool:
    """Use a champion's expend ability. Applies the card's effects again."""
    if bc.exhausted or not bc.alive:
        return False
    bc.exhausted = True

    card = bc.card

    # ---- "Or" choice: apply only the best option ----
    or_choice = card.get("or_choice", [])
    if or_choice:
        options = []
        if "combat" in or_choice:
            val = card.get("combat", 0)
            if val:
                guards = [bc for bc in opponent.board if bc.guard and bc.alive and not bc.exhausted] if opponent else []
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
            best = max(options, key=lambda x: x[2])
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
        other_wild = len([c for c in player.board if c.alive and c.card.faction == "Wild" and c != bc])
        player.combat += per_other_wild_combat * other_wild
    draws = card.get("draw", 0)
    if draws:
        player.draw(draws)

    discard_n = card.get("discard", 0)
    if discard_n > 0:
        if draws == 0:
            player.draw(discard_n)
        _discard_from_hand(player, discard_n)

    if card.get("discard_drawn", False) and draws > 0:
        _discard_from_hand(player, draws)

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
            idx = _find_worst_idx(source)
            if _worth_sacrificing(source[idx]):
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
            idx = _find_worst_idx(source)
            if not _worth_sacrificing(source[idx]):
                break
            player.banish.append(source.pop(idx))

    # ---- Stun on expend (Rake, Master Assassin) ----
    if card.get("stun", False) and opponent:
        for c in opponent.board:
            if c.alive:
                c.exhausted = True
                break

    # ---- Opponent discard on expend (Torgen Rocksplitter) ----
    od = card.get("opponent_discard", 0)
    if od > 0 and opponent:
        _force_opponent_discard(opponent, od)

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
                _discard_from_hand(player, ally_draw)

        # Champion ally top_of_deck (Rasmus: next bought card goes on top; Bribe: action only)
        if card.get("top_of_deck", False):
            player.next_buy_to_top = True
            if card.get("top_of_deck_action_only", False):
                player.next_buy_to_top_action_only = True

        # Champion ally opponent discard (Broelyn)
        ally_od = card.get("ally_opponent_discard", 0)
        if ally_od > 0 and opponent:
            _force_opponent_discard(opponent, ally_od)

    return True


def auto_expend_all(player: HRPlayer, opponent: HRPlayer = None):
    """Expend every ready champion on the board."""
    for bc in list(player.board):
        if bc.alive and not bc.exhausted:
            expend_champion(player, bc, opponent)


def buy_card(player: HRPlayer, market: HRMarket, index: int) -> bool:
    """Try to buy a market-row card (0-4) or Fire Gem side-pile card (5)."""
    if index == 5:
        if player.gold < FIRE_GEM.cost:
            return False
        bought = market.buy_fire_gem()
        if bought is None:
            return False
        player.gold -= FIRE_GEM.cost
    else:
        card = market.row[index]
        if card is None:
            return False
        if player.gold < card.cost:
            return False
        player.gold -= card.cost
        bought = market.buy(index)

    if bought:
        if player.next_buy_to_hand:
            player.hand.append(bought)
            player.next_buy_to_hand = False
        elif player.next_buy_to_top:
            if player.next_buy_to_top_action_only and bought.card_type != "action":
                # Bribe only puts actions on top; non-actions go to discard
                player.discard.append(bought)
            else:
                player.deck.insert(0, bought)
            player.next_buy_to_top = False
            player.next_buy_to_top_action_only = False
        else:
            player.discard.append(bought)
        player.cards_bought += 1
        return True
    return False


def has_ally(card: HRCard, player: HRPlayer) -> bool:
    """Check if player gets ally bonus for this card.
    
    The card itself does NOT count — you need ANOTHER card of the same faction
    in play (per official rules: 'as soon as you have another card of that faction').
    """
    ally_faction = card.effects.get("ally_faction", "")
    if not ally_faction:
        return False
    # Need another card (different object) of same faction on the board
    return any(bc.card.faction == ally_faction and bc.card is not card
               for bc in player.board)
