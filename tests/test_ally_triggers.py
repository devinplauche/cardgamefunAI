"""Regression tests for ally (faction) ability triggering.

Per the official rules, an ally ability triggers "as soon as you have another
card of that faction in play", and Actions/Items stay in play until the
Discard Phase. has_ally only checked player.board, which holds champions
only, so 21 of the 36 ally cards - every non-champion one - could never
trigger each other. Faction-stacking with actions, a core strategy, did
nothing.
"""

import unittest

from hero_engine import (
    BoardChampion,
    HRMarket,
    HRPlayer,
    has_ally,
    load_hero_cards,
    play_card,
)

CARDS = load_hero_cards("data/hero_realms_cards.json")


def _card(name):
    return next(c for c in CARDS if c.name == name)


def _fresh_market():
    return HRMarket(CARDS)


class TestActionToActionAlly(unittest.TestCase):
    def test_second_same_faction_action_gets_the_ally_bonus(self):
        profit = _card("Profit")          # Guild action, ally_combat 4
        intimidation = _card("Intimidation")  # Guild action, ally_gold 2
        player = HRPlayer("P")
        player.hand = [profit, intimidation]
        market = _fresh_market()

        self.assertFalse(has_ally(profit, player), "first Guild card has no ally yet")
        play_card(player, profit, market, ally_bonus=has_ally(profit, player))

        self.assertTrue(has_ally(intimidation, player),
                        "Profit is in play this turn, so Intimidation's Guild ally should trigger")
        gold_before = player.gold
        play_card(player, intimidation, market, ally_bonus=has_ally(intimidation, player))
        self.assertEqual(player.gold, gold_before + 2, "ally_gold 2 should have fired")

    def test_a_lone_action_gets_no_ally_bonus(self):
        intimidation = _card("Intimidation")
        player = HRPlayer("P")
        player.hand = [intimidation]
        play_card(player, intimidation, _fresh_market(), ally_bonus=has_ally(intimidation, player))
        self.assertEqual(player.gold, 0, "no other Guild card in play, so no ally_gold")

    def test_different_factions_do_not_trigger_each_other(self):
        profit = _card("Profit")        # Guild
        spark = _card("Spark")          # Wild
        player = HRPlayer("P")
        player.hand = [profit, spark]
        market = _fresh_market()
        play_card(player, profit, market, ally_bonus=has_ally(profit, player))
        self.assertFalse(has_ally(spark, player), "Guild card must not trigger a Wild ally")

    def test_a_card_does_not_trigger_its_own_ally(self):
        profit = _card("Profit")
        player = HRPlayer("P")
        player.hand = [profit]
        self.assertFalse(has_ally(profit, player))


class TestAllyZoneLifetime(unittest.TestCase):
    def test_played_card_cannot_be_reshuffled_and_replayed_this_turn(self):
        """Actions stay in play until cleanup, even when a later draw empties the deck."""
        profit = _card("Profit")
        death_threat = _card("Death Threat")
        player = HRPlayer("P")
        player.hand = [profit, death_threat]
        market = _fresh_market()

        play_card(player, profit, market, ally_bonus=has_ally(profit, player))
        play_card(player, death_threat, market, ally_bonus=has_ally(death_threat, player))

        self.assertNotIn(profit, player.hand)
        self.assertIn(profit, player.played_this_turn)
        self.assertNotIn(profit, player.discard)

    def test_played_cards_do_not_carry_over_to_the_next_turn(self):
        """Actions leave play at the Discard Phase, so they must not still be
        triggering allies on a later turn."""
        from web.session import create_session

        profit = _card("Profit")
        intimidation = _card("Intimidation")
        session = create_session(seed=3)
        session.bot.hand = [profit]
        session.active_player = "bot"
        session.phase = "play"
        session.play_card(profit.id)
        self.assertIn(profit, session.bot.played_this_turn)

        session.active_player = "bot"
        session._start_turn(session.bot)
        self.assertEqual(session.bot.played_this_turn, [],
                         "played_this_turn must reset at the start of a turn")

        player = session.bot
        player.hand = [intimidation]
        self.assertFalse(has_ally(intimidation, player),
                         "last turn's Profit must not still be in play")

    def test_champion_on_board_still_triggers_an_action_ally(self):
        from hero_engine import BoardChampion

        intimidation = _card("Intimidation")  # Guild
        guild_champ = next(c for c in CARDS if c.faction == "Guild" and c.card_type == "champion")
        player = HRPlayer("P")
        player.board.append(BoardChampion(guild_champ))
        self.assertTrue(has_ally(intimidation, player),
                        "a Guild champion on board should still trigger a Guild action's ally")


