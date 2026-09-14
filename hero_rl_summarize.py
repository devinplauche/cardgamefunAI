"""Aggregate training-run summaries into per-arm mean +/- SE across seeds.

The point of this file is to make the across-seed spread impossible to omit.
Every RL number in BASELINE.md from V15 onward is one training run reported as
a point estimate, and the V17 section shows what that costs: a checkpoint
selected because it scored 51.0% re-measured at 49.0% on the same seeds and
47.2% held out. A single run's "best" is a maximum over a noisy sequence, so it
is biased upward by construction; the mean of the *final* checkpoints across
independent seeds is not.

Usage:
    python hero_rl_summarize.py models_v21
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
from collections import defaultdict


def load(outdir):
    arms = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(outdir, "*.json"))):
        with open(path) as handle:
            record = json.load(handle)
        arm = record["run"].rsplit("_s", 1)[0]
        arms[arm].append(record)
    return arms


def stats(values):
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, float("nan")
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    return mean, math.sqrt(variance / n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", nargs="?", default="models_v21")
    args = ap.parse_args()

    arms = load(args.outdir)
    if not arms:
        raise SystemExit(f"no run summaries in {args.outdir}")

    print(f"{'arm':<16}{'n':>3}{'BC':>18}{'final':>18}{'best-in-train':>18}{'mins':>7}")
    print("-" * 80)
    for arm in sorted(arms):
        records = arms[arm]
        bc_mean, bc_se = stats([r["bc"] for r in records])
        final_mean, final_se = stats([r["final"] for r in records])
        best_mean, best_se = stats([r["best_in_training"] for r in records])
        minutes = sum(r["elapsed_s"] for r in records) / len(records) / 60
        print(f"{arm:<16}{len(records):>3}"
              f"{bc_mean:>12.1%} +-{bc_se:>4.1%}"
              f"{final_mean:>12.1%} +-{final_se:>4.1%}"
              f"{best_mean:>12.1%} +-{best_se:>4.1%}"
              f"{minutes:>7.0f}")

    print("\nper-seed final checkpoints")
    for arm in sorted(arms):
        seeds = ", ".join(f"s{r['seed']}={r['final']:.1%}"
                          for r in sorted(arms[arm], key=lambda r: r["seed"]))
        print(f"  {arm:<16} {seeds}")

    print("\nnote: 'best-in-train' is a maximum over a noisy eval sequence and is "
          "biased upward.\nCompare arms on 'final', and confirm the winner "
          "on held-out seeds with hero_rl_eval_masked.py.")


if __name__ == "__main__":
    main()
