"""Performance SLO tests for the Hero Realms backend.

Measures p95/p99 latencies for key user-facing endpoints and asserts they
meet Service Level Objectives. Runs against a local backend with SQLite.

SLOs (generous for local SQLite; production with Neon should be similar
or better once connection pooling is in place):
- GET /api/health: p95 < 200ms, p99 < 500ms (static response, no DB)
- POST /api/sessions (create): p95 < 500ms, p99 < 1000ms (DB write)
- POST play-card: p95 < 800ms, p99 < 1500ms (DB read/write + game logic)

The play-card SLO is the user-facing pain point: on 2026-09-17 every tap
took 1s+ because each request opened 3-4 fresh Postgres handshakes to Neon.
A regression like that fails the p95 assertion here.

SLA: 100% of requests must succeed (no 5xx). Any failure raises.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

# HR_DEBUG_SETUP is read by web.backend at import time; it unlocks the
# debug-setup route used here to rig deterministic hands.
os.environ["HR_DEBUG_SETUP"] = "1"

from web import backend as backend_mod  # noqa: E402
from web import db as db_store  # noqa: E402


@pytest.fixture()
def base_url(tmp_path, monkeypatch):
    """Live backend on an ephemeral port with throwaway SQLite."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db_store, "SQLITE_PATH", tmp_path / "test.db")
    assert not db_store.is_postgres()
    db_store.init_schema()
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


def _request(base_url, path, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base_url + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.read()
    latency_ms = (time.perf_counter() - start) * 1000
    assert status == 200, f"{method} {path} returned {status}"
    return latency_ms


def _new_session(base_url):
    data = json.dumps({"seed": 7}).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/api/sessions",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 200
        return json.loads(resp.read())["sessionId"]


def _assert_slo(latencies, p95_max, p99_max, name):
    latencies.sort()
    n = len(latencies)
    p50 = latencies[n // 2]
    p95 = latencies[int(n * 0.95)]
    p99 = latencies[int(n * 0.99)]
    print(
        f"\n{name}: n={n} p50={p50:.1f}ms p95={p95:.1f}ms "
        f"p99={p99:.1f}ms max={latencies[-1]:.1f}ms"
    )
    assert p95 < p95_max, f"{name} p95 {p95:.1f}ms exceeds SLO {p95_max}ms"
    assert p99 < p99_max, f"{name} p99 {p99:.1f}ms exceeds SLO {p99_max}ms"


def test_health_slo(base_url):
    """GET /api/health: p95 < 200ms, p99 < 500ms."""
    latencies = [_request(base_url, "/api/health") for _ in range(50)]
    _assert_slo(latencies, 200, 500, "GET /api/health")


def test_create_session_slo(base_url):
    """POST /api/sessions: p95 < 500ms, p99 < 1000ms."""
    latencies = [
        _request(base_url, "/api/sessions", "POST", {"seed": i})
        for i in range(20)
    ]
    _assert_slo(latencies, 500, 1000, "POST /api/sessions")


def test_play_card_slo(base_url):
    """POST play-card: p95 < 800ms, p99 < 1500ms.

    Full user tap flow: create session, rig a Gold in hand, play it.
    """
    latencies = []
    for i in range(20):
        session_id = _new_session(base_url)
        # Rig a single Gold in hand so the play always succeeds.
        data = json.dumps({"hand": ["Gold"], "gold": 0}).encode("utf-8")
        req = urllib.request.Request(
            base_url + f"/api/sessions/{session_id}/debug-setup",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            rigged = json.loads(resp.read())
        hand = rigged["player"]["hand"]
        gold_id = next(c["id"] for c in hand if c["name"] == "Gold")
        lat = _request(
            base_url,
            f"/api/sessions/{session_id}/play-card",
            "POST",
            {"cardId": gold_id},
        )
        latencies.append(lat)
    _assert_slo(latencies, 800, 1500, "POST play-card")