class TestClonePreservesAllyZone(unittest.TestCase):
    def test_played_this_turn_survives_a_session_clone(self):
        """_copy_player builds via HRPlayer.__new__, so a missing attribute is
        an AttributeError inside a rollout rather than a wrong value."""
        from web.session import create_session

        profit = _card("Profit")
        session = create_session(seed=3)
        session.bot.hand = [profit]
        session.active_player = "bot"
        session.phase = "play"
        session.play_card(profit.id)

        clone = session.clone()
        self.assertEqual([c.id for c in clone.bot.played_this_turn],
                         [c.id for c in session.bot.played_this_turn])
        clone.bot.played_this_turn.clear()
        self.assertTrue(session.bot.played_this_turn, "clone must not share the list")


class TestRetroactiveAlly(unittest.TestCase):
    def test_retroactive_ally_stun_uses_the_selected_target(self):
        death_threat = _card("Death Threat")
        profit = _card("Profit")
        guard = next(c for c in CARDS if c.card_type == "champion" and c.guard)
        player = HRPlayer("P")
        opponent = HRPlayer("O")
        target = BoardChampion(guard)
        opponent.board.append(target)
        player.hand = [death_threat, profit]
        market = _fresh_market()

        play_card(player, death_threat, market, ally_bonus=has_ally(death_threat, player),
                  opponent=opponent, stun_target=target)
        play_card(player, profit, market, ally_bonus=has_ally(profit, player), opponent=opponent)

        self.assertEqual(opponent.board, [])
        self.assertIn(guard, opponent.discard)

    """Per the rules: "The order in which you play your cards does not matter.
    As soon as you have two or more cards of the same faction in play, you may
    trigger all relevant Ally Abilities."

    play_card used to evaluate ally_bonus once, at play time, and never
    revisit it, so a lone faction card played first lost its ally for the
    whole turn even after a partner arrived.
    """

    def test_first_card_gets_its_ally_when_a_partner_arrives_later(self):
        profit = _card("Profit")            # Guild, ally_combat 4
        intimidation = _card("Intimidation")  # Guild, ally_gold 2
        player = HRPlayer("P")
        player.hand = [profit, intimidation]
        market = _fresh_market()

        play_card(player, profit, market, ally_bonus=has_ally(profit, player))
        self.assertEqual(player.combat, 0, "no partner yet, so no ally_combat")
        self.assertEqual(player.pending_ally, [profit])

        play_card(player, intimidation, market, ally_bonus=has_ally(intimidation, player))
        # Profit base 2 gold, Intimidation base 5 combat,
        # + Profit ally_combat 4 (retroactive) + Intimidation ally_gold 2
        self.assertEqual(player.combat, 9)
        self.assertEqual(player.gold, 4)
        self.assertEqual(player.pending_ally, [])

    def test_a_champion_arriving_triggers_an_earlier_actions_ally(self):
        from hero_engine import BoardChampion

        profit = _card("Profit")  # Guild action, ally_combat 4
        guild_champ = next(c for c in CARDS if c.faction == "Guild" and c.card_type == "champion")
        player = HRPlayer("P")
        player.hand = [profit, guild_champ]
        market = _fresh_market()

        play_card(player, profit, market, ally_bonus=has_ally(profit, player))
        self.assertEqual(player.combat, 0)
        play_card(player, guild_champ, market, ally_bonus=has_ally(guild_champ, player))
        self.assertEqual(player.combat, 4, "the champion completed the Guild pair")

    def test_a_different_faction_does_not_trigger_the_pending_ally(self):
        profit = _card("Profit")  # Guild
        spark = _card("Spark")    # Wild
        player = HRPlayer("P")
        player.hand = [profit, spark]
        market = _fresh_market()
        play_card(player, profit, market, ally_bonus=has_ally(profit, player))
        play_card(player, spark, market, ally_bonus=has_ally(spark, player))
        # Spark is a lone Wild card, so it queues as well; the point is that
        # neither fired - a Guild card must not complete a Wild pair.
        self.assertIn(profit, player.pending_ally, "Profit's Guild ally must still be pending")
        self.assertIn(spark, player.pending_ally, "Spark's Wild ally must still be pending")
        self.assertEqual(player.combat, 3, "only Spark's base combat, no ally bonuses")

    def test_pending_allies_do_not_leak_across_turns(self):
        from web.session import create_session

        profit = _card("Profit")
        session = create_session(seed=3)
        session.bot.hand = [profit]
        session.active_player = "bot"
        session.phase = "play"
        session.play_card(profit.id)
        self.assertTrue(session.bot.pending_ally)
        session._start_turn(session.bot)
        self.assertEqual(session.bot.pending_ally, [])

    def test_pending_ally_survives_a_clone(self):
        from web.session import create_session

        profit = _card("Profit")
        session = create_session(seed=3)
        session.bot.hand = [profit]
        session.active_player = "bot"
        session.phase = "play"
        session.play_card(profit.id)
        clone = session.clone()
        self.assertEqual([c.id for c in clone.bot.pending_ally],
                         [c.id for c in session.bot.pending_ally])
        clone.bot.pending_ally.clear()
        self.assertTrue(session.bot.pending_ally, "clone must not share the list")


