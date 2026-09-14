"""Pin the five hardcoded cards against the printed Hero Realms base set.

These are the only cards defined in Python rather than in
data/hero_realms_cards.json, and `tools/audit_cards.py` audits the JSON. So the
one automated check that compares printed text to the effects dict has never
covered them, and BASELINE.md records that audit concluding "the card data is
clean" on that basis.

The manual QA documents are no better: RULES_COMPLIANCE.md, QA_FINAL_REPORT.md
and QA_RULES_VERIFICATION.md each tick "Starting deck: 7 Gold + 1 Shortsword +
1 Dagger + 1 Ruby", which verifies the deck's *composition* and never any
card's *effects*.

Ruby was consequently encoded as a 1-health action for the entire life of the
project instead of a 2-gold treasure, cutting every player's starting economy
from 9 gold per deck cycle to 7. This file is the check that would have caught
it, and covers all five so the next one cannot hide the same way.

Reference: https://www.herorealms.com/base-game-rules/ for deck composition;
the base set card list for the individual card faces.
"""

import unittest

from hero_engine import DAGGER, FIRE_GEM, GOLD, HRPlayer, RUBY, SHORTSWORD


class TestStartingCardFaces(unittest.TestCase):
    """One assertion per printed card face."""

    def test_gold_is_a_one_gold_treasure(self):
        self.assertEqual(GOLD.card_type, "treasure")
        self.assertEqual(GOLD.effects, {"gold": 1})
        self.assertEqual(GOLD.cost, 0)

    def test_ruby_is_a_two_gold_treasure(self):
        """The regression. Ruby is a treasure worth 2 gold, not a heal."""
        self.assertEqual(RUBY.card_type, "treasure")
        self.assertEqual(RUBY.effects, {"gold": 2})
        self.assertEqual(RUBY.cost, 0)
        self.assertEqual(RUBY.get("health", 0), 0,
                         "Ruby has no healing; it was mis-encoded as {'health': 1}")

    def test_shortsword_is_two_combat(self):
        self.assertEqual(SHORTSWORD.card_type, "action")
        self.assertEqual(SHORTSWORD.effects, {"combat": 2})
        self.assertEqual(SHORTSWORD.cost, 0)

    def test_dagger_is_one_combat(self):
        self.assertEqual(DAGGER.card_type, "action")
        self.assertEqual(DAGGER.effects, {"combat": 1})
        self.assertEqual(DAGGER.cost, 0)

    def test_fire_gem_is_two_gold_and_sacrifices_for_three_combat(self):
        self.assertEqual(FIRE_GEM.cost, 2)
        self.assertEqual(FIRE_GEM.get("gold", 0), 2)
        self.assertEqual(FIRE_GEM.get("sacrifice_combat", 0), 3)

    def test_fire_gem_carries_its_printed_text(self):
        """The UI renders a card's rules from `text`, and this was the one card
        in hand with none - so a Fire Gem showed only its "+2 Gold" chip and a
        player could not learn from the card that it could be sacrificed.

        The other four hardcoded cards are vanilla (their whole face is the one
        effect the chip already shows); Fire Gem is not."""
        self.assertIn("sacrifice", FIRE_GEM.text.lower())
        self.assertIn("3 combat", FIRE_GEM.text.lower())
        self.assertIn("2 gold", FIRE_GEM.text.lower())


class TestStartingDeckEconomy(unittest.TestCase):
    """The aggregate the bug actually distorted."""

    def setUp(self):
        import random

        self.player = HRPlayer("Test", random.Random(0))
        self.player.setup_starting_deck()

    def test_deck_is_the_printed_ten_cards(self):
        ids = sorted(card.id for card in self.player.deck)
        self.assertEqual(ids, sorted(["gold"] * 7 + ["shortsword", "dagger", "ruby"]))

    def test_a_full_deck_cycle_produces_nine_gold(self):
        """7 Gold at 1 plus Ruby at 2. It produced 7 while Ruby was a heal."""
        total = sum(card.get("gold", 0) for card in self.player.deck)
        self.assertEqual(total, 9)

    def test_starting_gold_density_constants_match_the_deck(self):
        """Two tuning constants are documented as derived from this density and
        were therefore derived from the bug."""
        from hero_engine import _GOLD_DENSITY_DISCOUNT_SCALE, _deck_gold_density
        from web.bot import STARTING_GOLD_DENSITY

        density = _deck_gold_density(self.player)
        self.assertAlmostEqual(density, 0.9, places=6)
        self.assertAlmostEqual(STARTING_GOLD_DENSITY, density, places=6)
        self.assertAlmostEqual(_GOLD_DENSITY_DISCOUNT_SCALE, density * 4.0, places=6)

    def test_starting_deck_has_no_healing(self):
        """Ruby was the only source, and it should not be one."""
        self.assertEqual(
            sum(card.get("health", 0) for card in self.player.deck), 0)


if __name__ == "__main__":
    unittest.main()
