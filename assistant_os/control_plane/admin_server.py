"""Dedicated admin/control-plane HTTP server for operator restriction control."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from ..config import (
    CONTROL_PLANE_HOST,
    CONTROL_PLANE_PORT,
    CONTROL_PLANE_SCHEDULER_ENABLED,
    CONTROL_PLANE_SCHEDULER_INTERVAL_SECONDS,
)
from ..storage.mso_store import get_store_status
from .admin_service import (
    RestrictionConflictError,
    authenticate_request,
    bootstrap_control_plane_view,
    cleanup_expired_tokens_view,
    force_lock_cleanup_view,
    force_token_cleanup_view,
    get_restriction_detail,
    get_restriction_history_view,
    get_maintenance_status_view,
    inspect_active_locks_view,
    list_bootstrap_history_view,
    list_operator_identities_view,
    list_operator_actions_view,
    list_operator_tokens_view,
    list_restrictions,
    make_control_plane_request,
    mint_operator_token,
    perform_restriction_action,
    rotate_operator_token_view,
    revoke_operator_token,
    run_maintenance_cycle_view,
)
from .locks import lock_manager
from .scheduler import ControlPlaneScheduler
from .token_service import summarize_operator_tokens
from ..mso.operator_auth import OperatorAuthenticationError, OperatorAuthorizationError

logger = logging.getLogger("assistant_os.control_plane")


def _make_json_error(status_code: int, message: str, error_type: str) -> tuple[int, dict[str, Any]]:
    return status_code, {
        "status": "error",
        "error": {
            "type": error_type,
            "message": message,
        },
    }


def _safe_parse_json(body: bytes) -> tuple[dict[str, Any] | None, tuple[int, dict[str, Any]] | None]:
    try:
        data = json.loads(body.decode("utf-8")) if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, _make_json_error(400, f"Invalid JSON: {exc}", "BadRequest")
    if not isinstance(data, dict):
        return None, _make_json_error(400, "Request body must be a JSON object", "BadRequest")
    return data, None


class AdminHandler(BaseHTTPRequestHandler):
    """Dedicated handler for the operator control plane."""

    def log_message(self, format: str, *args: Any) -> None:
        logger.info(
            "control_plane.http.access",
            extra={
                "event": "control_plane.http.access",
                "client": self.client_address[0],
                "method": getattr(self, "command", ""),
                "path": getattr(self, "path", ""),
            },
        )

    def _send_json_response(self, status_code: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_path_without_query(self) -> str:
        return self.path.split("?", 1)[0]

    def _parse_query_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if "?" not in self.path:
            return params
        query_string = self.path.split("?", 1)[1]
        for pair in query_string.split("&"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                params[key] = value
            elif pair:
                params[pair] = "1"
        return params

    def _authenticate(self):
        header = self.headers.get("Authorization", "").strip()
        if not header.startswith("Bearer "):
            raise OperatorAuthenticationError("Missing bearer token")
        return authenticate_request(header.split(" ", 1)[1].strip())

    def _read_json_body(self) -> tuple[dict[str, Any], tuple[int, dict[str, Any]] | None]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return {}, None
        body = self.rfile.read(content_length)
        data, error = _safe_parse_json(body)
        return data or {}, error

    def do_GET(self) -> None:
        path = self._get_path_without_query()
        if path == "/health":
            self._send_json_response(200, self.server.health_payload())
            return
        try:
            context = self._authenticate()
            if path == "/admin/restrictions":
                params = self._parse_query_params()
                control_request = make_control_plane_request(
                    context,
                    action="list_restrictions",
                    payload=params,
                )
                payload = list_restrictions(
                    control_request,
                    restriction_type=params.get("type", "").strip(),
                    source_event_id=params.get("source_event_id", "").strip(),
                    review_state=params.get("review_state", "").strip(),
                    status_filter=params.get("status", "active").strip(),
                )
                self._send_json_response(200, {"ok": True, **payload})
                return
            restriction_history = re.match(r"^/admin/restrictions/([^/]+)/history$", path)
            if restriction_history:
                control_request = make_control_plane_request(
                    context,
                    action="get_restriction_history",
                    payload={"restriction_id": restriction_history.group(1)},
                )
                payload = get_restriction_history_view(control_request, restriction_history.group(1))
                self._send_json_response(200, {"ok": True, **payload})
                return
            restriction_detail = re.match(r"^/admin/restrictions/([^/]+)$", path)
            if restriction_detail:
                control_request = make_control_plane_request(
                    context,
                    action="get_restriction_detail",
                    payload={"restriction_id": restriction_detail.group(1)},
                )
                payload = get_restriction_detail(control_request, restriction_detail.group(1))
                self._send_json_response(200, {"ok": True, **payload})
                return
            if path == "/admin/operator-actions":
                params = self._parse_query_params()
                control_request = make_control_plane_request(
                    context,
                    action="list_operator_actions",
                    payload=params,
                )
                payload = list_operator_actions_view(
                    control_request,
                    filter_operator_id=params.get("filter_operator_id", "").strip(),
                    restriction_id=params.get("restriction_id", "").strip(),
                    action_type=params.get("action_type", "").strip(),
                )
                self._send_json_response(200, {"ok": True, **payload})
                return
            if path == "/admin/tokens":
                if context.role != "admin":
                    raise OperatorAuthorizationError("Only admin can inspect operator tokens")
                params = self._parse_query_params()
                payload = list_operator_tokens_view(
                    operator_id=params.get("operator_id", "").strip(),
                    is_active=(params.get("is_active", "").strip().lower() == "true")
                    if params.get("is_active", "").strip()
                    else None,
                )
                control_request = make_control_plane_request(
                    context,
                    action="list_operator_tokens",
                    payload=params,
                )
                self._send_json_response(
                    200,
                    {"ok": True, "control_plane_request": asdict(control_request), "operator_context": asdict(context), **payload},
                )
                return
            if path == "/admin/operators":
                if context.role != "admin":
                    raise OperatorAuthorizationError("Only admin can inspect operators")
                control_request = make_control_plane_request(
                    context,
                    action="list_operators",
                    payload={},
                )
                payload = list_operator_identities_view()
                self._send_json_response(
                    200,
                    {"ok": True, "control_plane_request": asdict(control_request), "operator_context": asdict(context), **payload},
                )
                return
            if path == "/admin/bootstrap":
                if context.role != "admin":
                    raise OperatorAuthorizationError("Only admin can inspect bootstrap history")
                control_request = make_control_plane_request(
                    context,
                    action="list_bootstrap_history",
                    payload={},
                )
                payload = list_bootstrap_history_view()
                self._send_json_response(
                    200,
                    {"ok": True, "control_plane_request": asdict(control_request), "operator_context": asdict(context), **payload},
                )
                return
            if path == "/admin/maintenance":
                if context.role != "admin":
                    raise OperatorAuthorizationError("Only admin can inspect maintenance status")
                control_request = make_control_plane_request(
                    context,
                    action="get_maintenance_status",
                    payload={},
                )
                payload = get_maintenance_status_view()
                self._send_json_response(
                    200,
                    {"ok": True, "control_plane_request": asdict(control_request), "operator_context": asdict(context), **payload},
                )
                return
            if path == "/admin/maintenance/locks":
                if context.role != "admin":
                    raise OperatorAuthorizationError("Only admin can inspect active locks")
                control_request = make_control_plane_request(
                    context,
                    action="inspect_active_locks",
                    payload={},
                )
                payload = inspect_active_locks_view(
                    operator_context=context,
                    trace_id=control_request.request_id,
                )
                self._send_json_response(
                    200,
                    {"ok": True, "control_plane_request": asdict(control_request), "operator_context": asdict(context), **payload},
                )
                return
            self._send_json_response(*_make_json_error(404, f"Not found: {path}", "NotFound"))
        except OperatorAuthenticationError as exc:
            self._send_json_response(*_make_json_error(401, str(exc), "Unauthorized"))
        except OperatorAuthorizationError as exc:
            self._send_json_response(*_make_json_error(403, str(exc), "Forbidden"))
        except ValueError as exc:
            self._send_json_response(*_make_json_error(404, str(exc), "NotFound"))

    def do_POST(self) -> None:
        path = self._get_path_without_query()
        try:
            context = self._authenticate()
            if path == "/admin/tokens/revoke":
                body, error = self._read_json_body()
                if error is not None:
                    self._send_json_response(*error)
                    return
                token_id = str(body.get("token_id", "")).strip()
                reason = str(body.get("reason", "")).strip()
                if not token_id:
                    self._send_json_response(*_make_json_error(400, "token_id is required", "BadRequest"))
                    return
                if not reason:
                    self._send_json_response(*_make_json_error(400, "reason is required", "BadRequest"))
                    return
                if context.role != "admin":
                    raise OperatorAuthorizationError("Only admin can revoke operator tokens")
                control_request = make_control_plane_request(
                    context,
                    action="revoke_operator_token",
                    payload={"token_id": token_id, "reason": reason},
                )
                payload = revoke_operator_token(
                    token_id=token_id,
                    reason=reason,
                    revoked_by=context.operator_id,
                )
                self._send_json_response(
                    200,
                    {"ok": True, "control_plane_request": asdict(control_request), "operator_context": asdict(context), **payload},
                )
                return
            if path == "/admin/tokens/rotate":
                body, error = self._read_json_body()
                if error is not None:
                    self._send_json_response(*error)
                    return
                token_id = str(body.get("token_id", "")).strip()
                reason = str(body.get("reason", "")).strip()
                ttl_minutes = int(body.get("ttl_minutes", 60))
                if not token_id:
                    self._send_json_response(*_make_json_error(400, "token_id is required", "BadRequest"))
                    return
                if not reason:
                    self._send_json_response(*_make_json_error(400, "reason is required", "BadRequest"))
                    return
                if context.role != "admin":
                    raise OperatorAuthorizationError("Only admin can rotate operator tokens")
                control_request = make_control_plane_request(
                    context,
                    action="rotate_operator_token",
                    payload={"token_id": token_id, "reason": reason, "ttl_minutes": ttl_minutes},
                )
                payload = rotate_operator_token_view(
                    token_id=token_id,
                    ttl_minutes=ttl_minutes,
                    rotated_by=context.operator_id,
                    rotation_reason=reason,
                )
                self._send_json_response(
                    200,
                    {"ok": True, "control_plane_request": asdict(control_request), "operator_context": asdict(context), **payload},
                )
                return
            if path == "/admin/tokens/cleanup":
                body, error = self._read_json_body()
                if error is not None:
                    self._send_json_response(*error)
                    return
                if context.role != "admin":
                    raise OperatorAuthorizationError("Only admin can clean expired tokens")
                control_request = make_control_plane_request(
                    context,
                    action="cleanup_expired_tokens",
                    payload=body,
                )
                payload = cleanup_expired_tokens_view(now_ts=str(body.get("now_ts", "")).strip())
                self._send_json_response(
                    200,
                    {"ok": True, "control_plane_request": asdict(control_request), "operator_context": asdict(context), **payload},
                )
                return
            if path == "/admin/maintenance/run":
                body, error = self._read_json_body()
                if error is not None:
                    self._send_json_response(*error)
                    return
                if context.role != "admin":
                    raise OperatorAuthorizationError("Only admin can run maintenance cycles")
                control_request = make_control_plane_request(
                    context,
                    action="run_maintenance_cycle",
                    payload=body,
                )
                payload = run_maintenance_cycle_view(
                    operator_context=context,
                    trace_id=control_request.request_id,
                    now_ts=str(body.get("now_ts", "")).strip(),
                )
                self._send_json_response(
                    200,
                    {"ok": True, "control_plane_request": asdict(control_request), "operator_context": asdict(context), **payload},
                )
                return
            if path == "/admin/maintenance/tokens/cleanup":
                body, error = self._read_json_body()
                if error is not None:
                    self._send_json_response(*error)
                    return
                if context.role != "admin":
                    raise OperatorAuthorizationError("Only admin can force token cleanup")
                control_request = make_control_plane_request(
                    context,
                    action="force_token_cleanup",
                    payload=body,
                )
                payload = force_token_cleanup_view(
                    operator_context=context,
                    trace_id=control_request.request_id,
                    now_ts=str(body.get("now_ts", "")).strip(),
                )
                self._send_json_response(
                    200,
                    {"ok": True, "control_plane_request": asdict(control_request), "operator_context": asdict(context), **payload},
                )
                return
            if path == "/admin/maintenance/locks/cleanup":
                body, error = self._read_json_body()
                if error is not None:
                    self._send_json_response(*error)
                    return
                if context.role != "admin":
                    raise OperatorAuthorizationError("Only admin can clean stale lock slots")
                control_request = make_control_plane_request(
                    context,
                    action="force_lock_cleanup",
                    payload=body,
                )
                payload = force_lock_cleanup_view(
                    operator_context=context,
                    trace_id=control_request.request_id,
                )
                self._send_json_response(
                    200,
                    {"ok": True, "control_plane_request": asdict(control_request), "operator_context": asdict(context), **payload},
                )
                return
            match = re.match(r"^/admin/restrictions/([^/]+)/(acknowledge|clear|extend|override)$", path)
            if not match:
                self._send_json_response(*_make_json_error(404, f"Not found: {path}", "NotFound"))
                return
            restriction_id = match.group(1)
            action_name = match.group(2)
            body, error = self._read_json_body()
            if error is not None:
                self._send_json_response(*error)
                return
            reason = str(body.get("reason", "")).strip()
            if not reason:
                self._send_json_response(*_make_json_error(400, "reason is required", "BadRequest"))
                return
            control_request = make_control_plane_request(
                context,
                action=f"{action_name}_restriction",
                payload=body,
            )
            payload = perform_restriction_action(
                control_request,
                restriction_id=restriction_id,
                action_name=action_name,
                reason=reason,
                trace_id=str(body.get("trace_id", "")).strip(),
                expires_at=str(body.get("expires_at", "")).strip(),
                override_mode=str(body.get("override_mode", "allow")).strip() or "allow",
            )
            self._send_json_response(200, {"ok": True, **payload})
        except OperatorAuthenticationError as exc:
            self._send_json_response(*_make_json_error(401, str(exc), "Unauthorized"))
        except OperatorAuthorizationError as exc:
            self._send_json_response(*_make_json_error(403, str(exc), "Forbidden"))
        except RestrictionConflictError as exc:
            self._send_json_response(*_make_json_error(409, str(exc), "Conflict"))
        except ValueError as exc:
            self._send_json_response(*_make_json_error(400, str(exc), "BadRequest"))


class AdminHTTPServer(HTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        host: str,
        port: int,
        *,
        scheduler_enabled: bool = CONTROL_PLANE_SCHEDULER_ENABLED,
        scheduler_interval_seconds: int = CONTROL_PLANE_SCHEDULER_INTERVAL_SECONDS,
    ):
        super().__init__((host, port), AdminHandler)
        self.started_monotonic = time.monotonic()
        self.started_at = time.time()
        self.service_identity = "assistant_os_control_plane"
        self.process_id = os.getpid()
        self.scheduler = (
            ControlPlaneScheduler(interval_seconds=scheduler_interval_seconds)
            if scheduler_enabled
            else None
        )
        if self.scheduler is not None:
            self.scheduler.start()

    def health_payload(self) -> dict[str, Any]:
        uptime_seconds = round(max(0.0, time.monotonic() - self.started_monotonic), 3)
        token_summary = summarize_operator_tokens()
        store_status = get_store_status()
        warnings: list[str] = []
        if self.scheduler is None:
            warnings.append("scheduler_disabled")
        elif not self.scheduler.is_running():
            warnings.append("scheduler_not_running")
        if token_summary["expired_active_tokens"] > 0:
            warnings.append("expired_active_tokens_present")
        if store_status["expired_record_count"] > 0:
            warnings.append("expired_store_records_present")
        return {
            "status": "ok" if not warnings else "degraded",
            "service": self.service_identity,
            "service_mode": "standalone_control_plane",
            "host": self.server_address[0],
            "port": self.server_address[1],
            "process_id": self.process_id,
            "uptime_seconds": uptime_seconds,
            "config": {
                "scheduler_enabled": self.scheduler is not None,
                "scheduler_interval_seconds": self.scheduler.interval_seconds if self.scheduler else 0,
            },
            "scheduler": self.scheduler.status() if self.scheduler is not None else {
                "running": False,
                "interval_seconds": 0,
                "started_at": "",
                "last_started_at": "",
                "last_finished_at": "",
                "run_count": 0,
                "last_run": None,
            },
            "tokens": token_summary,
            "locks": {
                "active_count": len(lock_manager.active_locks()),
                "active": lock_manager.active_locks(),
            },
            "store": store_status,
            "recent_maintenance": get_maintenance_status_view()["recent_maintenance"],
            "recent_signals": get_maintenance_status_view()["recent_signals"],
            "warnings": warnings,
        }

    def shutdown(self) -> None:
        if self.scheduler is not None:
            self.scheduler.stop(wait=False)
        super().shutdown()


def start_admin_server_thread(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    scheduler_enabled: bool = CONTROL_PLANE_SCHEDULER_ENABLED,
    scheduler_interval_seconds: int = CONTROL_PLANE_SCHEDULER_INTERVAL_SECONDS,
) -> tuple[AdminHTTPServer, int]:
    server = AdminHTTPServer(
        host,
        port,
        scheduler_enabled=scheduler_enabled,
        scheduler_interval_seconds=scheduler_interval_seconds,
    )
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, actual_port


def run_admin_server(host: str = CONTROL_PLANE_HOST, port: int = CONTROL_PLANE_PORT) -> None:
    """Run the dedicated control plane server as a standalone service."""

    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    server = AdminHTTPServer(
        host,
        port,
        scheduler_enabled=CONTROL_PLANE_SCHEDULER_ENABLED,
        scheduler_interval_seconds=CONTROL_PLANE_SCHEDULER_INTERVAL_SECONDS,
    )
    logger.info(
        "control_plane.server.starting",
        extra={
            "event": "control_plane.server.starting",
            "host": host,
            "port": port,
            "scheduler_enabled": CONTROL_PLANE_SCHEDULER_ENABLED,
            "scheduler_interval_seconds": CONTROL_PLANE_SCHEDULER_INTERVAL_SECONDS,
        },
    )
    print(f"Starting AssistantOS control plane on http://{host}:{port}")
    print("Endpoints:")
    print("  GET  /health")
    print("  GET  /admin/restrictions")
    print("  GET  /admin/restrictions/{id}")
    print("  GET  /admin/restrictions/{id}/history")
    print("  GET  /admin/operator-actions")
    print("  GET  /admin/operators")
    print("  GET  /admin/bootstrap")
    print("  GET  /admin/maintenance")
    print("  GET  /admin/maintenance/locks")
    print("  GET  /admin/tokens")
    print("  POST /admin/restrictions/{id}/acknowledge|clear|extend|override")
    print("  POST /admin/maintenance/run")
    print("  POST /admin/maintenance/tokens/cleanup")
    print("  POST /admin/maintenance/locks/cleanup")
    print("  POST /admin/tokens/rotate")
    print("  POST /admin/tokens/revoke")
    print("  POST /admin/tokens/cleanup")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("control_plane.server.stopping", extra={"event": "control_plane.server.stopping"})
        server.server_close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AssistantOS control plane service")
    parser.add_argument("--host", default=CONTROL_PLANE_HOST)
    parser.add_argument("--port", type=int, default=CONTROL_PLANE_PORT)
    parser.add_argument("--issue-token", action="store_true", help="Issue a one-time operator token and exit")
    parser.add_argument("--bootstrap", action="store_true", help="Bootstrap the initial admin operator and issue the first token")
    parser.add_argument("--operator-id", default="", help="Operator id for token issuance")
    parser.add_argument("--ttl-minutes", type=int, default=60, help="Token TTL in minutes")
    parser.add_argument("--reason", default="", help="Reason for bootstrap or token issuance")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.bootstrap:
        if not args.operator_id.strip():
            parser.error("--operator-id is required with --bootstrap")
        payload = bootstrap_control_plane_view(
            operator_id=args.operator_id.strip(),
            ttl_minutes=args.ttl_minutes,
            reason=args.reason.strip() or "initial_control_plane_bootstrap",
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.issue_token:
        if not args.operator_id.strip():
            parser.error("--operator-id is required with --issue-token")
        payload = mint_operator_token(operator_id=args.operator_id.strip(), ttl_minutes=args.ttl_minutes)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    run_admin_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
