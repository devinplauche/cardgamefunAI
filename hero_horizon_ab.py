"""A/B the MCTS rollout horizon (ROLLOUT_TURNS) on win rate.

The controlled test confirmed the mechanism: at horizon 12 a surviving enemy
economy champion's gold converts to attack inside the rollout, so pure HP-diff
values killing it (Broelyn 0% -> 85% snipe) with no shaping term. But horizon
16 at 400ms starved the search so badly even Cron stopped being cleared, so
deeper is not free - at a fixed wall-clock budget, longer rollouts mean fewer
of them.

This measures the net effect on win rate at a fixed budget (the practically
relevant comparison: what horizon should the shipped bot use). Tuning seeds
sweep the horizon; the best is confirmed on a disjoint held-out block, per the
selection-bias discipline.

Usage:
    python hero_horizon_ab.py [games_per_profile] [budget_ms]
"""
import math
import sys
import time

import web.bot as bot_module
from hero_mcts_bench import PROFILE_WEIGHTS, play_game

bot_module.EVAL_MODE = "search"
bot_module.DENY_BOARD_WEIGHT = 0.0  # horizon effect only, no shaping

PROFILES = list(PROFILE_WEIGHTS)
HORIZONS = [4, 8, 12]
TUNE_SEED = 1000
HOLDOUT_SEED = 60000


def win_rate(horizon, budget, games, seed_base):
    bot_module.ROLLOUT_TURNS = horizon
    wins = total = 0
    per = {}
    for profile in PROFILES:
        w = sum(play_game(profile, "mcts", budget, seed_base + i)[0] == "bot"
                for i in range(games))
        per[profile] = w / games
        wins += w
        total += games
    bot_module.ROLLOUT_TURNS = 4
    return wins / total, per


if __name__ == "__main__":
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    n = games * len(PROFILES)

    print(f"MCTS (search eval) vs profiles, {games} games/profile ({n}/arm), {budget}ms")
    print(f"Sweeping ROLLOUT_TURNS on tuning seeds {TUNE_SEED}+ (baseline horizon 4)\n")
    print("horizon " + "".join(f"{p[:6]:>9}" for p in PROFILES) + "     avg")

    start = time.time()
    tune = {}
    for h in HORIZONS:
        r, per = win_rate(h, budget, games, TUNE_SEED)
        tune[h] = r
        print(f"{h:6d} " + "".join(f"{per[p]:8.1%} " for p in PROFILES)
              + f"  {r:6.1%}   ({time.time() - start:.0f}s)", flush=True)

    best = max(HORIZONS, key=lambda h: tune[h])
    print(f"\nbest on tuning: horizon {best} at {tune[best]:.1%} "
          f"(vs horizon 4 at {tune[4]:.1%})")

    if best == 4:
        print("tuning favours the current horizon; no held-out confirmation needed")
    else:
        print(f"\nConfirming horizon 4 vs {best} on held-out seeds {HOLDOUT_SEED}+...")
        h4, _ = win_rate(4, budget, games, HOLDOUT_SEED)
        hb, _ = win_rate(best, budget, games, HOLDOUT_SEED)
        se = math.sqrt(h4 * (1 - h4) / n + hb * (1 - hb) / n)
        z = (hb - h4) / se
        print(f"  horizon 4 : {h4:.1%}")
        print(f"  horizon {best}: {hb:.1%}   {(hb - h4) * 100:+.1f}pp  z={z:.2f}  "
              f"{'SIGNIFICANT' if abs(z) > 1.96 else 'not significant'}")
