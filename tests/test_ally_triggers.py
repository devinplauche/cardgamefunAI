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


if __name__ == "__main__":
    unittest.main()
