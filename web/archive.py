"""Nightly archive of finished/abandoned games to Google Cloud Storage.

Bot matches live in the ``bot_sessions`` table only until the 7-day TTL
cleanup deletes them; multiplayer games live in ``games`` indefinitely but
still cost database storage. This module snapshots either kind as a readable
JSON document in a GCS bucket so old games survive the TTL sweep (bot
sessions) without growing the database.

Only bot_sessions rows are ever deleted here, and only after a successful
upload. Multiplayer game rows are never deleted - the app keeps serving
them; the archive is just a second copy.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from web import auth as auth_store
from web import db
from web import games as game_store

SNAPSHOT_VERSION = 1

#: Mirrors the TTL in games.cleanup_bot_sessions (max_age_days=7): bot
#: sessions untouched this long are archived, then deleted.
BOT_SESSION_TTL_DAYS = 7


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _full_state(session) -> dict:
    """Complete final state with BOTH players' hands visible.

    session.get_state() hides the bot seat's hand - it is the opponent's
    private zone while the game is live. The archive is written once the
    game is over (or abandoned), so merge the bot's hand in from the
    guest-seat view, which reveals it under the "player" key.
    """
    state = session.get_state()
    guest_view = session.get_state(for_side="bot")
    state["bot"]["hand"] = guest_view["player"]["hand"]
    return state


def build_bot_snapshot(session) -> dict:
    """JSON-serializable snapshot of one bot match (finished or abandoned)."""
    return {
        "version": SNAPSHOT_VERSION,
        "kind": "bot",
        "session_id": session.session_id,
        "seed": getattr(session, "seed", None),
        "archived_at": _utc_now_iso(),
        "winner": session.winner,
        "final_state": _full_state(session),
        "history": getattr(session, "history", None),
    }


def build_game_snapshot(game: dict) -> dict:
    """JSON-serializable snapshot of one multiplayer game row.

    ``game`` is a row dict from game_store.get_game (with a deserialized
    ``session``). Usernames are resolved for readability; the game is over,
    so the full state (both hands) is archived.
    """
    session = game["session"]
    host = auth_store.public_user(game["host_id"]) or {}
    guest = auth_store.public_user(game["guest_id"]) if game.get("guest_id") else None
    return {
        "version": SNAPSHOT_VERSION,
        "kind": "multiplayer",
        "game_id": game["id"],
        "invite_code": game["invite_code"],
        "status": game["status"],
        "turn_count": game["turn_count"],
        "archived_at": _utc_now_iso(),
        "host": host.get("username"),
        "guest": (guest or {}).get("username"),
        "winner": session.winner,
        "final_state": _full_state(session),
        "history": getattr(session, "history", None),
    }


def bucket_name() -> str | None:
    """Archive bucket from the environment; None means archiving is off."""
    return os.environ.get("HR_ARCHIVE_BUCKET") or None


def upload_json(object_name: str, payload: dict) -> str | None:
    """Upload ``payload`` as JSON to the archive bucket; return its gs:// path.

    No-op (returns None) when HR_ARCHIVE_BUCKET is unset, so local dev and
    tests never touch GCS. Storage errors propagate - the sweep catches them
    per row and keeps the database row for a later attempt.
    """
    bucket = bucket_name()
    if not bucket:
        return None
    # Lazy import: google-cloud-storage is a deploy dependency, not needed to
    # import this module (tests, research harnesses).
    from google.cloud import storage

    blob = storage.Client().bucket(bucket).blob(object_name)
    blob.upload_from_string(
        json.dumps(payload, ensure_ascii=False), content_type="application/json"
    )
    return f"gs://{bucket}/{object_name}"


def sweep(now: float | None = None) -> dict:
    """Archive stale bot sessions and finished games; return counts.

    Bot sessions untouched for BOT_SESSION_TTL_DAYS are uploaded, then
    deleted from the database - but ONLY after a successful upload. An unset
    bucket (upload returns None) counts as "not archived": the row is kept.
    Finished multiplayer games are uploaded (idempotent overwrite) and their
    rows are never deleted. A row that fails at any step is logged, skipped,
    and retried on the next sweep.
    """
    current = time.time() if now is None else now
    cutoff = current - BOT_SESSION_TTL_DAYS * 24 * 3600
    result = {"bot_archived": 0, "bot_deleted": 0, "games_archived": 0}

    stale = db.query_all(
        f"SELECT session_id FROM bot_sessions WHERE updated_at < {db.PH}",
        (cutoff,),
    )
    for row in stale:
        session_id = row["session_id"]
        try:
            session = game_store.get_bot_session(session_id)
            if session is None:
                continue
            path = upload_json(
                f"archives/bot/{session_id}.json", build_bot_snapshot(session)
            )
            if path is None:
                continue  # no bucket configured; keep the row
            result["bot_archived"] += 1
            game_store.delete_bot_session(session_id)
            result["bot_deleted"] += 1
        except Exception as exc:  # noqa: BLE001
            print(f"archive: skipping bot session {session_id}: {exc}")

    finished = db.query_all(
        f"SELECT id FROM games WHERE status = {db.PH}", ("finished",)
    )
    for row in finished:
        game_id = row["id"]
        try:
            game = game_store.get_game(game_id)
            if game is None:
                continue
            path = upload_json(
                f"archives/games/{game_id}.json", build_game_snapshot(game)
            )
            if path is None:
                continue  # no bucket configured; retry on a later sweep
            result["games_archived"] += 1
        except Exception as exc:  # noqa: BLE001
            print(f"archive: skipping game {game_id}: {exc}")

    return result
