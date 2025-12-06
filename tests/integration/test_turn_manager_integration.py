import unittest

from src.engine import Player, Deck, Card, TurnManager


class TestTurnManagerIntegration(unittest.TestCase):
    def test_start_turn_auto_draw_and_rotation(self):
        # prepare decks with known cards
        cards_p1 = [Card(id=f"p1-{i}", name=f"P1Card{i}") for i in range(3)]
        cards_p2 = [Card(id=f"p2-{i}", name=f"P2Card{i}") for i in range(3)]

        p1 = Player('Alice', deck=Deck(cards_p1[:]))
        p2 = Player('Bob', deck=Deck(cards_p2[:]))

        tm = TurnManager([p1, p2])

        # no cards in hand initially
        self.assertEqual(p1.hand_size(), 0)
        self.assertEqual(p2.hand_size(), 0)

        # starting first turn should auto-draw for player 1
        tm.start_turn()
        self.assertEqual(tm.phase, 'start')
        self.assertEqual(p1.hand_size(), 1)

        # advance to end and rotate to player 2
        tm.advance_phase()  # main
        tm.advance_phase()  # resolve
        tm.advance_phase()  # end
        tm.advance_phase()  # triggers rotation and new start

        # player 2 should now be active and have drawn one card at their start
        self.assertEqual(tm.active_player, p2)
        self.assertEqual(p2.hand_size(), 1)


if __name__ == '__main__':
    unittest.main()
