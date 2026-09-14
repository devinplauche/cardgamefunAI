import unittest

from src.engine import Player, TurnManager


class TestTurnManager(unittest.TestCase):
    def test_phase_progression_and_player_rotation(self):
        p1 = Player('Alice')
        p2 = Player('Bob')
        tm = TurnManager([p1, p2])

        # initial state
        self.assertEqual(tm.active_player, p1)
        self.assertEqual(tm.turn_number, 0)
        self.assertIsNone(tm.phase)

        # start first turn
        tm.start_turn()
        self.assertEqual(tm.phase, 'start')
        self.assertEqual(tm.turn_number, 1)

        # advance through phases to end
        tm.advance_phase()  # main
        self.assertEqual(tm.phase, 'main')
        tm.advance_phase()  # resolve
        self.assertEqual(tm.phase, 'resolve')
        tm.advance_phase()  # end
        self.assertEqual(tm.phase, 'end')

        # advancing past 'end' rotates player and starts next turn
        tm.advance_phase()
        self.assertEqual(tm.active_player, p2)
        self.assertEqual(tm.phase, 'start')
        self.assertEqual(tm.turn_number, 2)


if __name__ == '__main__':
    unittest.main()