class TestEnablerValue(unittest.TestCase):
    """A faction card with no ally ability of its own still turns on every
    other card of its faction. 18 of the 19 market cards without a printed
    ally ability have a faction; only Fire Gem has none - which is why it is
    a weak buy unless the market is all expensive."""

    def test_a_plain_faction_card_has_enabler_value_and_fire_gem_has_none(self):
        from hero_engine import FIRE_GEM
        from web.bot import _enabler_value, _resource_weights
        from web.session import create_session

        necros_plain = next(c for c in CARDS
                            if c.faction == "Necros" and "ally_faction" not in c.effects)
        necros_ally = next(c for c in CARDS
                           if c.faction == "Necros" and c.effects.get("ally_combat"))
        session = create_session(seed=1)
        session.bot.deck.extend([necros_ally] * 3)
        weights = _resource_weights(session, "bot")

        self.assertGreater(_enabler_value(session, "bot", necros_plain, weights), 0.0)
        self.assertEqual(_enabler_value(session, "bot", FIRE_GEM, weights), 0.0)

    def test_enabler_value_rises_with_owned_same_faction_ally_cards(self):
        from web.bot import _enabler_value, _resource_weights
        from web.session import create_session

        necros_plain = next(c for c in CARDS
                            if c.faction == "Necros" and "ally_faction" not in c.effects)
        necros_ally = next(c for c in CARDS
                           if c.faction == "Necros" and c.effects.get("ally_combat"))
        scores = []
        for n in (0, 1, 3):
            session = create_session(seed=1)
            session.bot.deck.extend([necros_ally] * n)
            scores.append(_enabler_value(session, "bot", necros_plain,
                                         _resource_weights(session, "bot")))
        self.assertEqual(scores, sorted(scores))
        self.assertGreater(scores[-1], scores[0])

    def test_owning_no_ally_cards_of_that_faction_gives_no_enabler_value(self):
        from web.bot import _enabler_value, _resource_weights
        from web.session import create_session

        necros_plain = next(c for c in CARDS
                            if c.faction == "Necros" and "ally_faction" not in c.effects)
        session = create_session(seed=1)  # starting deck has no faction cards at all
        self.assertEqual(
            _enabler_value(session, "bot", necros_plain, _resource_weights(session, "bot")),
            0.0,
        )


