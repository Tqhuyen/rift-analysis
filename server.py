#!/usr/bin/env python3
"""Local web server for the Rift Report dashboard.

Serves ``web/`` and a small JSON API backed by the LCU cache produced by
``lcu_stats.py``. Standard library only, bound to 127.0.0.1.

Endpoints:
    GET  /api/stats      -> dashboard payload (players, champions, matches)
    GET  /api/status     -> LCU + cache status
    POST /api/sync       -> refresh from LCU now

Usage:
    python server.py
    python server.py --port 8000 --no-sync
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import lcu_stats

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Sync at most once per N seconds when the client asks for stats.
SYNC_TTL = 120.0

_lock = threading.Lock()
_state = {
    "payload": None,
    "last_sync": 0.0,
    "last_error": None,
    "syncing": False,
}


# --------------------------------------------------------------------------- #
# Data layer
# --------------------------------------------------------------------------- #
def cached_payload() -> dict:
    """Rebuild stats from the on-disk cache (works without LCU)."""
    matches = lcu_stats.load_cached_matches()
    champs = lcu_stats.champion_map()
    me = {}
    roster = lcu_stats.resolve_roster(matches, me)
    return lcu_stats.build_payload(roster, matches, champs, me)


def do_sync(force: bool = False) -> dict:
    global _state
    with _lock:
        if _state["syncing"]:
            return _state
        if not force and _state["payload"] and time.time() - _state["last_sync"] < SYNC_TTL:
            return _state
        _state["syncing"] = True

    try:
        payload, me = lcu_stats.sync(pages=3, verbose=False)
        with _lock:
            _state.update(
                payload=payload,
                last_sync=time.time(),
                last_error=None,
                syncing=False,
            )
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _state["last_error"] = str(exc)
            _state["syncing"] = False
            _state["last_sync"] = time.time()
        if not _state["payload"]:
            try:
                with _lock:
                    _state["payload"] = cached_payload()
            except Exception:
                pass
    return _state


def get_payload(auto_sync: bool) -> dict:
    if auto_sync:
        do_sync(force=False)
    with _lock:
        payload = _state["payload"]
    if payload is None:
        payload = cached_payload()
        with _lock:
            _state["payload"] = payload
    return payload


def apply_filters(payload: dict, query: dict) -> dict:
    """Optional count/champion filters, mirroring what the UI does."""
    matches = payload["matches"]
    try:
        count = int((query.get("count") or ["0"])[0])
    except ValueError:
        count = 0
    if count > 0:
        matches = matches[:count]
    champion = (query.get("champion") or [""])[0]
    if champion:
        wanted = champion.lower()
        matches = [
            m for m in matches
            if any(p["champion"].lower() == wanted for p in m["participants"])
        ]
    if matches is payload["matches"]:
        return payload
    return {**payload, "matches": matches}


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(SimpleHTTPRequestHandler):
    server_version = "RiftReport/1.0"
    auto_sync = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    # -- helpers ----------------------------------------------------------- #
    def _json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: HTTPStatus, hint: str = "") -> None:
        self._json(
            {"error": message, "hint": hint, "at": datetime.now(timezone.utc).isoformat()},
            status,
        )

    def end_headers(self):
        # Local-only tool; avoid caching stale JS during development.
        if self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):  # quieter logs
        if self.path.startswith("/api/"):
            super().log_message(fmt, *args)

    # -- routes ------------------------------------------------------------ #
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/stats":
            try:
                payload = get_payload(self.auto_sync)
                payload = apply_filters(payload, parse_qs(parsed.query))
                self._json(payload)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._error(
                    "Could not build stats",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    hint=str(exc),
                )
            return

        if parsed.path == "/api/status":
            with _lock:
                last_error = _state["last_error"]
                last_sync = _state["last_sync"]
                payload = _state["payload"]
            cached = len(lcu_stats.load_cached_matches())
            self._json(
                {
                    "source": "lcu",
                    "lcuAvailable": lcu_stats.find_lockfile() is not None,
                    "lastSync": last_sync,
                    "lastError": last_error,
                    "cachedMatches": cached,
                    "players": len((payload or {}).get("players", [])),
                }
            )
            return

        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/sync":
            try:
                do_sync(force=True)
                with _lock:
                    error = _state["last_error"]
                if error:
                    self._error("LCU sync failed", HTTPStatus.SERVICE_UNAVAILABLE, error)
                else:
                    self._json({"ok": True, "syncedAt": _state["last_sync"]})
            except Exception as exc:  # noqa: BLE001
                self._error("LCU sync failed", HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
            return
        self._error("Not found", HTTPStatus.NOT_FOUND)

    def translate_path(self, path):
        # SimpleHTTPRequestHandler already normalises; keep it inside web/.
        resolved = Path(super().translate_path(path)).resolve()
        if WEB_DIR.resolve() not in resolved.parents and resolved != WEB_DIR.resolve():
            return str(WEB_DIR / "index.html")
        return str(resolved)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rift Report local server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-sync", action="store_true", help="serve cache only")
    args = parser.parse_args()

    if not WEB_DIR.exists():
        print(f"error: web directory not found at {WEB_DIR}")
        return 1

    Handler.auto_sync = not args.no_sync
    mimetypes.add_type("application/javascript", ".js")

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        print(f"error: cannot bind 127.0.0.1:{args.port} ({exc})")
        return 1

    # Warm the payload in the background so the first page load is fast.
    threading.Thread(target=lambda: get_payload(not args.no_sync), daemon=True).start()

    print(f"Rift Report -> http://127.0.0.1:{args.port}")
    if args.no_sync:
        print("LCU sync disabled (serving cached data)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
