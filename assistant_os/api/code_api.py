"""
code_api.py — HTTP adapter for triggering CODE executions from n8n (or any HTTP client).

Endpoint: POST /api/code/execute
Server:   http://localhost:8000  (configurable via CODE_API_PORT env var)
Auth:     Optional X-API-KEY header validated against CODE_API_KEY env var.
          If CODE_API_KEY is not set, auth is disabled.

Zero new dependencies — uses only the standard library + the existing Runner.
"""

from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import os
import traceback
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..runners.metadata_utils import EXECUTIONS_ROOT, patch_execution_metadata
from ..runners.runner_models import RunnerExecutionRequest
from ..sandbox.authorized_plan import AuthorizedPlan, KNOWN_POLICY_IDS

# ---------------------------------------------------------------------------
# Configuration (from environment / .env loaded by caller)
# ---------------------------------------------------------------------------

PORT: int = int(os.environ.get("CODE_API_PORT", "8000"))
API_KEY: Optional[str] = os.environ.get("CODE_API_KEY") or None
LOG_PATH = Path(__file__).parent.parent.parent / "logs" / "code_api.log"

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logger() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("code_api")
    if logger.handlers:
        return logger  # already configured (e.g. in tests)
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    # Rotating file handler — max 5 MB × 3 backups
    fh = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


logger = _setup_logger()

# ---------------------------------------------------------------------------
# Request / response helpers
# ---------------------------------------------------------------------------

def _ok(data: Dict[str, Any]) -> bytes:
    return json.dumps(data, indent=2).encode()


def _error_response(
    message: str,
    execution_id: Optional[str] = None,
    detail: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "execution_id": execution_id,
        "final_status": "failed",
        "summary": message,
        "report_json_path": None,
        "report_md_path": None,
        "done_path": None,
        "error": detail or message,
    }


def _validate_payload(body: Dict[str, Any]) -> Optional[str]:
    """Return an error string if the payload is invalid, else None."""
    if not body.get("repo_path", "").strip():
        return "repo_path is required and must not be empty."
    test_spec = body.get("test_spec")
    if test_spec is not None:
        if not isinstance(test_spec, dict):
            return "test_spec must be a JSON object."
        if not test_spec.get("command"):
            return "test_spec.command is required and must be a non-empty list."
    return None


def _build_execution_id(body: Dict[str, Any]) -> str:
    """Derive a stable execution_id from request_id, or generate one."""
    request_id = str(body.get("request_id", "")).strip()
    if request_id:
        # Sanitise: strip slashes and dots that would break the artifacts path
        safe = request_id.replace("/", "_").replace("\\", "_").replace("..", "__")
        return f"n8n_{safe}"
    return f"n8n_{uuid.uuid4().hex[:12]}"


