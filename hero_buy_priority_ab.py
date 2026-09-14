"""Does the buy-priority ordering that gates search itself matter?

`_buy_priority` (web/session.py) is not just the greedy fallback's tiebreaker -
it is the sort key `legal_actions()` uses for every `buy_card` action, which is
what `_root_search_actions` narrows to the top `MCTS_BUY_ROOT_WIDTH` (default
3) BEFORE the tree ever runs. Measured: 48.5% of buy decisions have more than 3
affordable options, and in every one of those at least one legal card is
excluded from the narrowed root - MCTS cannot consider it regardless of
iteration count.

`hero_card_audit.py` found the shipped formula disagrees with the search's own
oracle valuation by a mean |gap| of 0.26 (within-position percentile) across 14
cards, with Bribe and Elven Curse overrated and Elven Gift and Death Cultist
underrated. That audit's own oracle calls choose_bot_action, which applies this
SAME narrowing - so the audit could only see mispricing in positions with <=3
affordable options; in the (more common) 4+-option case, an underrated card
excluded from the root never gets an oracle utility at all. The true effect is
probably larger than what was measured, not smaller.

FOUR ARMS, each isolating one variable:

  width=3 (SHIP)     current behaviour, unchanged
  or_choice fix       FIX_OR_CHOICE_DOUBLE_COUNT=True - a narrow correctness
                       fix (Street Thug, Cult Priest were scored as if both
                       mutually-exclusive or_choice branches always fire).
                       Does not change simulation count.
  width=5             let more options reach the tree; each branch gets fewer
                       visits from the same 60ms budget - the same
                       breadth-vs-depth trade ISMCTS/ensemble lost to, tested
                       on the simplest possible tree (depth 1).
  width=0             unlimited - every affordable option reaches the root.

WALL CLOCK, not fixed iterations: this is explicitly a shipped-performance
question (does the current 60ms budget make a wider root pay for itself), which
is what CLAUDE.md's own rule says wall clock is for. The or_choice arm doesn't
change simulation count either way, so it is equally valid under this protocol.
hero_ab.paired_experiment supplies the null arm the jitter floor needs.

CAVEAT going in, stated before results: BASELINE.md records three separate
"obviously better" buy-valuation changes (situational scoring, routed policy,
game-phase term) that measured negative, all in the ROLLOUT policy. This is a
different mechanism - which options reach the tree at all, not how the rollout
simulates once they are there - but the base rate for "smarter buy logic helps"
in this project is not good, and that prior should weigh on how a positive
result here gets read.

Usage:
    python hero_buy_priority_ab.py
    python hero_buy_priority_ab.py --games 100
"""
from __future__ import annotations

import argparse

import web.bot as bot_module
import web.session as session_module
from hero_ab import Arm, paired_experiment
from hero_mcts_bench import play_game


def _setup(width, or_choice_fix):
    def apply():
        bot_module.MCTS_BUY_ROOT_WIDTH = width
        session_module.FIX_OR_CHOICE_DOUBLE_COUNT = or_choice_fix
        session_module._BUY_PRIORITY_CACHE.clear()
    return apply


def _preflight(arm):
    return (f"MCTS_BUY_ROOT_WIDTH={bot_module.MCTS_BUY_ROOT_WIDTH} "
            f"FIX_OR_CHOICE_DOUBLE_COUNT={session_module.FIX_OR_CHOICE_DOUBLE_COUNT}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--budget", type=int, default=60)
    args = ap.parse_args()

    arms = [
        Arm("width=3 (SHIP)", _setup(3, False)),
        Arm("or_choice fix", _setup(3, True)),
        Arm("width=5", _setup(5, False)),
        Arm("width=0 (unlimited)", _setup(0, False)),
    ]

    paired_experiment(
        arms=arms,
        play=lambda profile, seed: play_game(profile, "mcts", args.budget, seed)[0] == "bot",
        games=args.games,
        preflight=_preflight,
        restore_module=bot_module, restore_names=("MCTS_BUY_ROOT_WIDTH",),
    )


if __name__ == "__main__":
    main()
