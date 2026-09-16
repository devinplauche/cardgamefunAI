import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from hero_engine import DAGGER, FIRE_GEM, GOLD, HRCard
from web.backend import Handler, SESSION_LOCKS
from web import db as db_store
from web import games as game_store
from web.session import create_session


class HumanPlayTests(unittest.TestCase):
    def setUp(self):
        self.session = create_session(seed=7, algorithm="heuristic")
        self.session.player.hand = []
        self.session.player.played_this_turn.clear()

    def card(self, name):
        return next(c for c in self.session.cards if c.name == name)

    def test_play_all_keeps_decision_cards_and_optional_fire_gem(self):
        s = self.session
        s.player.hand = [GOLD, DAGGER, self.card("Profit"), self.card("Bribe"),
                         FIRE_GEM, self.card("Deception"), self.card("Cult Priest")]
        self.assertEqual(s.get_state()["autoPlayCount"], 5)
        s.play_all_action()
        self.assertEqual([c.name for c in s.player.hand], ["Deception", "Cult Priest"])
        self.assertEqual(s.player.gold, 8)
        # Dagger only: allies never fire on their own. Profit and Bribe are a
        # Guild pair in play, so both triggers are offered for the user.
        self.assertEqual(s.player.combat, 1)
        offered = [a for a in s.legal_actions() if a["type"] == "trigger_ally"]
        self.assertEqual({a["cardId"] for a in offered},
                         {self.card("Profit").id, self.card("Bribe").id})
        s.trigger_ally_action(self.card("Profit").id)
        self.assertEqual(s.player.combat, 5)  # Dagger + Profit's Guild ally.
        s.trigger_ally_action(self.card("Bribe").id)
        self.assertTrue(s.player.next_buy_to_top_action_only)
        self.assertIn(FIRE_GEM, s.player.played_this_turn)
        self.assertEqual(s.get_state()["autoPlayCount"], 0)

    def test_duplicates_are_played_once_each_and_empty_batch_is_noop(self):
        s = self.session
        s.player.hand = [GOLD, GOLD, GOLD]
        s.play_all_action()
        self.assertEqual(s.player.gold, 3)
        self.assertEqual(s.player.played_this_turn.count(GOLD), 3)
        history_length = len(s.history)
        s.play_all_action()
        self.assertEqual(len(s.history), history_length)

    def test_pending_choices_and_unsafe_allies_prevent_batching(self):
        s = self.session
        s.player.hand = [GOLD, self.card("Bribe")]
        s.player.pending_choices = [{"kind": "discard", "count": 1, "zone": "hand"}]
        s.play_all_action()
        self.assertEqual(len(s.player.hand), 2)
        s.player.pending_choices.clear()
        # A previously played Guild card's ally-draw makes order significant.
        s.player.played_this_turn = [HRCard(id="test", name="Ally draw", faction="Guild", cost=0, card_type="action",
                                          effects={"ally_faction": "Guild", "ally_draw": 1})]
        s.play_all_action()
        self.assertEqual([c.name for c in s.player.hand], ["Bribe"])

    def test_bot_turn_rejects_play_all(self):
        s = self.session
        s.end_turn()
        with self.assertRaises(ValueError):
            s.play_all_action()

    def test_declined_gem_stays_in_deck(self):
        s = self.session
        s.player.hand = [FIRE_GEM]
        s.bot.hp = 1  # Even a guaranteed lethal must not auto-sacrifice.
        s.play_card(FIRE_GEM.id, manual_self_sacrifice=True)
        self.assertEqual(s.player.combat, 0)
        s.end_turn()
        self.assertIn(FIRE_GEM, s.player.discard + s.player.hand + s.player.deck)

    def test_http_manual_play_then_explicit_sacrifice_returns_gem_to_supply(self):
        db_store.init_schema()
        s = self.session
        s.player.hand = [FIRE_GEM, FIRE_GEM]
        s.bot.hp = 1
        game_store.create_bot_session(s)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = HTTPConnection(*server.server_address, timeout=5)

        def post(route, body):
            conn.request("POST", f"/api/sessions/{s.session_id}/{route}", json.dumps(body))
            response = conn.getresponse()
            payload = json.loads(response.read())
            self.assertEqual(response.status, 200, payload)
            return payload

        try:
            state = post("play-card", {"cardId": FIRE_GEM.id})
            self.assertEqual(state["player"]["combat"], 0)
            self.assertEqual(state["player"]["gold"], 2)
            self.assertTrue(any(a["type"] == "sacrifice_played" for a in state["legalActions"]))
            state = post("play-all", {})
            self.assertEqual(state["player"]["gold"], 4)
            self.assertEqual(state["player"]["combat"], 0)
            pile = state["market"]["fireGemsRemaining"]
            state = post("sacrifice-played", {"cardId": FIRE_GEM.id})
            self.assertEqual(state["player"]["combat"], 3)
            self.assertEqual(state["market"]["fireGemsRemaining"], pile + 1)
            self.assertEqual(len(state["player"]["playedThisTurn"]), 1)
            self.assertEqual(state["player"]["banishCount"], 0)
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            game_store.delete_bot_session(s.session_id)
            SESSION_LOCKS.pop(s.session_id, None)
