from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Protocol
import random


class OpponentStrategy(Protocol):
    name: str

    def choose_card(self) -> int:
        ...

    def reset(self) -> None:
        ...


@dataclass
class AlwaysCardStrategy:
    name: str
    card_value: int

    def choose_card(self) -> int:
        return self.card_value

    def reset(self) -> None:
        return None


@dataclass
class RandomPoolStrategy:
    name: str
    card_pool: List[int]
    seed: int = 0

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def choose_card(self) -> int:
        return self._rng.choice(self.card_pool)

    def reset(self) -> None:
        self._rng = random.Random(self.seed)


@dataclass
class TrainedStrategy:
    action_by_opponent: Dict[str, int]

    def choose_card(self, opponent_name: str) -> int:
        return self.action_by_opponent[opponent_name]


class MLStrategyTrainer:
    """Data-driven trainer that finds the best counter card per opponent strategy."""

    def __init__(self, action_space: Iterable[int]):
        self.action_space = sorted(set(action_space))
        if not self.action_space:
            raise ValueError("action_space must include at least one card value")

    @staticmethod
    def _score_round(my_card: int, their_card: int) -> int:
        if my_card > their_card:
            return 1
        if my_card < their_card:
            return -1
        return 0

    def train(
        self,
        opponents: Iterable[OpponentStrategy],
        episodes_per_action: int = 100,
    ) -> TrainedStrategy:
        if episodes_per_action <= 0:
            raise ValueError("episodes_per_action must be > 0")

        learned: Dict[str, int] = {}
        for opponent in opponents:
            best_action = self.action_space[0]
            best_avg_score = float("-inf")

            for action in self.action_space:
                opponent.reset()
                total_score = 0
                for _ in range(episodes_per_action):
                    their_card = opponent.choose_card()
                    total_score += self._score_round(action, their_card)
                avg_score = total_score / episodes_per_action
                if avg_score > best_avg_score or (avg_score == best_avg_score and action > best_action):
                    best_avg_score = avg_score
                    best_action = action

            learned[opponent.name] = best_action
        return TrainedStrategy(action_by_opponent=learned)

    def evaluate(
        self,
        strategy: TrainedStrategy,
        opponents: Iterable[OpponentStrategy],
        rounds: int = 200,
    ) -> Dict[str, float]:
        if rounds <= 0:
            raise ValueError("rounds must be > 0")

        win_rates: Dict[str, float] = {}
        for opponent in opponents:
            opponent.reset()
            wins = 0
            for _ in range(rounds):
                my_card = strategy.choose_card(opponent.name)
                their_card = opponent.choose_card()
                if self._score_round(my_card, their_card) > 0:
                    wins += 1
            win_rates[opponent.name] = wins / rounds
        return win_rates


def default_existing_strategies() -> List[OpponentStrategy]:
    """Current baseline AI strategies to train against."""
    return [
        AlwaysCardStrategy(name="cautious", card_value=1),
        AlwaysCardStrategy(name="balanced", card_value=2),
        RandomPoolStrategy(name="noisy", card_pool=[1, 2], seed=7),
    ]
