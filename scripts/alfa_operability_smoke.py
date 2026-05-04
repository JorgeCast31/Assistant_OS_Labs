#!/usr/bin/env python3
"""
Local ALFA operability smoke runner.

Default mode is read-only. The confirmed HOST flow runs only when
--exercise-confirm-flow is passed.
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
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import urlencode, urlparse

DEFAULT_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_TOKEN_ENV = "WEBHOOK_TOKEN"
REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class SmokeError(RuntimeError):
    """Expected smoke failure with a concise message."""


@dataclass(frozen=True)
class Check:
    name: str
    method: str
    path: str
    token_required: bool = True
    optional: bool = False


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


READ_ONLY_CHECKS = (
    Check("health", "GET", "/health", token_required=False),
    Check("mso state", "GET", "/mso/state"),
    Check("governance status", "GET", "/mso/governance/status"),
    Check("governance recent", "GET", "/mso/governance/recent?limit=10"),
    Check("authority status", "GET", "/mso/authority/status"),
    Check("confirm pending", "GET", "/confirm/pending?limit=10"),
    Check("outcome status", "GET", "/mso/outcome/status"),
    Check("code readiness", "GET", "/code/readiness"),
    Check("system assistant state", "GET", "/system-assistant/state", optional=True),
    Check("cognition providers health", "GET", "/cognition/providers/health", optional=True),
    Check("cognition preferences", "GET", "/cognition/preferences", optional=True),
)


def _print(status: str, section: str, detail: str) -> None:
    print(f"{status:<7} {section} - {detail}")


def _json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


def _parse_local_base_url(base_url: str) -> tuple[str, int]:
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise SmokeError(f"invalid --base-url: {base_url!r}")
    if parsed.hostname not in LOCAL_HOSTS:
        raise SmokeError(f"--base-url must target local backend only, got host: {parsed.hostname!r}")
    return parsed.hostname, parsed.port or 80


def _read_json(response: http.client.HTTPResponse) -> dict[str, Any]:
    raw = response.read().decode("utf-8", errors="replace")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"non-JSON response: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise SmokeError(f"expected JSON object, got {type(data).__name__}")
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
    host, port = _parse_local_base_url(base_url)
    headers: dict[str, str] = {}
    payload = None
    if token is not None:
        headers["X-Assistant-Token"] = token
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = _json_bytes(body)

    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        status = response.status
        data = _read_json(response)
        conn.close()
        return status, data
    except OSError as exc:
        raise SmokeError(f"backend did not respond at {base_url}: {exc}") from exc


def _default_sandbox_root() -> str:
    host_agent_path = REPO_ROOT / "assistant_os" / "agents" / "host_agent.py"
    try:
        module = ast.parse(host_agent_path.read_text(encoding="utf-8"))
        for node in module.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "WRITE_SANDBOX_DIRECTORIES" and node.value is not None:
                    sandbox_dirs = ast.literal_eval(node.value)
                    if isinstance(sandbox_dirs, list) and sandbox_dirs:
                        return str(sandbox_dirs[0])
    except Exception as exc:  # noqa: BLE001 - operator-facing smoke
        raise SmokeError(f"unable to read HOST write sandbox root: {exc}") from exc
    raise SmokeError("unable to find HOST write sandbox root")


def _safe_demo_path(sandbox_root: str) -> str:
    root = PureWindowsPath(sandbox_root)
    if not root.is_absolute():
        raise SmokeError(f"--sandbox-root must be absolute, got: {sandbox_root!r}")
    suffix = f"alfa_operability_smoke_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    return str(root / suffix)


def _extract_plan_id(data: dict[str, Any]) -> str | None:
    values = [
        data.get("plan_id"),
        data.get("data", {}).get("plan_id") if isinstance(data.get("data"), dict) else None,
        (
            data.get("data", {}).get("plan", {}).get("plan_id")
            if isinstance(data.get("data"), dict) and isinstance(data.get("data", {}).get("plan"), dict)
            else None
        ),
    ]
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _contains_value(value: Any, target: str) -> bool:
    if value == target:
        return True
    if isinstance(value, dict):
        return any(_contains_value(item, target) for item in value.values())
    if isinstance(value, list):
        return any(_contains_value(item, target) for item in value)
    return False


def _validate_read_only_response(check: Check, http_status: int, data: dict[str, Any]) -> str:
    if http_status != 200:
        raise SmokeError(f"HTTP {http_status}: {data}")
    if check.path == "/health":
        if data.get("status") != "ok":
            raise SmokeError(f"expected status=ok, got: {data}")
        return "status=ok"
    if data.get("ok") is False:
        raise SmokeError(f"ok=false: {data}")
    return "ok"


def run_read_only_checks(args: argparse.Namespace, token: str | None) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in READ_ONLY_CHECKS:
        if check.token_required and not token:
            status = "BLOCKED" if check.optional else "FAIL"
            detail = f"missing token env {args.token_env}"
            _print(status, check.name, detail)
            results.append(CheckResult(check.name, status, detail))
            continue
        try:
            http_status, data = request_json(
                args.base_url,
                check.method,
                check.path,
                token=token if check.token_required else None,
                timeout=args.timeout,
            )
            detail = _validate_read_only_response(check, http_status, data)
            _print("PASS", check.name, detail)
            results.append(CheckResult(check.name, "PASS", detail))
        except SmokeError as exc:
            status = "BLOCKED" if check.optional else "FAIL"
            detail = str(exc)
            _print(status, check.name, detail)
            results.append(CheckResult(check.name, status, detail))
    return results


def run_confirm_flow(args: argparse.Namespace, token: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    sandbox_root = args.sandbox_root or _default_sandbox_root()
    demo_path = _safe_demo_path(sandbox_root)
    body = {
        "action": "create_directory",
        "payload": {"path": demo_path, "confirmed": True},
    }

    try:
        http_status, submitted = request_json(
            args.base_url,
            "POST",
            "/host/action",
            token=token,
            body=body,
            timeout=args.timeout,
        )
        if http_status not in {200, 202} or submitted.get("result_type") != "plan_confirmation_required":
            raise SmokeError(f"expected plan_confirmation_required, got HTTP {http_status}: {submitted}")
        plan_id = _extract_plan_id(submitted)
        if not plan_id:
            raise SmokeError(f"plan_id missing in response: {submitted}")
        _print("PASS", "confirm flow submit", f"plan_id={plan_id}")
        results.append(CheckResult("confirm flow submit", "PASS", plan_id))
    except SmokeError as exc:
        _print("FAIL", "confirm flow submit", str(exc))
        return [CheckResult("confirm flow submit", "FAIL", str(exc))]

    try:
        http_status, pending = request_json(
            args.base_url,
            "GET",
            "/confirm/pending?limit=50",
            token=token,
            timeout=args.timeout,
        )
        if http_status != 200 or not pending.get("ok") or not _contains_value(pending.get("pending", []), plan_id):
            raise SmokeError(f"created plan_id not found in pending response: {pending}")
        _print("PASS", "confirm flow pending", "created plan is pending")
        results.append(CheckResult("confirm flow pending", "PASS", "created plan is pending"))
    except SmokeError as exc:
        _print("FAIL", "confirm flow pending", str(exc))
        results.append(CheckResult("confirm flow pending", "FAIL", str(exc)))
        return results

    try:
        http_status, confirmed = request_json(
            args.base_url,
            "POST",
            "/host/confirm",
            token=token,
            body={"plan_id": plan_id},
            timeout=args.timeout,
        )
        if http_status != 200 or not confirmed.get("ok") or confirmed.get("result_type") != "host_action":
            raise SmokeError(f"confirm failed HTTP {http_status}: {confirmed}")
        _print("PASS", "confirm flow confirm", "own plan confirmed")
        results.append(CheckResult("confirm flow confirm", "PASS", "own plan confirmed"))
    except SmokeError as exc:
        _print("FAIL", "confirm flow confirm", str(exc))
        results.append(CheckResult("confirm flow confirm", "FAIL", str(exc)))
        return results

    outcome_path = "/mso/outcome/status?" + urlencode({"plan_id": plan_id})
    deadline = time.monotonic() + args.outcome_timeout
    last_outcome: dict[str, Any] | None = None
    while time.monotonic() <= deadline:
        try:
            http_status, outcome = request_json(
                args.base_url,
                "GET",
                outcome_path,
                token=token,
                timeout=args.timeout,
            )
        except SmokeError as exc:
            _print("FAIL", "confirm flow outcome", str(exc))
            results.append(CheckResult("confirm flow outcome", "FAIL", str(exc)))
            return results
        last_outcome = outcome
        outcome_body = outcome.get("outcome") if isinstance(outcome.get("outcome"), dict) else {}
        sources = outcome.get("sources") if isinstance(outcome.get("sources"), dict) else {}
        status_ok = outcome.get("found") is True and outcome_body.get("status") == "completed"
        source_ok = sources.get("task_registry") is True if "task_registry" in sources else True
        if http_status == 200 and outcome.get("ok") and status_ok and source_ok:
            _print("PASS", "confirm flow outcome", "outcome.status=completed")
            results.append(CheckResult("confirm flow outcome", "PASS", "outcome.status=completed"))
            return results
        time.sleep(args.poll_interval)

    detail = f"outcome did not complete; last={last_outcome}"
    _print("FAIL", "confirm flow outcome", detail)
    results.append(CheckResult("confirm flow outcome", "FAIL", detail))
    return results


def dry_run(args: argparse.Namespace) -> int:
    _parse_local_base_url(args.base_url)
    print("ALFA operability smoke dry-run")
    print(f"base_url={args.base_url}")
    print(f"token_env={args.token_env}")
    print("mode=read-only" if not args.exercise_confirm_flow else "mode=read-only + confirm flow")
    for check in READ_ONLY_CHECKS:
        print(f"GET {check.path}")
    if args.exercise_confirm_flow:
        sandbox_root = args.sandbox_root or _default_sandbox_root()
        print(f"sandbox_demo_path={_safe_demo_path(sandbox_root)}")
        print("confirm flow requests are enabled by --exercise-confirm-flow")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local ALFA operability smoke runner")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Backend base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV, help=f"Token environment variable (default: {DEFAULT_TOKEN_ENV})")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout in seconds")
    parser.add_argument("--outcome-timeout", type=float, default=10.0, help="Seconds to wait for completed outcome")
    parser.add_argument("--poll-interval", type=float, default=0.5, help="Seconds between outcome polls")
    parser.add_argument("--sandbox-root", default=None, help="HOST write sandbox root for --exercise-confirm-flow")
    parser.add_argument("--exercise-confirm-flow", action="store_true", help="Opt in to sandbox mutation and confirmation flow")
    parser.add_argument("--dry-run", action="store_true", help="Print planned checks without contacting backend")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        _parse_local_base_url(args.base_url)
        if args.dry_run:
            return dry_run(args)
        token = os.environ.get(args.token_env)
        results = run_read_only_checks(args, token)
        if args.exercise_confirm_flow:
            if not token:
                _print("FAIL", "confirm flow", f"missing token env {args.token_env}")
                results.append(CheckResult("confirm flow", "FAIL", "missing token"))
            else:
                results.extend(run_confirm_flow(args, token))
        failed = [result for result in results if result.status == "FAIL"]
        blocked = [result for result in results if result.status == "BLOCKED"]
        if failed:
            print(f"ALFA OPERABILITY SMOKE FAIL ({len(failed)} failed, {len(blocked)} blocked)")
            return 1
        print(f"ALFA OPERABILITY SMOKE PASS ({len(blocked)} blocked optional)")
        return 0
    except SmokeError as exc:
        print(f"FAIL    setup - {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
