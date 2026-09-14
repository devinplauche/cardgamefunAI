"""Two coherent strategy archetypes, to test whether Hero Realms has a
strategy-dependent best response (rock-paper-scissors) that an opponent
classifier could exploit.

The four existing profiles (aggressive/economic/champion/balanced) all pick
"best affordable card by a weighting" and turned out to form a dominance
hierarchy - champion beats all - with no cycle. That is not the RPS an
experienced player describes. The two archetypes here are actual game plans:

  RUSH: race. Buy the cheapest combat per gold, never invest in slow economy,
  and send all combat to the face (only clearing guards that block). Wants the
  game over before an engine comes online.

  SAC_ENGINE: go long. Prioritize acquiring sacrifice enablers, then economy
  and card quality; the engine's auto-sacrifice thins starters each turn, and
  a thinned, high-quality deck compounds. Plays for board control.

The player's claim is a specific cycle: SAC_ENGINE beats the slow grinders
(time to compound), RUSH beats SAC_ENGINE (no time to compound). If that shows
up, opponent-reading has measurable value and the classifier is worth building.
"""

from hero_ai import (_buy_val, attack_weakest, expend_all, play_all_playable,
                     remove_stunned_champions)
from hero_engine import buy_card


def _has_sacrifice(card):
    return bool(card.effects.get("sacrifice_card"))


def buy_rush(player, opponent, market):
    """Buy the most combat-per-turn available; always spend, never sit on gold.

    Combat-forward with a mild cheap-bias tiebreak (more cheap cards played per
    turn = more attacks), plus some weight on economy/draw so it can keep
    affording combat. The earlier version subtracted full cost and gated on a
    positive threshold, which rejected nearly every card and passed - a rush
    that buys nothing is just a slow loss."""
    for _ in range(5):
        best_i, best_val = -1, -1e9
        for i, c in enumerate(market.row_cards()):
            if c is None or c.cost > player.gold:
                continue
            val = (c.get("combat", 0) * 3 + c.get("sacrifice_combat", 0) * 2
                   + c.get("draw", 0) * 2 + c.get("gold", 0) * 1.0
                   - c.cost * 0.25)
            if c.card_type == "champion":
                val += c.health * 0.5 + (2 if c.guard else 0)
            if val > best_val:
                best_val, best_i = val, i
        if best_i >= 0:
            buy_card(player, market, best_i)
        elif player.gold >= 2 and market.can_buy_fire_gem():
            buy_card(player, market, 5)
        else:
            break


def attack_rush(player, opponent, guards):
    """Clear only the guards that block, then send everything to the face.

    Deliberately does NOT snipe non-guard champions: a rush wants face damage,
    not board control, and combat spent on a champion is a turn not spent
    closing the game."""
    guards.sort(key=lambda bc: bc.current_health)
    for bc in guards:
        if player.combat <= 0:
            break
        dmg = min(player.combat, bc.current_health)
        bc.current_health -= dmg
        player.combat -= dmg
    remove_stunned_champions(opponent)
    # leftover combat stays on player.combat and spills to the face in the
    # caller, exactly as the profiles' post-attack `opponent.hp -= combat` does.


def buy_sac_engine(player, opponent, market):
    """Sacrifice enablers first, then economy and quality; go long."""
    for _ in range(5):
        best_i, best_val = -1, 0.01
        for i, c in enumerate(market.row_cards()):
            if c is None or c.cost > player.gold:
                continue
            val = _buy_val(c, gold_weight=3, combat_weight=1, health_weight=1,
                           draw_weight=3, champ_weight=2, guard_bonus=2)
            if _has_sacrifice(c):
                val += 10  # the enabler is the whole plan; grab it on sight
            if val > best_val:
                best_val, best_i = val, i
        if best_i >= 0:
            buy_card(player, market, best_i)
        elif player.gold >= 2 and market.can_buy_fire_gem():
            buy_card(player, market, 5)
        else:
            break


ARCHETYPES = {
    "rush": dict(play=play_all_playable, buy=buy_rush,
                 attack=attack_rush, expend=expend_all),
    "sac_engine": dict(play=play_all_playable, buy=buy_sac_engine,
                       attack=attack_weakest, expend=expend_all),
}
