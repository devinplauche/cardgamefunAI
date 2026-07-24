"""Tests for the unified, action-masked RL environment (hero_rl_env_v2).

The v1 env only ever let the policy choose buys. This env drives the real
GameSession, so every phase is a decision - which means the action mapping
(flat index <-> session action) and the mask are now correctness-critical: a
wrong mapping silently trains the agent on the wrong move, and a wrong mask
lets it pick illegal ones.
"""

import random
import unittest

import numpy as np

from hero_rl_env_v2 import (
    ADVANCE, ATTACK_FACE, BUY_BASE, EXPEND_BASE, FIRE_GEM, N_ACTIONS, PLAY_BASE,
    HeroRealmsMaskedEnv,
)


class TestEnvContract(unittest.TestCase):
    def setUp(self):
        self.env = HeroRealmsMaskedEnv(opponent_profile="balanced")

    def test_observation_matches_declared_space(self):
        obs, _ = self.env.reset(seed=0)
        self.assertEqual(obs.shape, self.env.observation_space.shape)
        self.assertTrue(np.isfinite(obs).all())
        self.assertTrue((obs >= -1.0).all() and (obs <= 1.0).all(),
                        "features must stay inside the declared Box bounds")

    def test_mask_is_never_all_false(self):
        """MaskablePPO cannot sample from an all-false mask."""
        self.env.reset(seed=0)
        for _ in range(40):
            mask = self.env.action_masks()
            self.assertEqual(len(mask), N_ACTIONS)
            self.assertTrue(mask.any())
            legal = [i for i, v in enumerate(mask) if v]
            _, _, done, trunc, _ = self.env.step(random.choice(legal))
            if done or trunc:
                break

    def test_masked_actions_map_to_real_session_actions(self):
        self.env.reset(seed=1)
        for _ in range(30):
            table = self.env._action_table()
            mask = self.env.action_masks()
            for idx in range(N_ACTIONS):
                if mask[idx]:
                    self.assertIn(idx, table, f"action {idx} masked legal but unmapped")
            _, _, done, trunc, _ = self.env.step(max(table, key=lambda k: table[k].get("priority", 0)))
            if done or trunc:
                break


class TestActionMapping(unittest.TestCase):
    def test_play_actions_use_positional_hand_slots(self):
        """Duplicate copies of a card share card.id, so mapping by id alone
        would collapse two distinct hand slots onto one action."""
        env = HeroRealmsMaskedEnv(opponent_profile="balanced")
        env.reset(seed=3)
        env.session.phase = "play"
        table = env._action_table()
        play_idxs = [i for i in table if PLAY_BASE <= i < PLAY_BASE + len(env.session.player.hand)]
        self.assertEqual(len(play_idxs), len(set(play_idxs)))
        for i in play_idxs:
            self.assertEqual(table[i]["type"], "play_card")

    def test_fire_gem_has_its_own_index_separate_from_the_market_row(self):
        env = HeroRealmsMaskedEnv(opponent_profile="balanced")
        env.reset(seed=2)
        env.session.phase = "buy"
        env.session.player.gold = 20
        table = env._action_table()
        self.assertIn(FIRE_GEM, table)
        self.assertEqual(int(table[FIRE_GEM]["marketIndex"]), 5)
        for i in range(BUY_BASE, FIRE_GEM):
            if i in table:
                self.assertNotEqual(int(table[i]["marketIndex"]), 5)

    def test_advance_is_always_available(self):
        env = HeroRealmsMaskedEnv(opponent_profile="balanced")
        env.reset(seed=4)
        for _ in range(20):
            self.assertTrue(env.action_masks()[ADVANCE])
            _, _, done, trunc, _ = env.step(ADVANCE)
            if done or trunc:
                break

    def test_expend_and_attack_indices_are_disjoint(self):
        self.assertLess(EXPEND_BASE, ATTACK_FACE)
        self.assertLess(ATTACK_FACE, ADVANCE)
        self.assertEqual(N_ACTIONS, ADVANCE + 1)


