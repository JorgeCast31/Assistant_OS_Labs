#!/usr/bin/env python3
"""
Backend-only smoke/demo for the confirmed HOST outcome flow.

Flow:
    POST /host/action
    GET /confirm/pending
    POST /host/confirm
    GET /mso/outcome/status?plan_id=<PLAN_ID>
"""

from __future__ import annotations

import argparse
import ast
import http.client
import json
import os
import sys
import time
import uuid
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import urlencode, urlparse

DEFAULT_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_TOKEN_ENV = "WEBHOOK_TOKEN"
REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class DemoError(RuntimeError):
    """Expected demo failure with a concise operator-facing message."""


def _default_sandbox_root() -> str:
    try:
        host_agent_path = REPO_ROOT / "assistant_os" / "agents" / "host_agent.py"
        module = ast.parse(host_agent_path.read_text(encoding="utf-8"))
        for node in module.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "WRITE_SANDBOX_DIRECTORIES" and node.value is not None:
                    sandbox_dirs = ast.literal_eval(node.value)
                    if isinstance(sandbox_dirs, list) and sandbox_dirs:
                        return str(sandbox_dirs[0])
        raise DemoError("WRITE_SANDBOX_DIRECTORIES was not found")
    except Exception as exc:  # noqa: BLE001 - demo should fail clearly
        raise DemoError(f"Unable to load HOST write sandbox root: {exc}") from exc


def _json_dumps(data: Any) -> bytes:
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


def _read_json_response(response: http.client.HTTPResponse) -> dict[str, Any]:
    raw = response.read().decode("utf-8", errors="replace")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DemoError(f"Backend returned non-JSON response: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise DemoError(f"Backend returned JSON {type(data).__name__}, expected object")
    return data


def request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, Any]]:
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise DemoError(f"Invalid --base-url: {base_url!r}")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise DemoError(f"--base-url must target local backend only, got host: {parsed.hostname!r}")

    port = parsed.port or 80
    headers: dict[str, str] = {}
    payload = None
    if token is not None:
        headers["X-Assistant-Token"] = token
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = _json_dumps(body)

    try:
        conn = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        data = _read_json_response(response)
        status = response.status
        conn.close()
        return status, data
    except OSError as exc:
        raise DemoError(f"Backend did not respond at {base_url}: {exc}") from exc


