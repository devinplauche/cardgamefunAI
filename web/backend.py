from __future__ import annotations

import json
import os
import sys
import hmac
from collections import defaultdict
from threading import Lock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hero_engine import BoardChampion, DAGGER, FIRE_GEM, GOLD, RUBY, SHORTSWORD
from web import archive as archive_store
from web import auth as auth_store
from web import db as db_store
from web import games as game_store
from web.session import create_session


SESSION_LOCKS = defaultdict(Lock)
GAME_LOCKS = defaultdict(Lock)
# Single-step Undo: game_id -> pre-action snapshot dict (JSON-serializable).
# Set before each player mutation, cleared when the turn ends (end-turn
# commits the turn) and consumed by POST /api/games/<id>/undo.
UNDO_SNAPSHOTS: dict[str, dict] = {}
COOKIE_NAME = "hr_session"
REGISTER_ENABLED = os.environ.get("HR_REGISTER_ENABLED", "1") == "1"


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw) if raw else {}


def _session_or_404(session_id: str):
    # Bot sessions live in the database, not in process memory, so a server
    # restart or deploy cannot wipe a live match.
    session = game_store.get_bot_session(session_id)
    if session is None:
        return None, {"error": "Session not found"}
    return session, None


#: Opt-in, because it lets a caller rewrite any zone of a live game.
#: Start the backend with HR_DEBUG_SETUP=1 to enable it.
DEBUG_SETUP = os.environ.get("HR_DEBUG_SETUP") == "1"


def _debug_setup(session, body: dict) -> dict:
    """Deal a chosen position so a card's ability can be exercised on demand.

    Card abilities were previously only testable by playing until the card
    happened to appear - roughly a dozen turns to reach one Fire Gem, and the
    long tail (Tyrannor, Varrick, Rake) essentially never. This puts named
    cards straight into hand, board, or the market row so every ability can be
    driven through the *real* UI and the *real* backend, which is the only
    layer where the last three rules bugs were visible: benchmarks drive the
    engine directly and feed its own action dicts back in, so they cannot see
    the UI at all.

    Names are matched case-insensitively against the loaded card set. Unknown
    names are reported rather than silently dropped - a typo that quietly
    produced an empty hand would invalidate a test without saying so.
    """
    if not DEBUG_SETUP:
        raise ValueError("debug-setup disabled; start the backend with "
                         "HR_DEBUG_SETUP=1")

    by_name = {card.name.lower(): card for card in session.cards}
    for extra in (GOLD, SHORTSWORD, DAGGER, RUBY, FIRE_GEM):
        by_name[extra.name.lower()] = extra

    unknown: list[str] = []

    def resolve(names):
        out = []
        for name in names or []:
            card = by_name.get(str(name).lower())
            if card is None:
                unknown.append(name)
            else:
                out.append(card)
        return out

    who = session.bot if body.get("side") == "bot" else session.player
    target = session.player if who is session.bot else session.bot

    if "hand" in body:
        who.hand = resolve(body["hand"])
    if "discard" in body:
        who.discard = resolve(body["discard"])
    if "deck" in body:
        who.deck = resolve(body["deck"])
    if "board" in body:
        who.board = [BoardChampion(card) for card in resolve(body["board"])]
    if "opponentBoard" in body:
        target.board = [BoardChampion(card) for card in resolve(body["opponentBoard"])]
    if "market" in body:
        row = resolve(body["market"])
        session.market.row = (row + [None] * 5)[:5]
    for field in ("gold", "combat", "hp"):
        if field in body:
            setattr(who, field, int(body[field]))

    if unknown:
        raise ValueError(f"unknown card names: {unknown}")
    return session.get_state()


