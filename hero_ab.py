"""Paired A/B harness. Use this instead of hand-rolling another one.

Five A/B scripts in this repo were hand-rolled and three of them shipped bugs
that produced confident, plausible, wrong numbers:

  * a Fire Gem "ban" that zeroed the market pile but left 16 phantom cards in
    the public inventory, so `determinize_for_bot` raised and every search
    silently failed closed to the heuristic. It measured "MCTS is worse when
    you turn MCTS off" and reported it as a card result.
  * a searched-decision counter that averaged in auto-resolved phases
    (`algorithm="heuristic"`, `iterations=1`), reading 4-5 simulations per
    decision where the truth was ~66.
  * several arms compared by marginal win rate against a ~10pp seed-block
    effect and a ~4pp wall-clock jitter floor, neither of which was known at
    the time.

Everything this module enforces exists because of one of those.

WHAT IT ENFORCES

  1. **A null arm.** A byte-identical duplicate of the control runs as its own
     arm. Whatever separation it shows is pure harness noise and calibrates
     every other p-value in the table. In this project a duplicate arm has
     exposed a noise floor four times when no deliberate control did - once
     showing +4.0pp at p=0.076, and once putting two provably identical
     policies in different significance classes (p=0.006 vs p=0.298).

  2. **Paired McNemar, not marginal win rates.** Every arm plays identical
     seeds, so only games where two arms disagree on the outcome are counted.
     Seed difficulty cancels exactly, which matters because the same fully
     deterministic heuristic scores 45.6% / 39.4% / 51.0% across three blocks.

  3. **Sweep then confirm on a disjoint block.** Reported as a replication
     verdict, because a tuning-block lead that shrinks held out is the
     signature that has cost this project six candidate wins.

  4. **A preflight check.** Optional per-arm callable that must return a truthy
     diagnostic. Use it to assert the thing under test is actually running -
     that is the check whose absence made the Fire Gem result meaningless.

FIXED ITERATIONS VS WALL CLOCK

If the question is about search *mechanism*, pass a fixed simulation count
rather than a time budget: the search becomes deterministic given the seed, the
null replicate drops to exactly 0 discordant games, and detectable effects go
from ~5pp to ~1pp. Only use a wall clock when the question genuinely is about
shipped wall-clock performance - and verify first, by reporting simulations per
decision, that your change does not alter the simulation count. (The rollout
horizon, for instance, does not: rollouts almost always end in a real result
before reaching their limit.)

EXAMPLE

    from hero_ab import Arm, paired_experiment
    import web.bot as B

    def horizon(n):
        def setup():
            B.ROLLOUT_TURNS = n
        return setup

    paired_experiment(
        arms=[Arm("horizon 16 (SHIP)", horizon(16)),
              Arm("horizon 24", horizon(24))],
        play=lambda profile, seed: play_game(
            profile, "mcts", 60, seed, max_iterations=40)[0] == "bot",
    )
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from itertools import product
from typing import Callable

from web.opponent_profiles import PROFILE_NAMES

# Blocks used across this repo. Keep new experiments on these so results stay
# comparable, and never compare an absolute win rate between two of them.
TUNE_BLOCK = 1000
HOLDOUT_BLOCK = 60_000
SPARE_BLOCKS = (300_000, 500_000, 700_000, 800_000, 900_000)


@dataclass
class Arm:
    """One configuration. `setup` mutates module globals; `paired_experiment`
    snapshots and restores them around each arm, so setup only has to set."""

    label: str
    setup: Callable[[], None]


def mcnemar_exact(n01: int, n10: int) -> float:
    """Two-sided exact McNemar p on the discordant pairs."""
    n = n01 + n10
    if n == 0:
        return 1.0
    k = min(n01, n10)
    return min(1.0, 2.0 * sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n))


def discordant(arm: dict, base: dict) -> tuple[int, int]:
    """(arm won & base lost, arm lost & base won)."""
    return (sum(1 for k in arm if arm[k] and not base[k]),
            sum(1 for k in arm if not arm[k] and base[k]))


def run_block(label, seed_base, arms, play, games, profiles, snapshot):
    """Every arm on one seed block. Arm 0 is the control everything pairs to."""
    n = games * len(profiles)
    print(f"\n=== {label} (seeds {seed_base}+, {n} games/arm) ===")
    header = f"{'arm':<24}{'win rate':>10}{'vs control':>13}{'p':>9}{'secs':>7}"
    print(header)
    print("-" * len(header))

    results, base = {}, None
    for arm in arms:
        mark = time.time()
        snapshot.restore()
        arm.setup()
        outcomes = {(p, seed_base + i): play(p, seed_base + i)
                    for p, i in product(profiles, range(games))}
        results[arm.label] = outcomes
        rate = sum(outcomes.values()) / n
        cell = ""
        if base is None:
            base = outcomes
        else:
            n10, n01 = discordant(outcomes, base)
            cell = f"{n10:>5}/{n01:<6}{mcnemar_exact(n01, n10):>9.3f}"
        print(f"{arm.label:<24}{rate:>9.1%}{cell if cell else '':>22}"
              f"{time.time() - mark:>7.0f}", flush=True)
    snapshot.restore()
    return results


class _Snapshot:
    """Restores whatever globals the arms touched, so arms cannot leak into
    each other - a failure mode that is invisible in the output."""

    def __init__(self, module, names):
        self.module = module
        self.saved = {n: getattr(module, n) for n in names}

    def restore(self):
        for name, value in self.saved.items():
            setattr(self.module, name, value)


def paired_experiment(arms, play, *, blocks=None, games=100, profiles=None,
                      preflight=None, null_arm=True, restore_module=None,
                      restore_names=()):
    """Run a paired A/B with a null arm, then confirm the winner held out.

    `arms[0]` is the control. `play(profile, seed) -> bool` returns whether the
    bot won. `preflight(arm) -> str` should raise or return falsey if that arm
    is not actually doing what its label says.
    """
    profiles = list(profiles or PROFILE_NAMES)
    blocks = blocks or (("TUNE", TUNE_BLOCK), ("HOLDOUT", HOLDOUT_BLOCK))
    snapshot = (_Snapshot(restore_module, restore_names) if restore_module
                else _Snapshot(math, ()))  # no-op when nothing to restore

    control = arms[0]
    if null_arm:
        # Inserted second so it is adjacent to the control in the output and
        # impossible to overlook when reading the table.
        arms = [control, Arm(f"{control.label} [NULL]", control.setup)] + list(arms[1:])

    if preflight is not None:
        print("preflight: every arm must be doing what its label says")
        for arm in arms:
            snapshot.restore()
            arm.setup()
            print(f"  {arm.label:<24} {preflight(arm)}")
        snapshot.restore()
        print()

    tune = run_block(blocks[0][0], blocks[0][1], arms, play, games, profiles, snapshot)
    base = tune[control.label]

    null_label = f"{control.label} [NULL]"
    if null_arm and null_label in tune:
        n10, n01 = discordant(tune[null_label], base)
        print(f"\nnoise floor: the null arm differs from the control by "
              f"{n10}-{n01} discordant games (p={mcnemar_exact(n01, n10):.3f}). "
              f"Nothing below this is real.")

    candidates = {a.label: tune[a.label] for a in arms[1:] if "[NULL]" not in a.label}
    if not candidates:
        return tune
    best = max(candidates, key=lambda k: -discordant(candidates[k], base)[1]
               + discordant(candidates[k], base)[0])
    n10, n01 = discordant(candidates[best], base)
    if n10 <= n01:
        print(f"\nNo arm beat the control on the block it was selected on. Stop here.")
        return tune

    print(f"\nbest on tuning: {best} ({n10 - n01:+d} net discordant games)")
    winner = next(a for a in arms if a.label == best)
    confirm = run_block(blocks[1][0], blocks[1][1], [control, winner], play,
                        games, profiles, snapshot)
    n10, n01 = discordant(confirm[best], confirm[control.label])
    p = mcnemar_exact(n01, n10)
    print(f"\nconfirm: {best} vs control -> discordant {n10}-{n01}, p={p:.4f}")
    print("Replicated on a disjoint block." if n10 > n01 and p < 0.05 else
          "Did not replicate. This is the signature that has cost this project "
          "six candidate wins; do not promote it.")
    return {"tune": tune, "confirm": confirm}
