"""Tests for _buy_priority, the static per-card score that sorts every buy_card
action in legal_actions() and therefore gates MCTS_BUY_ROOT_WIDTH's narrowing.

Measured: 48.5% of buy decisions have more than 3 affordable options, and in
every one of those at least one legal card was excluded from the narrowed root
- MCTS never sees it, regardless of iteration count. That is what makes
_buy_priority's correctness matter beyond "which card the greedy fallback
picks": a mispriced ordering can hide the actual best option from search
entirely, not just from the fallback.

FIX_OR_CHOICE_DOUBLE_COUNT defaults to False (reproduces the historical
formula exactly) per this project's hard-won discipline: BASELINE.md records
three separate "obviously better" buy-valuation changes that measured negative.
"""
import unittest

from hero_engine import load_hero_cards
import web.session as session_module
from web.session import _buy_priority

CARDS = {card.name: card for card in load_hero_cards("data/hero_realms_cards.json")}


class TestOrChoiceDoubleCounting(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, session_module, "FIX_OR_CHOICE_DOUBLE_COUNT",
                        session_module.FIX_OR_CHOICE_DOUBLE_COUNT)
        session_module._BUY_PRIORITY_CACHE.clear()
        self.addCleanup(session_module._BUY_PRIORITY_CACHE.clear)

    def test_default_reproduces_the_historical_formula(self):
        self.assertFalse(session_module.FIX_OR_CHOICE_DOUBLE_COUNT)

    def test_default_sums_mutually_exclusive_branches(self):
        """The bug, pinned so a future refactor can't silently fix it in the
        default path without an A/B."""
        session_module.FIX_OR_CHOICE_DOUBLE_COUNT = False
        card = CARDS["Street Thug"]  # {gold: 1, combat: 2, or_choice: [gold, combat]}
        priority = _buy_priority(card)
        # cost*1 + combat*2 + gold*2 = 3 + 4 + 2 = 9, both branches summed.
        self.assertEqual(priority, 9.0)

    def test_fix_takes_the_better_branch_not_the_sum(self):
        session_module.FIX_OR_CHOICE_DOUBLE_COUNT = True
        card = CARDS["Street Thug"]
        priority = _buy_priority(card)
        # cost*1 + max(combat*2, gold*2) = 3 + max(4, 2) = 7.
        self.assertEqual(priority, 7.0)
        self.assertLess(priority, 9.0)

    def test_fix_only_moves_cards_with_more_than_one_priced_branch(self):
        """Darian, War Mage or_choices [combat, health] - health was never in
        _buy_priority's tracked resource set, so only one branch (combat) was
        ever priced either way. The fix must be a no-op here, and for every
        other non-or_choice card in the set."""
        card = CARDS["Darian, War Mage"]
        session_module.FIX_OR_CHOICE_DOUBLE_COUNT = False
        before = _buy_priority(card)
        session_module.FIX_OR_CHOICE_DOUBLE_COUNT = True
        after = _buy_priority(card)
        self.assertEqual(before, after)

    def test_fix_is_a_no_op_for_the_wider_card_set(self):
        affected = {"Street Thug", "Cult Priest"}
        for name, card in CARDS.items():
            if name in affected:
                continue
            with self.subTest(card=name):
                session_module.FIX_OR_CHOICE_DOUBLE_COUNT = False
                before = _buy_priority(card)
                session_module.FIX_OR_CHOICE_DOUBLE_COUNT = True
                after = _buy_priority(card)
                self.assertEqual(before, after, f"{name} changed unexpectedly")

    def test_cache_does_not_leak_stale_values_across_the_flag(self):
        """Regression: the cache is keyed by card.id alone in the naive
        version, which would serve a value computed under the other flag
        setting once both have been read at least once."""
        card = CARDS["Street Thug"]
        session_module.FIX_OR_CHOICE_DOUBLE_COUNT = False
        off = _buy_priority(card)
        session_module.FIX_OR_CHOICE_DOUBLE_COUNT = True
        on = _buy_priority(card)
        session_module.FIX_OR_CHOICE_DOUBLE_COUNT = False
        off_again = _buy_priority(card)
        self.assertEqual(off, off_again)
        self.assertNotEqual(off, on)


if __name__ == "__main__":
    unittest.main()