class TestDuplicateCopiesArePartners(unittest.TestCase):
    """A second *copy* of a card is another card of that faction.

    `load_hero_cards` shares one immutable HRCard across all printed copies
    (`[card] * quantity`), and `has_ally` used to exclude "the card itself"
    with `is not`, which also excluded every other copy. Found by playing the
    UI: a second Cult Priest joined the board next to the first and its
    "Necros Ally: gain 4 combat" did nothing. 12 of the 36 ally cards are
    printed in 2-3 copies, so this was the common case, not an edge one.
    """

    def test_two_copies_of_one_champion_are_allies(self):
        cult = _card("Cult Priest")  # 2x Necros champion, ally_combat 4
        player = HRPlayer("P")
        player.board.append(BoardChampion(cult))
        self.assertTrue(has_ally(cult, player))

    def test_two_copies_of_one_action_are_allies(self):
        profit = _card("Profit")  # 3x Guild action, ally_combat 4
        player = HRPlayer("P")
        player.played_this_turn.append(profit)
        self.assertTrue(has_ally(profit, player))

    def test_a_card_is_still_not_its_own_ally(self):
        """The self-exclusion the `is not` guard was there for must survive."""
        profit = _card("Profit")
        player = HRPlayer("P")
        player.played_this_turn.append(profit)
        self.assertFalse(has_ally(profit, player, self_played=True),
                         "only this very card is in play - no partner")

        cult = _card("Cult Priest")
        player = HRPlayer("P")
        champion = BoardChampion(cult)
        player.board.append(champion)
        self.assertFalse(has_ally(cult, player, self_champion=champion),
                         "only this very champion is in play - no partner")

    def test_every_multi_copy_ally_card_pairs_with_itself(self):
        multi = {}
        for card in CARDS:
            if card.effects.get("ally_faction"):
                multi.setdefault(card.name, []).append(card)
        pairs = [cards[0] for cards in multi.values() if len(cards) > 1]
        self.assertTrue(pairs, "expected multi-copy ally cards in the set")
        for card in pairs:
            with self.subTest(card=card.name):
                player = HRPlayer("P")
                if card.card_type == "champion":
                    player.board.append(BoardChampion(card))
                else:
                    player.played_this_turn.append(card)
                self.assertTrue(has_ally(card, player))


