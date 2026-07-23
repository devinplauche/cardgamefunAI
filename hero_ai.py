"""AI strategies for Hero Realms."""

from hero_engine import HRPlayer, HRMarket, HRCard, play_card, buy_card, has_ally, auto_expend_all, remove_stunned_champions


# --- Play strategies ---

def play_order_score(card: HRCard) -> int:
    """Priority score for playing a card (higher = play first)."""
    if card.id == "gold":
        return 100
    if card.get("draw", 0):
        return 90 + card.get("draw", 0) * 10
    if card.get("gold", 0):
        return 80 + card.get("gold", 0) * 10
    if card.id == "shortsword":
        return 75
    if card.id == "dagger":
        return 70
    if card.id == "ruby":
        return 65
    if card.card_type == "champion":
        return 60 + card.cost
    if card.get("combat", 0):
        return 50
    if card.get("opponent_discard", 0) or card.get("ally_opponent_discard", 0):
        return 40
    return 0


def play_all_playable(player: HRPlayer, opponent: HRPlayer, market: HRMarket):
    """Play every card in hand, ordered for optimal effect (gold/draw first)."""
    for _ in range(20):
        best = None
        best_score = -1
        for c in player.hand:
            s = play_order_score(c)
            ally = has_ally(c, player)
            if ally:
                s += 5
            if s > best_score:
                best = c
                best_score = s
        if best:
            play_card(player, best, market, ally_bonus=has_ally(best, player), opponent=opponent)
        else:
            break


def play_only_gold_and_combat(player: HRPlayer, opponent: HRPlayer, market: HRMarket):
    """Only play gold-generating and direct-damage cards."""
    for _ in range(20):
        played = False
        for c in list(player.hand):
            if c.id in ("gold", "shortsword", "dagger", "ruby") or c.get("gold", 0) or c.get("combat", 0):
                if c.card_type == "action" or c.id == "gold":
                    play_card(player, c, market, ally_bonus=has_ally(c, player), opponent=opponent)
                    played = True
            elif c.card_type == "champion":
                play_card(player, c, market, ally_bonus=has_ally(c, player), opponent=opponent)
                played = True
        if not played:
            break


# --- Buy strategies ---

def _buy_val(c: HRCard, gold_weight=1, combat_weight=1, health_weight=1,
             draw_weight=1, champ_weight=0, guard_bonus=0) -> int:
    """Compute a buy value for card c with given weights."""
    val = (c.get("gold", 0) * gold_weight +
           c.get("combat", 0) * combat_weight +
           c.get("health", 0) * health_weight +
           c.get("draw", 0) * draw_weight)
    val += c.get("opponent_discard", 0) * 2
    val += c.get("ally_opponent_discard", 0) * 2
    val += c.get("sacrifice_combat", 0) * 1.5
    if c.card_type == "champion":
        val += champ_weight + c.health
        if c.guard:
            val += guard_bonus
    return val


def buy_aggressive(player: HRPlayer, opponent: HRPlayer, market: HRMarket):
    """Buy the highest-combat card affordable."""
    for _ in range(5):
        best_i = -1
        best_val = -1
        for i, c in enumerate(market.row_cards()):
            if c is None or c.cost > player.gold:
                continue
            val = _buy_val(c, combat_weight=2, draw_weight=3, champ_weight=3)
            if val > best_val:
                best_val = val
                best_i = i
        if best_i >= 0:
            buy_card(player, market, best_i)
        elif player.gold >= 2 and market.can_buy_fire_gem():
            buy_card(player, market, 5)
        else:
            break


def buy_economic(player: HRPlayer, opponent: HRPlayer, market: HRMarket):
    """Buy cards that generate gold first, then champions."""
    for _ in range(5):
        best_i = -1
        best_val = -1
        for i, c in enumerate(market.row_cards()):
            if c is None or c.cost > player.gold:
                continue
            val = _buy_val(c, gold_weight=4, combat_weight=1, draw_weight=3,
                          health_weight=1, champ_weight=2)
            if val > best_val:
                best_val = val
                best_i = i
        if best_i >= 0:
            buy_card(player, market, best_i)
        elif player.gold >= 2 and market.can_buy_fire_gem():
            buy_card(player, market, 5)
        else:
            break