class Handler(BaseHTTPRequestHandler):
    server_version = "HeroRealmsML/0.1"

    def _send(self, status: int, payload: dict) -> None:
        self._send_raw(status, _json_bytes(payload))

    def _send_raw(self, status: int, data: bytes) -> None:
        """Send a pre-serialized JSON body (used to replay cached responses)."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, X-Idempotency-Key"
        )
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    # ---- idempotency helpers ---------------------------------------------

    def _idempotency_key(self) -> str | None:
        """The client's retry key for this request, if it sent one."""
        key = (self.headers.get("X-Idempotency-Key") or "").strip()
        return key or None

    def _idempotent_replay(self, scope_id: str) -> bool:
        """Replay the cached response when this request's key was seen before.

        Returns True when a cached response was sent (the caller must return
        immediately). Only successful mutations are ever cached, so a replay
        means the first delivery already applied. Never raises: a cache
        failure degrades to running the handler normally.
        """
        key = self._idempotency_key()
        if not key:
            return False
        try:
            cached = db_store.idempotency_get(scope_id, key)
        except Exception:  # noqa: BLE001
            return False
        if cached is None:
            return False
        self._send_raw(200, cached.encode("utf-8"))
        return True

    def _idempotent_store(self, scope_id: str, payload: dict) -> None:
        """Cache a successful mutation's JSON response under the request's key."""
        key = self._idempotency_key()
        if not key:
            return
        try:
            db_store.idempotency_put(
                scope_id, key, _json_bytes(payload).decode("utf-8")
            )
        except Exception:  # noqa: BLE001
            # Caching must never break the response that was just produced.
            pass

    # ---- auth helpers ----------------------------------------------------

    def _cookies(self) -> dict[str, str]:
        raw = self.headers.get("Cookie", "")
        out: dict[str, str] = {}
        for part in raw.split(";"):
            if "=" in part:
                key, _, value = part.partition("=")
                out[key.strip()] = value.strip()
        return out

    def _current_user(self) -> dict | None:
        return auth_store.user_for_token(self._cookies().get(COOKIE_NAME, ""))

    def _require_user(self) -> dict | None:
        user = self._current_user()
        if user is None:
            self._send(401, {"error": "Sign in to continue."})
        return user

    def _cookie_secure(self) -> bool:
        # Cookies must be Secure on HTTPS (Render) but must NOT be Secure on
        # plain-HTTP local dev, or the browser will refuse to store them.
        if os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true", "yes"):
            return True
        return (
            self.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
            == "https"
        )

    def _set_session_cookie(self, token: str | None) -> list[tuple[str, str]]:
        secure = "; Secure" if self._cookie_secure() else ""
        if token:
            return [(
                "Set-Cookie",
                f"{COOKIE_NAME}={token}; HttpOnly; Path=/; SameSite=Lax; "
                f"Max-Age={30 * 24 * 3600}{secure}",
            )]
        return [(
            "Set-Cookie",
            f"{COOKIE_NAME}=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0{secure}",
        )]

    def _send_with_cookies(
        self, status: int, payload: dict, cookies: list[tuple[str, str]]
    ) -> None:
        data = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for name, value in cookies:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _stream_bot_turn(self, session) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        connected = True

        def emit(payload):
            nonlocal connected
            if not connected:
                return
            try:
                self.wfile.write(_json_bytes(payload) + b"\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                # Finish the committed turn even if its viewer disconnects.
                connected = False

        try:
            state = session.run_bot_turn(on_event=lambda frame: emit({"type": "frame", "frame": frame}))
            game_store.save_bot_session(session)
            emit({"type": "complete", "state": state})
        except Exception as exc:  # A streamed response already has its HTTP headers.
            # Persist best-effort so a refresh recovers the finished turn;
            # never let a save failure mask the turn's own error.
            try:
                game_store.save_bot_session(session)
            except Exception:
                pass
            emit({"type": "error", "error": str(exc), "state": session.get_state()})

    # ---- multiplayer game helpers ------------------------------------------

    def _game_state_for(self, game: dict, side: str) -> dict:
        """Full state from one participant's seat, plus lobby metadata."""
        session = game["session"]
        state = session.get_state(for_side=side)
        host = auth_store.public_user(game["host_id"]) or {}
        guest = auth_store.public_user(game["guest_id"]) if game["guest_id"] else None
        state["gameId"] = game["id"]
        state["inviteCode"] = game["invite_code"]
        state["gameStatus"] = game["status"]
        state["turnCount"] = game["turn_count"]
        state["hostName"] = host.get("username")
        state["guestName"] = guest.get("username") if guest else None
        return state

    def _apply_game_action(self, session, route: str, body: dict) -> dict:
        # Both seats are human: optional sacrifices stay manual, never auto.
        if route == "play-card":
            return session.play_card(
                body["cardId"], body.get("stunTargetIndex"), manual_self_sacrifice=True
            )
        if route == "play-all":
            return session.play_all_action()
        if route == "expend-champion":
            return session.expend_champion_action(
                body["championId"], body.get("stunTargetIndex"), body.get("choice"),
                body.get("sacrificeIndex"), body.get("sacrificeZone", "hand"))
        if route == "sacrifice-played":
            return session.sacrifice_played_action(body["cardId"])
        if route == "trigger-ally":
            return session.trigger_ally_action(
                body["cardId"], body.get("stunTargetIndex"))
        if route == "resolve-choice":
            return session.resolve_choice_action(int(body["candidateIndex"]))
        if route == "buy-card":
            return session.buy_card_action(int(body["marketIndex"]))
        if route == "attack":
            return session.attack_target_action(body["target"], body.get("championId"))
        if route == "advance-phase":
            return session.advance_phase()
        if route == "end-turn":
            return session.end_turn()
        raise ValueError(f"Unknown action: {route}")

    def _handle_game_action(self, game_id: str, user: dict, body: dict) -> None:
        # A retried mutation replays its first response without re-running.
        if self._idempotent_replay(game_id):
            return
        lock = GAME_LOCKS[game_id]
        if not lock.acquire(blocking=False):
            self._send(409, {"error": "An action is already resolving."})
            return
        try:
            game = game_store.get_game(game_id)
            if game is None:
                self._send(404, {"error": "Game not found."})
                return
            side = game_store.participant_side(game, user["id"])
            if side is None:
                self._send(403, {"error": "You are not in this game."})
                return
            if game["status"] == "waiting":
                self._send(400, {"error": "Waiting for your opponent to join."})
                return
            if game["status"] == "finished":
                self._send(400, {"error": "This game is over."})
                return
            session = game["session"]
            if session.winner or session.active_player != side:
                self._send(400, {"error": "It is not your turn."})
                return
            action = body.get("action", "")
            if action == "undo":
                snap = UNDO_SNAPSHOTS.pop(game_id, None)
                if snap is None:
                    self._send(409, {"error": "Nothing to undo."})
                    return
                game_store.restore(session, snap)
            else:
                snap = game_store.snapshot(session)
                try:
                    self._apply_game_action(session, action, body)
                except Exception as exc:  # noqa: BLE001
                    self._send(400, {"error": str(exc)})
                    return
                # Ending the turn commits it: no undo across turns.
                if action == "end-turn":
                    UNDO_SNAPSHOTS.pop(game_id, None)
                else:
                    UNDO_SNAPSHOTS[game_id] = snap
            if session.winner:
                game_store.finish_game(game_id)
            game_store.save_game(game_id, session, bump_turn=True)
            game = game_store.get_game(game_id)
            payload = self._game_state_for(game, side)
        finally:
            lock.release()
        self._idempotent_store(game_id, payload)
        self._send(200, payload)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        parts = [item for item in parsed.path.split("/") if item]

        if parsed.path == "/api/health":
            self._send(200, {"ok": True})
            return

        if parsed.path == "/api/auth/me":
            user = self._current_user()
            if user is None:
                self._send(401, {"error": "Not signed in."})
            else:
                self._send(200, {"user": user})
            return

        if parsed.path == "/api/auth/config":
            # Public config for the sign-in screen. The Google client ID is
            # not a secret; the backend still verifies every ID token.
            self._send(200, {
                "googleClientId": os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or None,
            })
            return

        if parsed.path == "/api/games":
            user = self._require_user()
            if user is None:
                return
            self._send(200, {"games": game_store.list_for_user(user["id"])})
            return

        if len(parts) == 3 and parts[:2] == ["api", "games"] and parts[2]:
            user = self._require_user()
            if user is None:
                return
            game = game_store.get_game(parts[2])
            if game is None:
                self._send(404, {"error": "Game not found."})
                return
            side = game_store.participant_side(game, user["id"])
            if side is None:
                self._send(403, {"error": "You are not in this game."})
                return
            query = parse_qs(parsed.query)
            since = query.get("since", [None])[0]
            if since is not None and str(game["turn_count"]) == since:
                self._send(200, {"changed": False, "turnCount": game["turn_count"]})
                return
            self._send(200, self._game_state_for(game, side))
            return

        if len(parts) == 3 and parts[:2] == ["api", "sessions"] and parts[2]:
            session, err = _session_or_404(parts[2])
            if err:
                self._send(404, err)
                return
            lock = SESSION_LOCKS[session.session_id]
            if not lock.acquire(blocking=False):
                self._send(409, {"error": "A turn is still running. Try refreshing again shortly."})
                return
            try:
                self._send(200, session.get_state())
            finally:
                lock.release()
            return

        if not parsed.path.startswith("/api/"):
            self._serve_frontend(parsed.path)
            return

        self._send(404, {"error": "Not found"})

    # ---- static frontend -------------------------------------------------

    _MIME = {
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".woff2": "font/woff2",
    }

    def _serve_frontend(self, path: str) -> None:
        """Serve the vite build (web/dist); SPA fallback to index.html."""
        dist = REPO_ROOT / "web" / "dist"
        target = (dist / path.lstrip("/")).resolve() if path != "/" else dist / "index.html"
        try:
            target.relative_to(dist.resolve())
        except ValueError:
            self._send(404, {"error": "Not found"})
            return
        if not target.is_file():
            target = dist / "index.html"
        if not target.is_file():
            self._send(404, {"error": "Not found"})
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type",
            self._MIME.get(target.suffix.lower(), "application/octet-stream"),
        )
        self.send_header("Content-Length", str(len(data)))
        # index.html is never cached; hashed assets are immutable.
        if target.name == "index.html":
            self.send_header("Cache-Control", "no-cache")
        else:
            self.send_header(
                "Cache-Control", "public, max-age=31536000, immutable"
            )
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        parts = [item for item in parsed.path.split("/") if item]
        body = _read_body(self)

        if parsed.path == "/api/auth/register":
            if not REGISTER_ENABLED:
                self._send(403, {"error": "Registration is closed."})
                return
            try:
                user = auth_store.create_user(
                    (body.get("username") or "").strip(), body.get("password") or ""
                )
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
                return
            token = auth_store.create_token(user["id"])
            self._send_with_cookies(200, {"user": user}, self._set_session_cookie(token))
            return

        if parsed.path == "/api/auth/login":
            record = auth_store.find_by_username((body.get("username") or "").strip())
            if record is None or not auth_store.verify_password(
                body.get("password") or "", record["password_hash"]
            ):
                self._send(401, {"error": "Wrong username or password."})
                return
            token = auth_store.create_token(record["id"])
            self._send_with_cookies(
                200,
                {"user": {"id": record["id"], "username": record["username"]}},
                self._set_session_cookie(token),
            )
            return

        if parsed.path == "/api/auth/logout":
            auth_store.delete_token(self._cookies().get(COOKIE_NAME, ""))
            self._send_with_cookies(200, {"ok": True}, self._set_session_cookie(None))
            return

        if parsed.path == "/api/auth/google":
            # Sign in with Google: the frontend sends the ID token (JWT) that
            # Google Identity Services returned; we verify its signature,
            # expiry, and audience server-side, then find or create the user.
            id_token = (body.get("idToken") or "").strip()
            client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
            if not client_id:
                self._send(501, {"error": "Google sign-in is not configured on this server."})
                return
            if not id_token:
                self._send(400, {"error": "Missing Google ID token."})
                return
            try:
                from google.auth.transport import requests as google_requests
                from google.oauth2 import id_token as google_id_token

                claims = google_id_token.verify_oauth2_token(
                    id_token, google_requests.Request(), client_id
                )
            except Exception:
                self._send(401, {"error": "Google sign-in failed. Please try again."})
                return
            if not claims.get("email_verified"):
                self._send(401, {"error": "Google did not verify an email for this account."})
                return
            try:
                user = auth_store.create_google_user(
                    claims["sub"], claims.get("email") or "", claims.get("name") or ""
                )
            except Exception as exc:  # noqa: BLE001
                self._send(400, {"error": str(exc)})
                return
            token = auth_store.create_token(user["id"])
            self._send_with_cookies(200, {"user": user}, self._set_session_cookie(token))
            return

        if parsed.path == "/api/games" and self.command == "POST":
            user = self._require_user()
            if user is None:
                return
            session = create_session(bot_is_human=True)
            session.player.name = user["username"]
            created = game_store.create_game(user["id"], session)
            self._send(200, created)
            return

        if parsed.path == "/api/games/join":
            user = self._require_user()
            if user is None:
                return
            code = (body.get("code") or "").strip()
            game = game_store.get_by_code(code)
            if game is None:
                self._send(404, {"error": "No waiting game with that code."})
                return
            if game["status"] != "waiting":
                self._send(400, {"error": "That game already started."})
                return
            if game["host_id"] == user["id"]:
                self._send(200, {"id": game["id"], "inviteCode": game["invite_code"]})
                return
            session = game["session"]
            session.bot.name = user["username"]
            if not game_store.join_game(game["id"], user["id"], session):
                self._send(400, {"error": "That game already started."})
                return
            self._send(200, {"id": game["id"], "inviteCode": game["invite_code"]})
            return

        if (
            len(parts) == 4
            and parts[:2] == ["api", "games"]
            and parts[3] == "undo"
        ):
            user = self._require_user()
            if user is None:
                return
            body["action"] = "undo"
            self._handle_game_action(parts[2], user, body)
            return

        if (
            len(parts) == 4
            and parts[:2] == ["api", "games"]
            and parts[3] == "action"
        ):
            user = self._require_user()
            if user is None:
                return
            self._handle_game_action(parts[2], user, body)
            return

        if parsed.path == "/api/sessions":
            session = create_session(
                seed=body.get("seed"),
                algorithm=body.get("algorithm", "mcts"),
                budget_ms=int(body.get("budgetMs", 60)),
            )
            game_store.create_bot_session(session)
            # Opportunistic garbage collection of week-old abandoned matches;
            # never let it break session creation.
            try:
                game_store.cleanup_bot_sessions()
            except Exception:  # noqa: BLE001
                pass
            self._send(200, session.get_state())
            return

        if len(parts) >= 4 and parts[:2] == ["api", "sessions"]:
            session, err = _session_or_404(parts[2])
            if err:
                self._send(404, err)
                return

            route = parts[3]
            # Streaming bot turns cannot be replayed from a JSON cache; every
            # other player-state mutation honors the client's retry key.
            if route != "bot-turn-stream" and self._idempotent_replay(
                session.session_id
            ):
                return
            lock = SESSION_LOCKS[session.session_id]
            if not lock.acquire(blocking=False):
                self._send(409, {"error": "A turn is already running. Refresh when it finishes."})
                return
            try:
                if route == "play-card":
                    payload = session.play_card(body["cardId"], body.get("stunTargetIndex"),
                                                manual_self_sacrifice=session.active_player == "player")
                elif route == "play-all":
                    payload = session.play_all_action()
                elif route == "expend-champion":
                    payload = session.expend_champion_action(
                        body["championId"], body.get("stunTargetIndex"), body.get("choice"),
                        body.get("sacrificeIndex"), body.get("sacrificeZone", "hand"))
                elif route == "debug-setup":
                    payload = _debug_setup(session, body)
                elif route == "sacrifice-played":
                    payload = session.sacrifice_played_action(body["cardId"])
                elif route == "trigger-ally":
                    payload = session.trigger_ally_action(
                        body["cardId"], body.get("stunTargetIndex"))
                elif route == "resolve-choice":
                    payload = session.resolve_choice_action(int(body["candidateIndex"]))
                elif route == "buy-card":
                    payload = session.buy_card_action(int(body["marketIndex"]))
                elif route == "attack":
                    payload = session.attack_target_action(body["target"], body.get("championId"))
                elif route == "advance-phase":
                    payload = session.advance_phase()
                elif route == "end-turn":
                    payload = session.end_turn()
                elif route in ("bot-turn", "bot-turn-stream"):
                    if body.get("algorithm"):
                        session.algorithm = body["algorithm"]
                    if body.get("budgetMs") is not None:
                        session.budget_ms = int(body["budgetMs"])
                    if route == "bot-turn-stream":
                        self._stream_bot_turn(session)
                        return
                    payload = session.run_bot_turn()
                else:
                    self._send(404, {"error": "Unknown action"})
                    return
                # The session was loaded fresh from the database for this
                # request; persist the mutation before releasing the lock.
                game_store.save_bot_session(session)
            except Exception as exc:  # noqa: BLE001
                self._send(400, {"error": str(exc)})
                return
            finally:
                lock.release()

            if route != "bot-turn-stream":
                self._idempotent_store(session.session_id, payload)
            self._send(200, payload)
            return

        if parsed.path == "/api/admin/archive":
            # Cloud Scheduler's nightly sweep. Fail closed: a missing
            # HR_ARCHIVE_SECRET or any mismatch is a 403, never a sweep.
            expected = os.environ.get("HR_ARCHIVE_SECRET", "")
            provided = self.headers.get("X-Archive-Secret", "")
            try:
                authorized = bool(expected) and hmac.compare_digest(
                    provided, expected
                )
            except TypeError:
                authorized = False  # non-ASCII secret header: deny
            if not authorized:
                self._send(403, {"error": "Forbidden"})
                return
            try:
                result = archive_store.sweep()
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"error": str(exc)})
                return
            self._send(200, result)
            return

        self._send(404, {"error": "Not found"})


