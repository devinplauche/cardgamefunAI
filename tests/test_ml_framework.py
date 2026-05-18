import json
import tempfile
import unittest

from src.engine import Card, Player
from src.ml_framework import (
    AggressiveStrategy,
    MatchConfig,
    StrategyArena,
    StrategyTrainer,
    WeightedStrategy,
    save_training_result,
)


class TestMLFramework(unittest.TestCase):
    def test_weighted_strategy_prefers_finishing_blow(self):
        strategy = WeightedStrategy()
        player = Player("learner")
        opponent = Player("baseline")
        player.hand = [
            Card(id="guard", name="Guard", data={"armor": 5}),
            Card(id="strike", name="Strike", data={"damage": 6}),
        ]
        opponent.hp = 6
        opponent.armor = 0

        choice = strategy.choose_card(player, opponent, rng=None)

        self.assertEqual(choice.name, "Strike")

    def test_arena_runs_a_match(self):
        arena = StrategyArena(config=MatchConfig(starting_hp=18, opening_hand=3, max_turns=12))

        result = arena.play_match(WeightedStrategy(), AggressiveStrategy(), seed=7)

        self.assertIn(result.winner, {"player", "opponent", "draw"})
        self.assertGreaterEqual(result.turns_played, 1)

    def test_trainer_returns_history_and_persistable_result(self):
        trainer = StrategyTrainer(generations=2, population_size=4, matches_per_opponent=2)

        result = trainer.train(seed=3)

        self.assertEqual(result.strategy_name, "trained_weighted_strategy")
        self.assertEqual(len(result.history), trainer.generations + 1)
        self.assertEqual(result.evaluation.total_matches, 6)
        self.assertGreaterEqual(result.history[-1].average_score, result.history[0].average_score)

        with tempfile.NamedTemporaryFile(suffix=".json") as handle:
            path = save_training_result(result, handle.name)
            persisted = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(persisted["strategy_name"], result.strategy_name)
        self.assertEqual(persisted["evaluation"]["total_matches"], result.evaluation.total_matches)


if __name__ == "__main__":
    unittest.main()
