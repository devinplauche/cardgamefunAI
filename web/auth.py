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


def find_by_google_sub(google_sub: str) -> dict | None:
    return db.query_one(
        f"SELECT id, username FROM users WHERE google_sub = {db.PH}", (google_sub,)
    )


def link_google_sub(user_id: str, google_sub: str) -> None:
    db.execute(
        f"UPDATE users SET google_sub = {db.PH} WHERE id = {db.PH}",
        (google_sub, user_id),
    )


def create_google_user(google_sub: str, email: str, name: str) -> dict:
    """Create an account for a Google sign-in. The email is verified by Google
    (the caller must check the email_verified claim), so it is safe to link a
    pre-existing password account whose username is that email."""
    existing = find_by_google_sub(google_sub)
    if existing:
        return {"id": existing["id"], "username": existing["username"]}
    if email:
        by_email = find_by_username(email)
        if by_email:
            link_google_sub(by_email["id"], google_sub)
            return {"id": by_email["id"], "username": by_email["username"]}
    base = (email or "").split("@")[0].strip() or (name or "player").strip()
    base = re.sub(r"[^A-Za-z0-9_.@-]", "", base)[:32] or "player"
    username = base
    suffix = 0
    while find_by_username(username):
        suffix += 1
        username = f"{base[:28]}-{suffix}"
    user_id = uuid.uuid4().hex
    # Unusable password hash: Google-only accounts can never password-login.
    db.execute(
        f"INSERT INTO users (id, username, password_hash, google_sub, created_at) "
        f"VALUES ({db.PH}, {db.PH}, {db.PH}, {db.PH}, {db.PH})",
        (user_id, username, "google-oauth$" + secrets.token_hex(16), google_sub, db.now()),
    )
    return {"id": user_id, "username": username}


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
