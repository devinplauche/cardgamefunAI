import unittest

from src.ml_framework import MLStrategyTrainer, default_existing_strategies


TEST_EPISODES_PER_ACTION = 50


class TestMLFramework(unittest.TestCase):
    def test_trainer_learns_winning_actions(self):
        trainer = MLStrategyTrainer(action_space=[1, 2, 3, 4, 5])
        opponents = default_existing_strategies()

        trained = trainer.train(opponents, episodes_per_action=TEST_EPISODES_PER_ACTION)

        self.assertEqual(trained.choose_card("cautious"), 5)
        self.assertEqual(trained.choose_card("balanced"), 5)
        self.assertEqual(trained.choose_card("noisy"), 5)

    def test_trained_strategy_hits_target_win_rate(self):
        trainer = MLStrategyTrainer(action_space=[1, 2, 3, 4, 5])
        opponents = default_existing_strategies()
        trained = trainer.train(opponents, episodes_per_action=TEST_EPISODES_PER_ACTION)

        win_rates = trainer.evaluate(trained, opponents, rounds=200)

        for win_rate in win_rates.values():
            self.assertAlmostEqual(win_rate, 1.0)


if __name__ == "__main__":
    unittest.main()
