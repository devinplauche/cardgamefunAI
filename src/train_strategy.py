from __future__ import annotations

import argparse
import json

from src.ml_framework import StrategyTrainer, save_training_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train a weighted strategy against baseline AI strategies.")
    parser.add_argument("--generations", type=int, default=4)
    parser.add_argument("--population-size", type=int, default=6)
    parser.add_argument("--matches-per-opponent", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=str, help="Optional JSON output path for the trained strategy")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    trainer = StrategyTrainer(
        generations=args.generations,
        population_size=args.population_size,
        matches_per_opponent=args.matches_per_opponent,
    )
    result = trainer.train(seed=args.seed)
    if args.output:
        save_training_result(result, args.output)
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
