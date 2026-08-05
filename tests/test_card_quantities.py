"""Regression tests for card quantities and duplicate-champion identity.

The card data had exactly one entry per unique card, with no way to encode
that many cards are printed in 2-3 copies (Taxation and Profit at 3x each,
Man-at-Arms and Wolf Shaman at 2x, and so on). load_hero_cards built a market
deck of 54 cards where the base set ships 80 (16 Fire Gems live in a separate
pile, tracked correctly already), so every simulated game drew from a deck
skewed toward treating every card as equally rare.

Fixing that exposed a second, deeper bug: two board champions sharing the
same card.id (now possible since a 2x/3x champion can appear on one board
twice) broke every card.id-based lookup in web/session.py - the wrong copy,
or no copy, could be found for expend/attack/stun actions.
"""

import unittest

from hero_engine import BoardChampion, load_hero_cards

CARDS = load_hero_cards("data/hero_realms_cards.json")

# Spot-checked against the official base-set card list.
EXPECTED_QUANTITIES = {
    "Arkus, Imperial Dragon": 1,
    "Man-at-Arms": 2,
    "Recruit": 3,
    "Taxation": 3,
    "Profit": 3,
    "Death Touch": 3,
    "Influence": 3,
    "Elven Gift": 3,
    "Spark": 3,
    "Fire Gem": 16,
}


class TestMarketDeckSize(unittest.TestCase):
    def test_total_loaded_cards_matches_the_official_count(self):
        # 80 market-deck cards (26 of the 55 unique cards printed 2x or 3x)
        # plus 16 Fire Gems, tracked separately by the market.
        self.assertEqual(len(CARDS), 96)

    def test_market_deck_excluding_fire_gems_is_80_cards(self):
        from hero_engine import HRMarket

        market = HRMarket(CARDS)
        self.assertEqual(len(market.pool) + len(market.row_cards()), 80)

    def test_fire_gem_count_is_still_16_and_unaffected(self):
        from hero_engine import HRMarket

        market = HRMarket(CARDS)
        self.assertEqual(market.fire_gems_remaining, 16)

    def test_specific_card_quantities(self):
        from collections import Counter

        counts = Counter(c.name for c in CARDS)
        for name, expected in EXPECTED_QUANTITIES.items():
            self.assertEqual(counts[name], expected, f"{name} quantity wrong")

    def test_duplicate_copies_are_the_same_object(self):
        """Matches the existing convention for GOLD/SHORTSWORD/DAGGER/RUBY -
        safe because HRCard is never mutated anywhere in the engine."""
        taxations = [c for c in CARDS if c.name == "Taxation"]
        self.assertEqual(len(taxations), 3)
        self.assertTrue(all(c is taxations[0] for c in taxations))


class TestDuplicateChampionIdentity(unittest.TestCase):
    """Two board champions built from the same card share card.id, so they
    must be otherwise distinguishable."""

    def test_two_copies_of_the_same_champion_get_different_instance_ids(self):
        champ = next(c for c in CARDS if c.card_type == "champion")
        a = BoardChampion(champ)
        b = BoardChampion(champ)
        self.assertEqual(a.card.id, b.card.id)
        self.assertNotEqual(a.instance_id, b.instance_id)

    def test_expending_one_copy_does_not_affect_the_other(self):
        from hero_engine import HRPlayer, expend_champion

        champ = next(c for c in CARDS if c.card_type == "champion" and not c.guard)
        player = HRPlayer("P")
        a = BoardChampion(champ)
        b = BoardChampion(champ)
        player.board = [a, b]

        expend_champion(player, a, opponent=None)

        self.assertTrue(a.exhausted)
        self.assertFalse(b.exhausted, "expending one copy must not exhaust the other")

    def test_session_can_expend_the_second_copy_after_the_first_is_exhausted(self):
        """This is the exact failure this fix addresses: with card.id-based
        lookup, an exhausted first copy made an available second copy
        unreachable - "Champion could not be expended" even though one was
        legally available."""
        from web.session import create_session

        champ = next(c for c in CARDS if c.card_type == "champion" and not c.guard
                    and c.effects.get("combat", 0) > 0)
        session = create_session(seed=1)
        first = BoardChampion(champ)
        second = BoardChampion(champ)
        session.bot.board = [first, second]
        session.active_player = "bot"
        session.phase = "champion"

        session.expend_champion_action(str(first.instance_id))
        self.assertTrue(first.exhausted)
        self.assertFalse(second.exhausted)

        # The second copy must still be reachable and independently expendable.
        session.expend_champion_action(str(second.instance_id))
        self.assertTrue(second.exhausted)

    def test_legal_actions_offers_one_expend_action_per_copy(self):
        from web.session import create_session

        champ = next(c for c in CARDS if c.card_type == "champion" and not c.guard)
        session = create_session(seed=1)
        session.bot.board = [BoardChampion(champ), BoardChampion(champ)]
        session.active_player = "bot"
        session.phase = "champion"

        actions = [a for a in session.legal_actions() if a["type"] == "expend_champion"]
        ids = {a["championId"] for a in actions}
        self.assertEqual(len(ids), 2, "both copies must have distinct championIds")
        # An or_choice champion ("gain 1 gold *or* 1 combat") now contributes
        # one action per branch, so the count is per copy *per choice* - the
        # invariant that matters is that every copy is independently
        # addressable, which the distinct-id check above is what actually pins.
        per_copy = {champion_id: sum(1 for a in actions if a["championId"] == champion_id)
                    for champion_id in ids}
        self.assertEqual(len(set(per_copy.values())), 1,
                         "both copies must offer the same set of options")

    def test_champion_view_exposes_a_stable_instance_id(self):
        from web.session import _champion_view

        champ = next(c for c in CARDS if c.card_type == "champion")
        bc = BoardChampion(champ)
        view = _champion_view(bc)
        self.assertEqual(view["instanceId"], str(bc.instance_id))

    def test_clone_preserves_instance_id_rather_than_regenerating_it(self):
        from web.session import create_session

        champ = next(c for c in CARDS if c.card_type == "champion")
        session = create_session(seed=1)
        bc = BoardChampion(champ)
        session.bot.board = [bc]

        clone = session.clone()
        self.assertEqual(clone.bot.board[0].instance_id, bc.instance_id)

    def test_attack_target_action_distinguishes_duplicate_non_guard_champions(self):
        from web.session import create_session

        champ = next(c for c in CARDS if c.card_type == "champion" and not c.guard
                    and c.health >= 3)
        session = create_session(seed=1)
        weak = BoardChampion(champ)
        weak.current_health = 1
        strong = BoardChampion(champ)  # full health, same card.id as `weak`
        session.bot.board = [weak, strong]
        session.active_player = "player"
        session.phase = "combat"
        session.player.combat = 1

        session.attack_target_action("champion", str(weak.instance_id))

        self.assertFalse(weak.alive)
        self.assertTrue(strong.alive)
        self.assertEqual(strong.current_health, champ.health,
                         "targeting one copy must not damage the other")


if __name__ == "__main__":
    unittest.main()