def buy_champion(player: HRPlayer, opponent: HRPlayer, market: HRMarket):
    """Prioritize buying champions."""
    for _ in range(5):
        best_i = -1
        best_val = -1
        for i, c in enumerate(market.row_cards()):
            if c is None or c.cost > player.gold:
                continue
            if c.card_type == "champion":
                val = (_buy_val(c, combat_weight=2) +
                       c.health + (3 if c.guard else 0))
            else:
                val = _buy_val(c, combat_weight=1, gold_weight=2, draw_weight=2)
            if val > best_val:
                best_val = val
                best_i = i
        if best_i >= 0:
            buy_card(player, market, best_i)
        elif player.gold >= 2 and market.can_buy_fire_gem():
            buy_card(player, market, 5)
        else:
            break


def buy_balanced(player: HRPlayer, opponent: HRPlayer, market: HRMarket):
    """Balanced buy: value all stats evenly."""
    for _ in range(5):
        best_i = -1
        best_val = -1
        for i, c in enumerate(market.row_cards()):
            if c is None or c.cost > player.gold:
                continue
            val = _buy_val(c, gold_weight=2, combat_weight=2, health_weight=1,
                          draw_weight=3, champ_weight=c.health // 2)
            val -= c.cost // 2
            if val > best_val:
                best_val = val
                best_i = i
        if best_i >= 0:
            buy_card(player, market, best_i)
        elif player.gold >= 2 and market.can_buy_fire_gem():
            buy_card(player, market, 5)
        else:
            break


# --- Attack strategies ---

def attack_weakest(player: HRPlayer, opponent: HRPlayer, guards: list):
    """Attack the weakest guard champion first (fastest to kill)."""
    guards.sort(key=lambda bc: bc.current_health)
    for bc in guards:
        if player.combat <= 0:
            break
        dmg = min(player.combat, bc.current_health)
        bc.current_health -= dmg
        player.combat -= dmg
    # Stunned champions go to their owner's discard pile, not out of the game.
    remove_stunned_champions(opponent)


def attack_strongest(player: HRPlayer, opponent: HRPlayer, guards: list):
    """Attack the strongest guard champion first."""
    guards.sort(key=lambda bc: -bc.current_health)
    for bc in guards:
        if player.combat <= 0:
            break
        dmg = min(player.combat, bc.current_health)
        bc.current_health -= dmg
        player.combat -= dmg
    remove_stunned_champions(opponent)


# --- Expend strategy ---

def expend_all(player: HRPlayer, opponent: HRPlayer):
    """Expend all ready champions."""
    auto_expend_all(player, opponent)


def expend_none(player: HRPlayer, opponent: HRPlayer):
    """Skip champion expend phase."""
    pass


# --- Aggregated AI profiles ---

class AggressiveAI:
    name = "Aggressive"
    buy = staticmethod(buy_aggressive)
    play = staticmethod(play_all_playable)
    attack = staticmethod(attack_weakest)
    expend = staticmethod(expend_all)


class EconomicAI:
    name = "Economic"
    buy = staticmethod(buy_economic)
    play = staticmethod(play_all_playable)
    attack = staticmethod(attack_strongest)
    expend = staticmethod(expend_all)


class ChampionAI:
    name = "Champion"
    buy = staticmethod(buy_champion)
    play = staticmethod(play_all_playable)
    attack = staticmethod(attack_weakest)
    expend = staticmethod(expend_all)


class BalancedAI:
    name = "Balanced"
    buy = staticmethod(buy_balanced)
    play = staticmethod(play_all_playable)
    attack = staticmethod(attack_weakest)
    expend = staticmethod(expend_all)
