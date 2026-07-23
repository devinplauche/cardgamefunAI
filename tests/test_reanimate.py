"""Regression tests for Varrick's reanimate ability.

Found via a parallel research-agent audit ("MoE" pass across five rules
domains) prompted to check reanimate/recycle mechanics against printed text.

Varrick, the Necromancer: "{Expend}: Take a champion from your discard pile
and put it on top of your deck." reanimate only appears on this one card in
the whole set, and this code lived in play_card - which returns immediately
for any card_type == "champion" before ever reaching it. It had never fired
in any game this engine has simulated. Moved into expend_champion, where an
{Expend} ability actually belongs, and while there: it also picked the first
champion in discard list order rather than the best one, unlike recycle
(Smash and Grab) which already used the contextual valuation added earlier
this session for exactly this kind of "pick the best card" decision.
"""

import unittest

from hero_engine import BoardChampion, HRPlayer, expend_champion, load_hero_cards

CARDS = load_hero_cards("data/hero_realms_cards.json")
VARRICK = next(c for c in CARDS if c.name == "Varrick, the Necromancer")


class TestReanimateActuallyFires(unittest.TestCase):
    def test_reanimate_moves_a_champion_from_discard_to_top_of_deck(self):
        cheap_champ = next(c for c in CARDS if c.card_type == "champion" and c.cost <= 3)
        player = HRPlayer("P")
        bc = BoardChampion(VARRICK)
        player.board = [bc]
        player.discard = [cheap_champ]

        expend_champion(player, bc, opponent=None)

        self.assertEqual(player.deck[0], cheap_champ)
        self.assertNotIn(cheap_champ, player.discard)

    def test_does_nothing_when_discard_has_no_champion(self):
        non_champ = next(c for c in CARDS if c.card_type != "champion")
        player = HRPlayer("P")
        bc = BoardChampion(VARRICK)
        player.board = [bc]
        player.discard = [non_champ]

        expend_champion(player, bc, opponent=None)

        self.assertEqual(player.deck, [])
        self.assertIn(non_champ, player.discard)

    def test_ignores_non_champion_cards_mixed_into_discard(self):
        non_champ = next(c for c in CARDS if c.card_type != "champion")
        champ = next(c for c in CARDS if c.card_type == "champion")
        player = HRPlayer("P")
        bc = BoardChampion(VARRICK)
        player.board = [bc]
        player.discard = [non_champ, champ]

        expend_champion(player, bc, opponent=None)

        self.assertEqual(player.deck, [champ])
        self.assertEqual(player.discard, [non_champ])


class TestReanimatePicksTheBestChampion(unittest.TestCase):
    def test_picks_the_strongest_champion_not_the_first_discarded(self):
        weak = next(c for c in CARDS if c.card_type == "champion" and c.cost <= 2)
        strong = next(c for c in CARDS if c.card_type == "champion" and c.cost >= 7)
        player = HRPlayer("P")
        bc = BoardChampion(VARRICK)
        player.board = [bc]
        player.discard = [weak, strong]  # weak discarded first, in list order

        expend_champion(player, bc, opponent=None)

        self.assertEqual(player.deck, [strong], "must pick the strongest champion, not list order")
        self.assertEqual(player.discard, [weak])

    def test_order_in_discard_does_not_matter(self):
        weak = next(c for c in CARDS if c.card_type == "champion" and c.cost <= 2)
        strong = next(c for c in CARDS if c.card_type == "champion" and c.cost >= 7)
        player = HRPlayer("P")
        bc = BoardChampion(VARRICK)
        player.board = [bc]
        player.discard = [strong, weak]  # strong discarded first this time

        expend_champion(player, bc, opponent=None)

        self.assertEqual(player.deck, [strong])


if __name__ == "__main__":
    unittest.main()
