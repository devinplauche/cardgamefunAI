import unittest

from src.engine import Card, Deck, Player


class TestDeckDraw(unittest.TestCase):
    def test_deck_draw_and_counts(self):
        cards = [Card(id=str(i), name=f"Card{i}") for i in range(5)]
        deck = Deck(cards[:])
        player = Player("Alice", deck=deck)

        self.assertEqual(deck.count(), 5)

        # draw one
        drawn = player.draw(1)
        self.assertEqual(len(drawn), 1)
        self.assertEqual(player.hand_size(), 1)
        self.assertEqual(deck.count(), 4)

        # draw multiple
        drawn_more = player.draw(3)
        self.assertEqual(len(drawn_more), 3)
        self.assertEqual(player.hand_size(), 4)
        self.assertEqual(deck.count(), 1)

        # draw beyond deck size
        drawn_over = player.draw(5)
        # only one remains
        self.assertEqual(len(drawn_over), 1)
        self.assertEqual(player.hand_size(), 5)
        self.assertEqual(deck.count(), 0)


if __name__ == '__main__':
    unittest.main()
