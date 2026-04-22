"""Dedicated Ubuntu-side OpenClaw backend ingress for MACHINE_OPERATOR."""

from __future__ import annotations

import json
import logging
import re
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from . import config
from .runtime import (
    RuntimeDispatcher,
    RuntimeResult,
    RuntimeUnavailableError,
    SUPPORTED_CAPABILITIES,
    create_default_runtime_dispatcher,
)
from .audit_interim import emit_audit_event
from ..mso.mso_sovereign_state_store import MSOSovereignStateStore
from ..mso.sovereign_state_store import SovereignExecutionDecision, SovereignExecutionQuery

_log = logging.getLogger(__name__)

# Module-level sovereign store singleton — stateless; safe to share across
# all request handler threads (only reads from mso_store, no mutation).
_sovereign_store = MSOSovereignStateStore()

_REF_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$")


def _python_env_ready() -> bool:
    executable = (sys.executable or "").strip()
    if not executable:
        return False
    path = Path(executable)
    return path.exists() and path.is_file()


def _runtime_readiness(runtime_dispatcher: Any) -> dict[str, bool]:
    """Support both new `readiness()` and legacy `status()` runtime probes."""
    readiness_fn = getattr(runtime_dispatcher, "readiness", None)
    if callable(readiness_fn):
        try:
            readiness = readiness_fn()
            if isinstance(readiness, dict):
                merged = dict(readiness)
                merged.setdefault("python_env_ready", _python_env_ready())
                return merged
        except Exception:
            pass

    status_fn = getattr(runtime_dispatcher, "status", None)
    if callable(status_fn):
        try:
            status = status_fn()
            if isinstance(status, dict):
                merged = dict(status)
                merged.setdefault("python_env_ready", _python_env_ready())
                return merged
        except Exception:
            pass

    return {
        "runtime_available": False,
        "runtime_initialized": False,
        "runtime_usable": False,
        "python_env_ready": _python_env_ready(),
    }


def _health_surface(runtime_dispatcher: Any) -> dict[str, bool]:
    """Use the strict readiness surface for both health and ready to avoid drift."""
    return _runtime_readiness(runtime_dispatcher)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_error(error_type: str, message: str, *, request_id: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "error": {
            "type": error_type,
            "message": message,
        },
        "ts": _now_iso(),
    }
    if request_id:
        payload["request_id"] = request_id
    return payload


def _safe_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _build_failed_execution(
    *,
    error_type: str,
    message: str,
    capability_name: str,
    intent_id: str,
    correlation_id: str,
    latency_ms: int,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "intent_id": intent_id,
        "correlation_id": correlation_id,
        "observation": {
            "summary": f"Execution failed: {error_type}",
            "detail": message,
            "structured_data": {
                "error_type": error_type,
                "capability_name": capability_name,
            },
        },
        "evidence_refs": [],
        "consumed_budget": {
            "steps": 0,
            "duration_ms": max(latency_ms, 0),
            "output_bytes": 0,
            "side_effects": 0,
        },
        "side_effects_declared": [],
        "metadata": {
            "error_type": error_type,
        },
        "backend_execution_performed": False,
        "machine_action_performed": False,
    }


def _sovereign_blocked_response(
    *,
    decision: SovereignExecutionDecision,
    request_id: str,
) -> dict[str, Any]:
    """Build a 403-suitable response body for a sovereign enforcement block.

    Extends the standard ``_json_error`` envelope with a ``sovereign`` sub-key
    that carries structured policy context.  The outer shape (ok, error.type,
    error.message, ts, request_id) is identical to other error responses so
    callers need no special-case parsing.
    """
    payload = _json_error("sovereign_blocked", decision.reason.message, request_id=request_id)
    payload["error"]["reason_code"] = decision.reason.code
    payload["error"]["kill_switch_state"] = decision.kill_switch_state
    if decision.governance_ref:
        payload["error"]["governance_ref"] = decision.governance_ref
    if decision.approval_id:
        payload["error"]["approval_id"] = decision.approval_id
    return payload


