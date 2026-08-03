"""Tests for hero_value_net.py and its wiring into web/bot.py's _rollout.

Coverage split deliberately: correctness of the plumbing here (feature shape,
terminal handling, the utility round-trip, byte-identical default behaviour),
not whether the trained weights are any good - that is a model-quality question
answered by hero_value_net.py's own train/eval commands and the A/B harness,
not by a unit test.
"""
import math
import unittest

import numpy as np

from hero_value_net import FEATURE_DIM, TinyMLP, extract_features
from web.session import create_session


class TestExtractFeatures(unittest.TestCase):
    def test_shape_and_dtype(self):
        session = create_session(seed=1)
        features = extract_features(session)
        self.assertEqual(features.shape, (FEATURE_DIM,))
        self.assertEqual(features.dtype, np.float32)

    def test_finite_across_a_played_game(self):
        """Walks through varied hp/board/deck states, not just the opener."""
        from web.bot import _heuristic_rollout_action, apply_action

        session = create_session(seed=3)
        for _ in range(150):
            if session.winner:
                break
            features = extract_features(session)
            self.assertTrue(np.all(np.isfinite(features)),
                            f"non-finite feature at turn {session.turn_number}")
            apply_action(session, _heuristic_rollout_action(session))

    def test_hp_diff_feature_tracks_actual_hp_diff(self):
        session = create_session(seed=1)
        session.bot.hp, session.player.hp = 40, 10
        features = extract_features(session)
        self.assertGreater(features[0], 0)  # index 0 is (bot.hp - opp.hp)/50
        session.bot.hp, session.player.hp = 10, 40
        self.assertLess(extract_features(session)[0], 0)


class TestTinyMLP(unittest.TestCase):
    def test_forward_is_deterministic_and_bounded(self):
        rng = np.random.default_rng(0)
        weights = {
            "w0": rng.normal(size=(FEATURE_DIM, 4)).astype(np.float32),
            "b0": np.zeros(4, dtype=np.float32),
            "w1": rng.normal(size=(4, 1)).astype(np.float32),
            "b1": np.zeros(1, dtype=np.float32),
        }
        model = TinyMLP(weights)
        features = np.ones(FEATURE_DIM, dtype=np.float32)
        first = model.predict(features)
        second = model.predict(features)
        self.assertEqual(first, second)
        self.assertGreater(first, 0.0)
        self.assertLess(first, 1.0)

    def test_save_and_load_round_trip(self, tmp_path=None):
        import tempfile
        import os

        rng = np.random.default_rng(1)
        weights = {
            "w0": rng.normal(size=(FEATURE_DIM, 4)).astype(np.float32),
            "b0": rng.normal(size=4).astype(np.float32),
            "w1": rng.normal(size=(4, 1)).astype(np.float32),
            "b1": rng.normal(size=1).astype(np.float32),
        }
        model = TinyMLP(weights)
        features = np.ones(FEATURE_DIM, dtype=np.float32)
        expected = model.predict(features)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "model.npz")
            model.save(path)
            reloaded = TinyMLP.load(path)
        self.assertAlmostEqual(reloaded.predict(features), expected, places=6)


class TestUtilityRoundTrip(unittest.TestCase):
    """The inversion _value_net_raw_score relies on to stay a drop-in
    replacement for _rollout's return value."""

    def test_search_utility_and_its_inverse_round_trip(self):
        from web.bot import _search_utility

        for raw in (-400.0, -100.0, 0.0, 100.0, 400.0):
            utility = _search_utility(raw)
            bounded = min(max(utility, 1e-4), 1 - 1e-4)
            recovered = 250.0 * math.atanh((bounded - 0.5) / 0.4)
            self.assertAlmostEqual(recovered, raw, places=3)


