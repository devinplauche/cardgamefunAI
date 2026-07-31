"""Sweep the override gate: when is search allowed to overrule the heuristic?

This targets the one mechanism in this repo with a confirmed win behind it. The
shipped bot does not replace the heuristic with search - it runs the heuristic
as the default policy and lets MCTS deviate only when it clears a confidence
gate (`_guarded_root_choice`). That configuration beat the same-seat heuristic
49/80 to 39/80 on two fresh production-path blocks, discordant wins 12-2, exact
paired p=.013. Nothing else in the project has that pedigree.

So the interesting question is not "is search better than the heuristic" but
"how confident must search be before deviating is worth it" - the gate itself.
Too strict and the search never gets to contribute; too loose and it overrides
on sampling noise, which at ~66 rollouts per decision is a real risk.

WHY PAIRED / McNEMAR RATHER THAN WIN-RATE DIFFERENCES.

BASELINE.md now records a ~10pp seed-block effect and ~6pp training-seed noise,
and three of this session's candidate wins evaporated because they were read off
marginal win rates. Marginal rates at n=400 carry ~2.5pp of standard error each,
so a 3pp gate effect is unresolvable that way.

Every arm here plays the *same* seeds, so the comparison can be made per game:
count only the games where two gates disagree on the outcome (discordant pairs)
and test those with an exact McNemar. Seed difficulty cancels exactly, which is
what makes a small real effect visible at this sample size. The marginal rate is
still reported, but the paired test is the decision.

Usage:
    python hero_override_ab.py 100 60
    nohup python hero_override_ab.py 100 60 > override_ab.log 2>&1 &
"""
from __future__ import annotations

import argparse
import math
import time
from itertools import product

import web.bot as bot_module
from hero_mcts_bench import PROFILE_WEIGHTS, play_game

PROFILES = list(PROFILE_WEIGHTS)
TUNE_SEED = 1000
CONFIRM_SEED = 700_000

# label -> (algorithm, gate, margin, confidence_z)
# Calibrated on a pilot run, which measured how often each gate actually lets
# search deviate: unguarded 55.6%, margin 0.05 15.3%, confidence z=1.0 13.2%,
# the shipped margin 0.10 10.0%, confidence z=2.0 4.2%, margin 0.20 **0.0%**.
# Margin 0.20 never fires, so it is silently identical to the pure heuristic and
# would have burned an arm measuring the floor twice. The live range is 0.0-0.15.
ARMS = [
    ("heuristic (floor)",   "heuristic", "margin",     0.10, 1.0),
    ("unguarded (-1.0)",    "mcts",      "margin",     -1.0, 1.0),
    ("margin 0.00",         "mcts",      "margin",     0.00, 1.0),
    ("margin 0.05",         "mcts",      "margin",     0.05, 1.0),
    ("margin 0.10 (SHIP)",  "mcts",      "margin",     0.10, 1.0),
    ("margin 0.15",         "mcts",      "margin",     0.15, 1.0),
    ("confidence z=1.0",    "mcts",      "confidence", 0.10, 1.0),
    ("confidence z=2.0",    "mcts",      "confidence", 0.10, 2.0),
]
DEFAULT_ARM = "margin 0.10 (SHIP)"


def mcnemar_exact(n01: int, n10: int) -> float:
    """Two-sided exact McNemar p-value on the discordant pairs."""
    n = n01 + n10
    if n == 0:
        return 1.0
    k = min(n01, n10)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return min(1.0, 2.0 * tail)


def run_arm(arm, budget, games, seed_base, iterations=None):
    """Per-game outcomes keyed by (profile, seed) so arms can be paired.

    `iterations` replaces the wall-clock budget with a fixed simulation count,
    which makes the search deterministic given the seed. That matters more than
    it sounds: under a wall-clock budget the iteration count drifts with machine
    load, so the *same* configuration picks different moves between runs. This
    sweep measured margin 0.00 and margin -1.0 - which are provably the same
    policy, since `proposed` is the max-mean-utility child and so `advantage` is
    always >= 0 - at 48.2% and 53.5%, giving p=0.006 and p=0.298 against the
    same comparator. Pairing cancels seed difficulty but not that.
    """
    label, algorithm, gate, margin, z = arm
    saved = (bot_module.MCTS_OVERRIDE_GATE, bot_module.MCTS_OVERRIDE_MARGIN,
             bot_module.MCTS_CONFIDENCE_Z)
    bot_module.SELECTION_COUNTS.clear()
    try:
        bot_module.MCTS_OVERRIDE_GATE = gate
        bot_module.MCTS_OVERRIDE_MARGIN = margin
        bot_module.MCTS_CONFIDENCE_Z = z
        outcomes = {}
        for profile, index in product(PROFILES, range(games)):
            seed = seed_base + index
            winner, _, _ = play_game(profile, algorithm, budget, seed,
                                     max_iterations=iterations)
            outcomes[(profile, seed)] = winner == "bot"
        return outcomes, dict(bot_module.SELECTION_COUNTS)
    finally:
        (bot_module.MCTS_OVERRIDE_GATE, bot_module.MCTS_OVERRIDE_MARGIN,
         bot_module.MCTS_CONFIDENCE_Z) = saved


