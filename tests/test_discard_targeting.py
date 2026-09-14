"""Regression tests for context-aware discard/sacrifice target selection.

_find_worst_idx and _find_best_idx used a single fixed _card_score (cost and
raw stats only) to decide which card to discard, sacrifice, or return from
discard, with no idea whether the player is racing for lethal, needs
healing, already has plenty of gold, or has an ally on board that makes a
card's ally_* fields real rather than dead text. _contextual_card_value adds
that, and lives in hero_engine.py itself (not the bot layer) because these
functions are called from every simulated game - RL training, heuristic AI
opponents, and the MCTS bot alike.
"""

import unittest

from hero_engine import (
    BoardChampion,
    GOLD,
    HRCard,
    HRPlayer,
    _contextual_card_value,
    _deck_gold_density,
    _find_best_idx,
    _find_worst_idx,
    _worth_sacrificing,
    load_hero_cards,
)

CARDS = load_hero_cards("data/hero_realms_cards.json")


def _card(name):
    return next(c for c in CARDS if c.name == name)


class TestStartingCardsAlwaysWorst(unittest.TestCase):
    """The four starting cards must remain the default target regardless of
    context - _contextual_card_value is explicitly exempt for them."""

    def test_starting_cards_unaffected_by_context(self):
        player = HRPlayer("P")
        player.hp = 5  # would otherwise raise a card's contextual value
        opponent = HRPlayer("O")
        opponent.hp = 5
        for card in (GOLD,):
            self.assertEqual(_contextual_card_value(card, player, opponent),
                             _contextual_card_value(card, HRPlayer("Q"), None))

    def test_find_worst_still_prefers_starting_junk(self):
        player = HRPlayer("P")
        player.hp = 5
        opponent = HRPlayer("O")
        strong_card = _card("Domination")
        hand = [strong_card, GOLD]
        idx = _find_worst_idx(hand, player, opponent)
        self.assertEqual(hand[idx].id, "gold")


class TestOwnHealthUrgency(unittest.TestCase):
    def test_a_card_with_no_heal_becomes_relatively_worse_when_critical(self):
        combat_card = _card("Death Cultist")  # combat only, no health effect
        heal_card = _card("Command")  # has a health effect among others
        player = HRPlayer("P")
        opponent = HRPlayer("O")
        hand = [combat_card, heal_card]

        player.hp = 50
        healthy_gap = (_contextual_card_value(heal_card, player, opponent)
                      - _contextual_card_value(combat_card, player, opponent))
        player.hp = 5
        critical_gap = (_contextual_card_value(heal_card, player, opponent)
                       - _contextual_card_value(combat_card, player, opponent))

        self.assertGreater(critical_gap, healthy_gap,
                           "the healing card's edge should widen once critically low")


class TestOpponentHealthUrgency(unittest.TestCase):
    def test_a_combat_card_becomes_relatively_better_as_opponent_nears_death(self):
        combat_card = _card("Death Cultist")
        no_combat_card = _card("Recruit")  # gold/health only, no combat
        player = HRPlayer("P")
        player.setup_starting_deck()
        opponent = HRPlayer("O")

        opponent.hp = 50
        healthy_gap = (_contextual_card_value(combat_card, player, opponent)
                      - _contextual_card_value(no_combat_card, player, opponent))
        opponent.hp = 5
        critical_gap = (_contextual_card_value(combat_card, player, opponent)
                       - _contextual_card_value(no_combat_card, player, opponent))

        self.assertGreater(critical_gap, healthy_gap)


class TestAllyCertainty(unittest.TestCase):
    def test_ally_card_gains_value_once_the_faction_is_on_board(self):
        card = _card("Recruit")  # ally_faction Imperial, ally_gold 1
        player = HRPlayer("P")
        player.setup_starting_deck()
        opponent = HRPlayer("O")

        without_ally = _contextual_card_value(card, player, opponent)
        imperial_champ = next(c for c in CARDS if c.faction == "Imperial" and c.card_type == "champion")
        player.board.append(BoardChampion(imperial_champ))
        with_ally = _contextual_card_value(card, player, opponent)

        self.assertGreater(with_ally, without_ally)


class TestGoldDiminishingReturns(unittest.TestCase):
    def test_gold_card_value_falls_as_deck_gold_density_rises(self):
        gold_card = _card("Recruit")
        player = HRPlayer("P")
        player.setup_starting_deck()
        opponent = HRPlayer("O")

        before_density = _deck_gold_density(player)
        before = _contextual_card_value(gold_card, player, opponent)
        player.deck.extend([gold_card] * 20)
        after_density = _deck_gold_density(player)
        after = _contextual_card_value(gold_card, player, opponent)

        self.assertGreater(after_density, before_density)
        self.assertLess(after, before)

    def test_a_non_gold_card_is_unaffected_by_gold_density(self):
        combat_card = _card("Death Cultist")
        gold_card = _card("Recruit")
        player = HRPlayer("P")
        player.setup_starting_deck()
        opponent = HRPlayer("O")

        before = _contextual_card_value(combat_card, player, opponent)
        player.deck.extend([gold_card] * 20)
        after = _contextual_card_value(combat_card, player, opponent)

        self.assertEqual(before, after)


class TestWorthSacrificingGeneralises(unittest.TestCase):
    """With player context, a redundant purchased card (not only the four
    starting cards) can become worth sacrificing once it is clearly the
    weakest option in a gold-saturated deck."""

    def test_context_free_call_still_only_flags_starting_junk(self):
        gold_card = _card("Recruit")
        self.assertFalse(_worth_sacrificing(gold_card))
        self.assertTrue(_worth_sacrificing(GOLD))

    def test_a_card_can_become_not_worth_keeping_only_relative_to_junk_floor(self):
        # _contextual_card_value never pushes a real purchased card below the
        # -50..-100 junk floor in practice; this pins that invariant so a
        # future weight change can't silently start sacrificing real cards
        # the same way starting junk is sacrificed.
        gold_card = _card("Recruit")
        player = HRPlayer("P")
        player.setup_starting_deck()
        player.deck.extend([gold_card] * 200)  # extreme gold saturation
        opponent = HRPlayer("O")
        self.assertFalse(_worth_sacrificing(gold_card, player, opponent))


class TestFindBestIdxUsesContext(unittest.TestCase):
    def test_recycle_prefers_the_contextually_stronger_card(self):
        weak = _card("Death Cultist")
        strong = _card("Domination")
        player = HRPlayer("P")
        opponent = HRPlayer("O")
        discard = [weak, strong]
        idx = _find_best_idx(discard, player, opponent)
        self.assertEqual(discard[idx].name, "Domination")


if __name__ == "__main__":
    unittest.main()
