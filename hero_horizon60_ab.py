"""Is ROLLOUT_TURNS=16 the right horizon at the *60ms* budget?

Motivation, measured rather than assumed. Sampling real bot decisions and
scoring every option with a 480-simulation oracle at several horizons gives the
discriminative power available at each:

    horizon      buy stakes    combat stakes
          8         2.0 HP           0.3 HP
         16         4.1 HP           0.5 HP
         32         5.7 HP           0.5 HP
         48         5.7 HP           0.5 HP

Buy stakes grow with horizon and saturate at 32; combat is flat (the
high-stakes combat choices never reach the search - `_combat_search_actions`
resolves lethal, guard and killable-champion cases by rule first). So the
shipped horizon of 16 exposes only 4.1 HP of the 5.7 HP the objective can
actually see, i.e. the bot under-resolves its most consequential decision class
by ~28%.

THERE IS NO DEPTH/BREADTH TRADE HERE, which is the surprise. The obvious
objection is that a deeper rollout costs simulations at a fixed wall clock. It
does not, because the rollout almost always ends in a real win or loss long
before it reaches its limit:

    horizon   mean turns played   ended in win/loss   HIT THE LIMIT
          8                 6.6                 36%             64%
         16                10.0                 82%             18%
         24                11.9                 96%              4%
         32                10.6                 99%              0%
         48                10.5                 99%              0%

Confirmed at the benchmark level: 38 / 42 / 39 / 44 simulations per decision at
horizons 16 / 16 / 24 / 32. Flat.

So ROLLOUT_TURNS=16 does not buy speed. It truncates ~18% of rollouts for no
saving, replacing a definite win/loss with a squashed tanh of a mid-game HP
difference - and the oracle table above saturates at exactly the horizon where
truncation reaches 0%. The "extra signal" at 32 *is* those truncated rollouts
resolving properly. Above ~24 the setting is entirely inert.

BASELINE.md's horizon sweep chose 16, but it ran at 200ms and explicitly listed
"sweep the horizon at the 60ms interactive budget" as not-yet-done.

PROTOCOL. Prefer --iterations. Because a longer horizon costs no simulations,
holding simulations fixed hides no cost, and it makes the search deterministic
given the seed - which matters enormously here. Run under a wall clock instead
and the NULL REPLICATE arm (a byte-identical duplicate of SHIP) measured +4.0pp
at p=0.076 on 400 games: re-running the same bot moves 18% of games. Horizon 24
scored +4.3pp (p=0.152) and horizon 32 +4.8pp (p=0.127) in that same run, i.e.
both were indistinguishable from re-running the control.

Keep the null arm in either mode. Under fixed iterations it should read exactly
0/0, which is what makes every other p-value in the table trustworthy.

Usage:
    python hero_horizon60_ab.py 100 60 --iterations 40
"""
from __future__ import annotations

import argparse
import math
import time
from itertools import product

import web.bot as bot_module
from hero_mcts_bench import PROFILE_WEIGHTS, play_game

PROFILES = list(PROFILE_WEIGHTS)
BLOCKS = (("TUNE", 1000), ("HOLDOUT", 60_000))
CONTROL = 16
ARMS = [
    ("horizon 16 (SHIP)", 16),
    ("horizon 16 (null)", 16),
    ("horizon 24", 24),
    ("horizon 32", 32),
]


def mcnemar_exact(n01: int, n10: int) -> float:
    n = n01 + n10
    if n == 0:
        return 1.0
    k = min(n01, n10)
    return min(1.0, 2.0 * sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n))


