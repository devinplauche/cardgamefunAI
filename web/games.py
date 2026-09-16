"""Multiplayer game persistence: pickled GameSession rows plus invite codes."""

from __future__ import annotations

import pickle
import secrets
import string
import uuid

from web import auth, db

_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no lookalikes


def _new_code() -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not db.query_one(
            f"SELECT id FROM games WHERE invite_code = {db.PH}", (code,)
        ):
            return code
    raise RuntimeError("could not mint an invite code")


def _serialize(session) -> bytes:
    # Never persist a live event listener (unpicklable); human games never set
    # one, but a bot turn interrupted mid-stream could.
    session._event_listener = None
    return pickle.dumps(session, protocol=pickle.HIGHEST_PROTOCOL)


def _deserialize(blob: bytes):
    return pickle.loads(blob)


def create_game(host_id: str, session) -> dict:
    game_id = uuid.uuid4().hex
    code = _new_code()
    now = db.now()
    db.execute(
        f"INSERT INTO games (id, invite_code, host_id, guest_id, status, "
        f"turn_count, session, created_at, updated_at) VALUES "
        f"({db.PH}, {db.PH}, {db.PH}, {db.PH}, {db.PH}, {db.PH}, {db.PH}, {db.PH}, {db.PH})",
        (game_id, code, host_id, None, "waiting", 0, _serialize(session), now, now),
    )
    return {"id": game_id, "inviteCode": code}


def get_game(game_id: str) -> dict | None:
    row = db.query_one(f"SELECT * FROM games WHERE id = {db.PH}", (game_id,))
    if not row:
        return None
    row["session"] = _deserialize(bytes(row["session"]))
    return row


def get_by_code(code: str) -> dict | None:
    row = db.query_one(
        f"SELECT * FROM games WHERE invite_code = {db.PH}", (code.strip().upper(),)
    )
    if not row:
        return None
    row["session"] = _deserialize(bytes(row["session"]))
    return row


def save_game(game_id: str, session, bump_turn: bool = True) -> None:
    now = db.now()
    if bump_turn:
        db.execute(
            f"UPDATE games SET session = {db.PH}, turn_count = turn_count + 1, "
            f"updated_at = {db.PH} WHERE id = {db.PH}",
            (_serialize(session), now, game_id),
        )
    else:
        db.execute(
            f"UPDATE games SET session = {db.PH}, updated_at = {db.PH} WHERE id = {db.PH}",
            (_serialize(session), now, game_id),
        )


def join_game(game_id: str, guest_id: str, session) -> bool:
    """Atomically claim a waiting game for a guest.

    The conditional UPDATE makes the claim race-safe: two guests racing to
    join the same code cannot both succeed, since only one row transitions
    out of 'waiting'. Returns True when this caller won the game.
    """
    changed = db.execute(
        f"UPDATE games SET guest_id = {db.PH}, status = 'playing', "
        f"session = {db.PH}, updated_at = {db.PH} "
        f"WHERE id = {db.PH} AND status = 'waiting'",
        (guest_id, _serialize(session), db.now(), game_id),
    )
    return changed == 1


def finish_game(game_id: str) -> None:
    db.execute(
        f"UPDATE games SET status = 'finished', updated_at = {db.PH} WHERE id = {db.PH}",
        (db.now(), game_id),
    )


# ---- bot-match sessions -------------------------------------------------
# Bot games live here (pickled GameSession rows keyed by session id) instead
# of an in-memory dict, so a server restart or deploy cannot wipe a live
# match: every request loads the session fresh from the database and saves
# it back after mutating it.


def create_bot_session(session) -> None:
    now = db.now()
    db.execute(
        f"INSERT INTO bot_sessions (session_id, state, created_at, updated_at) "
        f"VALUES ({db.PH}, {db.PH}, {db.PH}, {db.PH})",
        (session.session_id, _serialize(session), now, now),
    )


def get_bot_session(session_id: str):
    row = db.query_one(
        f"SELECT * FROM bot_sessions WHERE session_id = {db.PH}", (session_id,)
    )
    if not row:
        return None
    return _deserialize(bytes(row["state"]))


def save_bot_session(session) -> None:
    now = db.now()
    changed = db.execute(
        f"UPDATE bot_sessions SET state = {db.PH}, updated_at = {db.PH} "
        f"WHERE session_id = {db.PH}",
        (_serialize(session), now, session.session_id),
    )
    if changed == 0:
        db.execute(
            f"INSERT INTO bot_sessions (session_id, state, created_at, updated_at) "
            f"VALUES ({db.PH}, {db.PH}, {db.PH}, {db.PH})",
            (session.session_id, _serialize(session), now, now),
        )


def delete_bot_session(session_id: str) -> None:
    db.execute(f"DELETE FROM bot_sessions WHERE session_id = {db.PH}", (session_id,))


def cleanup_bot_sessions(max_age_days: float = 7) -> int:
    """Delete bot sessions untouched for longer than the TTL; returns count."""
    cutoff = db.now() - max_age_days * 24 * 3600
    return db.execute(
        f"DELETE FROM bot_sessions WHERE updated_at < {db.PH}", (cutoff,)
    )


def participant_side(game: dict, user_id: str) -> str | None:
    """Engine side ('player' = host, 'bot' = guest) for this user, if any."""
    if user_id == game["host_id"]:
        return "player"
    if game["guest_id"] and user_id == game["guest_id"]:
        return "bot"
    return None


def list_for_user(user_id: str) -> list[dict]:
    rows = db.query_all(
        f"SELECT id, invite_code, host_id, guest_id, status, turn_count, updated_at "
        f"FROM games WHERE host_id = {db.PH} OR guest_id = {db.PH} "
        f"ORDER BY updated_at DESC",
        (user_id, user_id),
    )
    out = []
    for row in rows:
        opponent_id = row["guest_id"] if row["host_id"] == user_id else row["host_id"]
        opponent = auth.public_user(opponent_id) if opponent_id else None
        out.append(
            {
                "id": row["id"],
                "inviteCode": row["invite_code"],
                "status": row["status"],
                "opponent": opponent["username"] if opponent else None,
                "updatedAt": row["updated_at"],
            }
        )
    return out
