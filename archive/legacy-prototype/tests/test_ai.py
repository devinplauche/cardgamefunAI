import unittest

from src.engine import Card, Deck, Player
from src.ai import AggressiveAI, SimpleAI


class TestSimpleAI(unittest.TestCase):
    def test_ai_chooses_highest_damage_and_plays(self):
        cards = [Card(id="c1", name="Weak", data={"damage": 1}),
                 Card(id="c2", name="Strong", data={"damage": 5}),
                 Card(id="c3", name="None", data={})]
        deck = Deck(cards[:])
        ai_player = Player('AI', deck=deck)
        opponent = Player('Human', deck=Deck([]))

        ai_player.draw(3)
        self.assertEqual(ai_player.hand_size(), 3)
        prev_hp = opponent.hp

        chosen = AggressiveAI.choose_card(ai_player, opponent)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.name, 'Strong')

        played = AggressiveAI.take_turn(ai_player, opponent)
        self.assertIsNotNone(played)
        self.assertEqual(opponent.hp, prev_hp - 5)
        # ensure card moved to discard
        self.assertIn(played, ai_player.discard)

    def test_simple_ai_alias(self):
        """SimpleAI should still exist and work as an alias for AggressiveAI."""
        cards = [Card(id="c1", name="Weak", data={"damage": 1}),
                 Card(id="c2", name="Strong", data={"damage": 5})]
        deck = Deck(cards[:])
        ai_player = Player('AI', deck=deck)
        opponent = Player('Human', deck=Deck([]))
        ai_player.draw(2)
        chosen = SimpleAI.choose_card(ai_player, opponent)
        self.assertEqual(chosen.name, 'Strong')


if __name__ == '__main__':
    unittest.main()
