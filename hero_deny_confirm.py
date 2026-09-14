"""Powered confirmation of the board-denial term at the chosen weight.

The sweep found weight 15 positive on both tuning (+2pp) and held-out (+6pp),
but held-out was only z=1.40 - underpowered. This runs a single 2-arm test
(weight 0 vs 15) on a fresh seed block large enough to resolve a ~5pp effect
(~290 games/profile at 80% power), with a proper two-proportion z-test.
"""
import math
import sys
import time

import web.bot as bot_module
from hero_mcts_bench import PROFILE_WEIGHTS, play_game

bot_module.EVAL_MODE = "search"
PROFILES = list(PROFILE_WEIGHTS)
CONFIRM_SEED = 300000


def run(weight, budget, games, seed_base):
    bot_module.DENY_BOARD_WEIGHT = weight
    wins = total = 0
    per = {}
    for profile in PROFILES:
        w = sum(play_game(profile, "mcts", budget, seed_base + i)[0] == "bot"
                for i in range(games))
        per[profile] = w / games
        wins += w
        total += games
    bot_module.DENY_BOARD_WEIGHT = 0.0
    return wins / total, per


if __name__ == "__main__":
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    weight = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0
    n = games * len(PROFILES)

    print(f"Confirmation: weight 0 vs {weight:.0f}, {games} games/profile "
          f"({n}/arm), {budget}ms, fresh seeds {CONFIRM_SEED}+\n", flush=True)
    start = time.time()
    p0, per0 = run(0.0, budget, games, CONFIRM_SEED)
    print(f"  weight  0: {p0:.1%}  {({k: round(v,2) for k,v in per0.items()})}  ({time.time()-start:.0f}s)", flush=True)
    pw, perw = run(weight, budget, games, CONFIRM_SEED)
    print(f"  weight {weight:.0f}: {pw:.1%}  {({k: round(v,2) for k,v in perw.items()})}  ({time.time()-start:.0f}s)", flush=True)

    se = math.sqrt(p0 * (1 - p0) / n + pw * (1 - pw) / n)
    z = (pw - p0) / se
    ci = 1.96 * se
    print(f"\n  delta {(pw-p0)*100:+.1f}pp   95% CI [{(pw-p0-ci)*100:+.1f}, {(pw-p0+ci)*100:+.1f}]pp"
          f"   z={z:.2f}   {'SIGNIFICANT' if abs(z) > 1.96 else 'not significant'}")
