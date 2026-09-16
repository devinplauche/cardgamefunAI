"""Account management: pbkdf2 password hashing (stdlib only) and token sessions."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid

from web import db

_ITERATIONS = 210_000
_TOKEN_TTL = 30 * 24 * 3600  # 30 days
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{2,64}$")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, digest_hex = stored.split("$")
        assert algo == "pbkdf2_sha256"
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
    except Exception:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def valid_username(username: str) -> bool:
    return bool(_USERNAME_RE.match(username or ""))


def create_user(username: str, password: str) -> dict:
    if not valid_username(username):
        raise ValueError("Username must be 2-64 characters: letters, numbers, _, -, . or @.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    if db.query_one(
        f"SELECT id FROM users WHERE lower(username) = lower({db.PH})", (username,)
    ):
        raise ValueError("That username is taken.")
    user_id = uuid.uuid4().hex
    db.execute(
        f"INSERT INTO users (id, username, password_hash, created_at) "
        f"VALUES ({db.PH}, {db.PH}, {db.PH}, {db.PH})",
        (user_id, username, hash_password(password), db.now()),
    )
    return {"id": user_id, "username": username}


def find_by_username(username: str) -> dict | None:
    return db.query_one(
        f"SELECT id, username, password_hash FROM users WHERE lower(username) = lower({db.PH})",
        (username,),
    )


def public_user(user_id: str) -> dict | None:
    row = db.query_one(
        f"SELECT id, username FROM users WHERE id = {db.PH}", (user_id,)
    )
    return dict(row) if row else None


def create_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    db.execute(
        f"INSERT INTO auth_tokens (token, user_id, expires_at) "
        f"VALUES ({db.PH}, {db.PH}, {db.PH})",
        (token, user_id, db.now() + _TOKEN_TTL),
    )
    return token


def user_for_token(token: str) -> dict | None:
    if not token:
        return None
    row = db.query_one(
        f"SELECT user_id, expires_at FROM auth_tokens WHERE token = {db.PH}", (token,)
    )
    if not row:
        return None
    if row["expires_at"] < db.now():
        db.execute(f"DELETE FROM auth_tokens WHERE token = {db.PH}", (token,))
        return None
    return public_user(row["user_id"])


def delete_token(token: str) -> None:
    db.execute(f"DELETE FROM auth_tokens WHERE token = {db.PH}", (token,))
