"""A/B the enemy-board-denial term in evaluate_state.

MCTS (bot seat) vs the four heuristic profiles, win rate, across several values
of DENY_BOARD_WEIGHT. Weight 0 is the current pure-HP-diff search eval; higher
values price the recurring economy an enemy champion generates, which the
ROLLOUT_TURNS=4 horizon cannot see.

Selection discipline (learned from v17_best): sweep on a tuning seed block,
then confirm the chosen weight on a disjoint held-out block. A weight that wins
only on the seeds it was picked on is noise.

Usage:
    python hero_deny_ab.py [games_per_profile] [budget_ms]
"""
import sys
import time

import web.bot as bot_module
from hero_mcts_bench import PROFILE_WEIGHTS, play_game

bot_module.EVAL_MODE = "search"  # the mode with the blind spot

PROFILES = list(PROFILE_WEIGHTS)
WEIGHTS = [0.0, 15.0, 30.0]
TUNE_SEED = 1000
HOLDOUT_SEED = 60000


def win_rate(weight, budget, games, seed_base):
    bot_module.DENY_BOARD_WEIGHT = weight
    rates = {}
    for profile in PROFILES:
        wins = sum(play_game(profile, "mcts", budget, seed_base + i)[0] == "bot"
                   for i in range(games))
        rates[profile] = wins / games
    bot_module.DENY_BOARD_WEIGHT = 0.0
    return rates


def _avg(rates):
    return sum(rates.values()) / len(rates)


if __name__ == "__main__":
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    print(f"MCTS (search eval) vs profiles, {games} games/profile, {budget}ms")
    print(f"Sweeping DENY_BOARD_WEIGHT on tuning seeds {TUNE_SEED}+\n")
    print("weight " + "".join(f"{p[:6]:>9}" for p in PROFILES) + "     avg")

    start = time.time()
    tune = {}
    for w in WEIGHTS:
        r = win_rate(w, budget, games, TUNE_SEED)
        tune[w] = r
        print(f"{w:6.0f}" + "".join(f"{r[p]:8.1%} " for p in PROFILES)
              + f"  {_avg(r):6.1%}   ({time.time() - start:.0f}s)", flush=True)

    best = max(WEIGHTS, key=lambda w: _avg(tune[w]))
    print(f"\nbest on tuning: weight {best:.0f} at {_avg(tune[best]):.1%} "
          f"(vs weight 0 at {_avg(tune[0.0]):.1%})")

    if best == 0.0:
        print("tuning favours the original eval; no held-out confirmation needed")
    else:
        print(f"\nConfirming weight 0 vs {best:.0f} on held-out seeds {HOLDOUT_SEED}+...")
        h0 = win_rate(0.0, budget, games, HOLDOUT_SEED)
        hb = win_rate(best, budget, games, HOLDOUT_SEED)
        print(f"  weight 0 : {_avg(h0):.1%}")
        print(f"  weight {best:.0f}: {_avg(hb):.1%}   ({(_avg(hb) - _avg(h0)) * 100:+.1f}pp)")
