"""Confirm the MCTS-minus-heuristic reference delta, paired.

WHY

The delta has now read three different values on three different games:
+11pp before the Ruby fix, ~5pp after it, and +1.3pp in
`rebaseline_main_phase.log` after the Main-phase fix (`d046b9e`). That last
figure is the one everything is currently judged against, and it is the
weakest of the three: one seed block, marginal win rates, no pairing.

CLAUDE.md is explicit that a single block cannot pin an absolute better than
~+/-10pp and that the stable quantity is a paired delta within one block. So
this re-asks the same question with the right instrument - `hero_ab`'s paired
McNemar, a null arm, and a disjoint confirmation block.

It matters beyond bookkeeping: if search's real edge over a hand-written
heuristic is ~1pp, then most of the search-mechanism work in CLAUDE.md was
chasing effects smaller than the noise floor it was measured against, and the
sacrifice/targeting flags now waiting for an A/B would need enormous effects to
clear it.

WALL CLOCK

Deliberately uses the shipped 60 ms action budget rather than fixed
iterations: the question is what the shipped configuration is worth, not a
question about search mechanism. That makes this a wall-clock benchmark, so
per CLAUDE.md it must not run concurrently with anything else - CPU contention
starves the search and corrupts the result.

    python hero_baseline_confirm.py --games 100
"""
from __future__ import annotations

import argparse

import web.bot as B
from hero_ab import Arm, paired_experiment
from hero_mcts_bench import play_game


def algorithm(name: str):
    """Arms differ only in which algorithm plays the bot seat."""
    def setup() -> None:
        B.BENCH_ALGORITHM = name
    return setup


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100,
                    help="games per profile per arm (x4 profiles)")
    ap.add_argument("--budget", type=int, default=60)
    args = ap.parse_args()

    def play(profile, seed):
        return play_game(profile, B.BENCH_ALGORITHM, args.budget, seed)[0] == "bot"

    B.BENCH_ALGORITHM = "heuristic"
    paired_experiment(
        arms=[Arm("heuristic (control)", algorithm("heuristic")),
              Arm("mcts", algorithm("mcts"))],
        play=play,
        games=args.games,
        preflight=lambda arm: f"algorithm={B.BENCH_ALGORITHM}",
        restore_module=B,
        restore_names=("BENCH_ALGORITHM",),
    )


if __name__ == "__main__":
    main()