def main() -> None:
    # In the web game the acting agent chooses Lys/Krythos sacrifices: the
    # human picks from the per-card buttons web/session.py offers via
    # legal_actions (the engine no longer auto-sacrifices with no prompt),
    # and the web bot picks from the same legal actions. Scoped to the
    # server entry point so research harnesses importing web.session keep
    # the engine default (see AGENT_CHOOSES_SACRIFICE in hero_engine.py).
    import hero_engine
    hero_engine.AGENT_CHOOSES_SACRIFICE = True
    # Sacrifice/discard/reanimate/recycle targeting is a real decision, not
    # something _find_worst_idx settles inline: the human picks from the
    # choice sheets web/session.py offers via legal_actions, and the web bot
    # picks from the same legal actions (it answers resolve_choice through
    # its search - see test_bot_can_play_a_whole_turn_with_targeting_on).
    # Without this the whole pending-choice UI (The Rot, Elven Gift,
    # Varrick, Smash and Grab) never fires in the web game. Scoped to the
    # server entry point so research harnesses importing web.session keep
    # the engine default.
    hero_engine.AGENT_CHOOSES_TARGETS = True
    # PORT is what Render/Railway/Fly inject; HR_BACKEND_PORT stays the local
    # override so .claude/launch.json and the dev proxy are unaffected.
    port = int(os.environ.get("HR_BACKEND_PORT") or os.environ.get("PORT") or "8000")
    # Bind every interface when hosted - 127.0.0.1 is unreachable from outside
    # the container - but keep loopback as the default so running it on a dev
    # machine does not silently expose a game server on the LAN.
    host = os.environ.get("HR_BACKEND_HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    db_store.init_schema()
    if db_store.is_postgres():
        print("Hero Realms backend using PostgreSQL")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Hero Realms backend listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
