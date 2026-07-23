"""Regression tests for optional sacrifice mechanics in hero_engine.py.

Every printed sacrifice effect in the card set reads "you may sacrifice" (or
uses the {Sacrifice}: keyword, which means the same thing by Hero Realms
convention) - never mandatory. The engine used to apply every one of them
unconditionally, which meant a lean, thinned deck (what a sacrifice-focused
strategy builds toward) had no bad card left to decline sacrificing and was
forced to burn something actually useful. That is a rules deviation affecting
every game simulated with this engine, not merely an AI valuation nuance.
"""

import unittest

from hero_engine import (
    DAGGER,
    GOLD,
    HRCard,
    HRMarket,
    HRPlayer,
    RUBY,
    SHORTSWORD,
    expend_champion,
    load_hero_cards,
    play_card,
)

CARDS = load_hero_cards("data/hero_realms_cards.json")
FIRE_GEM_CARD = next(c for c in CARDS if c.name == "Fire Gem")
DARK_REWARD = next(c for c in CARDS if c.name == "Dark Reward")
KRYTHOS = next(c for c in CARDS if c.name == "Krythos, Master Vampire")
TYRANNOR = next(c for c in CARDS if c.name == "Tyrannor, the Devourer")

# A real, non-junk market card for "already own economy" / "no junk left" setups.
GOOD_CARD = next(c for c in CARDS if c.get("gold", 0) > 0 and c.cost >= 2 and c.name != "Fire Gem")


def _player_with_hand(*cards, board=()):
    p = HRPlayer("P")
    p.hp = 50
    p.hand = list(cards)
    for c in board:
        from hero_engine import BoardChampion
        p.board.append(BoardChampion(c))
    return p


class TestSelfSacrifice(unittest.TestCase):
    """sacrifice_combat: the played card sacrifices ITSELF for bonus combat."""

    def test_declines_when_a_guard_would_absorb_the_combat(self):
        player = _player_with_hand(FIRE_GEM_CARD)
        opponent = HRPlayer("O")
        from hero_engine import BoardChampion
        guard_champ = next(c for c in CARDS if c.card_type == "champion" and c.guard > 0)
        opponent.board.append(BoardChampion(guard_champ))
        market = HRMarket(CARDS)

        play_card(player, FIRE_GEM_CARD, market, opponent=opponent)

        self.assertEqual(player.combat, 0, "combat gained despite an open guard")
        self.assertIn(FIRE_GEM_CARD, player.played_this_turn,
                      "card should remain in play when it is not sacrificed")
        self.assertNotIn(FIRE_GEM_CARD, player.banish)
        self.assertEqual(player.gold, 2, "the non-sacrifice base effect still applies")

    def test_declines_without_established_economy(self):
        player = _player_with_hand(FIRE_GEM_CARD)
        player.deck = [GOLD] * 7 + [SHORTSWORD, DAGGER, RUBY]  # only the basic starting deck
        market = HRMarket(CARDS)

        play_card(player, FIRE_GEM_CARD, market, opponent=None)

        self.assertEqual(player.combat, 0)
        self.assertIn(FIRE_GEM_CARD, player.played_this_turn)

    def test_takes_it_once_economy_is_established_and_no_guard_blocks(self):
        player = _player_with_hand(FIRE_GEM_CARD)
        player.deck = [GOOD_CARD, GOOD_CARD]  # >= 2 owned non-starting economy cards
        market = HRMarket(CARDS)

        play_card(player, FIRE_GEM_CARD, market, opponent=None)

        self.assertEqual(player.combat, 3)
        self.assertIn(FIRE_GEM_CARD, player.banish)
        self.assertNotIn(FIRE_GEM_CARD, player.discard)


class TestHandDiscardSacrifice(unittest.TestCase):
    """sacrifice_card: "you may sacrifice a card in your hand or discard pile."""

    def test_declines_when_nothing_in_hand_or_discard_is_junk(self):
        player = _player_with_hand(DARK_REWARD, GOOD_CARD)
        player.discard = [GOOD_CARD]
        market = HRMarket(CARDS)

        play_card(player, DARK_REWARD, market, opponent=None)

        self.assertEqual(len(player.hand), 1, "the only remaining hand card should not be sacrificed")
        self.assertEqual(player.banish, [])

    def test_sacrifices_a_starting_junk_card_when_available(self):
        player = _player_with_hand(DARK_REWARD, GOLD)
        market = HRMarket(CARDS)

        play_card(player, DARK_REWARD, market, opponent=None)

        self.assertIn(GOLD, player.banish)
        self.assertNotIn(GOLD, player.hand)


class TestExpendSacrifice(unittest.TestCase):
    """sacrifice_for_combat / sacrifice_up_to on champion expend abilities."""

    def test_sacrifice_for_combat_grants_bonus_only_if_it_actually_sacrifices(self):
        player = _player_with_hand()
        from hero_engine import BoardChampion
        bc = BoardChampion(KRYTHOS)
        player.board.append(bc)
        player.hand = [GOOD_CARD]  # nothing junk to sacrifice

        expend_champion(player, bc, opponent=None)

        self.assertEqual(player.combat, 3, "base expend combat still applies")
        self.assertEqual(player.banish, [])

    def test_sacrifice_for_combat_grants_bonus_when_junk_is_available(self):
        player = _player_with_hand()
        from hero_engine import BoardChampion
        bc = BoardChampion(KRYTHOS)
        player.board.append(bc)
        player.hand = [GOLD]

        expend_champion(player, bc, opponent=None)

        self.assertEqual(player.combat, 6, "base 3 plus the conditional 3 bonus")
        self.assertIn(GOLD, player.banish)

    def test_sacrifice_up_to_stops_once_junk_runs_out(self):
        player = _player_with_hand()
        from hero_engine import BoardChampion
        bc = BoardChampion(TYRANNOR)
        player.board.append(bc)
        player.hand = [GOLD, GOOD_CARD]  # one junk, one not: should sacrifice only the one

        expend_champion(player, bc, opponent=None)

        self.assertIn(GOLD, player.banish)
        self.assertIn(GOOD_CARD, player.hand)
        self.assertEqual(len(player.banish), 1, "must not force-sacrifice the non-junk card too")

    def test_sacrifice_up_to_takes_multiple_when_all_are_junk(self):
        player = _player_with_hand()
        from hero_engine import BoardChampion
        bc = BoardChampion(TYRANNOR)
        player.board.append(bc)
        player.hand = [GOLD, DAGGER, GOOD_CARD]

        expend_champion(player, bc, opponent=None)

        self.assertEqual(len(player.banish), 2)
        self.assertIn(GOOD_CARD, player.hand)


if __name__ == "__main__":
    unittest.main()
