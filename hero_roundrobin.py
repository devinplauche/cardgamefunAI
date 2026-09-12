"""Round-robin every strategy against every other and test for RPS.

Two players alternate full turns via their profile's play/expend/buy/attack
functions. Player A draws 3 and moves first (the seat compensation the real
client uses); common seeds down each column isolate strategy from shuffle.

The RPS test: is the best agent opponent-dependent? A single dominating
strategy means opponent-reading is worthless here; a cycle (rush beats
sac_engine beats grinders beats rush) means it has measurable value.
"""
import sys

import numpy as np

from hero_ai import (attack_strongest, attack_weakest, buy_aggressive,
                     buy_balanced, buy_champion, buy_economic, expend_all,
                     play_all_playable)
from hero_archetypes import ARCHETYPES
from hero_engine import HRMarket, HRPlayer, load_hero_cards, _resolve_board_allies
import random

CARDS = load_hero_cards("data/hero_realms_cards.json")

STRATS = {
    "aggressive": dict(play=play_all_playable, buy=buy_aggressive, attack=attack_weakest, expend=expend_all),
    "economic": dict(play=play_all_playable, buy=buy_economic, attack=attack_strongest, expend=expend_all),
    "champion": dict(play=play_all_playable, buy=buy_champion, attack=attack_weakest, expend=expend_all),
    "balanced": dict(play=play_all_playable, buy=buy_balanced, attack=attack_weakest, expend=expend_all),
    **ARCHETYPES,
}


def _take_turn(p, o, mkt, strat):
    p.gold = p.combat = p.actions_played = p.cards_bought = 0
    p.played_this_turn.clear()
    p.pending_per_champion.clear()
    for bc in p.board:
        bc.exhausted = False
        bc.ally_paid_this_turn = False
        bc.current_health = bc.card.health
    _resolve_board_allies(p, o)
    strat["play"](p, o, mkt)
    strat["expend"](p, o)
    strat["buy"](p, o, mkt)
    if p.combat > 0:
        guards = [bc for bc in o.board if bc.guard and bc.alive]
        strat["attack"](p, o, guards)
        o.hp -= p.combat
        p.combat = 0
    # Discard Phase: cards played this turn go to the discard pile, exactly as
    # GameSession.end_turn does via discard_played_cards(). Omitting this left
    # every played card in played_this_turn limbo - it never returned to the
    # deck, so decks degraded to starters and games ran 80+ turns.
    p.discard_played_cards()
    for c in p.hand:
        p.discard.append(c)
    p.hand.clear()
    p.draw(5)


def play_game(a_name, b_name, seed):
    rng = random.Random(seed)
    a, b = HRPlayer("A", rng), HRPlayer("B", rng)
    a.setup_starting_deck()
    b.setup_starting_deck()
    mkt = HRMarket(CARDS, rng)
    a.draw(3)
    b.draw(5)
    A, B = STRATS[a_name], STRATS[b_name]
    for _ in range(300):
        _take_turn(a, b, mkt, A)
        if b.hp <= 0:
            return "A"
        _take_turn(b, a, mkt, B)
        if a.hp <= 0:
            return "B"
    return "A" if a.hp >= b.hp else "B"


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    names = list(STRATS)

    print(f"Win rate as agent A (row) vs opponent B (column), n={n}, common seeds\n")
    print("agent".ljust(12) + "".join(x[:6].rjust(9) for x in names) + "    mean")
    M = {}
    for ai in names:
        row = [sum(1 for s in range(n) if play_game(ai, bj, 8000 + s) == "A") / n
               for bj in names]
        M[ai] = row
        print(ai.ljust(12) + "".join(f"{v:8.1%} " for v in row) + f"  {np.mean(row):5.1%}")

    print()
    best_per = {names[j]: max(names, key=lambda a: M[a][j]) for j in range(len(names))}
    for opp, best in best_per.items():
        print(f"  best vs {opp:11s}: {best}")
    distinct = len(set(best_per.values()))
    print(f"\ndistinct best-responses across opponents: {distinct}"
          + ("  -> STRATEGY-DEPENDENT (RPS present, classifier has value)"
             if distinct > 1 else "  -> one strategy dominates (no RPS)"))

    # The player's specific claim, checked directly.
    print("\nThe claimed cycle:")
    print(f"  sac_engine vs grinders (economic/champion/balanced): "
          f"{np.mean([M['sac_engine'][names.index(g)] for g in ['economic','champion','balanced']]):.1%}")
    print(f"  rush vs sac_engine: {M['rush'][names.index('sac_engine')]:.1%}")
    print(f"  sac_engine vs rush: {M['sac_engine'][names.index('rush')]:.1%}")
