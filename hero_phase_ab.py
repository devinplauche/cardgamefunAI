"""A/B the game-phase valuation term, using within-block paired deltas.

The hypothesis, which is the one point every Hero Realms strategy source agrees
on: economy has a delayed payoff ("a two-deck delay from the time you purchase
the economy card to the time you can play the card you purchased"), so gold
bought late is never converted, while damage scales into the endgame. The bot
could not express this - _resource_weights ramps gold down and combat up, but
only against *opponent HP*, which is a proxy that fails in a grind (two players
at high HP on turn 20 score identically to turn 2) and in a race.

PROTOCOL, and it is different from every earlier A/B in this repo.

BASELINE.md now records a ~10pp seed-block effect: the same *fully
deterministic* heuristic scores 45.6% / 39.4% / 51.0% on three blocks. Absolute
win rates therefore cannot be compared across blocks at these sample sizes, and
two of this session's false positives (ISMCTS d1, the 60->240ms budget lead)
were exactly that mistake. What is stable across blocks is the paired *delta*
between two arms measured on the same seeds.

So: every block runs its own control. The reported quantity is always
(treatment - control) within one block, and the verdict requires the delta to
replicate on a disjoint block - not merely to be positive once.

Usage:
    python hero_phase_ab.py 100 60
    nohup python hero_phase_ab.py 100 60 > phase_ab.log 2>&1 &
"""
from __future__ import annotations

import argparse
import math
import time

import web.bot as bot_module
from hero_mcts_bench import PROFILE_WEIGHTS, play_game

PROFILES = list(PROFILE_WEIGHTS)
TUNE_SEED = 1000
CONFIRM_SEED = 500_000


def win_rate(weight, budget, games, seed_base, algorithm="mcts"):
    previous = bot_module.GAME_PHASE_WEIGHT
    try:
        bot_module.GAME_PHASE_WEIGHT = weight
        per = {}
        wins = total = 0
        for profile in PROFILES:
            won = sum(play_game(profile, algorithm, budget, seed_base + index)[0] == "bot"
                      for index in range(games))
            per[profile] = won / games
            wins += won
            total += games
        return wins / total, per
    finally:
        bot_module.GAME_PHASE_WEIGHT = previous


def run_block(label, seed_base, weights, budget, games, include_heuristic=True):
    """Every arm in one block, control first, so all deltas are within-block."""
    n = games * len(PROFILES)
    print(f"\n=== block {label} (seeds {seed_base}+, {n}/arm) ===")
    header = f"{'arm':<22}" + "".join(f"{p[:8]:>10}" for p in PROFILES) + f"{'avg':>9}{'delta':>9}{'secs':>7}"
    print(header)
    print("-" * len(header))

    results = {}
    control = None
    for weight in weights:
        mark = time.time()
        rate, per = win_rate(weight, budget, games, seed_base)
        results[weight] = rate
        if control is None:
            control = rate
        delta = f"{(rate - control) * 100:+8.1f}" if weight != weights[0] else "  control"
        name = "w=0.0 (control)" if weight == 0.0 else f"w={weight}"
        print(f"{name:<22}" + "".join(f"{per[p]:9.1%} " for p in PROFILES)
              + f"{rate:8.1%}{delta}{time.time() - mark:7.0f}", flush=True)

    if include_heuristic:
        mark = time.time()
        rate, per = win_rate(0.0, budget, games, seed_base, algorithm="heuristic")
        print(f"{'heuristic (ref)':<22}" + "".join(f"{per[p]:9.1%} " for p in PROFILES)
              + f"{rate:8.1%}{'':>9}{time.time() - mark:7.0f}", flush=True)
        print(f"  (mcts control - heuristic = {(control - rate) * 100:+.1f}pp; "
              "this delta is the stable quantity across blocks, not the absolutes)")
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("games", type=int, nargs="?", default=100,
                    help="games per profile (default 100 -> 400/arm)")
    ap.add_argument("budget", type=int, nargs="?", default=60,
                    help="search budget ms (default 60, the shipping constraint)")
    ap.add_argument("--weights", type=float, nargs="+", default=[0.0, 0.3, 0.6, 0.9],
                    help="GAME_PHASE_WEIGHT values; the first must be 0.0 (control)")
    args = ap.parse_args()
    if args.weights[0] != 0.0:
        ap.error("the first weight must be 0.0 so every block carries its own control")

    n = args.games * len(PROFILES)
    standard_error = math.sqrt(2 * 0.25 / n) * 100
    print(f"game-phase A/B, {args.games} games/profile ({n}/arm), {args.budget}ms/action")
    print(f"expected_game_turns={bot_module.EXPECTED_GAME_TURNS} "
          f"rollout_turns={bot_module.ROLLOUT_TURNS} "
          f"rollout_buy_policy={bot_module.ROLLOUT_BUY_POLICY}")
    print(f"one SE on a within-block delta is {standard_error:.1f}pp; "
          f"a delta needs ~{1.96 * standard_error:.1f}pp to clear noise alone")

    tune = run_block("TUNE", TUNE_SEED, args.weights, args.budget, args.games)
    control = tune[0.0]
    best = max((w for w in args.weights if w != 0.0), key=lambda w: tune[w])
    tune_delta = tune[best] - control
    print(f"\nbest on tuning: w={best} at {tune[best]:.1%} "
          f"({tune_delta * 100:+.1f}pp vs control)")

    if tune_delta <= 0:
        print("\nNo phase weight beat the control on the block it was selected on. "
              "Confirmation would only measure noise; GAME_PHASE_WEIGHT stays 0.0.")
        return

    confirm = run_block("CONFIRM", CONFIRM_SEED, [0.0, best], args.budget, args.games)
    confirm_delta = confirm[best] - confirm[0.0]
    se = math.sqrt(2 * 0.25 / n)
    z = confirm_delta / se

    print(f"\n{'':<12}{'tuning':>12}{'confirm':>12}")
    print(f"{'delta w=' + str(best):<12}{tune_delta * 100:>11.1f}{confirm_delta * 100:>11.1f}")
    print(f"\nconfirm delta {confirm_delta * 100:+.1f}pp  z={z:.2f}  "
          f"{'SIGNIFICANT' if abs(z) > 1.96 else 'not significant'}")
    if confirm_delta > 0 and z > 1.96:
        print("Replicated on a disjoint block. GAME_PHASE_WEIGHT is a candidate "
              f"for promotion to {best}.")
    else:
        print("Did not replicate. GAME_PHASE_WEIGHT stays 0.0 - a tuning-block "
              "delta that does not survive a disjoint block is the selection-bias "
              "signature this repo has now been bitten by three times.")


if __name__ == "__main__":
    main()
