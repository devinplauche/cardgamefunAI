"""Which cards does the shipped buy policy misprice, and by how much?

`BUY_POLICY="static"` uses `_buy_priority` (web/session.py), a fixed per-card
score with no board context. The override gate admits only ~9% of search's
proposed deviations, so this policy makes ~91% of the bot's buy decisions.

`hero_regret.py` measures what that costs in aggregate: buy decisions carry
~3.6 HP of stakes, search gives up ~0.3 HP of it and the heuristic gives up
~1.2 HP - a third of the available value, and 4x search's regret. This file
localises *which cards* that comes from.

METHOD. Sample real buy decisions. In each, rank the affordable options two
ways: by `_buy_priority` (what the bot uses) and by oracle utility (heavy paired
rollouts - the best available estimate of what the option is actually worth).
Convert both to percentile-within-position so positions with different numbers
of options are comparable, then average per card.

A card the policy ranks near the top while the oracle ranks it near the bottom
is being **overrated**, and the bot buys it too often. The reverse is
**underrated**. The gap is reported in HP so it is comparable to the 3.6 HP of
stakes a buy decision carries.

WHY AN INTERNAL ORACLE RATHER THAN A COMMUNITY TIER LIST. A human tier list
ranks cards in *Hero Realms*; this ranks them in *this engine*, which is what
the bot is actually playing and what its policy should be tuned against. The
two differ wherever the engine is an imperfect reimplementation - and it has
been wrong before (Ruby was a 1-health action for the project's entire life).
BASELINE.md's existing card-lift analysis has the opposite problem: it comes
from the digital client's Hero mode, with hero decks and 12 cards this engine
does not model, so it does not transfer cleanly.

CAVEAT. The oracle uses the same rollout the search does, so this finds cards
the *objective* prices differently from `_buy_priority` - not cards that are
truly good or bad. Where the objective itself is blind, both will agree and be
wrong together. Read it as "the buy heuristic disagrees with the search's own
valuation on these cards", which is still exactly the gap worth closing, since
search demonstrably converts more of the available value.

Usage:
    python hero_card_audit.py                    # 60 positions
    python hero_card_audit.py --positions 120 --oracle 720
"""
from __future__ import annotations

import argparse
import random
import statistics
from collections import defaultdict

from hero_engine import FIRE_GEM
from web.bot import (_action_key, _heuristic_rollout_action, apply_action,
                     choose_bot_action)
from web.opponent_profiles import profile_buy_action
from web.session import _buy_priority, create_session

HP_PER_UTILITY = 62.5


def _card_for(session, action):
    index = int(action.get("marketIndex", -1))
    if index == 5:
        return FIRE_GEM
    row = session.market.row_cards()
    return row[index] if 0 <= index < len(row) else None


def sample_buy_positions(count, seed_base, opponent="balanced"):
    """Positions where the bot faces at least three affordable buys.

    Three rather than two: with only two options a percentile is either 0 or 1
    and carries almost no information about *degree* of mispricing.
    """
    positions = []
    seed = seed_base
    while len(positions) < count and seed < seed_base + 600:
        random.seed(seed)
        session = create_session(seed=seed, algorithm="mcts")
        steps = 0
        while session.winner is None and steps < 400 and len(positions) < count:
            if session.active_player == "player":
                actions = session.legal_actions()
                apply_action(session, profile_buy_action(session, actions, opponent)
                             if session.phase == "buy" else _heuristic_rollout_action(session))
            else:
                if session.phase == "buy":
                    buys = [a for a in session.legal_actions() if a["type"] == "buy_card"]
                    if len(buys) >= 3:
                        positions.append(session.clone())
                apply_action(session, _heuristic_rollout_action(session))
            steps += 1
        seed += 1
    return positions


def _percentiles(values):
    """Rank -> percentile in [0,1]; 1.0 is best. Ties share the mean rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    span = max(len(values) - 1, 1)
    return [r / span for r in ranks]


def audit(positions, oracle_sims):
    stats = defaultdict(lambda: {"policy": [], "oracle": [], "hp": []})
    for position in positions:
        buys = [a for a in position.legal_actions() if a["type"] == "buy_card"]
        cards = [_card_for(position, a) for a in buys]
        keep = [(a, c) for a, c in zip(buys, cards) if c is not None]
        if len(keep) < 3:
            continue

        result = choose_bot_action(position.clone(), algorithm="mcts",
                                   max_iterations=oracle_sims)
        utility = {_action_key(c): c["averageUtility"] for c in result["candidates"]
                   if c.get("averageUtility") is not None}
        scored = [(a, c) for a, c in keep if _action_key(a) in utility]
        if len(scored) < 3:
            continue

        policy_pct = _percentiles([_buy_priority(c) for _, c in scored])
        oracle_values = [utility[_action_key(a)] for a, _ in scored]
        oracle_pct = _percentiles(oracle_values)
        best = max(oracle_values)

        for (action, card), p_pct, o_pct, value in zip(scored, policy_pct,
                                                       oracle_pct, oracle_values):
            entry = stats[card.name]
            entry["policy"].append(p_pct)
            entry["oracle"].append(o_pct)
            entry["hp"].append((best - value) * HP_PER_UTILITY)
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--positions", type=int, default=60)
    ap.add_argument("--oracle", type=int, default=480)
    ap.add_argument("--seed-base", type=int, default=4000)
    ap.add_argument("--min-appearances", type=int, default=4)
    args = ap.parse_args()

    positions = sample_buy_positions(args.positions, args.seed_base)
    print(f"{len(positions)} buy decisions with >=3 affordable options, "
          f"oracle at {args.oracle} sims\n")
    stats = audit(positions, args.oracle)

    rows = []
    for name, entry in stats.items():
        n = len(entry["policy"])
        if n < args.min_appearances:
            continue
        rows.append((
            statistics.mean(entry["policy"]) - statistics.mean(entry["oracle"]),
            name, n,
            statistics.mean(entry["policy"]),
            statistics.mean(entry["oracle"]),
            statistics.mean(entry["hp"]),
        ))
    if not rows:
        raise SystemExit("no card met --min-appearances; sample more positions")
    rows.sort(reverse=True)

    header = (f"{'card':<26}{'n':>4}{'policy':>9}{'oracle':>9}"
              f"{'gap':>8}{'HP behind best':>16}")
    print("OVERRATED by the buy heuristic (policy ranks it above the oracle)")
    print(header)
    print("-" * len(header))
    for gap, name, n, p, o, hp in rows[:8]:
        print(f"{name:<26}{n:>4}{p:>9.2f}{o:>9.2f}{gap:>+8.2f}{hp:>13.1f} HP")

    print("\nUNDERRATED by the buy heuristic")
    print(header)
    print("-" * len(header))
    for gap, name, n, p, o, hp in rows[-8:][::-1]:
        print(f"{name:<26}{n:>4}{p:>9.2f}{o:>9.2f}{gap:>+8.2f}{hp:>13.1f} HP")

    gaps = [abs(r[0]) for r in rows]
    print(f"\nmean |gap| over {len(rows)} cards: {statistics.mean(gaps):.2f} "
          f"(0 = the heuristic ranks exactly as the oracle does, 1 = fully inverted)")
    print("percentiles are within-position, 1.0 = best available option.")
    print("Caveat: the oracle shares the search's objective, so this finds where")
    print("the buy heuristic and the search disagree - not ground truth about the game.")


if __name__ == "__main__":
    main()
