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


def join_game(game_id: str, guest_id: str) -> None:
    db.execute(
        f"UPDATE games SET guest_id = {db.PH}, status = 'playing', "
        f"updated_at = {db.PH} WHERE id = {db.PH}",
        (guest_id, db.now(), game_id),
    )


def finish_game(game_id: str) -> None:
    db.execute(
        f"UPDATE games SET status = 'finished', updated_at = {db.PH} WHERE id = {db.PH}",
        (db.now(), game_id),
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
