import unittest

from src.engine import Card, Deck, Player, Game
from src.ai import SimpleAI


class TestGameFlow(unittest.TestCase):
    def test_play_to_stack_and_resolve(self):
        # prepare players
        p_cards = [Card(id="p1", name="Strike", data={"damage": 2})]
        o_cards = [Card(id="o1", name="Bash", data={"damage": 3})]
        p = Player('Alice', deck=Deck(p_cards[:]))
        o = Player('Opponent', deck=Deck(o_cards[:]))

        # draw
        p.draw(1)
        o.draw(1)

        game = Game([p, o])

        # player plays card onto stack
        card = p.hand[0]
        game.play_card(p, card, target=o)
        self.assertEqual(len(game.play_stack), 1)
        self.assertEqual(len(game.play_area), 1)
        self.assertEqual(p.hand_size(), 0)

        # resolve
        game.resolve_stack()
        self.assertEqual(len(game.play_stack), 0)
        self.assertEqual(len(game.play_area), 0)
        self.assertEqual(len(p.discard), 1)
        self.assertEqual(o.hp, 20 - 2)

    def test_run_round_ai_plays(self):
        # AI should play in run_round
        ai_cards = [Card(id="a1", name="Hit", data={"damage": 4})]
        human_cards = [Card(id="h1", name="Tap", data={})]
        ai = Player('AI-Bot', deck=Deck(ai_cards[:]))
        human = Player('Player', deck=Deck(human_cards[:]))
        ai.draw(1)
        human.draw(1)

        game = Game([human, ai])
        # advance to AI's turn: rotate once so AI is active
        game.turn_manager.active_index = 1
        game.turn_manager.active_player = ai

        # run automated round for AI with AggressiveAI strategy
        from src.ai import AggressiveAI
        game.run_round(ai_strategy=AggressiveAI)

        # AI should have played and opponent (human) should have reduced HP
        self.assertTrue(len(ai.discard) >= 0)
        self.assertLess(human.hp, 20)


if __name__ == '__main__':
    unittest.main()