def override_rate(counts):
    total = sum(counts.values())
    if not total:
        return 0.0
    return counts.get("mcts_override", 0) / total


def run_block(label, seed_base, arms, budget, games, iterations=None):
    print(f"\n=== block {label} (seeds {seed_base}+, {games * len(PROFILES)} games/arm) ===")
    header = (f"{'arm':<22}{'win rate':>10}{'override':>10}"
              f"{'vs SHIP: +/-':>14}{'p':>9}{'secs':>7}")
    print(header)
    print("-" * len(header))

    results = {}
    for arm in arms:
        mark = time.time()
        outcomes, counts = run_arm(arm, budget, games, seed_base, iterations)
        results[arm[0]] = outcomes
        rate = sum(outcomes.values()) / len(outcomes)
        line = f"{arm[0]:<22}{rate:>9.1%}{override_rate(counts):>10.1%}"
        if arm[0] != DEFAULT_ARM and DEFAULT_ARM in results:
            base = results[DEFAULT_ARM]
            n10 = sum(1 for k in outcomes if outcomes[k] and not base[k])
            n01 = sum(1 for k in outcomes if not outcomes[k] and base[k])
            line += f"{n10:>7}/{n01:<6}{mcnemar_exact(n01, n10):>9.3f}"
        else:
            line += f"{'':>14}{'':>9}"
        print(line + f"{time.time() - mark:>7.0f}", flush=True)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("games", type=int, nargs="?", default=100)
    ap.add_argument("budget", type=int, nargs="?", default=60)
    ap.add_argument("--iterations", type=int, default=None,
                    help="fixed simulations per decision instead of a wall-clock budget; "
                         "makes the search deterministic given the seed, which is required "
                         "for any gate-vs-gate question")
    ap.add_argument("--null-control", action="store_true",
                    help="add a duplicate of the shipped arm; any discordance it shows "
                         "is pure harness noise and calibrates every other p-value")
    args = ap.parse_args()

    print(f"override-gate sweep, {args.games} games/profile "
          f"({args.games * len(PROFILES)}/arm), {args.budget}ms/action")
    print("'vs SHIP' counts discordant games as wins-for-arm/wins-for-ship; "
          "p is a two-sided exact McNemar on those pairs only.")
    print("Seed difficulty cancels in a paired test, which is why this can see "
          "effects the marginal win rate cannot.")

    # The shipped arm must run first so later arms can be paired against it.
    ordered = ([a for a in ARMS if a[0] == DEFAULT_ARM]
               + [a for a in ARMS if a[0] != DEFAULT_ARM])
    if args.null_control:
        ship = next(a for a in ARMS if a[0] == DEFAULT_ARM)
        ordered = ordered + [("SHIP (null replicate)",) + ship[1:]]
    tune = run_block("TUNE", TUNE_SEED, ordered, args.budget, args.games,
                     args.iterations)

    base = tune[DEFAULT_ARM]
    best, best_gain = None, 0
    for label, outcomes in tune.items():
        if label in (DEFAULT_ARM, "heuristic (floor)", "SHIP (null replicate)"):
            continue
        n10 = sum(1 for k in outcomes if outcomes[k] and not base[k])
        n01 = sum(1 for k in outcomes if not outcomes[k] and base[k])
        if n10 - n01 > best_gain:
            best, best_gain = label, n10 - n01

    if best is None:
        print(f"\nNo gate beat the shipped {DEFAULT_ARM} on discordant pairs. "
              "Nothing to confirm; the gate stays as shipped.")
        return

    print(f"\nbest on tuning: '{best}' (+{best_gain} net discordant games)")
    arms = ([a for a in ARMS if a[0] == DEFAULT_ARM]
            + [a for a in ARMS if a[0] == best])
    confirm = run_block("CONFIRM", CONFIRM_SEED, arms, args.budget, args.games,
                        args.iterations)

    base, arm = confirm[DEFAULT_ARM], confirm[best]
    n10 = sum(1 for k in arm if arm[k] and not base[k])
    n01 = sum(1 for k in arm if not arm[k] and base[k])
    p = mcnemar_exact(n01, n10)
    print(f"\nconfirm: '{best}' vs shipped, discordant {n10}-{n01}, exact p={p:.4f}")
    if n10 > n01 and p < 0.05:
        print("Replicated on a disjoint block. This gate is a promotion candidate.")
    else:
        print("Did not replicate. The gate stays as shipped - a tuning-block "
              "lead that does not survive a disjoint block is the pattern that "
              "has now cost this project four candidate wins.")


if __name__ == "__main__":
    main()
