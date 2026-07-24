"""Tests for the self-play environment.

The subtle failure mode here is not a crash: it is an opposing policy that
silently plays from the wrong seat's perspective, or that shares parameters
with the live model and improves alongside it. Either produces a training run
that looks fine and teaches nothing, so the perspective plumbing and the
frozen-ness of pool entries are what these cover.
"""

import unittest

from sb3_contrib import MaskablePPO

from hero_rl_env_v2 import HeroRealmsMaskedEnv
from hero_rl_selfplay import SelfPlayEnv

MODEL_PATH = "models_v16/v16_final"


class TestPerspective(unittest.TestCase):
    """Every perspective-dependent method takes a side; asking for the opposing
    seat has to give that seat's view, not a copy of the agent's."""

    def setUp(self):
        self.env = HeroRealmsMaskedEnv(opponent_profile="balanced")
        self.env.reset(seed=5)

    def test_seats_helper_returns_opposite_pairs(self):
        me, foe = self.env._seats("player")
        self.assertIs(me, self.env.session.player)
        self.assertIs(foe, self.env.session.bot)
        me, foe = self.env._seats("bot")
        self.assertIs(me, self.env.session.bot)
        self.assertIs(foe, self.env.session.player)

    def test_observation_differs_between_seats(self):
        a = self.env._get_obs(side="player")
        b = self.env._get_obs(side="bot")
        self.assertEqual(a.shape, b.shape)
        self.assertFalse((a == b).all(), "both seats produced an identical observation")

    def test_hp_features_are_mirrored_between_seats(self):
        self.env.session.player.hp = 40
        self.env.session.bot.hp = 20
        a = self.env._get_obs(side="player")
        b = self.env._get_obs(side="bot")
        self.assertAlmostEqual(a[0], b[1], places=5)
        self.assertAlmostEqual(a[1], b[0], places=5)

    def test_default_side_is_the_agent_side(self):
        for side in ("player", "bot"):
            env = HeroRealmsMaskedEnv(opponent_profile="balanced", agent_side=side)
            env.reset(seed=1)
            self.assertTrue((env._get_obs() == env._get_obs(side=side)).all())


class TestSelfPlayEnv(unittest.TestCase):
    def test_empty_pool_falls_back_to_the_heuristic_opponent(self):
        env = SelfPlayEnv(opponent_pool=[], opponent_profile="balanced")
        env.reset(seed=0)
        done = trunc = False
        steps = 0
        while not (done or trunc) and steps < 400:
            table = env._action_table()
            _, _, done, trunc, _ = env.step(max(table, key=lambda k: table[k].get("priority", 0)))
            steps += 1
        self.assertTrue(done, "game with an empty pool should still finish")

    def test_random_seat_uses_both_seats(self):
        env = SelfPlayEnv(random_seat=True, opponent_profile="balanced")
        seats = set()
        for ep in range(40):
            env.reset(seed=ep)
            seats.add(env.agent_side)
        self.assertEqual(seats, {"player", "bot"})

    def test_fixed_seat_is_respected_when_random_seat_is_off(self):
        env = SelfPlayEnv(random_seat=False, agent_side="bot", opponent_profile="balanced")
        for ep in range(5):
            env.reset(seed=ep)
            self.assertEqual(env.agent_side, "bot")


class TestSelfPlayAgainstRealModel(unittest.TestCase):
    """Uses the shipped V16 checkpoint; skipped if it is not present."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.model = MaskablePPO.load(MODEL_PATH)
        except Exception as exc:  # noqa: BLE001 - any load failure means skip
            raise unittest.SkipTest(f"{MODEL_PATH} unavailable: {exc}")

    def test_mirror_match_is_complementary_across_seats(self):
        """The same deterministic policy on the same seed plays the identical
        game from either seat, so wins from the two seats must sum to the game
        count. A mismatch means the perspective or swap logic is inconsistent."""
        results = {}
        for side in ("player", "bot"):
            env = SelfPlayEnv(opponent_pool=[self.model], deterministic_opponent=True,
                              agent_side=side, opponent_profile="balanced")
            wins = 0
            for ep in range(12):
                obs, _ = env.reset(seed=ep)
                done = trunc = False
                reward = 0.0
                while not (done or trunc):
                    action, _ = self.model.predict(obs, action_masks=env.action_masks(),
                                                   deterministic=True)
                    obs, reward, done, trunc, _ = env.step(action)
                wins += bool(done and reward > 0)
            results[side] = wins
        self.assertEqual(results["player"] + results["bot"], 12,
                         f"mirror wins must sum to the game count, got {results}")

    def test_pool_entries_are_independent_of_the_live_model(self):
        """A pool holding the live model would let the opponent improve in
        lockstep with the agent, which is not self-play against a frozen past."""
        frozen = MaskablePPO.load(MODEL_PATH)
        env = SelfPlayEnv(opponent_pool=[frozen], opponent_profile="balanced")
        self.assertIsNot(env.opponent_pool[0], self.model)
        self.assertIsNot(env.opponent_pool[0].policy, self.model.policy)

    def test_opponent_turn_actually_uses_the_pool_model(self):
        env = SelfPlayEnv(opponent_pool=[self.model], deterministic_opponent=True,
                          opponent_profile="balanced")
        env.reset(seed=3)
        self.assertIs(env._current_opponent, self.model)


if __name__ == "__main__":
    unittest.main()
