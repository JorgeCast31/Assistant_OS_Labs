"""GET-only HTTP adapter for read-only Mission Core observation."""

from __future__ import annotations

import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from assistant_os.missions.query import get_mission, get_mission_events, list_missions
from assistant_os.missions.store import InMemoryMissionStore


PORT: int = int(os.environ.get("MISSION_API_PORT", "8200"))


def _json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, indent=2).encode("utf-8")


class MissionAPIHandler(BaseHTTPRequestHandler):
    """Mission observation handler."""

    store: InMemoryMissionStore | None = None

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path

        if path == "/health":
            self._send(200, {"ok": True, "service": "mission_api"})
            return

        if path == "/api/missions":
            store = self._store()
            if store is None:
                return
            self._send(200, list_missions(store))
            return

        if path.startswith("/api/missions/"):
            store = self._store()
            if store is None:
                return
            suffix = path[len("/api/missions/"):]
            if not suffix:
                self._send(400, {"ok": False, "error": "mission_id required"})
                return

            if suffix.endswith("/events"):
                raw_id = suffix[: -len("/events")]
                if not raw_id or "/" in raw_id:
                    self._send(400, {"ok": False, "error": "mission_id required"})
                    return
                mission_id = urllib.parse.unquote(raw_id)
                result = get_mission_events(store, mission_id)
                if result is None:
                    self._send(404, {"ok": False, "error": f"mission not found: {mission_id}"})
                else:
                    self._send(200, result)
                return

            if "/" in suffix:
                self._send(404, {"ok": False, "error": "not found"})
                return

            mission_id = urllib.parse.unquote(suffix)
            if not mission_id:
                self._send(400, {"ok": False, "error": "mission_id required"})
                return
            result = get_mission(store, mission_id)
            if result is None:
                self._send(404, {"ok": False, "error": f"mission not found: {mission_id}"})
            else:
                self._send(200, result)
            return

        self._send(404, {"ok": False, "error": "not found"})

    def _store(self) -> InMemoryMissionStore | None:
        if self.store is None:
            self._send(503, {"ok": False, "error": "mission store unavailable"})
            return None
        return self.store

    def _send(self, status: int, data: dict[str, Any]) -> None:
        body = _json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_server(*, port: int = PORT, store: InMemoryMissionStore) -> HTTPServer:
    class BoundMissionAPIHandler(MissionAPIHandler):
        pass

    BoundMissionAPIHandler.store = store
    return HTTPServer(("localhost", port), BoundMissionAPIHandler)


def run(*, port: int = PORT, store: InMemoryMissionStore) -> None:
    server = create_server(port=port, store=store)
    try:
        server.serve_forever()
    finally:
        server.server_close()