class TestRolloutWiring(unittest.TestCase):
    def setUp(self):
        import web.bot as bot_module

        self.bot_module = bot_module
        self.addCleanup(setattr, bot_module, "LEAF_EVAL_MODE",
                        bot_module.LEAF_EVAL_MODE)
        self.addCleanup(bot_module._VALUE_NET_CACHE.clear)

    def test_default_mode_is_rollout(self):
        self.assertEqual(self.bot_module.LEAF_EVAL_MODE, "rollout")

    def test_value_net_mode_does_not_simulate(self):
        """The whole point: no turns are played, unlike a real rollout."""
        from unittest.mock import patch

        session = create_session(seed=1)
        start_turn = session.turn_number
        fake_model = _ConstantModel(0.7)
        self.bot_module.LEAF_EVAL_MODE = "value_net"
        with patch.object(self.bot_module, "_load_value_net", return_value=fake_model):
            self.bot_module._rollout(session)
        self.assertEqual(session.turn_number, start_turn,
                         "value_net mode must not advance the game")

    def test_value_net_score_round_trips_through_the_constant_model(self):
        from unittest.mock import patch

        session = create_session(seed=1)
        fake_model = _ConstantModel(0.7)
        self.bot_module.LEAF_EVAL_MODE = "value_net"
        with patch.object(self.bot_module, "_load_value_net", return_value=fake_model):
            raw = self.bot_module._rollout(session)
        self.assertAlmostEqual(self.bot_module._search_utility(raw), 0.7, places=3)

    def test_terminal_states_bypass_the_network_entirely(self):
        from unittest.mock import patch

        session = create_session(seed=1)
        session.bot.hp = 0
        session._check_winner()
        self.bot_module.LEAF_EVAL_MODE = "value_net"
        with patch.object(self.bot_module, "_load_value_net",
                          side_effect=AssertionError("must not be called")):
            raw = self.bot_module._rollout(session)
        self.assertEqual(raw, -self.bot_module.WIN_SCORE)

    def test_raw_utility_mode_is_rejected_rather_than_mis_scaled(self):
        session = create_session(seed=1)
        self.bot_module.LEAF_EVAL_MODE = "value_net"
        previous = self.bot_module.MCTS_UTILITY_MODE
        self.bot_module.MCTS_UTILITY_MODE = "raw"
        self.addCleanup(setattr, self.bot_module, "MCTS_UTILITY_MODE", previous)
        with self.assertRaises(AssertionError):
            self.bot_module._rollout(session)

    def test_choose_bot_action_completes_with_value_net_mode(self):
        """One real search decision, end to end, with the trained weights."""
        from web.bot import choose_bot_action

        self.bot_module.LEAF_EVAL_MODE = "value_net"
        session = create_session(seed=5, algorithm="mcts")
        session.active_player = "bot"
        session.phase = "buy"
        session.bot.gold = 8
        result = choose_bot_action(session, algorithm="mcts", max_iterations=20)
        self.assertIn(result["type"], {a["type"] for a in session.legal_actions()})

    def test_warm_value_net_populates_the_cache_before_any_search_call(self):
        """The regression test for the cold-start footgun.

        A real npz load costs ~330ms - long enough to consume an entire 60ms
        search budget on its own. `_paired_root_rounds` requires a complete
        root round before committing any statistics, so if that 330ms lands
        inside iteration 1 of round 1, the round is discarded as incomplete and
        the decision silently returns iterations=0. warm_value_net() must
        populate the cache synchronously, before choose_bot_action ever runs,
        so this can only happen if a caller skips it.
        """
        self.assertEqual(self.bot_module._VALUE_NET_CACHE, {})
        self.bot_module.warm_value_net()
        self.assertIn(self.bot_module.VALUE_NET_PATH, self.bot_module._VALUE_NET_CACHE)

        # Once warm, extract_features + predict is order 0.1ms - a real search
        # at a real budget must be able to complete many iterations, not just
        # avoid the zero-iteration failure mode.
        from web.bot import choose_bot_action

        session = create_session(seed=41, algorithm="mcts")
        session.active_player = "bot"
        session.phase = "buy"
        session.bot.gold = 8
        result = choose_bot_action(session, algorithm="mcts", budget_ms=60)
        self.assertGreater(result["iterations"], 0,
                           "a warmed value net must not return a zero-iteration decision")


class _ConstantModel:
    def __init__(self, value):
        self.value = value

    def predict(self, features):
        return self.value


if __name__ == "__main__":
    unittest.main()
