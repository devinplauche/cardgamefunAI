"""Nightly GCS archive: snapshots, sweep, and the admin endpoint.

Finished/abandoned games are snapshotted as readable JSON and uploaded to
Google Cloud Storage. Bot sessions are deleted from the database only after
a successful upload; multiplayer game rows are never deleted.
"""
import json
import os
import threading
import unittest
import uuid
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from web import archive
from web import auth as auth_store
from web import db as db_store
from web import games as game_store
from web.backend import Handler
from web.session import create_session


def _backdate_bot_session(session_id: str, days: float) -> None:
    db_store.execute(
        f"UPDATE bot_sessions SET updated_at = {db_store.PH} "
        f"WHERE session_id = {db_store.PH}",
        (db_store.now() - days * 24 * 3600, session_id),
    )


class SnapshotTests(unittest.TestCase):
    def test_bot_snapshot_is_strictly_json(self):
        session = create_session(seed=3)
        session.winner = "player"
        snap = archive.build_bot_snapshot(session)
        json.dumps(snap)  # must not raise
        self.assertEqual(snap["version"], 1)
        self.assertEqual(snap["kind"], "bot")
        self.assertEqual(snap["session_id"], session.session_id)
        self.assertEqual(snap["seed"], 3)
        self.assertEqual(snap["winner"], "player")
        self.assertIn("archived_at", snap)
        self.assertIn("final_state", snap)
        self.assertIn("history", snap)
        # The archive shows both hands; the live API hides the bot's.
        self.assertTrue(snap["final_state"]["player"]["hand"])
        self.assertTrue(snap["final_state"]["bot"]["hand"])
        live = session.get_state()
        self.assertEqual(live["bot"]["hand"], [])

    def test_game_snapshot_is_strictly_json(self):
        db_store.init_schema()
        username = f"archiveuser_{uuid.uuid4().hex[:8]}"
        user = auth_store.create_user(username, "archive-pw-1")
        try:
            session = create_session(bot_is_human=True)
            session.winner = "bot"
            created = game_store.create_game(user["id"], session)
            try:
                game = game_store.get_game(created["id"])
                snap = archive.build_game_snapshot(game)
                json.dumps(snap)  # must not raise
                self.assertEqual(snap["version"], 1)
                self.assertEqual(snap["kind"], "multiplayer")
                self.assertEqual(snap["game_id"], created["id"])
                self.assertEqual(snap["invite_code"], created["inviteCode"])
                self.assertEqual(snap["host"], username)
                self.assertIsNone(snap["guest"])
                self.assertEqual(snap["winner"], "bot")
                self.assertTrue(snap["final_state"]["bot"]["hand"])
            finally:
                db_store.execute(
                    f"DELETE FROM games WHERE id = {db_store.PH}",
                    (created["id"],),
                )
        finally:
            db_store.execute(
                f"DELETE FROM users WHERE id = {db_store.PH}", (user["id"],)
            )


