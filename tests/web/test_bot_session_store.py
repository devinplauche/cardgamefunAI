"""Bot-match sessions persist in the database, not in process memory.

A Cloud Run deploy wipes the server process, so the database is the only
state that survives a restart. These tests pin that contract: a session
must round-trip through bot_sessions with no in-memory dict to lean on,
unknown ids must read back as None, and TTL cleanup must only reap stale
rows. An HTTP-level test proves a mutation survives across requests.
"""
import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from web import db as db_store
from web import games as game_store
from web.backend import Handler
from web.session import create_session


class BotSessionStoreTests(unittest.TestCase):
    def setUp(self):
        db_store.init_schema()
        self._session_ids = []

    def tearDown(self):
        for session_id in self._session_ids:
            game_store.delete_bot_session(session_id)

    def _track(self, session):
        self._session_ids.append(session.session_id)
        return session

    def test_bot_session_round_trip(self):
        session = self._track(create_session(seed=11))
        game_store.create_bot_session(session)

        loaded = game_store.get_bot_session(session.session_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.get_state()["sessionId"], session.session_id)
        self.assertEqual(loaded.get_state()["turnNumber"], session.get_state()["turnNumber"])

        # Mutate through the session API, save, and load fresh: the mutation
        # must survive with no in-memory state left to lean on.
        loaded.player.gold = 99
        game_store.save_bot_session(loaded)
        fresh = game_store.get_bot_session(session.session_id)
        self.assertEqual(fresh.player.gold, 99)
        self.assertEqual(fresh.get_state()["player"]["gold"], 99)

    def test_bot_session_unknown_id_returns_none(self):
        self.assertIsNone(game_store.get_bot_session("no-such-session"))

    def test_cleanup_bot_sessions(self):
        old = self._track(create_session(seed=21))
        new = self._track(create_session(seed=22))
        game_store.create_bot_session(old)
        game_store.create_bot_session(new)
        # Backdate the old row past the TTL.
        stale_at = db_store.now() - 8 * 24 * 3600
        db_store.execute(
            f"UPDATE bot_sessions SET updated_at = {db_store.PH} "
            f"WHERE session_id = {db_store.PH}",
            (stale_at, old.session_id),
        )
        deleted = game_store.cleanup_bot_sessions(max_age_days=7)
        self.assertGreaterEqual(deleted, 1)
        self.assertIsNone(game_store.get_bot_session(old.session_id))
        self.assertIsNotNone(game_store.get_bot_session(new.session_id))

    def test_http_mutation_persists_across_requests(self):
        # With the DB store there is no process dict to clear: the "restart"
        # is simply a later request, and it must see the earlier mutation.
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = HTTPConnection(*server.server_address, timeout=10)
        try:
            conn.request("POST", "/api/sessions", json.dumps({"seed": 33}))
            response = conn.getresponse()
            created = json.loads(response.read())
            self.assertEqual(response.status, 200, created)
            session_id = created["sessionId"]
            self._session_ids.append(session_id)

            self.assertIsNotNone(game_store.get_bot_session(session_id))

            conn.request("POST", f"/api/sessions/{session_id}/end-turn", "{}")
            response = conn.getresponse()
            after = json.loads(response.read())
            self.assertEqual(response.status, 200, after)
            self.assertEqual(after["activePlayer"], "bot")

            reloaded = game_store.get_bot_session(session_id)
            self.assertEqual(reloaded.get_state()["activePlayer"], "bot")

            conn.request("GET", "/api/sessions/does-not-exist")
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 404)
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
