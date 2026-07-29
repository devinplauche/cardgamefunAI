"""Regression coverage for the benchmark's budget-scope switch."""

import unittest
from unittest.mock import patch

from hero_mcts_bench import play_game


class _TurnScopeSession:
    active_player = "bot"
    winner = None
    turn_number = 1
    last_bot_insight = None

    def run_bot_turn(self):
        self.last_bot_insight = {"actions": [{"type": "buy_card"}]}
        self.winner = "bot"


class TestHeroMctsBenchmarkScope(unittest.TestCase):
    def test_turn_scope_uses_the_production_turn_entrypoint(self):
        session = _TurnScopeSession()
        with patch("hero_mcts_bench.create_session", return_value=session), \
             patch("hero_mcts_bench.choose_bot_action") as choose:
            winner, _, stalled = play_game("balanced", "mcts", 60, 1,
                                           budget_scope="turn")

        self.assertEqual(winner, "bot")
        self.assertFalse(stalled)
        choose.assert_not_called()
        self.assertTrue(session.last_bot_insight["actions"])

    def test_unknown_budget_scope_is_rejected_before_starting_a_game(self):
        with self.assertRaisesRegex(ValueError, "Unknown budget scope"):
            play_game("balanced", "mcts", 60, 1, budget_scope="unknown")

    def test_turn_scope_rejects_fixed_iteration_mode(self):
        with self.assertRaisesRegex(ValueError, "fixed iterations"):
            play_game("balanced", "mcts", 60, 1, max_iterations=8,
                      budget_scope="turn")