def _validate_execute_request(data: Any) -> tuple[dict[str, Any] | None, tuple[int, dict[str, Any]] | None]:
    if not isinstance(data, dict):
        return None, (400, _json_error("invalid_request", "Request body must be a JSON object"))

    required_fields = ("intent_id", "correlation_id", "capability_name", "arguments")
    for field in required_fields:
        if field not in data:
            return None, (400, _json_error("invalid_request", f"Missing required field: {field}"))

    intent_id = data.get("intent_id")
    correlation_id = data.get("correlation_id")
    capability_name = data.get("capability_name")
    arguments = data.get("arguments")

    if not isinstance(intent_id, str) or not intent_id.strip():
        return None, (400, _json_error("invalid_request", "intent_id must be a non-empty string"))
    if not isinstance(correlation_id, str) or not correlation_id.strip():
        return None, (400, _json_error("invalid_request", "correlation_id must be a non-empty string"))
    if not isinstance(capability_name, str) or not capability_name.strip():
        return None, (400, _json_error("invalid_request", "capability_name must be a non-empty string"))
    if capability_name not in SUPPORTED_CAPABILITIES:
        return None, (400, _json_error("unsupported_capability", f"Unsupported capability: {capability_name}"))
    if not isinstance(arguments, dict):
        return None, (400, _json_error("invalid_request", "arguments must be a JSON object"))

    policy = data.get("policy")
    if not isinstance(policy, dict):
        return None, (400, _json_error("invalid_request", "policy must be a JSON object"))

    approval_id = policy.get("approval_id")
    if not isinstance(approval_id, str) or not _REF_ID_RE.fullmatch(approval_id.strip()):
        return None, (
            400,
            _json_error(
                "invalid_request",
                "policy.approval_id must be a non-empty identifier (6-128 chars, alnum/._:-)",
            ),
        )

    policy_decision_ref = policy.get("policy_decision_ref")
    if not isinstance(policy_decision_ref, str) or not _REF_ID_RE.fullmatch(policy_decision_ref.strip()):
        return None, (
            400,
            _json_error(
                "invalid_request",
                "policy.policy_decision_ref must be a non-empty identifier (6-128 chars, alnum/._:-)",
            ),
        )

    governance_ref = policy.get("governance_ref")
    if not isinstance(governance_ref, str) or not _REF_ID_RE.fullmatch(governance_ref.strip()):
        return None, (
            400,
            _json_error(
                "invalid_request",
                "policy.governance_ref must be a non-empty identifier (6-128 chars, alnum/._:-)",
            ),
        )

    capability_scope = policy.get("capability_scope")
    if not isinstance(capability_scope, str) or not capability_scope.strip():
        return None, (400, _json_error("invalid_request", "policy.capability_scope must be a non-empty string"))

    scope = capability_scope.strip()
    capability = capability_name.strip()
    if scope.endswith(".*"):
        scope_prefix = scope[:-2]
        scope_ok = bool(scope_prefix) and capability.startswith(f"{scope_prefix}.")
    else:
        scope_ok = scope == capability
    if not scope_ok:
        return None, (
            400,
            _json_error(
                "invalid_request",
                "policy.capability_scope does not authorize capability_name",
            ),
        )

    expires_at = policy.get("expires_at")
    if not isinstance(expires_at, str) or not expires_at.strip():
        return None, (400, _json_error("invalid_request", "policy.expires_at must be an RFC3339 timestamp"))
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return None, (400, _json_error("invalid_request", "policy.expires_at must be a valid RFC3339 timestamp"))
    if expires.tzinfo is None:
        return None, (400, _json_error("invalid_request", "policy.expires_at must include timezone information"))
    if expires <= datetime.now(timezone.utc):
        return None, (400, _json_error("invalid_request", "policy.expires_at is expired"))

    # All current Tier A capabilities require a URL argument.
    url_value = arguments.get("url")
    if not isinstance(url_value, str) or not url_value.strip():
        return None, (400, _json_error("invalid_request", "arguments.url must be a non-empty string"))

    return data, None


