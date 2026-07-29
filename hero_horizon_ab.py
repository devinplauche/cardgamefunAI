"""A/B the MCTS rollout horizon (ROLLOUT_TURNS) on win rate.

Historical full-state experiments established the mechanism: a surviving
economy champion's gold can buy a card that is later drawn and used for combat,
so pure HP-diff values that chain without a hand-tuned exchange rate. The
current bot uses fair root-only information-set samples, however, so every
horizon change must be measured again here. Deeper is not free: at a fixed
wall-clock budget, longer rollouts mean fewer of them.

This measures the net effect on win rate at a fixed budget (the practically
relevant comparison: what horizon should the shipped bot use). Tuning seeds
sweep the horizon; the best is confirmed on a disjoint held-out block, per the
selection-bias discipline.

Usage:
    python hero_horizon_ab.py [games_per_profile] [budget_ms]
    python hero_horizon_ab.py 40 60 --budget-scope turn
    python hero_horizon_ab.py 40 60 --iterations 16
"""
import argparse
import math
import time

import web.bot as bot_module
from hero_mcts_bench import PROFILE_WEIGHTS, play_game

PROFILES = list(PROFILE_WEIGHTS)
HORIZONS = [4, 8, 12, 16, 24]
TUNE_SEED = 1000
HOLDOUT_SEED = 60000


def win_rate(horizon, budget, games, seed_base, max_iterations=None,
             budget_scope="action"):
    previous_horizon = bot_module.ROLLOUT_TURNS
    try:
        bot_module.ROLLOUT_TURNS = horizon
        wins = total = 0
        per = {}
        for profile in PROFILES:
            w = sum(play_game(profile, "mcts", budget, seed_base + i,
                              max_iterations=max_iterations,
                              budget_scope=budget_scope)[0] == "bot"
                    for i in range(games))
            per[profile] = w / games
            wins += w
            total += games
        return wins / total, per
    finally:
        bot_module.ROLLOUT_TURNS = previous_horizon


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("games", type=int, nargs="?", default=40,
                    help="seeded games per profile (default: 40)")
    ap.add_argument("budget", type=int, nargs="?", default=200,
                    help="MCTS budget in milliseconds (default: 200)")
    ap.add_argument("--iterations", type=int, default=None,
                    help="root-simulation cap per MCTS decision; action scope only")
    ap.add_argument("--budget-scope", choices=["action", "turn"], default="action",
                    help="action: historical per-choice budget; turn: production run_bot_turn path")
    ap.add_argument("--horizons", type=int, nargs="+", default=HORIZONS,
                    help="rollout horizons to sweep (default: 4 8 12 16 24)")
    args = ap.parse_args()
    if args.budget_scope == "turn" and args.iterations is not None:
        ap.error("--iterations is only supported with --budget-scope action")

    bot_module.EVAL_MODE = "search"
    bot_module.DENY_BOARD_WEIGHT = 0.0  # horizon effect only, no shaping
    bot_module.BUY_POLICY = "static"
    bot_module.MCTS_UTILITY_MODE = "bounded"
    games = args.games
    budget = args.budget
    horizons = args.horizons
    n = games * len(PROFILES)

    budget_label = (f"{args.iterations} simulation cap/action"
                    if args.iterations is not None else f"{budget}ms/{args.budget_scope}")
    print(f"MCTS (search eval) vs profiles, {games} games/profile ({n}/arm), {budget_label}")
    print(f"Sweeping ROLLOUT_TURNS on tuning seeds {TUNE_SEED}+ (baseline horizon {horizons[0]})\n")
    print("horizon " + "".join(f"{p[:6]:>9}" for p in PROFILES) + "     avg")

    start = time.time()
    tune = {}
    for h in horizons:
        r, per = win_rate(h, budget, games, TUNE_SEED,
                          max_iterations=args.iterations,
                          budget_scope=args.budget_scope)
        tune[h] = r
        print(f"{h:6d} " + "".join(f"{per[p]:8.1%} " for p in PROFILES)
              + f"  {r:6.1%}   ({time.time() - start:.0f}s)", flush=True)

    baseline = horizons[0]
    best = max(horizons, key=lambda h: tune[h])
    print(f"\nbest on tuning: horizon {best} at {tune[best]:.1%} "
          f"(vs horizon {baseline} at {tune[baseline]:.1%})")

    if best == baseline:
        print("tuning favours the current horizon; no held-out confirmation needed")
    else:
        print(f"\nConfirming horizon {baseline} vs {best} on held-out seeds {HOLDOUT_SEED}+...")
        h4, _ = win_rate(baseline, budget, games, HOLDOUT_SEED,
                         max_iterations=args.iterations,
                         budget_scope=args.budget_scope)
        hb, _ = win_rate(best, budget, games, HOLDOUT_SEED,
                         max_iterations=args.iterations,
                         budget_scope=args.budget_scope)
        se = math.sqrt(h4 * (1 - h4) / n + hb * (1 - hb) / n)
        z = (hb - h4) / se
        print(f"  horizon {baseline} : {h4:.1%}")
        print(f"  horizon {best}: {hb:.1%}   {(hb - h4) * 100:+.1f}pp  z={z:.2f}  "
              f"{'SIGNIFICANT' if abs(z) > 1.96 else 'not significant'}")
