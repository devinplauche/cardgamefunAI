"""Regression tests for optional sacrifice mechanics in hero_engine.py.

Every printed sacrifice effect in the card set reads "you may sacrifice" (or
uses the {Sacrifice}: keyword, which means the same thing by Hero Realms
convention) - never mandatory. The engine used to apply every one of them
unconditionally, which meant a lean, thinned deck (what a sacrifice-focused
strategy builds toward) had no bad card left to decline sacrificing and was
forced to burn something actually useful. That is a rules deviation affecting
every game simulated with this engine, not merely an AI valuation nuance.
"""

import random
import unittest

from hero_engine import (
    DAGGER,
    GOLD,
    HRCard,
    HRMarket,
    HRPlayer,
    RUBY,
    SHORTSWORD,
    apply_choice,
    auto_resolve_choices,
    choice_candidates,
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

    def test_declines_when_an_exhausted_guard_would_absorb_the_combat(self):
        player = _player_with_hand(FIRE_GEM_CARD)
        opponent = HRPlayer("O")
        from hero_engine import BoardChampion
        guard_champ = next(c for c in CARDS if c.card_type == "champion" and c.guard > 0)
        guard = BoardChampion(guard_champ)
        guard.exhausted = True
        opponent.board.append(guard)
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

    def test_takes_lethal_sacrifice_without_established_economy(self):
        player = _player_with_hand(FIRE_GEM_CARD)
        player.combat = 48
        opponent = HRPlayer("O")
        opponent.hp = 3
        market = HRMarket(CARDS)

        play_card(player, FIRE_GEM_CARD, market, opponent=opponent)

        self.assertEqual(player.combat, 51)
        self.assertIn(FIRE_GEM_CARD, player.banish)

    def test_takes_lethal_sacrifice_after_clearing_guard_health(self):
        player = _player_with_hand(FIRE_GEM_CARD)
        player.combat = 5
        opponent = HRPlayer("O")
        opponent.hp = 3
        from hero_engine import BoardChampion
        guard_champ = next(c for c in CARDS if c.card_type == "champion" and c.guard > 0)
        guard = BoardChampion(guard_champ)
        guard.current_health = 5
        opponent.board.append(guard)
        market = HRMarket(CARDS)

        play_card(player, FIRE_GEM_CARD, market, opponent=opponent)

        self.assertEqual(player.combat, 8)
        self.assertIn(FIRE_GEM_CARD, player.banish)


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


class TestTyrannorPlayerChoice(unittest.TestCase):
    """Tyrannor's "you may sacrifice up to two cards in your hand and/or
    discard pile" is the player's pick, not the engine's.

    With defer_choices the expend enqueues one multi-count pending choice
    instead of resolving inline; the engine's junk-threshold pick survives
    only as the automated fallback (auto_resolve_choices), which must stay
    identical to the inline path - the equivalence test pins that.
    """

    def _deferred_tyrannor(self, hand, discard=()):
        player = _player_with_hand()
        player.defer_choices = True
        player.hand = list(hand)
        player.discard = list(discard)
        from hero_engine import BoardChampion
        bc = BoardChampion(TYRANNOR)
        player.board.append(bc)
        expend_champion(player, bc, opponent=None)
        return player

    def test_expend_enqueues_a_two_pick_sacrifice_choice(self):
        player = self._deferred_tyrannor([GOLD, DAGGER], [RUBY])

        self.assertEqual(len(player.pending_choices), 1)
        choice = player.pending_choices[0]
        self.assertEqual(choice["kind"], "sacrifice")
        self.assertEqual(choice["count"], 2)
        self.assertEqual(choice["zone"], "hand_or_discard")
        self.assertEqual(choice["source"], "Tyrannor, the Devourer")
        self.assertEqual(player.banish, [],
                         "nothing is sacrificed until the player picks")

    def test_choice_count_caps_at_available_cards(self):
        player = self._deferred_tyrannor([GOLD])
        self.assertEqual(player.pending_choices[0]["count"], 1)

    def test_no_choice_when_nothing_to_sacrifice(self):
        player = self._deferred_tyrannor([], [])
        self.assertEqual(player.pending_choices, [])

    def test_answering_twice_sacrifices_two_cards(self):
        player = self._deferred_tyrannor([GOLD, DAGGER, GOOD_CARD])
        choice = player.pending_choices[0]

        apply_choice(player, choice, choice_candidates(player, choice).index(GOLD))
        self.assertEqual(len(player.pending_choices), 1, "one pick left")
        self.assertEqual(choice["count"], 1)

        apply_choice(player, choice, choice_candidates(player, choice).index(DAGGER))
        self.assertEqual(player.pending_choices, [])
        self.assertIn(GOLD, player.banish)
        self.assertIn(DAGGER, player.banish)
        self.assertIn(GOOD_CARD, player.hand)

    def test_declining_stops_the_effect_early(self):
        # The session answers Decline by dropping the choice; the engine only
        # needs the choice to be removable mid-count.
        player = self._deferred_tyrannor([GOLD, DAGGER])
        choice = player.pending_choices[0]

        apply_choice(player, choice, choice_candidates(player, choice).index(GOLD))
        player.pending_choices.remove(choice)

        self.assertEqual(list(player.banish), [GOLD])
        self.assertIn(DAGGER, player.hand)

    def test_deferred_plus_auto_resolve_matches_inline(self):
        """The automated fallback must equal the inline behaviour it replaced,
        across junk/good mixes in both zones."""
        pool = [GOLD, DAGGER, RUBY, SHORTSWORD, GOOD_CARD, FIRE_GEM_CARD]
        mismatches = []
        for seed in range(40):
            rng = random.Random(seed)
            hand = [rng.choice(pool) for _ in range(rng.randint(0, 5))]
            discard = [rng.choice(pool) for _ in range(rng.randint(0, 4))]

            from hero_engine import BoardChampion
            a = _player_with_hand()
            a.hand = list(hand)
            a.discard = list(discard)
            a.board.append(BoardChampion(TYRANNOR))
            b = _player_with_hand()
            b.defer_choices = True
            b.hand = list(hand)
            b.discard = list(discard)
            b.board.append(BoardChampion(TYRANNOR))

            expend_champion(a, a.board[0], opponent=None)
            expend_champion(b, b.board[0], opponent=None)
            auto_resolve_choices(b, None)

            def snap(p):
                return (sorted(c.name for c in p.banish),
                        sorted(c.name for c in p.hand),
                        sorted(c.name for c in p.discard),
                        p.combat)
            if snap(a) != snap(b):
                mismatches.append(seed)
        self.assertEqual(mismatches, [],
                         f"deferred path diverged on seeds {mismatches[:5]}")


if __name__ == "__main__":
    unittest.main()
