"""Regression tests for the RL environment's opponent wiring and setup rules.

The opponent_profile bug these guard against was reported as fixed in
QA_CRITICAL_FINDING_2026-06-20.md but survived, because nothing asserted
that a requested profile actually reaches the opponent turn.
"""

import unittest

from hero_engine import HRMarket, load_hero_cards
from hero_rl_env import OPPONENT_PROFILES, HeroRealmsEnv

CARDS = load_hero_cards("data/hero_realms_cards.json")


class TestOpponentProfile(unittest.TestCase):
    def test_named_profile_is_active_before_reset(self):
        for key, profile in OPPONENT_PROFILES.items():
            with self.subTest(profile=key):
                env = HeroRealmsEnv(CARDS, opponent_profile=key)
                self.assertEqual(env.opponent_profile_key, key)
                self.assertIs(env._opponent_profile, profile)

    def test_named_profile_survives_reset(self):
        for key, profile in OPPONENT_PROFILES.items():
            with self.subTest(profile=key):
                env = HeroRealmsEnv(CARDS, opponent_profile=key)
                env.reset(seed=1)
                self.assertEqual(env.opponent_profile_key, key)
                self.assertEqual(env.opponent.name, profile["name"])

    def test_profiles_use_distinct_buy_functions(self):
        """A profile switch is only meaningful if the behaviour differs."""
        buys = {key: p["buy"] for key, p in OPPONENT_PROFILES.items()}
        self.assertEqual(len(set(buys.values())), len(buys))

    def test_random_profile_varies_across_resets(self):
        env = HeroRealmsEnv(CARDS, opponent_profile="random")
        seen = set()
        for seed in range(40):
            env.reset(seed=seed)
            seen.add(env.opponent_profile_key)
        self.assertGreater(len(seen), 1, "random profile never re-rolled")
        self.assertTrue(seen <= set(OPPONENT_PROFILES))

    def test_unknown_profile_falls_back_to_balanced(self):
        env = HeroRealmsEnv(CARDS, opponent_profile="nonsense")
        self.assertEqual(env.opponent_profile_key, "balanced")


class TestSetupRules(unittest.TestCase):
    """Setup values from the official base-set rulebook."""

    def test_first_player_draws_three_second_draws_five(self):
        env = HeroRealmsEnv(CARDS)
        env.reset(seed=3)
        # Agent's hand is post-auto-play, so assert on total cards accounted for.
        agent_total = (len(env.agent.hand) + len(env.agent.deck)
                       + len(env.agent.discard) + len(env.agent.played_this_turn))
        self.assertEqual(agent_total, 10)
        self.assertEqual(len(env.opponent.hand), 5)

    def test_market_row_has_five_slots(self):
        market = HRMarket(CARDS)
        self.assertEqual(len(market.row_cards()), 5)
        self.assertTrue(all(c is not None for c in market.row_cards()))

    def test_market_refills_to_five_after_buy(self):
        market = HRMarket(CARDS)
        market.buy(2)
        self.assertEqual(len(market.row_cards()), 5)
        self.assertIsNotNone(market.row_cards()[2])

    def test_fire_gem_stack_is_sixteen(self):
        self.assertEqual(HRMarket(CARDS).fire_gems_remaining, 16)

    def test_fire_gems_are_not_shuffled_into_market_deck(self):
        market = HRMarket(CARDS)
        self.assertNotIn("fire gem", [c.name.lower() for c in market.pool])

    def test_starting_deck_composition(self):
        env = HeroRealmsEnv(CARDS)
        env.reset(seed=5)
        p = env.opponent
        ids = sorted(c.id for c in p.deck + p.hand + p.discard)
        self.assertEqual(ids, sorted(["gold"] * 7 + ["shortsword", "dagger", "ruby"]))

    def test_starting_health_is_fifty(self):
        # A fresh player starts at 50 HP. The v1 env auto-plays the opening
        # hand on reset, and the starting Ruby heals 1 - with no health cap
        # (physical health cards are double-sided to track above 50) the
        # agent legitimately opens above 50 when the Ruby is in hand.
        # (The deck shuffle uses the global RNG, so seed it for determinism.)
        import random
        from hero_engine import HRPlayer
        self.assertEqual(HRPlayer("P").hp, 50)
        random.seed(5)
        env = HeroRealmsEnv(CARDS)
        env.reset()
        ruby_played = any(c.id == "ruby" for c in env.agent.played_this_turn)
        self.assertEqual(env.agent.hp, 51 if ruby_played else 50)
        self.assertEqual(env.opponent.hp, 50)


class TestTurnBoundaryCleanup(unittest.TestCase):
    """The v1 env's turn boundary used to delete played cards (clearing
    played_this_turn without discarding) and leak pending_ally state into
    later turns. Every owned card must survive the turn; all pending lists
    must reset."""

    def _owned_total(self, player):
        zones = [player.deck, player.hand, player.discard,
                 player.played_this_turn]
        total = sum(len(z) for z in zones)
        total += sum(1 for bc in player.board if bc.alive)
        return total

    def test_played_cards_are_discarded_not_deleted(self):
        env = HeroRealmsEnv(CARDS)
        env.reset(seed=7)
        p = env.agent
        self.assertEqual(self._owned_total(p), 10)
        # reset() already ran the agent's opening main phase; note how many
        # cards are already in played_this_turn before adding more.
        already_played = len(p.played_this_turn)
        # Force three Golds into hand and play them, then run the turn.
        golds = [c for c in p.deck if c.name == "Gold"][:3]
        self.assertEqual(len(golds), 3)
        for c in golds:
            p.deck.remove(c)
        p.hand.extend(golds)
        from hero_engine import play_card
        for card in list(golds):
            play_card(p, card, env.market)
        self.assertEqual(len(p.played_this_turn), already_played + 3)
        env._resolve_turn()
        self.assertEqual(self._owned_total(p), 10,
                         "played cards must reach the discard pile, not vanish")

    def test_pending_ally_cleared_at_turn_boundary(self):
        env = HeroRealmsEnv(CARDS)
        env.reset(seed=11)
        o = env.opponent
        taxation = next(c for c in CARDS if c.name == "Taxation")
        o.hand = [taxation]
        from hero_ai import play_all_playable
        play_all_playable(o, env.agent, env.market)
        self.assertEqual(len(o.pending_ally), 1)
        env._resolve_turn()
        self.assertEqual(o.pending_ally, [],
                         "pending_ally must not leak into the next turn")
        self.assertEqual(o.pending_stun_targets, [])
        self.assertEqual(o.pending_prepares, 0)
        self.assertFalse(o.next_buy_to_hand)
        self.assertFalse(o.next_buy_to_top)


if __name__ == "__main__":
    unittest.main()
