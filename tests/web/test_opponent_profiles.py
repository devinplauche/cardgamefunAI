import unittest

from web.opponent_profiles import (
    inferred_profile,
    inferred_profile_posterior,
    profile_buy_action,
)
from web.session import PublicOpponentPurchase, create_session


class TestPublicOpponentPurchases(unittest.TestCase):
    @staticmethod
    def _rich_buy_session(seed=7):
        session = create_session(seed=seed)
        session.active_player = "player"
        session.phase = "buy"
        session.player.gold = 99
        return session

    def test_player_buy_records_only_public_choices_before_market_mutates(self):
        session = self._rich_buy_session()
        action = next(action for action in session.legal_actions()
                      if action["type"] == "buy_card")
        expected_options = {
            int(candidate["marketIndex"])
            for candidate in session.legal_actions() if candidate["type"] == "buy_card"
        }

        session.buy_card_action(int(action["marketIndex"]))

        self.assertEqual(len(session.opponent_purchase_observations), 1)
        observation = session.opponent_purchase_observations[0]
        self.assertEqual(observation.gold_before_buy, 99)
        self.assertEqual(observation.chosen_market_index, int(action["marketIndex"]))
        self.assertEqual({index for index, _ in observation.buy_options}, expected_options)
        self.assertTrue(all(card_id for _, card_id in observation.buy_options))

    def test_clone_preserves_public_observations_without_recording_rollout_buys(self):
        session = self._rich_buy_session()
        action = next(action for action in session.legal_actions()
                      if action["type"] == "buy_card")
        session.buy_card_action(int(action["marketIndex"]))
        clone = session.clone()

        self.assertEqual(clone.opponent_purchase_observations,
                         session.opponent_purchase_observations)
        self.assertFalse(clone.record_history)

    def test_profile_posterior_uses_only_the_public_observation(self):
        session = self._rich_buy_session()
        actions = session.legal_actions()
        economic = profile_buy_action(session, actions, "economic")
        options = tuple(
            (int(action["marketIndex"]),
             next(card.id for index, card in enumerate(session.market.row_cards())
                  if index == int(action["marketIndex"]))
             if int(action["marketIndex"]) != 5 else "fire_gem")
            for action in actions if action["type"] == "buy_card"
        )
        observation = PublicOpponentPurchase(
            gold_before_buy=session.player.gold,
            buy_options=options,
            chosen_market_index=int(economic["marketIndex"]),
        )
        session.opponent_purchase_observations = (observation, observation)

        posterior = inferred_profile_posterior(session)
        self.assertIsNotNone(posterior)
        self.assertEqual(inferred_profile(session), "economic")
        self.assertAlmostEqual(sum(posterior.values()), 1.0)
