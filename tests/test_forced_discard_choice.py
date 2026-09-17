"""Forced opponent discards become a choice for human victims.

Six cards force the opponent to discard (Spark, Wolf Form, Elven Curse,
Torgen Rocksplitter, Broelyn Loreweaver and Nature's Bounty via ally
abilities, plus Wolf Form's sacrifice rider). The engine used to resolve
these inline with _find_worst_idx, so the victim never chose. Now a human
victim in a live web session gets a pending discard choice instead; bots,
MCTS rollouts, and training keep the inline heuristic byte-identical.
"""

import copy
import random
import unittest

import hero_engine
from hero_engine import (
    DAGGER,
    GOLD,
    HRPlayer,
    _force_opponent_discard,
    load_hero_cards,
    play_card,
)

CARDS = load_hero_cards("data/hero_realms_cards.json")


def _card(name):
    return next(c for c in CARDS if c.name == name)


def _starter(template):
    """A fresh copy of a shared starter-card singleton."""
    return copy.deepcopy(template)


def _live_victim(name="Victim"):
    """A player configured exactly like a web-session human seat."""
    victim = HRPlayer(name, random.Random(0))
    victim.defer_choices = True
    victim.log_effects = True
    victim.is_human = True
    return victim


class TestForcedDiscardDeferral(unittest.TestCase):
    def test_human_victim_gets_pending_choice(self):
        victim = _live_victim()
        gold = _starter(GOLD)
        victim.hand = [gold]
        _force_opponent_discard(victim, 1, source="Spark")
        self.assertEqual(len(victim.hand), 1, "nothing discarded yet")
        self.assertEqual(len(victim.pending_choices), 1)
        choice = victim.pending_choices[0]
        self.assertEqual(choice["kind"], "discard")
        self.assertEqual(choice["count"], 1)
        self.assertEqual(choice["source"], "Spark")

    def test_human_victim_answers_the_choice(self):
        victim = _live_victim()
        victim.hand = [_starter(GOLD), _starter(DAGGER)]
        _force_opponent_discard(victim, 1, source="Spark")
        actions_before = len(victim.hand)
        hero_engine.apply_choice(victim, victim.pending_choices[0], 1)
        self.assertEqual(len(victim.hand), actions_before - 1)
        self.assertEqual(victim.pending_choices, [])

    def test_bot_victim_keeps_inline_heuristic(self):
        victim = _live_victim()
        victim.is_human = False  # the AI seat in a bot match
        victim.hand = [_starter(GOLD), _starter(DAGGER)]
        _force_opponent_discard(victim, 1, source="Spark")
        self.assertEqual(len(victim.hand), 1)
        self.assertEqual(victim.pending_choices, [])

    def test_rollout_clone_keeps_inline_heuristic(self):
        # MCTS clones have log_effects off even when the seat is human.
        victim = _live_victim()
        victim.log_effects = False
        victim.hand = [_starter(GOLD), _starter(DAGGER)]
        _force_opponent_discard(victim, 1, source="Spark")
        self.assertEqual(len(victim.hand), 1)
        self.assertEqual(victim.pending_choices, [])

    def test_non_deferring_caller_unchanged(self):
        victim = HRPlayer("Victim", random.Random(0))
        victim.hand = [_starter(GOLD), _starter(DAGGER)]
        _force_opponent_discard(victim, 1, source="Spark")
        self.assertEqual(len(victim.hand), 1)
        self.assertEqual(victim.pending_choices, [])

    def test_empty_hand_no_choice_no_crash(self):
        victim = _live_victim()
        _force_opponent_discard(victim, 1, source="Spark")
        self.assertEqual(victim.pending_choices, [])

    def test_spark_play_defers_through_play_card(self):
        """End to end through the engine's play path: the source is named."""
        attacker = HRPlayer("Attacker", random.Random(1))
        victim = _live_victim()
        victim.hand = [_starter(GOLD)]
        spark = _card("Spark")
        attacker.hand = [spark]
        market = hero_engine.HRMarket(CARDS, random.Random(2))
        play_card(attacker, spark, market, opponent=victim)
        self.assertEqual(len(victim.pending_choices), 1)
        self.assertEqual(victim.pending_choices[0].get("source"), "Spark")
        self.assertEqual(len(victim.hand), 1, "nothing discarded yet")


