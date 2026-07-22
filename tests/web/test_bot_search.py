"""Regression tests for the MCTS bot's search loop and session cloning.

All three guard bugs found while building hero_mcts_bench.py:
  1. legal_actions() offered attack_target at 0 combat, which the action
     handler then rejected -> ValueError mid-game.
  2. The MCTS tree cached actions across stochastic redraws, so a cached
     action could be illegal in a later sample -> ValueError mid-search.
  3. clone() deep-copied history/log (full state snapshots) on every search
     iteration, capping MCTS at ~9 iterations per decision.
"""

import random
import unittest

from web.bot import apply_action, choose_bot_action, _heuristic_rollout_action
from web.session import create_session


def _drive(session, steps=400, algorithm="heuristic", budget_ms=10):
    while session.winner is None and steps > 0:
        if session.active_player == "bot":
            action = choose_bot_action(session, budget_ms=budget_ms, algorithm=algorithm)
        else:
            action = _heuristic_rollout_action(session)
        apply_action(session, action)
        steps -= 1
    return session


class TestLegalActions(unittest.TestCase):
    def test_no_attack_actions_without_combat(self):
        random.seed(11)
        session = create_session(seed=11)
        for _ in range(300):
            if session.winner:
                break
            if session.phase == "combat" and session._current().combat <= 0:
                kinds = {a["type"] for a in session.legal_actions()}
                self.assertNotIn("attack_target", kinds)
            apply_action(session, _heuristic_rollout_action(session))

    def test_every_offered_action_is_applicable(self):
        """Whatever legal_actions() lists must not raise when applied."""
        for seed in (3, 21):
            random.seed(seed)
            session = create_session(seed=seed)
            for _ in range(150):
                if session.winner:
                    break
                for action in session.legal_actions():
                    probe = session.clone()
                    try:
                        apply_action(probe, action)
                    except ValueError as exc:
                        self.fail(f"legal action {action['type']} raised: {exc}")
                apply_action(session, _heuristic_rollout_action(session))


class TestClone(unittest.TestCase):
    def test_clone_drops_presentation_state(self):
        session = create_session(seed=5)
        _drive(session, steps=40)
        self.assertTrue(session.history)
        clone = session.clone()
        self.assertEqual(clone.history, [])
        self.assertEqual(clone.log, [])
        self.assertFalse(clone.record_history)

    def test_clone_preserves_original_history(self):
        session = create_session(seed=5)
        _drive(session, steps=40)
        before = len(session.history)
        session.clone()
        self.assertEqual(len(session.history), before)
        self.assertTrue(session.record_history)

    def test_clone_does_not_accumulate_history_during_simulation(self):
        session = create_session(seed=5)
        clone = session.clone()
        _drive(clone, steps=60)
        self.assertEqual(clone.history, [])

    def test_clone_is_independent_of_original(self):
        session = create_session(seed=5)
        clone = session.clone()
        clone.bot.hp = 1
        self.assertEqual(session.bot.hp, 50)


class TestMctsSearch(unittest.TestCase):
    def test_mcts_completes_games_without_raising(self):
        for seed in (1, 2, 3):
            random.seed(seed)
            session = create_session(seed=seed, algorithm="mcts", budget_ms=15)
            _drive(session, steps=400, algorithm="mcts", budget_ms=15)

    def test_mcts_returns_a_currently_legal_action(self):
        random.seed(9)
        session = create_session(seed=9, algorithm="mcts", budget_ms=15)
        for _ in range(60):
            if session.winner:
                break
            if session.active_player == "bot":
                action = choose_bot_action(session, budget_ms=15, algorithm="mcts")
                offered = {a["type"] for a in session.legal_actions()}
                self.assertIn(action["type"], offered)
                apply_action(session, action)
            else:
                apply_action(session, _heuristic_rollout_action(session))


if __name__ == "__main__":
    unittest.main()