def _extract_plan_id(data: dict[str, Any]) -> str | None:
    candidates = [
        data.get("plan_id"),
        data.get("data", {}).get("plan_id") if isinstance(data.get("data"), dict) else None,
        (
            data.get("data", {}).get("plan", {}).get("plan_id")
            if isinstance(data.get("data"), dict) and isinstance(data.get("data", {}).get("plan"), dict)
            else None
        ),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _contains_plan_id(value: Any, plan_id: str) -> bool:
    if value == plan_id:
        return True
    if isinstance(value, dict):
        return any(_contains_plan_id(item, plan_id) for item in value.values())
    if isinstance(value, list):
        return any(_contains_plan_id(item, plan_id) for item in value)
    return False


def _safe_demo_path(sandbox_root: str) -> str:
    root = PureWindowsPath(sandbox_root)
    if not root.is_absolute():
        raise DemoError(f"--sandbox-root must be an absolute sandbox path, got: {sandbox_root!r}")
    suffix = f"backend_outcome_demo_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    return str(root / suffix)


def _print_step(message: str) -> None:
    print(f"[demo] {message}")


def _print_json(label: str, data: dict[str, Any]) -> None:
    print(f"[demo] {label}: {json.dumps(data, indent=2, sort_keys=True)}")


def run_demo(args: argparse.Namespace) -> int:
    sandbox_root = args.sandbox_root or _default_sandbox_root()
    demo_path = _safe_demo_path(sandbox_root)
    host_action_body = {
        "action": "create_directory",
        "payload": {
            "path": demo_path,
            "confirmed": True,
        },
    }

    if args.dry_run:
        _print_step("dry run only; no backend requests will be sent")
        _print_step(f"base_url={args.base_url}")
        _print_step(f"token_env={args.token_env}")
        _print_step(f"sandbox_demo_path={demo_path}")
        _print_json("POST /host/action body", host_action_body)
        return 0

    token = os.environ.get(args.token_env)
    if not token:
        raise DemoError(f"Missing token: set {args.token_env} before running this demo")

    _print_step("submitting request to POST /host/action")
    status, submitted = request_json(
        args.base_url,
        "POST",
        "/host/action",
        token=token,
        body=host_action_body,
        timeout=args.timeout,
    )
    if status not in {200, 202}:
        raise DemoError(f"request submitted failed: HTTP {status}: {submitted}")
    if submitted.get("result_type") != "plan_confirmation_required":
        raise DemoError(f"expected plan_confirmation_required, got: {submitted}")
    _print_step("request submitted")

    plan_id = _extract_plan_id(submitted)
    if not plan_id:
        raise DemoError(f"plan_id did not appear in /host/action response: {submitted}")
    _print_step(f"plan_id captured: {plan_id}")

    _print_step("checking GET /confirm/pending")
    status, pending = request_json(
        args.base_url,
        "GET",
        "/confirm/pending?limit=50",
        token=token,
        timeout=args.timeout,
    )
    if status != 200 or not pending.get("ok"):
        raise DemoError(f"pending confirmation lookup failed: HTTP {status}: {pending}")
    if int(pending.get("pending_count") or 0) <= 0:
        raise DemoError(f"pending confirmation did not appear; pending response: {pending}")
    if not _contains_plan_id(pending.get("pending", []), plan_id):
        raise DemoError(f"pending confirmation not found for plan_id={plan_id}: {pending}")
    _print_step("pending confirmation found")

    _print_step("submitting confirmation to POST /host/confirm")
    status, confirmed = request_json(
        args.base_url,
        "POST",
        "/host/confirm",
        token=token,
        body={"plan_id": plan_id},
        timeout=args.timeout,
    )
    if status != 200 or not confirmed.get("ok") or confirmed.get("result_type") != "host_action":
        raise DemoError(f"confirm failed: HTTP {status}: {confirmed}")
    _print_step("confirm submitted")

    outcome_path = "/mso/outcome/status?" + urlencode({"plan_id": plan_id})
    deadline = time.monotonic() + args.outcome_timeout
    last_outcome: dict[str, Any] | None = None
    while time.monotonic() <= deadline:
        status, outcome = request_json(
            args.base_url,
            "GET",
            outcome_path,
            token=token,
            timeout=args.timeout,
        )
        if status != 200 or not outcome.get("ok"):
            raise DemoError(f"outcome fetch failed: HTTP {status}: {outcome}")
        last_outcome = outcome
        outcome_body = outcome.get("outcome") if isinstance(outcome.get("outcome"), dict) else {}
        sources = outcome.get("sources") if isinstance(outcome.get("sources"), dict) else {}
        if (
            outcome.get("found") is True
            and outcome_body.get("status") == "completed"
            and sources.get("task_registry") is True
        ):
            _print_step("outcome fetched")
            _print_step(f"final outcome.status: {outcome_body.get('status')}")
            return 0
        time.sleep(args.poll_interval)

    raise DemoError(
        "outcome did not reach completed with sources.task_registry=true "
        f"for plan_id={plan_id}; last outcome: {last_outcome}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backend-only outcome flow smoke/demo")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Backend base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--sandbox-root", default=None, help="Write sandbox root; defaults to HOST write sandbox")
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV, help=f"Token environment variable (default: {DEFAULT_TOKEN_ENV})")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout in seconds")
    parser.add_argument("--outcome-timeout", type=float, default=10.0, help="Seconds to wait for completed outcome")
    parser.add_argument("--poll-interval", type=float, default=0.5, help="Seconds between outcome polls")
    parser.add_argument("--dry-run", action="store_true", help="Print planned request body without contacting backend")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return run_demo(args)
    except DemoError as exc:
        print(f"[demo] FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
