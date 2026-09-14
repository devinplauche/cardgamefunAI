"""Does the value net's ~13x iteration gain at 60ms actually convert to win rate?

The real risk, stated before running this: the budget-sweep A/B already showed
that 4x more compute of the *same* rollout-based search buys nothing past
~240ms - it saturates. The value net could hit the same wall from the other
direction: more iterations of a *cheaper, noisier* evaluator, and there is no
guarantee 13x the samples buys back what each sample lost in fidelity.

Wall clock is the correct budget for this question specifically - the whole
premise is "more iterations at a fixed time budget", not a fixed simulation
count, so --iterations would test a different (also interesting, but not this)
question about the network's per-sample decision quality.

Uses hero_ab.paired_experiment: null arm, paired McNemar, disjoint-block
confirmation - see .claude/skills/ab-experiment.

Usage:
    python hero_value_net_ab.py
    python hero_value_net_ab.py --games 100
"""
from __future__ import annotations

import argparse

import web.bot as bot_module
from hero_ab import Arm, paired_experiment
from hero_mcts_bench import play_game


def _rollout_mode():
    bot_module.LEAF_EVAL_MODE = "rollout"


def _value_net_mode():
    bot_module.LEAF_EVAL_MODE = "value_net"
    bot_module.warm_value_net()  # never inside the budgeted call being timed


def _preflight(arm):
    mode = bot_module.LEAF_EVAL_MODE
    if mode == "value_net":
        cached = bot_module.VALUE_NET_PATH in bot_module._VALUE_NET_CACHE
        return f"LEAF_EVAL_MODE={mode} warmed={cached}"
    return f"LEAF_EVAL_MODE={mode}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--budget", type=int, default=60)
    args = ap.parse_args()

    paired_experiment(
        arms=[Arm("rollout (SHIP)", _rollout_mode), Arm("value_net", _value_net_mode)],
        play=lambda profile, seed: play_game(
            profile, "mcts", args.budget, seed)[0] == "bot",
        games=args.games,
        preflight=_preflight,
        restore_module=bot_module, restore_names=("LEAF_EVAL_MODE",),
    )


if __name__ == "__main__":
    main()
