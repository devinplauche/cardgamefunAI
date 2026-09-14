import unittest

from src.engine import Card, Deck, Player


class TestPlayDiscard(unittest.TestCase):
    def test_play_moves_card_to_discard(self):
        cards = [Card(id=str(i), name=f"Card{i}") for i in range(3)]
        deck = Deck(cards[:])
        p = Player('Alice', deck=deck)

        # draw all into hand
        p.draw(3)
        self.assertEqual(p.hand_size(), 3)
        self.assertEqual(len(p.discard), 0)

        # play the second card
        card_to_play = p.hand[1]
        returned = p.play_card(card_to_play)
        self.assertIs(returned, card_to_play)

        # verify hand decreased and discard increased
        self.assertEqual(p.hand_size(), 2)
        self.assertEqual(len(p.discard), 1)
        self.assertIn(card_to_play, p.discard)

        # playing a card not in hand should raise
        try:
            p.play_card(card_to_play)  # already discarded
            self.fail("Expected ValueError when playing card not in hand")
        except ValueError:
            pass


if __name__ == '__main__':
    unittest.main()
