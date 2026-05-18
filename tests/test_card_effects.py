import unittest

from src.engine import Card, Deck, Player


class TestCardEffects(unittest.TestCase):
    def test_damage_and_armor_effects(self):
        attacker = Player("Attacker")
        defender = Player("Defender")
        attacker.hand = [Card(id="c1", name="Strike", data={"damage": 4})]
        defender.armor = 2

        attacker.play_card(attacker.hand[0], opponent=defender)
        self.assertEqual(defender.hp, 18)  # 2 armor absorbs, 2 hp damage
        self.assertEqual(defender.armor, 0)

        defender.hand = [Card(id="c2", name="Guard", data={"armor": 3})]
        defender.play_card(defender.hand[0])
        self.assertEqual(defender.armor, 3)

    def test_draw_and_heal_effects(self):
        player = Player("Player", deck=Deck([Card(id="d1", name="DeckCard")]))
        player.hp = 10
        player.hand = [Card(id="c3", name="Recover", data={"heal": 3, "draw": 1})]

        player.play_card(player.hand[0])
        self.assertEqual(player.hp, 13)
        self.assertEqual(player.hand_size(), 1)  # drew one after playing one
        self.assertEqual(player.deck.count(), 0)

    def test_unique_piercing_strike_ignores_armor(self):
        attacker = Player("Attacker")
        defender = Player("Defender")
        defender.armor = 5
        attacker.hand = [
            Card(
                id="u1",
                name="Piercing Strike",
                data={"damage": 3, "ability": "piercing_strike"},
            )
        ]

        attacker.play_card(attacker.hand[0], opponent=defender)
        self.assertEqual(defender.hp, 17)
        self.assertEqual(defender.armor, 5)

    def test_unique_guard_breaker_clears_armor_then_damages(self):
        attacker = Player("Attacker")
        defender = Player("Defender")
        defender.armor = 4
        attacker.hand = [
            Card(
                id="u2",
                name="Guard Breaker",
                data={"damage": 2, "ability": "guard_breaker"},
            )
        ]

        attacker.play_card(attacker.hand[0], opponent=defender)
        self.assertEqual(defender.armor, 0)
        self.assertEqual(defender.hp, 18)

    def test_unique_siphon_heals_by_dealt_damage(self):
        attacker = Player("Attacker")
        defender = Player("Defender")
        attacker.hp = 8
        defender.armor = 1
        attacker.hand = [
            Card(id="u3", name="Siphon", data={"damage": 4, "ability": "siphon"})
        ]

        attacker.play_card(attacker.hand[0], opponent=defender)
        self.assertEqual(defender.hp, 17)  # 1 absorbed by armor, 3 damage dealt
        self.assertEqual(attacker.hp, 11)

    def test_unique_callable_ability(self):
        def custom_ability(owner, opponent, card):
            if opponent is None and card.name == "Blessing":
                owner.heal(2)

        player = Player("Player")
        player.hp = 5
        player.hand = [Card(id="u4", name="Blessing", data={"ability": custom_ability})]
        player.play_card(player.hand[0])
        self.assertEqual(player.hp, 7)

    def test_unknown_unique_ability_raises(self):
        player = Player("Player")
        opponent = Player("Opponent")
        player.hand = [Card(id="u5", name="Mystery", data={"ability": "unknown"})]

        with self.assertRaises(ValueError):
            player.play_card(player.hand[0], opponent=opponent)

    def test_damage_requires_opponent(self):
        player = Player("Player")
        player.hand = [Card(id="u6", name="Strike", data={"damage": 2})]

        with self.assertRaises(ValueError):
            player.play_card(player.hand[0])


if __name__ == "__main__":
    unittest.main()
