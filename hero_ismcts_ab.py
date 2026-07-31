"""A/B true ISMCTS against the committed root-determinization search.

What is being compared, and why it is the only fair comparison:

  control   ROOT_SAMPLING_MODE="paired" - the currently committed search.
            One sampled world per round, cloned once per public root action,
            exactly one rollout per branch, no interior nodes at all.
  treatment ROOT_SAMPLING_MODE="ismcts" - one determinization per iteration
            descending a persistent tree keyed by information sets, so
            statistics survive a change of determinization below the root.

Same budget, same seat (the bot seat - see hero_mcts_bench's docstring), same
seeds, same everything else. The `heuristic` row is web/bot.py's own greedy
fallback in that same seat: the MCTS-minus-heuristic delta is the signal and
the absolute number carries the second-player advantage.

Selection-bias discipline (this project has been bitten repeatedly, see
BASELINE.md): sweep the ISMCTS knobs on the tuning seed block, then confirm the
single best arm against the control on a *disjoint* held-out block and report a
z-score. Nothing gets a new default on a tuning-block win.

Power: the measured variance ceiling on this game is ~78%, and at 40
games/profile (160/arm) one standard error on a difference is ~5.5pp, so only
gaps above ~11pp are detectable. A small positive delta here is not a win.

Usage:
    python hero_ismcts_ab.py 40 60
    python hero_ismcts_ab.py 40 60 --depths 1 2 3 --opponent-nodes both
    nohup python hero_ismcts_ab.py 40 60 > ismcts_ab.log 2>&1 &
"""
from __future__ import annotations

import argparse
import math
import time

import web.bot as bot_module
from hero_mcts_bench import PROFILE_WEIGHTS, play_game

PROFILES = list(PROFILE_WEIGHTS)
TUNE_SEED = 1000
HOLDOUT_SEED = 60000


class Arm:
    """One search configuration, applied to web.bot for the duration of a run."""

    def __init__(self, label, sampling, depth=None, exploration=None,
                 opponent_nodes=False, algorithm="mcts"):
        self.label = label
        self.sampling = sampling
        self.depth = depth
        self.exploration = exploration
        self.opponent_nodes = opponent_nodes
        self.algorithm = algorithm

    def __enter__(self):
        self._saved = {
            name: getattr(bot_module, name)
            for name in ("ROOT_SAMPLING_MODE", "ISMCTS_MAX_DEPTH",
                         "ISMCTS_EXPLORATION", "ISMCTS_OPPONENT_NODES")
        }
        bot_module.ROOT_SAMPLING_MODE = self.sampling
        bot_module.ISMCTS_OPPONENT_NODES = self.opponent_nodes
        if self.depth is not None:
            bot_module.ISMCTS_MAX_DEPTH = self.depth
        if self.exploration is not None:
            bot_module.ISMCTS_EXPLORATION = self.exploration
        return self

    def __exit__(self, *exc):
        for name, value in self._saved.items():
            setattr(bot_module, name, value)
        return False


def win_rate(arm, budget, games, seed_base, budget_scope="action"):
    with arm:
        per = {}
        wins = total = 0
        for profile in PROFILES:
            won = sum(
                play_game(profile, arm.algorithm, budget, seed_base + index,
                          budget_scope=budget_scope)[0] == "bot"
                for index in range(games)
            )
            per[profile] = won / games
            wins += won
            total += games
    return wins / total, per


def z_score(rate_a, rate_b, n):
    """Two-proportion z for independent seed blocks of n games each."""
    standard_error = math.sqrt(rate_a * (1 - rate_a) / n + rate_b * (1 - rate_b) / n)
    if standard_error <= 0:
        return 0.0
    return (rate_b - rate_a) / standard_error


