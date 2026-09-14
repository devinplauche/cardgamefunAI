"""Is Fire Gem a trap card? Ban it and see.

Motivation: a purchase log over 40 games shows Fire Gem is ~19% of the bot's
entire acquired deck - 2.9 copies per game, three times more than any other
card - for both MCTS and the greedy heuristic. It is also the only market card
with no faction, so it can never participate in an ally trigger and never
enables one (see `_enabler_value` in web/bot.py). A deck that is one-fifth Fire
Gem is structurally one-fifth incapable of the game's main engine. RL v12x
independently converged on spamming it too, through a -0.01 penalty designed to
stop exactly that.

BANNING IT CORRECTLY IS NOT ONE LINE.

The obvious hack - `market.fire_gems_remaining = 0` - silently lobotomises the
bot. `GameSession._inventory_counts` still contains 16 Fire Gems, so
`determinize_for_bot` finds 16 cards it cannot place in any hidden zone, raises
ValueError, and every search **fails closed to the pure heuristic**. The first
version of this experiment did that and produced a beautifully plausible
"MCTS loses 3.7pp without Fire Gem", which actually measured "MCTS loses 3.7pp
when you turn MCTS off". Three tells were visible and all three were missed: a
50x speedup, a win rate byte-identical to the heuristic arm, and a delta that
happened to equal search's whole contribution.

So the ban here removes Fire Gem from the public inventory as well, and the
harness asserts that search still runs before it trusts a single game.

Paired by seed and tested with exact McNemar: both arms see identical shuffles,
so seed difficulty cancels, which matters because BASELINE.md records a ~10pp
seed-block effect that swamps marginal win-rate comparisons at this sample size.

Usage:
    python hero_firegem_ab.py 100 60
"""
from __future__ import annotations

import argparse
import math
import time
from collections import Counter
from itertools import product

import web.bot as bot_module
import web.session as session_module
from hero_mcts_bench import PROFILE_WEIGHTS, play_game

PROFILES = list(PROFILE_WEIGHTS)
BLOCKS = (("TUNE", 1000), ("HOLDOUT", 60_000))

_BAN = [False]
_original_post_init = session_module.GameSession.__post_init__


def _post_init(self):
    _original_post_init(self)
    if not _BAN[0]:
        return
    # Remove Fire Gem from the side pile *and* from the public inventory the
    # determinizer reconciles against. Dropping only the pile leaves 16 phantom
    # cards that cannot be placed, which fails the determinization invariant.
    self.market.fire_gems_remaining = 0
    self._full_inventory = tuple(
        card for card in self._full_inventory if card.id != "fire_gem"
    )
    self._inventory_counts = Counter(card.id for card in self._full_inventory)
    self._inventory_cards_by_id = {card.id: card for card in self._full_inventory}


session_module.GameSession.__post_init__ = _post_init


def mcnemar_exact(n01: int, n10: int) -> float:
    n = n01 + n10
    if n == 0:
        return 1.0
    k = min(n01, n10)
    return min(1.0, 2.0 * sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n))


def verify_search_runs(banned: bool) -> float:
    """Refuse to measure a bot that is not searching.

    Returns mean iterations per searched decision. This is the check whose
    absence invalidated the first run.
    """
    import random

    from web.session import create_session

    _BAN[0] = banned
    totals = []
    for seed in (5, 11, 23):
        session = create_session(seed=seed, algorithm="mcts")
        session.active_player, session.phase = "bot", "buy"
        session.bot.gold = 8
        try:
            session.determinize_for_bot(random.Random(0))
        except ValueError as exc:
            raise SystemExit(
                f"determinization broken with banned={banned}: {exc}\n"
                "The ban left the public inventory inconsistent; search would "
                "fail closed to the heuristic and the whole run would be void."
            )
        result = bot_module.choose_bot_action(session, budget_ms=60, algorithm="mcts")
        totals.append(result["iterations"])
    mean = sum(totals) / len(totals)
    if mean <= 0:
        raise SystemExit(f"search ran 0 iterations with banned={banned}; aborting")
    return mean


def run(algorithm, banned, budget, games, seed_base):
    _BAN[0] = banned
    outcomes = {}
    for profile, index in product(PROFILES, range(games)):
        seed = seed_base + index
        outcomes[(profile, seed)] = play_game(profile, algorithm, budget, seed)[0] == "bot"
    return outcomes


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("games", type=int, nargs="?", default=100)
    ap.add_argument("budget", type=int, nargs="?", default=60)
    args = ap.parse_args()

    print("pre-flight: search must run in BOTH arms or the comparison is void")
    for banned in (False, True):
        mean = verify_search_runs(banned)
        print(f"  fire_gem_banned={str(banned):<5}  mean iterations/decision = {mean:.0f}")
    print()

    for label, seed_base in BLOCKS:
        n = args.games * len(PROFILES)
        print(f"=== {label} block (seeds {seed_base}+, {n} games/arm) ===")
        header = (f"{'arm':<22}{'fire gem':>10}{'win rate':>10}"
                  f"{'ban-wins/keep-wins':>20}{'p':>9}{'secs':>7}")
        print(header)
        print("-" * len(header))
        for algorithm in ("heuristic", "mcts"):
            cells = {}
            for banned in (False, True):
                mark = time.time()
                cells[banned] = run(algorithm, banned, args.budget, args.games, seed_base)
                rate = sum(cells[banned].values()) / len(cells[banned])
                extra = ""
                if banned:
                    keep, ban = cells[False], cells[True]
                    n10 = sum(1 for k in ban if ban[k] and not keep[k])
                    n01 = sum(1 for k in ban if not ban[k] and keep[k])
                    extra = f"{n10:>9}/{n01:<10}{mcnemar_exact(n01, n10):>9.3f}"
                print(f"{algorithm:<22}{'BANNED' if banned else 'kept':>10}"
                      f"{rate:>9.1%}{extra if banned else '':>29}"
                      f"{time.time() - mark:>7.0f}", flush=True)
            delta = (sum(cells[True].values()) - sum(cells[False].values())) / n
            print(f"  -> {algorithm} delta from banning Fire Gem: {delta * 100:+.1f}pp")
        print()


if __name__ == "__main__":
    main()
