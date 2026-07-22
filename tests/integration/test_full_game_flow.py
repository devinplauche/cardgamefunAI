import unittest

from src.engine import Card, Deck, Player, Game


class TestFullGameFlow(unittest.TestCase):
    def test_full_game_alternating_turns_until_winner(self):
        """Simulate a small full game where players alternate turns and deal damage until one loses."""
        # Build small decks of damage cards for both players
        # use larger decks and higher damage so a winner will be reached within test rounds
        p1_cards = [Card(id=f"p1-{i}", name=f"P1Strike{i}", data={"damage": 5}) for i in range(8)]
        p2_cards = [Card(id=f"p2-{i}", name=f"P2Strike{i}", data={"damage": 4}) for i in range(8)]

        p1 = Player('Player1', deck=Deck(p1_cards[:]))
        p2 = Player('Player2', deck=Deck(p2_cards[:]))

        # draw initial hands
        p1.draw(3)
        p2.draw(3)

        game = Game([p1, p2])

        max_rounds = 40
        rounds = 0
        winner = None

        # ensure turn manager starts at player1
        game.turn_manager.active_index = 0
        game.turn_manager.active_player = p1

        while rounds < max_rounds and p1.hp > 0 and p2.hp > 0:
            active = game.turn_manager.active_player
            other = p2 if active is p1 else p1

            # If active has a damage card in hand, play the first one
            damage_card = None
            for c in list(active.hand):
                if isinstance(c.data, dict) and 'damage' in c.data:
                    damage_card = c
                    break

            if damage_card:
                game.play_card(active, damage_card, target=other)

            # Resolve immediately for this prototype (player resolves at end of their main phase)
            game.resolve_stack()

            # check for winner
            if p1.hp <= 0:
                winner = p2
                break
            if p2.hp <= 0:
                winner = p1
                break

            # advance turn (rotate active player)
            game.turn_manager.end_turn()
            rounds += 1

        # After loop, assert there is a winner within allowed rounds
        self.assertIsNotNone(winner, "No winner reached within max rounds")
        self.assertTrue(winner.hp > 0)


if __name__ == '__main__':
    unittest.main()
