"""SQLite/PostgreSQL persistence for accounts and multiplayer games.

DATABASE_URL set to a postgres:// URL uses PostgreSQL (psycopg); otherwise a
local SQLite file is used, which keeps local dev and tests dependency-free.
PostgreSQL uses BYTEA for the session blob where SQLite uses BLOB.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SQLITE_PATH = REPO_ROOT / "web" / "data" / "app.db"


def is_postgres() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    return url.startswith(("postgres://", "postgresql://"))


#: Parameter placeholder style: psycopg wants %s, sqlite3 wants ?.
PH = "%s" if is_postgres() else "?"


def connect():
    if is_postgres():
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "DATABASE_URL is set but psycopg is not installed; "
                "pip install 'psycopg[binary]'"
            ) from exc
        return psycopg.connect(os.environ["DATABASE_URL"])
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    # Lag fix (2026-09-17): every bot tap commits 2-3 times, and on Cloud
    # Run's overlayfs each fsync costs ~50-150ms, which stacked up to the
    # ~300-500ms players felt on every tap. WAL + synchronous=NORMAL cuts
    # the fsyncs per commit without risking corruption (a crash can only
    # lose the tail transaction, which the client retries idempotently).
    # journal_mode is sticky per database file; setting it here is cheap
    # and keeps fresh dev/test databases identical to production.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


#: Session blob column type: PostgreSQL has no BLOB type, so use BYTEA there.
SESSION_TYPE = "BYTEA" if is_postgres() else "BLOB"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    google_sub TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    invite_code TEXT UNIQUE NOT NULL,
    host_id TEXT NOT NULL REFERENCES users(id),
    guest_id TEXT REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'waiting',
    turn_count INTEGER NOT NULL DEFAULT 0,
    session {SESSION_TYPE} NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_sessions (
    session_id TEXT PRIMARY KEY,
    state {SESSION_TYPE} NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency_keys (
    scope_id TEXT NOT NULL,
    idem_key TEXT NOT NULL,
    response TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (scope_id, idem_key)
);
"""


def init_schema() -> None:
    conn = connect()
    try:
        # sqlite3 has executescript; psycopg does not, so split manually.
        for stmt in [s for s in SCHEMA.split(";") if s.strip()]:
            conn.execute(stmt)
        # Migration for databases created before the Google sign-in column.
        # (SQLite cannot ADD a UNIQUE column, so the uniqueness comes from
        # the index below on both engines.)
        try:
            conn.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")
        except Exception as exc:  # noqa: BLE001
            if "duplicate" not in str(exc).lower() and "already exists" not in str(exc).lower():
                raise
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS users_google_sub ON users (google_sub)"
        )
        conn.commit()
    finally:
        conn.close()


def now() -> float:
    return time.time()


def _rows(conn, query, params=()):
    cur = conn.execute(query, params)
    cols = [d[0] for d in cur.description] if cur.description else []
    if is_postgres():
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    return [dict(row) for row in cur.fetchall()]


def query_all(query: str, params=()):
    conn = connect()
    try:
        return _rows(conn, query, params)
    finally:
        conn.close()


def query_one(query: str, params=()):
    rows = query_all(query, params)
    return rows[0] if rows else None


def execute(query: str, params=()) -> int:
    """Run an INSERT/UPDATE/DELETE; returns affected row count."""
    conn = connect()
    try:
        cur = conn.execute(query, params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


#: How long an idempotency record is honored: a retried mutation replays the
#: cached JSON response instead of re-running for ~24h.
IDEMPOTENCY_TTL = 24 * 3600


def idempotency_get(scope_id: str, key: str) -> str | None:
    """Return the cached JSON response body for a (scope, key) pair.

    Returns None when the key was never seen for this scope, or when the
    record is older than IDEMPOTENCY_TTL (a stale record is simply replaced
    on the next save).
    """
    row = query_one(
        f"SELECT response, created_at FROM idempotency_keys "
        f"WHERE scope_id = {PH} AND idem_key = {PH}",
        (scope_id, key),
    )
    if row is None:
        return None
    if now() - row["created_at"] > IDEMPOTENCY_TTL:
        return None
    return row["response"]


def idempotency_put(scope_id: str, key: str, response: str) -> None:
    """Cache the JSON response body under (scope, key).

    Upserts, so a (scope, key) pair keeps only its latest response.
    Stale rows are swept by cleanup_idempotency_keys(), which runs on the
    same rare cadence as cleanup_bot_sessions - sweeping them here used to
    add a full-table DELETE to every single mutation, which was a
    measurable part of the per-tap lag on Cloud Run's slow filesystem.
    """
    ts = now()
    conn = connect()
    try:
        if is_postgres():
            conn.execute(
                "INSERT INTO idempotency_keys (scope_id, idem_key, response, created_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (scope_id, idem_key) DO UPDATE SET "
                "response = EXCLUDED.response, created_at = EXCLUDED.created_at",
                (scope_id, key, response, ts),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO idempotency_keys "
                "(scope_id, idem_key, response, created_at) VALUES (?, ?, ?, ?)",
                (scope_id, key, response, ts),
            )
        conn.commit()
    finally:
        conn.close()


def cleanup_idempotency_keys(max_age_seconds: float = IDEMPOTENCY_TTL) -> int:
    """Delete idempotency rows older than the TTL; returns the row count."""
    cutoff = now() - max_age_seconds
    return execute(
        f"DELETE FROM idempotency_keys WHERE created_at < {PH}",
        (cutoff,),
    )