def build_arms(depths, explorations, opponent_nodes):
    arms = [Arm("paired (committed)", "paired")]
    variants = {"off": [False], "on": [True], "both": [False, True]}[opponent_nodes]
    for depth in depths:
        for exploration in explorations:
            for opponent in variants:
                suffix = " +oppnodes" if opponent else ""
                label = f"ismcts d{depth} c{exploration:g}{suffix}"
                arms.append(Arm(label, "ismcts", depth=depth,
                                exploration=exploration, opponent_nodes=opponent))
    return arms


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("games", type=int, nargs="?", default=40,
                    help="seeded games per profile (default: 40)")
    ap.add_argument("budget", type=int, nargs="?", default=60,
                    help="search budget in ms (default: 60, the shipping constraint)")
    ap.add_argument("--depths", type=int, nargs="+", default=[1, 2, 3],
                    help="ISMCTS_MAX_DEPTH values to sweep")
    ap.add_argument("--exploration", type=float, nargs="+", default=[0.7],
                    help="ISMCTS_EXPLORATION values to sweep")
    ap.add_argument("--opponent-nodes", choices=["off", "on", "both"], default="both",
                    help="whether the opponent gets real tree nodes; 'both' measures it")
    ap.add_argument("--budget-scope", choices=["action", "turn"], default="action",
                    help="action: budget each bot choice; turn: production run_bot_turn path")
    ap.add_argument("--skip-heuristic", action="store_true",
                    help="omit the same-seat greedy reference row")
    args = ap.parse_args()

    bot_module.EVAL_MODE = "search"
    bot_module.BUY_POLICY = "static"
    bot_module.MCTS_UTILITY_MODE = "bounded"

    arms = build_arms(args.depths, args.exploration, args.opponent_nodes)
    n = args.games * len(PROFILES)

    print(f"ISMCTS vs committed search, {args.games} games/profile ({n}/arm), "
          f"{args.budget}ms/{args.budget_scope}")
    print(f"rollout_turns={bot_module.ROLLOUT_TURNS} eval={bot_module.EVAL_MODE} "
          f"buy_root_width={bot_module.MCTS_BUY_ROOT_WIDTH} "
          f"override_margin={bot_module.MCTS_OVERRIDE_MARGIN}")
    print(f"one SE on a difference at this n is "
          f"{math.sqrt(2 * 0.5 * 0.5 / n) * 100:.1f}pp; treat anything under ~11pp as unresolved")
    print(f"\nSweeping on tuning seeds {TUNE_SEED}+\n")

    header = f"{'arm':<26}" + "".join(f"{p[:8]:>10}" for p in PROFILES) + f"{'avg':>9}{'secs':>8}"
    print(header)
    print("-" * len(header))

    start = time.time()
    tuning = {}
    for arm in arms:
        mark = time.time()
        rate, per = win_rate(arm, args.budget, args.games, TUNE_SEED,
                             budget_scope=args.budget_scope)
        tuning[arm.label] = (rate, arm)
        print(f"{arm.label:<26}" + "".join(f"{per[p]:9.1%} " for p in PROFILES)
              + f"{rate:8.1%}{time.time() - mark:8.0f}", flush=True)

    if not args.skip_heuristic:
        reference = Arm("heuristic (same seat)", "paired", algorithm="heuristic")
        mark = time.time()
        rate, per = win_rate(reference, args.budget, args.games, TUNE_SEED,
                             budget_scope=args.budget_scope)
        print(f"{reference.label:<26}" + "".join(f"{per[p]:9.1%} " for p in PROFILES)
              + f"{rate:8.1%}{time.time() - mark:8.0f}", flush=True)

    control = arms[0]
    candidates = {label: value for label, value in tuning.items() if label != control.label}
    best_label = max(candidates, key=lambda label: candidates[label][0])
    best_rate, best_arm = candidates[best_label]
    control_rate = tuning[control.label][0]

    print(f"\ntuning: best ISMCTS arm is '{best_label}' at {best_rate:.1%}, "
          f"control at {control_rate:.1%} ({(best_rate - control_rate) * 100:+.1f}pp)")
    print(f"tuning-block sweep total: {time.time() - start:.0f}s "
          "(wildly uneven per-arm times above mean the machine slept mid-run; "
          "win rates are outcome-based and survive that)")

    if best_rate <= control_rate:
        print("\nNo ISMCTS arm beat the committed search even on the seeds it was "
              "selected on. Held-out confirmation would only measure noise; "
              "the default stays 'paired'.")
        return

    print(f"\nConfirming '{best_label}' vs control on held-out seeds {HOLDOUT_SEED}+\n")
    held = {}
    for arm in (control, best_arm):
        mark = time.time()
        rate, per = win_rate(arm, args.budget, args.games, HOLDOUT_SEED,
                             budget_scope=args.budget_scope)
        held[arm.label] = rate
        print(f"{arm.label:<26}" + "".join(f"{per[p]:9.1%} " for p in PROFILES)
              + f"{rate:8.1%}{time.time() - mark:8.0f}", flush=True)

    delta = held[best_arm.label] - held[control.label]
    z = z_score(held[control.label], held[best_arm.label], n)
    print(f"\nheld-out delta {delta * 100:+.1f}pp  z={z:.2f}  "
          f"{'SIGNIFICANT' if abs(z) > 1.96 else 'NOT significant'}")
    print(f"tuning delta was {(best_rate - control_rate) * 100:+.1f}pp; a held-out "
          "delta far below it is the selection-bias signature, not a result.")
    if z <= 1.96:
        print("Default stays 'paired'.")


if __name__ == "__main__":
    main()