class TestChampionAllyTiming(unittest.TestCase):
    """A champion's ally is a separate ability from its expend ability.

    It used to be paid inside expend_champion, which meant it fired only if you
    expended the champion, never on the turn it was played unless you also
    expended it, and again on every later expend. The rule is state-based and
    once per turn (RULES_COMPLIANCE.md: "Trigger when 2+ cards of same faction
    in play", "Each ally ability triggers only ONCE per turn").
    """

    def setUp(self):
        self.opponent = HRPlayer("O")
        self.opponent.hp = 50

    def _player(self, board=(), hand=()):
        player = HRPlayer("P")
        player.hp = 50
        player.board = [BoardChampion(c) for c in board]
        player.hand = list(hand)
        return player

    def test_ally_fires_when_the_champion_is_played(self):
        cult, lys = _card("Cult Priest"), _card("Lys, the Unseen")  # both Necros
        player = self._player(board=[lys], hand=[cult])
        play_card(player, cult, _fresh_market(),
                  ally_bonus=has_ally(cult, player), opponent=self.opponent)
        self.assertEqual(player.combat, 4, "Necros ally should pay on play")

    def test_ally_does_not_require_expending(self):
        cult, lys = _card("Cult Priest"), _card("Lys, the Unseen")
        player = self._player(board=[lys], hand=[cult])
        play_card(player, cult, _fresh_market(),
                  ally_bonus=has_ally(cult, player), opponent=self.opponent)
        self.assertEqual(player.combat, 4)
        self.assertFalse(player.board[-1].exhausted,
                         "no expend was needed to collect the ally")

    def test_ally_is_not_re_paid_on_expend(self):
        from hero_engine import expend_champion

        cult, lys = _card("Cult Priest"), _card("Lys, the Unseen")
        player = self._player(board=[lys], hand=[cult])
        play_card(player, cult, _fresh_market(),
                  ally_bonus=has_ally(cult, player), opponent=self.opponent)
        champion = player.board[-1]
        expend_champion(player, champion, self.opponent, choice="combat")
        self.assertEqual(player.combat, 5,
                         "expend adds only its own +1 combat, not the ally again")

    def test_ally_fires_at_most_once_per_turn(self):
        cult = _card("Cult Priest")
        player = self._player(board=[cult, cult])
        from hero_engine import _resolve_board_allies

        _resolve_board_allies(player, self.opponent)
        first = player.combat
        _resolve_board_allies(player, self.opponent)
        self.assertEqual(player.combat, first, "must not re-trigger within a turn")

    def test_an_action_played_later_completes_the_pair_for_a_board_champion(self):
        myros, profit = _card("Myros, Guild Mage"), _card("Profit")  # both Guild
        player = self._player(board=[myros], hand=[profit])
        play_card(player, profit, _fresh_market(),
                  ally_bonus=has_ally(profit, player), opponent=self.opponent)
        self.assertEqual(player.combat, 8,
                         "Myros ally 4 (partner arrived) + Profit ally 4")

    def test_ally_re_fires_at_the_start_of_a_later_turn(self):
        """The trigger is the condition holding, not a card being played.

        Two Necros champions left on the board satisfy the ally condition
        before the next turn's first card, so the payout repeats every turn -
        confirmed against the printed rules. The engine briefly fired only when
        a card entered play, which dropped it on any turn you played nothing of
        that faction.
        """
        from web.session import create_session

        cult, lys = _card("Cult Priest"), _card("Lys, the Unseen")
        session = create_session(seed=3)
        session.player.board = [BoardChampion(lys)]
        session.player.hand = [cult]
        session.active_player = "player"
        session.play_card(cult.id)
        self.assertEqual(session.player.combat, 4, "ally on the turn it is played")

        # A new turn: combat resets to 0, then the standing pair pays again
        # without a single card being played.
        session._start_turn(session.player)
        self.assertEqual(session.player.combat, 4,
                         "the standing Necros pair re-triggers on the new turn")

    def test_ally_still_fires_only_once_within_that_later_turn(self):
        from web.session import create_session

        cult, lys = _card("Cult Priest"), _card("Lys, the Unseen")
        session = create_session(seed=3)
        session.player.board = [BoardChampion(lys), BoardChampion(cult)]
        session.active_player = "player"
        session._start_turn(session.player)
        opened_with = session.player.combat
        self.assertEqual(opened_with, 4)

        # Playing another Necros card must not pay the same ally a second time.
        death_touch = _card("Death Touch")  # Necros action
        session.player.hand = [death_touch]
        session.play_card(death_touch.id)
        self.assertEqual(
            session.player.combat,
            opened_with + death_touch.get("combat", 0) + death_touch.get("ally_combat", 0),
            "Cult Priest's ally already paid this turn and must not repeat",
        )

    def test_kraka_ally_survives_the_move_off_expend(self):
        """ally_per_champion_health lived only in expend_champion's ally block;
        removing that block would have silently dropped Kraka's ally."""
        kraka, arkus = _card("Kraka, High Priest"), _card("Arkus, Imperial Dragon")
        player = self._player(board=[kraka], hand=[arkus])
        player.hp = 20
        play_card(player, arkus, _fresh_market(),
                  ally_bonus=has_ally(arkus, player), opponent=self.opponent)
        # Kraka: +2 health per champion (2 in play) = 4; Arkus: +6 health.
        self.assertEqual(player.hp, 30)

    def test_a_clone_does_not_re_trigger_an_ally_the_real_game_paid(self):
        from web.session import create_session

        cult, lys = _card("Cult Priest"), _card("Lys, the Unseen")
        session = create_session(seed=3)
        session.player.board = [BoardChampion(lys)]
        session.player.hand = [cult]
        session.active_player = "player"
        session.play_card(cult.id)

        clone = session.clone()
        self.assertTrue(all(c.ally_paid_this_turn for c in clone.player.board
                            if c.card is cult),
                        "ally_paid_this_turn must survive cloning or MCTS "
                        "re-collects allies the real game already paid")


if __name__ == "__main__":
    unittest.main()