class OpenClawBackendHandler(BaseHTTPRequestHandler):
    server: "OpenClawBackendHTTPServer"

    def log_message(self, format: str, *args: Any) -> None:
        # Keep stdlib HTTP server noise out of stderr; structured logs are emitted explicitly.
        return

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _request_id(self, payload: dict[str, Any] | None = None) -> str:
        if isinstance(payload, dict):
            request_id = _safe_str(payload.get("intent_id"), "").strip()
            if request_id:
                return request_id
        return ""

    def _enforce_auth(self, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]] | None:
        config_error = config.get_auth_config_error()
        request_id = self._request_id(payload)
        if config_error:
            _log.error(
                "openclaw_auth_misconfigured path=%s request_id=%s error_type=auth_misconfigured",
                self.path,
                request_id,
            )
            return 503, _json_error(
                "auth_misconfigured",
                "Authentication is misconfigured",
                request_id=request_id,
            )

        token = self.headers.get(config.OPENCLAW_AUTH_HEADER_NAME, "")
        if not token:
            _log.warning(
                "openclaw_auth_rejected path=%s request_id=%s error_type=unauthorized reason=missing_header",
                self.path,
                request_id,
            )
            return 401, _json_error(
                "unauthorized",
                f"Missing authentication header: {config.OPENCLAW_AUTH_HEADER_NAME}",
                request_id=request_id,
            )
        if token != config.OPENCLAW_EXPECTED_AUTH_TOKEN:
            _log.warning(
                "openclaw_auth_rejected path=%s request_id=%s error_type=unauthorized reason=invalid_token",
                self.path,
                request_id,
            )
            return 401, _json_error("unauthorized", "Invalid authentication token", request_id=request_id)
        return None

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/ready":
            readiness = _runtime_readiness(self.server.runtime_dispatcher)
            auth_ok = config.get_auth_config_error() is None
            ready = auth_ok and readiness.get("runtime_usable", False)
            self._send_json(
                200 if ready else 503,
                {
                    "ok": ready,
                    "status": "ready" if ready else "not_ready",
                    "service": "openclaw_backend",
                    "version": config.SERVICE_VERSION,
                    "auth_configured": auth_ok,
                    **readiness,
                    "ts": _now_iso(),
                },
            )
            return

        if self.path != "/health":
            self._send_json(404, _json_error("not_found", f"Not found: {self.path}"))
            return

        status = _health_surface(self.server.runtime_dispatcher)
        auth_ok = config.get_auth_config_error() is None
        runtime_ready = status.get("runtime_usable", False)
        alive_state = "ok" if auth_ok and runtime_ready else "degraded"
        self._send_json(
            200,
            {
                "ok": True,
                "status": alive_state,
                "service": "openclaw_backend",
                "version": config.SERVICE_VERSION,
                **status,
                "auth_configured": auth_ok,
                "ts": _now_iso(),
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        started = time.perf_counter()
        if self.path != "/v1/machine-operator/execute":
            self._send_json(404, _json_error("not_found", f"Not found: {self.path}"))
            return

        content_length_raw = self.headers.get("Content-Length", "0")
        try:
            content_length = int(content_length_raw)
        except ValueError:
            self._send_json(400, _json_error("invalid_request", "Invalid Content-Length header"))
            return

        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            auth_error = self._enforce_auth(None)
            if auth_error:
                self._send_json(*auth_error)
                return
            self._send_json(400, _json_error("invalid_request", "Malformed JSON body"))
            return

        auth_error = self._enforce_auth(payload if isinstance(payload, dict) else None)
        if auth_error:
            self._send_json(*auth_error)
            return

        validated, validation_error = _validate_execute_request(payload)
        if validation_error:
            self._send_json(*validation_error)
            return

        assert validated is not None
        intent_id = validated["intent_id"]
        correlation_id = validated["correlation_id"]
        capability_name = validated["capability_name"]
        arguments = validated["arguments"]

        execution_cfg = validated.get("execution", {})
        timeout_seconds = 5.0
        reuse_session = False
        close_session = True
        workflow_execution_id = ""
        if isinstance(execution_cfg, dict):
            raw_timeout = execution_cfg.get("timeout_seconds", 5.0)
            try:
                timeout_seconds = float(raw_timeout)
            except (TypeError, ValueError):
                timeout_seconds = 5.0
            reuse_session = bool(execution_cfg.get("reuse_session", False))
            close_session = bool(execution_cfg.get("close_session", True))
            workflow_execution_id = _safe_str(execution_cfg.get("workflow_execution_id"), "").strip()

        request_context = {
            "ts": _now_iso(),
            "intent_id": intent_id,
            "correlation_id": correlation_id,
            "capability": capability_name,
        }

        # ── Sovereign enforcement gate ────────────────────────────────────────
        # This check runs AFTER auth and request validation, BEFORE any runtime
        # call.  A blocked decision makes execution impossible — no fallback.
        _policy = validated.get("policy", {})
        _sovereign_query = SovereignExecutionQuery(
            approval_id=_safe_str(_policy.get("approval_id")),
            capability_name=capability_name,
            capability_scope=_safe_str(_policy.get("capability_scope")),
            expires_at=_safe_str(_policy.get("expires_at")),
            policy_decision_ref=_safe_str(_policy.get("policy_decision_ref")),
            governance_ref=_safe_str(_policy.get("governance_ref")),
            trace_id=intent_id,
            plan_id=_safe_str(validated.get("plan_id")),
            intent_id=intent_id,
            correlation_id=correlation_id,
            target_domain="MACHINE_OPERATOR",
            target_action=capability_name,
        )
        _sovereign_decision = _sovereign_store.is_execution_allowed(_sovereign_query)
        _audit_common: dict[str, Any] = {
            "timestamp": _now_iso(),
            "intent_id": intent_id,
            "correlation_id": correlation_id,
            "approval_id": _sovereign_query.approval_id,
            "capability_name": capability_name,
            "policy_decision_ref": _sovereign_query.policy_decision_ref,
            "governance_ref": _sovereign_query.governance_ref,
        }
        _log.info(
            "openclaw_sovereign_check ts=%s intent_id=%s capability=%s allowed=%s "
            "reason_code=%s kill_switch_state=%s approval_id=%s",
            request_context["ts"],
            intent_id,
            capability_name,
            _sovereign_decision.allowed,
            _sovereign_decision.reason.code,
            _sovereign_decision.kill_switch_state,
            _sovereign_query.approval_id,
        )
        emit_audit_event(
            {
                **_audit_common,
                "outcome": "allowed" if _sovereign_decision.allowed else "blocked",
                "reason_code": _sovereign_decision.reason.code,
                "kill_switch_state": _sovereign_decision.kill_switch_state,
                "event_type": "execution_attempt",
            }
        )
        if not _sovereign_decision.allowed:
            emit_audit_event(
                {
                    **_audit_common,
                    "outcome": "blocked",
                    "reason_code": _sovereign_decision.reason.code,
                    "kill_switch_state": _sovereign_decision.kill_switch_state,
                    "event_type": "sovereign_blocked",
                }
            )
            self._send_json(
                403,
                _sovereign_blocked_response(
                    decision=_sovereign_decision,
                    request_id=intent_id,
                ),
            )
            return
        # ── End sovereign gate ────────────────────────────────────────────────

        try:
            runtime_result: RuntimeResult = self.server.runtime_dispatcher.execute(
                capability_name=capability_name,
                arguments=arguments,
                timeout_seconds=timeout_seconds,
                reuse_session=reuse_session,
                close_session=close_session,
                workflow_execution_id=workflow_execution_id,
                intent_id=intent_id,
                correlation_id=correlation_id,
            )
        except RuntimeUnavailableError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            emit_audit_event(
                {
                    **_audit_common,
                    "outcome": "failed",
                    "reason_code": "runtime_unavailable",
                    "kill_switch_state": _sovereign_decision.kill_switch_state,
                    "event_type": "runtime_failure",
                }
            )
            response = _build_failed_execution(
                error_type="runtime_unavailable",
                message=str(exc),
                capability_name=capability_name,
                intent_id=intent_id,
                correlation_id=correlation_id,
                latency_ms=latency_ms,
            )
            _log.warning(
                "openclaw_execute_failed ts=%s intent_id=%s correlation_id=%s capability=%s status=failed error_type=runtime_unavailable latency_ms=%s",
                request_context["ts"],
                intent_id,
                correlation_id,
                capability_name,
                latency_ms,
            )
            self._send_json(200, response)
            return
        except TimeoutError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            emit_audit_event(
                {
                    **_audit_common,
                    "outcome": "failed",
                    "reason_code": "timeout",
                    "kill_switch_state": _sovereign_decision.kill_switch_state,
                    "event_type": "runtime_failure",
                }
            )
            response = _build_failed_execution(
                error_type="timeout",
                message=str(exc),
                capability_name=capability_name,
                intent_id=intent_id,
                correlation_id=correlation_id,
                latency_ms=latency_ms,
            )
            _log.warning(
                "openclaw_execute_failed ts=%s intent_id=%s correlation_id=%s capability=%s status=failed error_type=timeout latency_ms=%s",
                request_context["ts"],
                intent_id,
                correlation_id,
                capability_name,
                latency_ms,
            )
            self._send_json(200, response)
            return
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            emit_audit_event(
                {
                    **_audit_common,
                    "outcome": "failed",
                    "reason_code": "execution_failed",
                    "kill_switch_state": _sovereign_decision.kill_switch_state,
                    "event_type": "runtime_failure",
                }
            )
            response = _build_failed_execution(
                error_type="execution_failed",
                message=str(exc),
                capability_name=capability_name,
                intent_id=intent_id,
                correlation_id=correlation_id,
                latency_ms=latency_ms,
            )
            _log.exception(
                "openclaw_execute_exception ts=%s intent_id=%s correlation_id=%s capability=%s status=failed error_type=execution_failed latency_ms=%s",
                request_context["ts"],
                intent_id,
                correlation_id,
                capability_name,
                latency_ms,
            )
            self._send_json(200, response)
            return

        latency_ms = int((time.perf_counter() - started) * 1000)
        response: dict[str, Any] = {
            "status": runtime_result.status,
            "intent_id": intent_id,
            "correlation_id": correlation_id,
            "observation": runtime_result.observation,
            "evidence_refs": runtime_result.evidence_refs,
            "consumed_budget": {
                "steps": int(runtime_result.consumed_budget.get("steps", 1)),
                "duration_ms": max(int(runtime_result.consumed_budget.get("duration_ms", latency_ms)), latency_ms),
                "output_bytes": int(runtime_result.consumed_budget.get("output_bytes", 0)),
                "side_effects": 0,
            },
            "side_effects_declared": [],
            "metadata": {
                "backend": "openclaw_backend",
            },
            "backend_execution_performed": runtime_result.status in {"ok", "partial"},
            "machine_action_performed": runtime_result.status in {"ok", "partial"},
        }
        if runtime_result.final_url:
            response["final_url"] = runtime_result.final_url

        if runtime_result.status in {"ok", "partial"}:
            emit_audit_event(
                {
                    **_audit_common,
                    "outcome": "allowed",
                    "reason_code": runtime_result.status,
                    "kill_switch_state": _sovereign_decision.kill_switch_state,
                    "event_type": "execution_success",
                }
            )
        else:
            emit_audit_event(
                {
                    **_audit_common,
                    "outcome": "failed",
                    "reason_code": runtime_result.status,
                    "kill_switch_state": _sovereign_decision.kill_switch_state,
                    "event_type": "runtime_failure",
                }
            )

        _log.info(
            "openclaw_execute ts=%s intent_id=%s correlation_id=%s capability=%s status=%s latency_ms=%s",
            request_context["ts"],
            intent_id,
            correlation_id,
            capability_name,
            runtime_result.status,
            latency_ms,
        )
        self._send_json(200, response)


class OpenClawBackendHTTPServer(HTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        host: str,
        port: int,
        *,
        runtime_dispatcher: RuntimeDispatcher | None = None,
    ):
        # Assign dispatcher before bind so server_close() remains safe even if
        # HTTPServer.__init__ fails while binding the socket.
        self.runtime_dispatcher: RuntimeDispatcher = runtime_dispatcher or create_default_runtime_dispatcher()
        super().__init__((host, port), OpenClawBackendHandler)

    def server_close(self) -> None:
        try:
            dispatcher = getattr(self, "runtime_dispatcher", None)
            if dispatcher is not None:
                dispatcher.close_all()
        finally:
            super().server_close()


def run_server(
    host: str = config.OPENCLAW_BACKEND_HOST,
    port: int = config.OPENCLAW_BACKEND_PORT,
    *,
    runtime_dispatcher: RuntimeDispatcher | None = None,
    require_ready: bool = config.OPENCLAW_STARTUP_REQUIRE_READY,
) -> None:
    try:
        server = OpenClawBackendHTTPServer(host, port, runtime_dispatcher=runtime_dispatcher)
    except OSError:
        _log.exception("openclaw_startup_bind_failed host=%s port=%s", host, port)
        raise

    try:
        _run_startup_preflight(server, require_ready=require_ready)
    except Exception:
        _log.exception("openclaw_startup_preflight_failed host=%s port=%s", host, port)
        server.server_close()
        raise

    shutdown_requested = threading.Event()
    previous_handlers: dict[int, Any] = {}

    def _request_shutdown(reason: str) -> None:
        if shutdown_requested.is_set():
            return
        shutdown_requested.set()
        _log.info("openclaw_shutdown_requested reason=%s", reason)
        threading.Thread(target=server.shutdown, daemon=True).start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda _signum, _frame, sig_name=sig.name.lower(): _request_shutdown(sig_name))
        except ValueError:
            pass

    _log.info("OpenClaw backend listening on http://%s:%s", host, port)
    _log.info("Endpoint: POST /v1/machine-operator/execute")
    _log.info("Endpoint: GET /health")
    _log.info("Endpoint: GET /ready")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _request_shutdown("keyboard_interrupt")
    finally:
        for sig, previous in previous_handlers.items():
            try:
                signal.signal(sig, previous)
            except ValueError:
                pass
        server.server_close()
        _log.info("openclaw_shutdown_complete")


def start_server_thread(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    runtime_dispatcher: RuntimeDispatcher | None = None,
    require_ready: bool = False,
) -> tuple[OpenClawBackendHTTPServer, int]:
    server = OpenClawBackendHTTPServer(host, port, runtime_dispatcher=runtime_dispatcher)
    _run_startup_preflight(server, require_ready=require_ready)
    actual_port = server.server_address[1]
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.05},
        daemon=True,
    )
    thread.start()
    return server, actual_port