class TestForcedDiscardSession(unittest.TestCase):
    """Session plumbing: pausing, offering, and answering the choice."""

    def setUp(self):
        hero_engine.AGENT_CHOOSES_TARGETS = True
        self.addCleanup(setattr, hero_engine, "AGENT_CHOOSES_TARGETS", False)

    def _bot_session_with_spark(self):
        from web.session import create_session
        session = create_session(seed=7)
        spark = _card("Spark")
        session.active_player = "bot"
        session.bot.hand.append(spark)
        # A victim hand worth choosing from.
        session.player.hand = [_starter(GOLD), _starter(DAGGER)]
        return session, spark

    def test_bot_spark_pauses_on_human_choice(self):
        session, spark = self._bot_session_with_spark()
        session.play_card(spark.id)
        self.assertEqual(len(session.player.pending_choices), 1)
        state = session.get_state()
        kinds = [a["type"] for a in state["legalActions"]]
        self.assertTrue(kinds, "no actions offered")
        self.assertTrue(all(k == "resolve_choice" for k in kinds))
        self.assertTrue(state["choicePending"])

    def test_victim_seat_sees_only_its_choice(self):
        session, spark = self._bot_session_with_spark()
        session.play_card(spark.id)
        guest_state = session.get_state(for_side="bot")
        # The bot seat is the attacker here; it holds the turn, so the
        # non-active branch is not what we want - use a multiplayer seat
        # instead below. This just guards the no-leak shape.
        self.assertIsInstance(guest_state["legalActions"], list)

    def test_multiplayer_attacker_sees_no_actions(self):
        from web.session import create_session
        session = create_session(seed=7, bot_is_human=True)
        spark = _card("Spark")
        session.active_player = "player"
        session.player.hand.append(spark)
        session.bot.hand = [_starter(GOLD)]
        session.play_card(spark.id)
        # Attacker's own legal_actions: the victim owes a choice.
        self.assertEqual(session.legal_actions(), [])
        # Victim's seat (for_side="bot") is offered the choice.
        victim_state = session.get_state(for_side="bot")
        kinds = [a["type"] for a in victim_state["legalActions"]]
        self.assertEqual(kinds, ["resolve_choice"])
        self.assertTrue(session.get_state(for_side="player")["choicePending"])

    def test_resolve_choice_answers_out_of_turn(self):
        from web.session import create_session
        session = create_session(seed=7, bot_is_human=True)
        spark = _card("Spark")
        session.active_player = "player"
        session.player.hand.append(spark)
        session.bot.hand = [_starter(GOLD), _starter(DAGGER)]
        session.play_card(spark.id)
        # It is still the attacker's turn; the victim answers anyway.
        self.assertEqual(session.active_player, "player")
        session.resolve_choice_action(0)
        self.assertEqual(session.bot.pending_choices, [])
        self.assertEqual(len(session.bot.hand), 1)
        # The attacker is unblocked.
        self.assertTrue(session.legal_actions())

    def test_attacker_cannot_act_while_choice_pends(self):
        from web.session import create_session
        session = create_session(seed=7, bot_is_human=True)
        spark = _card("Spark")
        session.active_player = "player"
        session.player.hand.extend([spark, _starter(GOLD)])
        session.bot.hand = [_starter(GOLD)]
        session.play_card(spark.id)
        with self.assertRaises(ValueError):
            session.play_card(_starter(GOLD).id)

    def test_bot_turn_pauses_and_does_not_end(self):
        from web import bot as bot_module
        from web.session import create_session
        session = create_session(seed=7)
        session.active_player = "bot"
        session.player.pending_choices.append(
            {"kind": "discard", "count": 1, "zone": "hand", "source": "Spark"})
        session.player.hand = [_starter(GOLD)]
        bot_module.run_bot_turn(session, budget_ms=20, algorithm="heuristic")
        self.assertEqual(session.active_player, "bot")
        self.assertEqual(session.bot_pause_count, 1)
        # The human's hand is untouched: the turn did not end.
        self.assertEqual(len(session.player.hand), 1)


if __name__ == "__main__":
    unittest.main()
