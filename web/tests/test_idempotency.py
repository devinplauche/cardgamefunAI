"""Idempotency-key safe retry for backend mutations.

Spins up the real HTTP backend (web.backend.Handler) against a throwaway
SQLite database and proves the double-delivery contract: sending the same
``X-Idempotency-Key`` twice applies the mutation exactly once and returns
byte-identical responses.
"""

import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

# HR_DEBUG_SETUP is read by web.backend at import time; it unlocks the
# debug-setup route used here to rig a deterministic hand.
os.environ["HR_DEBUG_SETUP"] = "1"

from web import backend as backend_mod  # noqa: E402
from web import db as db_store  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Throwaway SQLite database for the backend under test."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db_store, "SQLITE_PATH", tmp_path / "test.db")
    assert not db_store.is_postgres()
    db_store.init_schema()
    return db_store


@pytest.fixture()
def base_url(db):
    """Live backend on an ephemeral port, torn down after the test."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), backend_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _post(base_url, path, body, idem_key=None):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base_url + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if idem_key:
        req.add_header("X-Idempotency-Key", idem_key)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _new_session(base_url, seed=7):
    status, body = _post(base_url, "/api/sessions", {"seed": seed})
    assert status == 200, body
    return json.loads(body)["sessionId"]


def _rig_golds(base_url, session_id, count=4):
    status, body = _post(
        base_url,
        f"/api/sessions/{session_id}/debug-setup",
        {"hand": ["Gold"] * count, "gold": 0},
    )
    assert status == 200, body
    hand = json.loads(body)["player"]["hand"]
    gold_id = next(card["id"] for card in hand if card["name"] == "Gold")
    return gold_id


def test_double_delivery_applies_mutation_once(base_url):
    """Same idempotency key twice: one mutation, identical responses."""
    session_id = _new_session(base_url)
    gold_id = _rig_golds(base_url, session_id)
    route = f"/api/sessions/{session_id}/play-card"

    status1, body1 = _post(base_url, route, {"cardId": gold_id}, "key-abc")
    status2, body2 = _post(base_url, route, {"cardId": gold_id}, "key-abc")

    assert status1 == 200, body1
    assert status2 == 200, body2
    assert body1 == body2, "retried delivery must replay the exact response"
    assert json.loads(body1)["player"]["gold"] == 1, "mutation applied exactly once"

    # A fresh key is a fresh mutation.
    status3, body3 = _post(base_url, route, {"cardId": gold_id}, "key-def")
    assert status3 == 200, body3
    assert json.loads(body3)["player"]["gold"] == 2
    assert body3 != body1

    # No key at all: no dedup, each delivery applies.
    status4, body4 = _post(base_url, route, {"cardId": gold_id})
    status5, body5 = _post(base_url, route, {"cardId": gold_id})
    assert status4 == 200 and status5 == 200
    assert json.loads(body4)["player"]["gold"] == 3
    assert json.loads(body5)["player"]["gold"] == 4


def test_failed_mutation_is_not_cached(base_url):
    """A 400 is never cached: fixing the request and retrying runs it."""
    session_id = _new_session(base_url)
    route = f"/api/sessions/{session_id}/play-card"

    status1, _ = _post(base_url, route, {"cardId": "no-such-card"}, "key-fail")
    assert status1 == 400

    gold_id = _rig_golds(base_url, session_id, count=1)
    status2, body2 = _post(base_url, route, {"cardId": gold_id}, "key-fail")
    assert status2 == 200, body2
    assert json.loads(body2)["player"]["gold"] == 1


def test_idempotency_store_roundtrip(db):
    assert db.idempotency_get("scope-1", "k1") is None

    db.idempotency_put("scope-1", "k1", '{"ok":true}')
    assert db.idempotency_get("scope-1", "k1") == '{"ok":true}'

    # Scopes do not collide.
    assert db.idempotency_get("scope-2", "k1") is None
    db.idempotency_put("scope-2", "k1", '{"ok":"other"}')
    assert db.idempotency_get("scope-1", "k1") == '{"ok":true}'
    assert db.idempotency_get("scope-2", "k1") == '{"ok":"other"}'

    # Re-saving under the same key keeps only the latest response.
    db.idempotency_put("scope-1", "k1", '{"ok":false}')
    assert db.idempotency_get("scope-1", "k1") == '{"ok":false}'


def test_idempotency_ttl_expiry_and_cleanup(db):
    stale = db.now() - db.IDEMPOTENCY_TTL - 10
    db.execute(
        f"INSERT INTO idempotency_keys (scope_id, idem_key, response, created_at) "
        f"VALUES ({db.PH}, {db.PH}, {db.PH}, {db.PH})",
        ("scope-old", "k", "{}", stale),
    )
    # A stale record is treated as a miss...
    assert db.idempotency_get("scope-old", "k") is None
    # ...and a plain save no longer sweeps it (that sweep cost a DELETE on
    # every mutation, part of the per-tap lag). The periodic cleanup does.
    db.idempotency_put("scope-new", "k", "{}")
    assert (
        db.query_one(
            f"SELECT * FROM idempotency_keys WHERE scope_id = {db.PH}",
            ("scope-old",),
        )
        is not None
    )
    assert db.cleanup_idempotency_keys() == 1
    assert (
        db.query_one(
            f"SELECT * FROM idempotency_keys WHERE scope_id = {db.PH}",
            ("scope-old",),
        )
        is None
    )
    # Fresh rows survive the sweep.
    assert db.idempotency_get("scope-new", "k") == "{}"


def test_sqlite_pragmas_cut_fsyncs(db):
    """WAL + synchronous=NORMAL is what makes the per-tap commits cheap."""
    conn = db.connect()
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal", mode
    assert sync == 1, f"synchronous=NORMAL is 1, got {sync}"


def test_cleanup_keeps_fresh_rows(db):
    db.idempotency_put("scope-fresh", "k", '{"ok":true}')
    assert db.cleanup_idempotency_keys() == 0
    assert db.idempotency_get("scope-fresh", "k") == '{"ok":true}'