def _run_startup_preflight(server: OpenClawBackendHTTPServer, *, require_ready: bool) -> None:
    auth_error = config.get_auth_config_error()
    readiness = _runtime_readiness(server.runtime_dispatcher)
    python_env_ready = readiness.get("python_env_ready", False)
    _log.info(
        "openclaw_startup_preflight auth_configured=%s runtime_usable=%s runtime_importable=%s browser_binaries_available=%s evidence_dir_writable=%s python_env_ready=%s python_executable=%s",
        auth_error is None,
        readiness.get("runtime_usable", False),
        readiness.get("runtime_importable", False),
        readiness.get("browser_binaries_available", False),
        readiness.get("evidence_dir_writable", False),
        python_env_ready,
        sys.executable,
    )

    if not require_ready:
        return
    if not python_env_ready:
        _log.error("openclaw_startup_blocked reason=python_env_not_ready")
        raise RuntimeError("OpenClaw backend startup blocked: python environment is not ready.")
    if auth_error:
        _log.error("openclaw_startup_blocked reason=auth_misconfigured detail=%s", auth_error)
        raise RuntimeError(f"OpenClaw backend startup blocked: {auth_error}")
    if not readiness.get("runtime_usable", False):
        _log.error("openclaw_startup_blocked reason=runtime_not_ready")
        raise RuntimeError(
            "OpenClaw backend startup blocked: runtime is not ready "
            "(check Playwright install, browser binaries, and evidence directory writability)."
        )
