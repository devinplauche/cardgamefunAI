import io
import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

from web.backend import Handler, SESSION_LOCKS
from web import db as db_store
from web import games as game_store
from web.session import create_session


class BotStreamTests(unittest.TestCase):
    def test_observer_preserves_turn_and_does_not_reveal_hand(self):
        for seed in (7, 19, 41):
            with self.subTest(seed=seed):
                control = create_session(seed=seed, algorithm="heuristic")
                streamed = create_session(seed=seed, algorithm="heuristic")
                control.end_turn()
                streamed.end_turn()
                frames = []
                expected = control.run_bot_turn()
                actual = streamed.run_bot_turn(on_event=frames.append)
                self.assertGreater(len(frames), 2)
                self.assertEqual(len({f["id"] for f in frames}), len(frames))
                self.assertTrue(all(f["state"]["bot"]["hand"] == [] for f in frames))
                for key in ("player", "bot", "market", "activePlayer", "phase", "winner", "turnNumber"):
                    self.assertEqual(expected[key], actual[key], key)
                self.assertIsNone(streamed._event_listener)

    def test_simulations_never_emit_live_events(self):
        session = create_session(seed=7)
        session._event_listener = Mock()
        clone = session.clone()
        clone.record_event("play", "Simulated play")
        session._event_listener.assert_not_called()
        self.assertIsNone(clone._event_listener)

    def test_http_flushes_before_turn_finishes_and_rejects_concurrent_mutation(self):
        db_store.init_schema()
        session = create_session(seed=7, algorithm="heuristic")
        session.end_turn()
        game_store.create_bot_session(session)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        release = threading.Event()
        finished = threading.Event()

        def slow_turn(current, **kwargs):
            current.record_event("play", "First visible action")
            if not release.wait(5):
                raise TimeoutError("Test did not receive a flushed frame")
            current.end_turn()
            finished.set()
            return {"algorithm": "heuristic"}

        connection = HTTPConnection(*server.server_address, timeout=5)
        other = HTTPConnection(*server.server_address, timeout=5)
        try:
            with patch("web.bot.run_bot_turn", side_effect=slow_turn):
                connection.request("POST", f"/api/sessions/{session.session_id}/bot-turn-stream", "{}")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                first = json.loads(response.readline())
                self.assertEqual(first["frame"]["label"], "First visible action")
                self.assertFalse(finished.is_set())
                other.request("POST", f"/api/sessions/{session.session_id}/end-turn", "{}")
                conflict = other.getresponse()
                self.assertEqual(conflict.status, 409)
                conflict.read()
                other.request("GET", f"/api/sessions/{session.session_id}")
                reading = other.getresponse()
                self.assertEqual(reading.status, 409)
                reading.read()
                release.set()
                events = [json.loads(line) for line in response.read().splitlines()]
                self.assertEqual(events[-1]["type"], "complete")
                self.assertEqual(events[-1]["state"]["activePlayer"], "player")
                self.assertFalse(SESSION_LOCKS[session.session_id].locked())
        finally:
            release.set()
            connection.close()
            other.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            game_store.delete_bot_session(session.session_id)
            SESSION_LOCKS.pop(session.session_id, None)

    def make_handler(self):
        handler = object.__new__(Handler)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = io.BytesIO()
        return handler

    def test_disconnect_finishes_turn_and_clears_observer(self):
        session = create_session(seed=7, algorithm="heuristic")
        session.end_turn()
        handler = self.make_handler()
        handler.wfile = Mock()
        handler.wfile.write.side_effect = BrokenPipeError()
        handler._stream_bot_turn(session)
        self.assertEqual(session.active_player, "player")
        self.assertIsNone(session._event_listener)
        self.assertEqual(handler.wfile.write.call_count, 1)

    def test_failure_emits_recoverable_state_and_clears_observer(self):
        session = create_session(seed=7)
        session.end_turn()
        handler = self.make_handler()
        with patch("web.bot.run_bot_turn", side_effect=ValueError("Search failed")):
            handler._stream_bot_turn(session)
        error = json.loads(handler.wfile.getvalue())
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["error"], "Search failed")
        self.assertEqual(error["state"]["sessionId"], session.session_id)
        self.assertIsNone(session._event_listener)
