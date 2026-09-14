"""Decision-level regret: how much is each decision worth, and who captures it?

Use this BEFORE reaching for a win-rate A/B. Win rate needs thousands of games
to resolve 3pp, carries a ~10pp seed-block effect, and tells you only that
something changed. This resolves in about a minute, has no game-outcome
variance, and localises *which* decisions are being lost.

METHOD. Sample real bot decisions, then score every legal option with a heavy
oracle (paired common-random-number rounds at a large simulation count). The
oracle's per-option utilities are the closest thing to ground truth available
under the search's own objective. Three quantities fall out:

  stakes  the oracle's best option minus its worst - how much choosing well at
          this decision is worth *at all*. If this is near zero the decision
          does not matter and no policy change to it can help.
  regret  what a given policy gives up by picking what it picks. Small regret
          against large stakes means the policy is already fine.
  agree   how often a policy picks the oracle's top option.

Utilities are reported in HP. _search_utility is 0.5 + 0.4*tanh(HP_diff*10/250),
so near parity one utility point is ~62.5 HP, which makes the numbers readable
against a 50 HP starting total.

WHAT IT FOUND (2026-08-01, and it reframed the project):

    phase     n   stakes   search regret   heuristic regret   agree
    buy      25   3.6 HP          0.3 HP             1.2 HP     72%
    combat   25   0.6 HP          0.1 HP             0.5 HP     64%

Buy decisions are worth ~6x what combat decisions are worth, and the bot already
captures most of the buy value. That explains why years of buy-policy tuning
moved nothing: there is only ~3.6 HP on the table and search leaves only 0.3 of
it. It also explains the flat combat number - `_combat_search_actions` resolves
lethal, guard and killable-champion cases by rule *before* search sees them, so
what reaches the tree is the genuinely near-equivalent residue.

CAVEAT, and it is the important one. The oracle uses the same rollout the search
does, so this measures the objective's opinion of itself. It cannot see a value
the objective is blind to. Read a near-zero stakes number as "this objective
does not distinguish these options", not as "these options are equivalent" - the
two differ exactly when the objective is wrong, which is worth knowing about.

Usage:
    python hero_regret.py                     # buy and combat, 25 positions each
    python hero_regret.py --positions 40 --oracle 2000
"""
from __future__ import annotations

import argparse
import random
import statistics

from web.bot import (_action_key, _heuristic_rollout_action, _search_actions,
                     apply_action, choose_bot_action)
from web.opponent_profiles import profile_buy_action
from web.session import create_session

# _search_utility is 0.5 + 0.4*tanh(raw/250) with raw = HP_diff*10, so near
# parity d(utility)/d(HP) = 0.4*10/250 = 0.016, i.e. 62.5 HP per utility point.
HP_PER_UTILITY = 62.5


def sample_positions(phases, per_phase, seed_base=4000, opponent="balanced"):
    """Real positions reached in play, where the bot has a genuine choice."""
    buckets = {phase: [] for phase in phases}
    seed = seed_base
    while min(len(v) for v in buckets.values()) < per_phase and seed < seed_base + 400:
        random.seed(seed)
        session = create_session(seed=seed, algorithm="mcts")
        steps = 0
        while session.winner is None and steps < 400:
            if session.active_player == "player":
                actions = session.legal_actions()
                apply_action(session, profile_buy_action(session, actions, opponent)
                             if session.phase == "buy" else _heuristic_rollout_action(session))
            else:
                if (session.phase in buckets and len(buckets[session.phase]) < per_phase
                        and len(_search_actions(session)) >= 2):
                    buckets[session.phase].append(session.clone())
                apply_action(session, _heuristic_rollout_action(session))
            steps += 1
        seed += 1
    return buckets


def score_positions(positions, oracle_sims, policy_sims):
    """Per-position (stakes, search regret, heuristic regret, search agreed)."""
    rows = []
    for position in positions:
        oracle = choose_bot_action(position.clone(), algorithm="mcts",
                                   max_iterations=oracle_sims)
        utility = {_action_key(c): c["averageUtility"] for c in oracle["candidates"]
                   if c.get("averageUtility") is not None}
        if len(utility) < 2:
            continue
        best = max(utility.values())

        fast = choose_bot_action(position.clone(), algorithm="mcts",
                                 max_iterations=policy_sims)
        # candidates[0] is the search's own top pick, read before the override
        # gate can substitute the heuristic action.
        fast_key = _action_key(fast["candidates"][0]) if fast.get("candidates") else None
        heuristic_key = _action_key(_heuristic_rollout_action(position.clone()))

        rows.append((
            best - min(utility.values()),
            best - utility.get(fast_key, min(utility.values())),
            best - utility.get(heuristic_key, min(utility.values())),
            fast_key == _action_key(oracle["candidates"][0]),
        ))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--positions", type=int, default=25, help="positions per phase")
    ap.add_argument("--oracle", type=int, default=1320,
                    help="simulations for the ground-truth oracle")
    ap.add_argument("--policy", type=int, default=66,
                    help="simulations for the policy under test (~what 60ms buys)")
    ap.add_argument("--phases", nargs="+", default=["buy", "combat"])
    ap.add_argument("--seed-base", type=int, default=4000)
    args = ap.parse_args()

    buckets = sample_positions(args.phases, args.positions, args.seed_base)
    print(f"oracle {args.oracle} sims vs policy {args.policy} sims, "
          f"utilities converted at {HP_PER_UTILITY} HP/point\n")
    header = (f"{'phase':<9}{'n':>4}{'stakes':>10}{'search regret':>15}"
              f"{'heur regret':>14}{'search agrees':>15}")
    print(header)
    print("-" * len(header))
    for phase, positions in buckets.items():
        rows = score_positions(positions, args.oracle, args.policy)
        if not rows:
            continue
        stakes, fast, heur, agree = zip(*rows)
        print(f"{phase:<9}{len(rows):>4}"
              f"{statistics.mean(stakes) * HP_PER_UTILITY:>9.1f} HP"
              f"{statistics.mean(fast) * HP_PER_UTILITY:>14.1f} HP"
              f"{statistics.mean(heur) * HP_PER_UTILITY:>13.1f} HP"
              f"{sum(agree) / len(agree):>15.0%}")

    print("\nstakes = oracle's best option minus its worst, i.e. how much choosing")
    print("well at that decision is worth at all. regret = HP given up versus the")
    print("oracle's best. Near-zero stakes means the *objective* does not separate")
    print("these options - which is not the same as the options being equivalent.")


if __name__ == "__main__":
    main()