class TestRewardAndTermination(unittest.TestCase):
    def test_winner_is_scored_by_side_key_not_player_name(self):
        """GameSession.winner is "player"/"bot"; HRPlayer.name is
        "Player"/"Bot". Comparing against the name made every finished
        episode - wins included - score as a loss."""
        env = HeroRealmsMaskedEnv(opponent_profile="balanced")
        env.reset(seed=0)
        env.session.bot.hp = 1
        env.session.player.combat = 50
        env.session.phase = "combat"
        _, reward, done, _, _ = env.step(ATTACK_FACE)
        self.assertTrue(done)
        self.assertEqual(reward, 1.0)

    def test_losing_scores_negative(self):
        env = HeroRealmsMaskedEnv(opponent_profile="balanced")
        env.reset(seed=0)
        env.session.player.hp = 1
        done = False
        reward = 0.0
        for _ in range(60):
            table = env._action_table()
            _, reward, done, trunc, _ = env.step(max(table, key=lambda k: table[k].get("priority", 0)))
            if done or trunc:
                break
        self.assertTrue(done)
        self.assertEqual(reward, -1.0)

    def test_episodes_terminate_rather_than_truncating(self):
        env = HeroRealmsMaskedEnv(opponent_profile="random")
        for ep in range(5):
            env.reset(seed=ep)
            done = trunc = False
            while not (done or trunc):
                table = env._action_table()
                _, _, done, trunc, _ = env.step(random.choice(list(table)))
            self.assertTrue(done, "game should end in a win/loss, not hit max_steps")


class TestPolicySeparation(unittest.TestCase):
    def test_greedy_beats_random_by_a_wide_margin(self):
        """The action space has to be expressive enough that a better policy
        actually scores better - otherwise there is nothing to learn."""
        env = HeroRealmsMaskedEnv(opponent_profile="random")

        def run(greedy, n=25):
            wins = 0
            for ep in range(n):
                env.reset(seed=ep)
                done = trunc = False
                reward = 0.0
                while not (done or trunc):
                    table = env._action_table()
                    action = (max(table, key=lambda k: table[k].get("priority", 0))
                              if greedy else random.choice(list(table)))
                    _, reward, done, trunc, _ = env.step(action)
                if done and reward > 0:
                    wins += 1
            return wins / n

        self.assertGreater(run(True), run(False) + 0.15)




class TestAgentSide(unittest.TestCase):
    """The two seats are not symmetric - the player seat moves first and is
    compensated with a 3-card opening hand against the bot seat's 5 - so a
    benchmark that always seats the tested policy on one side measures the seat
    as well as the policy."""

    def test_rejects_an_unknown_side(self):
        with self.assertRaises(ValueError):
            HeroRealmsMaskedEnv(agent_side="neither")

    def test_seated_second_the_opponent_has_already_moved_at_reset(self):
        env = HeroRealmsMaskedEnv(opponent_profile="balanced", agent_side="bot")
        env.reset(seed=7)
        self.assertEqual(env.session.active_player, "bot")
        self.assertIs(env.me, env.session.bot)
        self.assertIs(env.foe, env.session.player)

    def test_reward_follows_the_agent_side_not_a_hardcoded_seat(self):
        for side in ("player", "bot"):
            env = HeroRealmsMaskedEnv(opponent_profile="balanced", agent_side=side)
            env.reset(seed=0)
            env.foe.hp = 1
            env.me.combat = 50
            env.session.active_player = side
            env.session.phase = "combat"
            _, reward, done, _, _ = env.step(ATTACK_FACE)
            self.assertTrue(done, f"{side}: lethal should end the game")
            self.assertEqual(reward, 1.0, f"{side}: agent's own lethal must score +1")

    def test_both_seats_are_playable_end_to_end(self):
        for side in ("player", "bot"):
            env = HeroRealmsMaskedEnv(opponent_profile="random", agent_side=side)
            for ep in range(3):
                env.reset(seed=ep)
                done = trunc = False
                while not (done or trunc):
                    table = env._action_table()
                    _, _, done, trunc, _ = env.step(random.choice(list(table)))
                self.assertTrue(done, f"{side}: game should reach a win/loss")


if __name__ == "__main__":
    unittest.main()