def _build_request_snapshot(body: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a minimal snapshot of the original request for future rerun."""
    return {
        "repo_path":       body.get("repo_path"),
        "changes":         body.get("changes") or None,
        "test_spec":       body.get("test_spec") or None,
        "validation_spec": body.get("validation_spec") or None,
        "source":          body.get("source", "unknown"),
        "mode":            body.get("mode", "code_execution"),
        "metadata":        body.get("metadata") or None,
        # M1B governance fields — preserved so reruns carry the same policy binding.
        "plan_id":          body.get("plan_id") or None,
        "policy_id":        body.get("policy_id") or None,
        "capability_scope": body.get("capability_scope") or None,
        "code":             body.get("code") or None,
    }


def _build_authorized_plan(
    execution_id: str,
    body: Dict[str, Any],
) -> AuthorizedPlan:
    """Build and return an AuthorizedPlan for every execution from code_api.

    The plan is ALWAYS constructed so that every execution entering this path
    carries a real governance binding (policy_id, plan_id, capability_scope).

    Fields
    ------
    plan_id         : from body if provided, else auto-generated.
    policy_id       : from body if valid, else "default".
    capability_scope: from body if non-empty list, else ["code_execute"].
    authorized_plan_hash: SHA-256 of the canonicalised plan identity dict.
                          Deterministic: same inputs → same hash, which makes
                          reruns traceable back to the original plan content.
    """
    plan_id = str(body.get("plan_id") or "").strip() or f"plan_{uuid.uuid4().hex[:12]}"

    raw_policy = str(body.get("policy_id") or "default").strip()
    policy_id = raw_policy if raw_policy in KNOWN_POLICY_IDS else "default"

    capability_scope: List[str] = body.get("capability_scope") or []
    if not isinstance(capability_scope, list) or not capability_scope:
        capability_scope = ["code_execute"]

    # Deterministic hash over the plan identity fields — NOT over secret values.
    plan_content = {
        "execution_id": execution_id,
        "plan_id": plan_id,
        "policy_id": policy_id,
        "capability_scope": sorted(capability_scope),
        "repo_path": str(body.get("repo_path", "")),
    }
    authorized_plan_hash = hashlib.sha256(
        json.dumps(plan_content, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    return AuthorizedPlan(
        execution_id=execution_id,
        plan_id=plan_id,
        authorized_plan_hash=authorized_plan_hash,
        policy_id=policy_id,
        capability_scope=capability_scope,
    )



def handle_execute(body: Dict[str, Any]) -> Dict[str, Any]:
    """External adapter for n8n / HTTP clients — validate, authorize, run, return.

    Scope
    -----
    This function is the execution entry point for EXTERNAL clients (n8n, CI
    pipelines, direct HTTP callers).  It is NOT on the chat path.

    The chat path for CODE domain requests flows exclusively through:
      CanonicalRequest → orchestrator → planner → policy → code_pipeline

    Governance
    ----------
    AuthorizedPlan is built here for the external path only.  It carries a
    governance binding (plan_id, policy_id, capability_scope) derived from the
    HTTP request body.  This is intentionally separate from the kernel-issued
    AuthorizedPlan, which is built inside code_pipeline._apply_code_proposal
    and always carries execution_id == kernel plan_id.

    Residual authority
    ------------------
    code_api retains full permission/decision authority for the external path.
    This is by design: external clients do not go through the kernel orchestrator.
    No conflict arises because both paths serve different clients and produce
    independent execution IDs.

    Separated from the HTTP layer so it can be tested without a live server.
    """
    request_id = str(body.get("request_id", ""))
    execution_id = _build_execution_id(body)

    logger.info("REQUEST request_id=%s execution_id=%s repo=%s",
                request_id, execution_id, body.get("repo_path"))

    # Validate
    err = _validate_payload(body)
    if err:
        logger.warning("VALIDATION_FAILED execution_id=%s error=%s", execution_id, err)
        return _error_response(err, execution_id=execution_id)

    # Build AuthorizedPlan — every execution from code_api carries a governance binding.
    authorized_plan = _build_authorized_plan(execution_id, body)
    logger.info(
        "AUTHORIZED_PLAN execution_id=%s plan_id=%s policy_id=%s",
        execution_id, authorized_plan.plan_id, authorized_plan.policy_id,
    )

    # Build RunnerExecutionRequest — authorized_plan and code are M1B fields.
    # code triggers Docker sandbox execution in RunnerService (Phase 2.5).
    code: Optional[str] = body.get("code") or None
    request = RunnerExecutionRequest(
        execution_id=execution_id,
        repo_path=body["repo_path"],
        changes=body.get("changes") or None,
        test_spec=body.get("test_spec") or None,
        validation_spec=body.get("validation_spec") or None,
        metadata={
            "source": body.get("source", "unknown"),
            "mode": body.get("mode", "code_execution"),
            **(body.get("metadata") or {}),
        },
        authorized_plan=authorized_plan,
        code=code,
    )

    # Execute — via agent registry (consistent with kernel path).
    # Deferred import mirrors the pattern used in code_pipeline._apply_code_proposal.
    from ..agents.registry import get_agent
    _agent = get_agent("code_executor")
    try:
        result = _agent["entrypoint"](request)
    except Exception as exc:
        detail = traceback.format_exc()
        logger.error("RUNNER_ERROR execution_id=%s error=%s", execution_id, exc)
        return _error_response("Runner raised an unexpected exception.", execution_id, detail)

    logger.info("DONE execution_id=%s final_status=%s agent=%s",
                execution_id, result.final_status, _agent["name"])

    # Agent invocation metadata — mirrors audit_summary.agent_invocation in kernel path.
    agent_invocation = {
        "agent_name":             _agent["name"],
        "agent_version":          _agent["version"],
        "agent_requires_review":  _agent["requires_review"],
        "agent_capability_scope": _agent["capability_scope"],
    }

    # Persist request snapshot + agent_invocation to metadata.json (best-effort, non-fatal).
    # Persisting agent_invocation here closes the trazabilidad gap: GET /executions/{id}
    # can now read it from disk rather than relying on in-memory state.
    patch_execution_metadata(result.execution_id, {
        "request_snapshot": _build_request_snapshot(body),
        "agent_invocation": agent_invocation,
    })

    return {
        "ok": True,             # normalize envelope (consumed by frontend apiFetch)
        "execution_id":   result.execution_id,
        "final_status":   result.final_status,
        "summary":        result.summary,
        "report_json_path": result.report_json_path,
        "report_md_path": result.report_md_path,
        "done_path":      result.notification_path,
        "error":          result.error,
        "agent_invocation": agent_invocation,
    }


# ---------------------------------------------------------------------------
# Execution listing and detail
# EXECUTIONS_ROOT is imported from runners.metadata_utils — single definition.
# ---------------------------------------------------------------------------


def _safe_exec_id(raw: str) -> Optional[str]:
    """Sanitise execution_id to prevent path traversal. Returns None if invalid."""
    eid = raw.strip()
    if not eid or "/" in eid or "\\" in eid or ".." in eid or eid.startswith("."):
        return None
    return eid


def handle_list_executions() -> Dict[str, Any]:
    """List all execution directories sorted by start time (most recent first)."""
    if not EXECUTIONS_ROOT.exists():
        return {"ok": True, "executions": [], "count": 0}

    results = []
    for d in EXECUTIONS_ROOT.iterdir():
        if not d.is_dir():
            continue
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("LIST_SKIP dir=%s error=%s", d.name, exc)
            continue

        results.append({
            "execution_id":    meta.get("execution_id", d.name),
            "final_status":    meta.get("final_status") or "unknown",
            "summary":         meta.get("summary", ""),
            "timestamp":       meta.get("started_at", ""),
            "report_json_path": str(d / "report.json") if (d / "report.json").exists() else None,
            "report_md_path":   str(d / "report.md")   if (d / "report.md").exists()   else None,
            "done_path":        str(d / "done.json")    if (d / "done.json").exists()    else None,
            "metadata_path":    str(meta_path),
            "source":           (meta.get("metadata") or {}).get("source", "unknown"),
        })

    results.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    return {"ok": True, "executions": results, "count": len(results)}


def handle_get_execution(execution_id: str) -> Optional[Dict[str, Any]]:
    """Return metadata + report + log for one execution. None if not found."""
    safe_id = _safe_exec_id(execution_id)
    if not safe_id:
        return None

    exec_dir = EXECUTIONS_ROOT / safe_id
    if not exec_dir.is_dir():
        return None

    meta_path = exec_dir / "metadata.json"
    if not meta_path.exists():
        return None

    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("DETAIL_ERROR id=%s error=%s", execution_id, exc)
        return None

    report: Optional[Dict[str, Any]] = None
    report_path = exec_dir / "report.json"
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass  # report is optional

    log_path = exec_dir / "runner.log"
    log_content: Optional[str] = None
    if log_path.exists():
        try:
            log_content = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    report_md_path = exec_dir / "report.md"

    review: Optional[Dict[str, Any]] = None
    review_path = exec_dir / "review.json"
    if review_path.exists():
        try:
            review = json.loads(review_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Derive review_status from the human decision stored in review.json.
    # None when no review exists.  Never overrides or conflates with final_status.
    review_status: Optional[str] = (
        _REVIEW_STATUS_MAP.get(review.get("review_action", ""))
        if review else None
    )

    # Derive execution_assessment: combined visible interpretation of the execution.
    # Reads final_status from metadata (system layer) + review_status (human layer).
    execution_assessment: str = _derive_execution_assessment(
        final_status=metadata.get("final_status"),
        review_status=review_status,
    )

    # agent_invocation — read from metadata.json if persisted; None for older executions.
    agent_invocation: Optional[Dict[str, Any]] = metadata.get("agent_invocation")

    return {
        "ok": True,
        "metadata": metadata,
        "report": report,
        "report_md_path": str(report_md_path) if report_md_path.exists() else None,
        "log_path": str(log_path) if log_path.exists() else None,
        "log_content": log_content,
        "review":               review,
        "review_status":        review_status,
        "execution_assessment": execution_assessment,
        "agent_invocation":     agent_invocation,
        "rerun_of":             metadata.get("rerun_of"),
        "has_snapshot":         "request_snapshot" in metadata,
    }


def handle_rerun_execution(execution_id: str) -> Dict[str, Any]:
    """Rerun an execution using its stored request_snapshot.

    Raises:
        ValueError: if execution not found, or snapshot missing (no rerun available).
    """
    safe_id = _safe_exec_id(execution_id)
    if not safe_id:
        raise ValueError(f"Invalid execution_id: {execution_id!r}")

    exec_dir = EXECUTIONS_ROOT / safe_id
    if not exec_dir.is_dir():
        raise LookupError(f"Execution not found: {execution_id}")

    meta_path = exec_dir / "metadata.json"
    if not meta_path.exists():
        raise LookupError(f"Execution not found: {execution_id}")

    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Could not read execution metadata: {exc}") from exc

    snapshot = metadata.get("request_snapshot")
    if not snapshot:
        raise ValueError(
            "This execution has no stored request snapshot. "
            "Rerun is only available for executions created after Sprint 7."
        )

    if not snapshot.get("repo_path"):
        raise ValueError("Stored snapshot is missing repo_path. Cannot rerun.")

    # Reconstruct the request body from the snapshot
    new_request_id = f"rerun_{safe_id[:20]}_{uuid.uuid4().hex[:6]}"
    body: Dict[str, Any] = {
        "request_id":      new_request_id,
        "repo_path":       snapshot["repo_path"],
        "changes":         snapshot.get("changes"),
        "test_spec":       snapshot.get("test_spec"),
        "validation_spec": snapshot.get("validation_spec"),
        "source":          "rerun",
        "mode":            snapshot.get("mode", "code_execution"),
        "metadata": {
            **(snapshot.get("metadata") or {}),
            "rerun_of":     safe_id,
            "trigger_type": "rerun",
        },
    }

    logger.info("RERUN original_id=%s new_request_id=%s", safe_id, new_request_id)
    response = handle_execute(body)

    # Tag the new execution with rerun_of (best-effort)
    new_exec_id = response.get("execution_id")
    if new_exec_id:
        _patch_metadata(new_exec_id, {"rerun_of": safe_id})

    response["rerun_of"] = safe_id
    return response


_VALID_REVIEW_ACTIONS = {"approved", "rejected", "needs_followup"}

# Maps review_action (human decision) → review_status (derived system label).
# Kept separate from final_status, which describes what the runner produced.
_REVIEW_STATUS_MAP: Dict[str, str] = {
    "approved":        "accepted",
    "rejected":        "rejected",
    "needs_followup":  "pending_followup",
}


def _derive_execution_assessment(
    final_status: Optional[str],
    review_status: Optional[str],
) -> str:
    """Combine final_status and review_status into a single visible assessment.

    Three distinct layers — none overrides the others:
      final_status        : what the runner produced (technical result)
      review_status       : what the human decided (evaluation)
      execution_assessment: the combined visible interpretation

    Priority rules (in order):
      1. failed is terminal — no human review changes a failed run.
      2. If a human decision exists, it is the primary signal.
      3. No human decision: derive from runner status.
      4. Unknown combinations: "unknown" (explicit, never silent).
    """
    if final_status == "failed":
        return "failed"

    if review_status == "accepted":
        return "accepted"
    if review_status == "rejected":
        return "rejected_after_review"
    if review_status == "pending_followup":
        return "awaiting_followup"

    # No human decision yet.
    if final_status == "needs_review":
        return "awaiting_review"
    if final_status == "success":
        return "completed_unreviewed"

    return "unknown"


def handle_review_execution(execution_id: str, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Write review.json for a human review decision. Returns None if execution not found.

    Required body fields: review_action, reviewed_by
    Optional body fields: review_notes

    Raises ValueError on invalid payload.
    """
    safe_id = _safe_exec_id(execution_id)
    if not safe_id:
        return None

    exec_dir = EXECUTIONS_ROOT / safe_id
    if not exec_dir.is_dir():
        return None

    review_action = str(body.get("review_action") or "").strip().lower()
    if not review_action:
        raise ValueError("review_action is required.")
    if review_action not in _VALID_REVIEW_ACTIONS:
        raise ValueError(
            f"Invalid review_action: {review_action!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_REVIEW_ACTIONS))}"
        )

    reviewed_by = str(body.get("reviewed_by") or "").strip()
    if not reviewed_by:
        raise ValueError("reviewed_by is required.")

    review_notes = str(body.get("review_notes") or "").strip()
    reviewed_at = datetime.now(timezone.utc).isoformat()

    review = {
        "execution_id":  safe_id,
        "review_action": review_action,
        "review_notes":  review_notes,
        "reviewed_by":   reviewed_by,
        "reviewed_at":   reviewed_at,
    }

    review_path = exec_dir / "review.json"
    review_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    logger.info("REVIEW id=%s action=%s reviewed_by=%s", safe_id, review_action, reviewed_by)

    return {
        "ok":     True,
        "review": review,
    }


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class CodeAPIHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler — POST /api/code/execute only."""

    # Origins allowed to call this API from a browser.
    _CORS_ORIGINS = {"http://localhost:3100", "http://127.0.0.1:3100"}

    # Suppress default access log to stderr (we have our own)
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass

    def _cors_origin(self) -> str:
        """Return the request origin if it is allowed, else empty string."""
        origin = self.headers.get("Origin", "")
        return origin if origin in self._CORS_ORIGINS else ""

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight requests."""
        origin = self._cors_origin()
        self.send_response(204)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-KEY")
            self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]

        # --- optional API-key check ---
        if API_KEY:
            provided = self.headers.get("X-API-KEY", "")
            if provided != API_KEY:
                logger.warning("AUTH_FAILED from %s", self.client_address)
                self._send(401, {"error": "Invalid or missing X-API-KEY."})
                return

        # --- parse body ---
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"error": f"Invalid JSON: {exc}"})
            return

        # --- dispatch ---
        if path == "/api/code/execute":
            try:
                response = handle_execute(body)
                self._send(200, response)
            except Exception as exc:
                logger.exception("INTERNAL_ERROR")
                self._send(500, _error_response("Internal server error.", detail=str(exc)))

        elif path.startswith("/api/code/executions/") and path.endswith("/rerun"):
            # POST /api/code/executions/{execution_id}/rerun
            inner = path[len("/api/code/executions/"):-len("/rerun")]
            if not inner:
                self._send(400, {"error": "execution_id required"})
                return
            try:
                result = handle_rerun_execution(inner)
                result["ok"] = True   # normalize envelope (execute response lacks ok field)
                self._send(200, result)
            except LookupError as exc:
                self._send(404, {"error": str(exc)})
            except ValueError as exc:
                self._send(409, {"error": str(exc)})
            except Exception as exc:
                logger.exception("RERUN_ERROR id=%s", inner)
                self._send(500, {"error": str(exc)})

        elif path.startswith("/api/code/executions/") and path.endswith("/review"):
            # POST /api/code/executions/{execution_id}/review
            inner = path[len("/api/code/executions/"):-len("/review")]
            if not inner:
                self._send(400, {"error": "execution_id required"})
                return
            try:
                result = handle_review_execution(inner, body)
                if result is None:
                    self._send(404, {"error": f"Execution not found: {inner}"})
                else:
                    self._send(200, result)
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:
                logger.exception("REVIEW_ERROR id=%s", inner)
                self._send(500, {"error": str(exc)})

        else:
            self._send(404, {"error": f"Unknown endpoint: {self.path}"})

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]  # strip query string
        if path in ("/health", "/"):
            self._send(200, {"status": "ok", "service": "code_api"})
        elif path == "/api/code/executions":
            try:
                self._send(200, handle_list_executions())
            except Exception as exc:
                logger.exception("LIST_ERROR")
                self._send(500, {"ok": False, "error": str(exc)})
        elif path.startswith("/api/code/executions/"):
            execution_id = path[len("/api/code/executions/"):]
            if not execution_id:
                self._send(400, {"error": "execution_id required"})
                return
            detail = handle_get_execution(execution_id)
            if detail is None:
                self._send(404, {"error": f"Execution not found: {execution_id}"})
            else:
                self._send(200, detail)
        else:
            self._send(404, {"error": "Not found."})

    def _send(self, status: int, data: Dict[str, Any]) -> None:
        body = _ok(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_server(port: int = PORT) -> HTTPServer:
    """Create and return an HTTPServer bound to *port* (not yet started)."""
    return HTTPServer(("localhost", port), CodeAPIHandler)


def run(port: int = PORT) -> None:
    """Start the server and block until interrupted."""
    server = create_server(port)
    logger.info("CODE API listening on http://localhost:%d", port)
    logger.info("Endpoint: POST http://localhost:%d/api/code/execute", port)
    if API_KEY:
        logger.info("Auth: X-API-KEY required")
    else:
        logger.info("Auth: DISABLED (set CODE_API_KEY env var to enable)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down.")
    finally:
        server.server_close()
