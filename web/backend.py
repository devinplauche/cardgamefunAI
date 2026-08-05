from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.session import create_session


SESSIONS: dict[str, object] = {}


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw) if raw else {}


def _session_or_404(session_id: str):
    session = SESSIONS.get(session_id)
    if session is None:
        return None, {"error": "Session not found"}
    return session, None


class Handler(BaseHTTPRequestHandler):
    server_version = "HeroRealmsML/0.1"

    def _send(self, status: int, payload: dict) -> None:
        data = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(data)

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

        if len(parts) == 3 and parts[:2] == ["api", "sessions"] and parts[2]:
            session, err = _session_or_404(parts[2])
            if err:
                self._send(404, err)
                return
            self._send(200, session.get_state())
            return

        self._send(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        parts = [item for item in parsed.path.split("/") if item]
        body = _read_body(self)

        if parsed.path == "/api/sessions":
            session = create_session(
                seed=body.get("seed"),
                algorithm=body.get("algorithm", "mcts"),
                budget_ms=int(body.get("budgetMs", 60)),
            )
            SESSIONS[session.session_id] = session
            self._send(200, session.get_state())
            return

        if len(parts) >= 4 and parts[:2] == ["api", "sessions"]:
            session, err = _session_or_404(parts[2])
            if err:
                self._send(404, err)
                return

            route = parts[3]
            try:
                if route == "play-card":
                    payload = session.play_card(body["cardId"], body.get("stunTargetIndex"))
                elif route == "expend-champion":
                    payload = session.expend_champion_action(
                        body["championId"], body.get("stunTargetIndex"), body.get("choice"))
                elif route == "sacrifice-played":
                    payload = session.sacrifice_played_action(body["cardId"])
                elif route == "buy-card":
                    payload = session.buy_card_action(int(body["marketIndex"]))
                elif route == "attack":
                    payload = session.attack_target_action(body["target"], body.get("championId"))
                elif route == "advance-phase":
                    payload = session.advance_phase()
                elif route == "end-turn":
                    payload = session.end_turn()
                elif route == "bot-turn":
                    if body.get("algorithm"):
                        session.algorithm = body["algorithm"]
                    if body.get("budgetMs") is not None:
                        session.budget_ms = int(body["budgetMs"])
                    payload = session.run_bot_turn()
                else:
                    self._send(404, {"error": "Unknown action"})
                    return
            except Exception as exc:  # noqa: BLE001
                self._send(400, {"error": str(exc)})
                return

            self._send(200, payload)
            return

        self._send(404, {"error": "Not found"})


def main() -> None:
    port = int(os.environ.get("HR_BACKEND_PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Hero Realms backend listening on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
