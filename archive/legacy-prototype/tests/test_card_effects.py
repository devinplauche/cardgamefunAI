import unittest

from src.engine import Card, Deck, Player


class TestCardEffects(unittest.TestCase):
    def test_play_damage_card_reduces_target_hp(self):
        # create a damage card and put into player's hand
        dmg_card = Card(id="d1", name="Smash", data={"damage": 5})
        deck = Deck([dmg_card])
        p = Player('Alice', deck=deck)
        opp = Player('Bob', deck=Deck([]))

        # draw the card
        p.draw(1)
        self.assertEqual(p.hand_size(), 1)
        self.assertEqual(opp.hp, 20)

        # play targeting opponent
        card = p.hand[0]
        p.play_card(card, target=opp)

        # card should be in discard
        self.assertEqual(len(p.discard), 1)
        # opponent hp reduced
        self.assertEqual(opp.hp, 15)


if __name__ == '__main__':
    unittest.main()