class SweepTests(unittest.TestCase):
    def setUp(self):
        db_store.init_schema()
        self._session_ids = []
        self._game_ids = []
        self.uploaded = {}
        self._real_upload = archive.upload_json

        def fake_upload(object_name, payload):
            json.dumps(payload)  # snapshots must stay strictly JSON
            self.uploaded[object_name] = payload
            return f"gs://test-bucket/{object_name}"

        archive.upload_json = fake_upload

    def tearDown(self):
        archive.upload_json = self._real_upload
        for session_id in self._session_ids:
            game_store.delete_bot_session(session_id)
        for game_id in self._game_ids:
            db_store.execute(
                f"DELETE FROM games WHERE id = {db_store.PH}", (game_id,)
            )

    def _track_bot(self, session):
        game_store.create_bot_session(session)
        self._session_ids.append(session.session_id)
        return session

    def _track_game(self, status="waiting"):
        session = create_session(bot_is_human=True)
        created = game_store.create_game("archive-host", session)
        self._game_ids.append(created["id"])
        if status != "waiting":
            db_store.execute(
                f"UPDATE games SET status = {db_store.PH} WHERE id = {db_store.PH}",
                (status, created["id"]),
            )
        return created["id"]

    def test_stale_bot_session_archived_then_deleted(self):
        session = self._track_bot(create_session(seed=31))
        _backdate_bot_session(session.session_id, days=8)

        result = archive.sweep()

        self.assertEqual(result["bot_archived"], 1)
        self.assertEqual(result["bot_deleted"], 1)
        self.assertIn(f"archives/bot/{session.session_id}.json", self.uploaded)
        snap = self.uploaded[f"archives/bot/{session.session_id}.json"]
        self.assertEqual(snap["kind"], "bot")
        self.assertIsNone(game_store.get_bot_session(session.session_id))
        self._session_ids.remove(session.session_id)  # already deleted

    def test_fresh_bot_session_untouched(self):
        session = self._track_bot(create_session(seed=32))

        result = archive.sweep()

        self.assertEqual(result["bot_archived"], 0)
        self.assertEqual(result["bot_deleted"], 0)
        self.assertEqual(self.uploaded, {})
        self.assertIsNotNone(game_store.get_bot_session(session.session_id))

    def test_finished_game_archived_and_row_kept(self):
        game_id = self._track_game(status="finished")

        result = archive.sweep()

        self.assertEqual(result["games_archived"], 1)
        self.assertIn(f"archives/games/{game_id}.json", self.uploaded)
        snap = self.uploaded[f"archives/games/{game_id}.json"]
        self.assertEqual(snap["kind"], "multiplayer")
        # The app keeps serving finished games; the archive is a second copy.
        self.assertIsNotNone(game_store.get_game(game_id))

    def test_unfinished_game_untouched(self):
        self._track_game(status="playing")

        result = archive.sweep()

        self.assertEqual(result["games_archived"], 0)
        self.assertEqual(self.uploaded, {})

    def test_upload_failure_keeps_bot_row(self):
        def boom(object_name, payload):
            raise RuntimeError("gcs is down")

        archive.upload_json = boom
        session = self._track_bot(create_session(seed=33))
        _backdate_bot_session(session.session_id, days=8)

        result = archive.sweep()

        self.assertEqual(result["bot_archived"], 0)
        self.assertEqual(result["bot_deleted"], 0)
        self.assertIsNotNone(game_store.get_bot_session(session.session_id))

    def test_no_bucket_configured_keeps_rows(self):
        archive.upload_json = self._real_upload  # real one, no env var set
        old = os.environ.pop("HR_ARCHIVE_BUCKET", None)
        try:
            session = self._track_bot(create_session(seed=34))
            _backdate_bot_session(session.session_id, days=8)
            game_id = self._track_game(status="finished")

            result = archive.sweep()

            self.assertEqual(
                result, {"bot_archived": 0, "bot_deleted": 0, "games_archived": 0}
            )
            self.assertIsNotNone(game_store.get_bot_session(session.session_id))
            self.assertIsNotNone(game_store.get_game(game_id))
        finally:
            if old is not None:
                os.environ["HR_ARCHIVE_BUCKET"] = old


class ArchiveEndpointTests(unittest.TestCase):
    def setUp(self):
        db_store.init_schema()
        self._old_secret = os.environ.get("HR_ARCHIVE_SECRET")
        os.environ["HR_ARCHIVE_SECRET"] = "test-secret"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self._old_secret is None:
            os.environ.pop("HR_ARCHIVE_SECRET", None)
        else:
            os.environ["HR_ARCHIVE_SECRET"] = self._old_secret

    def _post(self, secret=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {"Content-Type": "application/json"}
        if secret is not None:
            headers["X-Archive-Secret"] = secret
        conn.request("POST", "/api/admin/archive", body="{}", headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, json.loads(raw) if raw else {}

    def test_missing_secret_forbidden(self):
        status, body = self._post()
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "Forbidden")

    def test_wrong_secret_forbidden(self):
        status, _ = self._post("wrong")
        self.assertEqual(status, 403)

    def test_missing_env_secret_forbidden(self):
        os.environ.pop("HR_ARCHIVE_SECRET", None)
        try:
            status, _ = self._post("test-secret")
            self.assertEqual(status, 403)
        finally:
            os.environ["HR_ARCHIVE_SECRET"] = "test-secret"

    def test_correct_secret_runs_sweep(self):
        status, body = self._post("test-secret")
        self.assertEqual(status, 200)
        self.assertEqual(
            set(body), {"bot_archived", "bot_deleted", "games_archived"}
        )


if __name__ == "__main__":
    unittest.main()
