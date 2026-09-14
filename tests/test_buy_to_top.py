import random
import unittest

from hero_engine import HRCard, HRMarket, HRPlayer, buy_card


def _card(card_id: str, card_type: str) -> HRCard:
    return HRCard(
        id=card_id,
        name=card_id.title(),
        cost=1,
        faction="",
        card_type=card_type,
    )


class TestActionOnlyBuyToTop(unittest.TestCase):
    def setUp(self):
        self.action = _card("action", "action")
        self.champion = _card("champion", "champion")
        self.market = HRMarket([self.champion, self.action], random.Random(1))
        self.market.row = [self.champion, self.action, None, None, None]
        self.market.pool = []
        self.player = HRPlayer("P", random.Random(1))
        self.player.gold = 2
        self.player.next_buy_to_top = False
        self.player.next_buy_to_top_action_only = True

    def test_non_action_does_not_consume_bribe_effect(self):
        self.assertTrue(buy_card(self.player, self.market, 0))

        self.assertIn(self.champion, self.player.discard)
        self.assertFalse(self.player.next_buy_to_top)
        self.assertTrue(self.player.next_buy_to_top_action_only)

    def test_later_action_goes_to_top_and_consumes_effect(self):
        self.assertTrue(buy_card(self.player, self.market, 0))
        self.assertTrue(buy_card(self.player, self.market, 1))

        self.assertIs(self.player.deck[0], self.action)
        self.assertFalse(self.player.next_buy_to_top)
        self.assertFalse(self.player.next_buy_to_top_action_only)

    def test_rasmus_non_action_is_consumed_without_consuming_bribe(self):
        self.player.next_buy_to_top = True

        self.assertTrue(buy_card(self.player, self.market, 0))

        self.assertIs(self.player.deck[0], self.champion)
        self.assertFalse(self.player.next_buy_to_top)
        self.assertTrue(self.player.next_buy_to_top_action_only)

        self.assertTrue(buy_card(self.player, self.market, 1))
        self.assertIs(self.player.deck[0], self.action)
        self.assertFalse(self.player.next_buy_to_top_action_only)


if __name__ == "__main__":
    unittest.main()
