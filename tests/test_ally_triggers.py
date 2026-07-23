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


if __name__ == "__main__":
    unittest.main()