def run(horizon, budget, games, seed_base, iterations=None):
    """Outcomes per (profile, seed), plus mean simulations per searched decision.

    The iteration count is a required diagnostic, not decoration: the entire
    premise is that a deeper rollout costs samples. If it does not drop roughly
    in proportion to the horizon, the arm is not doing what the label says.
    """
    previous = bot_module.ROLLOUT_TURNS
    bot_module.ROLLOUT_TURNS = horizon
    sims, decisions = 0, 0
    real = bot_module.choose_bot_action

    def counting(session, *args, **kwargs):
        nonlocal sims, decisions
        result = real(session, *args, **kwargs)
        # Both filters are load-bearing. The auto-resolved play/champion phases
        # return algorithm="heuristic" with iterations=1, and averaging those in
        # buries the real count (it read 4-5 instead of ~66). The fail-closed
        # determinization path returns algorithm="mcts" with iterations=0, which
        # is not a searched decision either.
        if result.get("algorithm") == "mcts" and result.get("iterations", 0) > 0:
            sims += result["iterations"]
            decisions += 1
        return result

    import hero_mcts_bench as bench
    bench.choose_bot_action = counting
    try:
        outcomes = {}
        for profile, index in product(PROFILES, range(games)):
            seed = seed_base + index
            outcomes[(profile, seed)] = play_game(
                profile, "mcts", budget, seed, max_iterations=iterations)[0] == "bot"
        return outcomes, (sims / decisions if decisions else 0.0)
    finally:
        bench.choose_bot_action = real
        bot_module.ROLLOUT_TURNS = previous


def block(label, seed_base, arms, budget, games, iterations=None):
    n = games * len(PROFILES)
    print(f"\n=== {label} (seeds {seed_base}+, {n} games/arm) ===")
    header = (f"{'arm':<22}{'win rate':>10}{'sims/dec':>10}"
              f"{'vs SHIP':>12}{'p':>9}{'secs':>7}")
    print(header)
    print("-" * len(header))
    results = {}
    for name, horizon in arms:
        mark = time.time()
        outcomes, sims = run(horizon, budget, games, seed_base, iterations)
        results[name] = outcomes
        rate = sum(outcomes.values()) / n
        cell = ""
        if name != arms[0][0]:
            base = results[arms[0][0]]
            n10 = sum(1 for k in outcomes if outcomes[k] and not base[k])
            n01 = sum(1 for k in outcomes if not outcomes[k] and base[k])
            cell = f"{n10:>5}/{n01:<6}{mcnemar_exact(n01, n10):>9.3f}"
        print(f"{name:<22}{rate:>9.1%}{sims:>10.0f}{cell if cell else '':>21}"
              f"{time.time() - mark:>7.0f}", flush=True)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("games", type=int, nargs="?", default=100)
    ap.add_argument("budget", type=int, nargs="?", default=60)
    ap.add_argument("--iterations", type=int, default=None,
                    help="fixed simulations per decision instead of wall clock. Valid "
                         "here *because* a longer horizon costs no simulations - measured "
                         "38/42/39/44 sims/decision at horizons 16/16/24/32 - so holding "
                         "simulations fixed does not hide a cost. Makes the search "
                         "deterministic, taking the null replicate to exactly 0/0.")
    args = ap.parse_args()

    print(f"horizon A/B at the shipped budget: {args.games} games/profile "
          f"({args.games * len(PROFILES)}/arm), {args.budget}ms/action")
    print("the 'null' arm is a duplicate of SHIP; whatever it shows is pure "
          "harness noise and every other p must be read against it")

    tune = block("TUNE", BLOCKS[0][1], ARMS, args.budget, args.games, args.iterations)
    base = tune[ARMS[0][0]]
    best, gain = None, 0
    for name, _ in ARMS[1:]:
        if "null" in name:
            continue
        outcomes = tune[name]
        net = (sum(1 for k in outcomes if outcomes[k] and not base[k])
               - sum(1 for k in outcomes if not outcomes[k] and base[k]))
        if net > gain:
            best, gain = name, net

    if best is None:
        print("\nNo horizon beat 16 on the block it was selected on. "
              "ROLLOUT_TURNS stays 16.")
        return

    print(f"\nbest on tuning: {best} (+{gain} net discordant games)")
    arms = [ARMS[0]] + [a for a in ARMS if a[0] == best]
    confirm = block("HOLDOUT", BLOCKS[1][1], arms, args.budget, args.games, args.iterations)
    b, a = confirm[ARMS[0][0]], confirm[best]
    n10 = sum(1 for k in a if a[k] and not b[k])
    n01 = sum(1 for k in a if not a[k] and b[k])
    p = mcnemar_exact(n01, n10)
    print(f"\nconfirm: {best} vs horizon 16 -> discordant {n10}-{n01}, p={p:.4f}")
    print("Replicated." if n10 > n01 and p < 0.05 else
          "Did not replicate. ROLLOUT_TURNS stays 16.")


if __name__ == "__main__":
    main()
