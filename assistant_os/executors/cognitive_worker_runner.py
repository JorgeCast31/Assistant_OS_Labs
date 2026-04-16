"""Process boundary wrapper for bounded cognitive worker execution."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Lock
import time
import uuid
import socket

from ..config import MEMORY_DIR
from ..contracts import now_iso
from ..mso.contracts import (
    DelegationTask,
    EscalationRequest,
    ExecutionCapability,
    ExecutionReport,
    WorkerExecutionLimits,
    WorkerSecurityEvent,
)
from ..storage.mso_store import persist_worker_security_event
from ..mso.security_response import apply_security_responses, enrich_event_window_counts
from .worker_isolation import apply_os_process_hardening, default_creationflags, install_network_deny_hooks

RUNNER_ID = "local_cognitive_worker_runner"
_RUNTIME_DIR = MEMORY_DIR / "worker_runtime"
_TIMEOUT_BUFFER_MS = 100
_RUN_LOCK = Lock()
_STATE_LOCK = Lock()
_ACTIVE_PROCESSES: dict[int, dict[str, str]] = {}


def _limits_for_task(task: DelegationTask) -> WorkerExecutionLimits:
    from .cognitive_worker import _limits_for_task as _worker_limits_for_task

    return _worker_limits_for_task(task)


def _event(
    task: DelegationTask,
    *,
    event_type: str,
    lifecycle_state: str,
    detail: str,
    severity: str = "low",
    process_id: int = 0,
    scope_ref: str = "",
    limit_name: str = "",
) -> WorkerSecurityEvent:
    return WorkerSecurityEvent(
        event_id=str(uuid.uuid4()),
        task_id=task.task_id,
        trace_id=task.trace_id,
        worker_id=RUNNER_ID,
        event_type=event_type,
        lifecycle_state=lifecycle_state,
        detail=detail,
        created_at=now_iso(),
        severity=severity,
        process_id=process_id,
        scope_ref=scope_ref,
        limit_name=limit_name,
    )


def _build_escalation(
    task: DelegationTask,
    *,
    current_limit_hit: str,
    reason: str,
) -> EscalationRequest:
    return EscalationRequest(
        escalation_id=str(uuid.uuid4()),
        task_id=task.task_id,
        worker_id=RUNNER_ID,
        requested_capability=task.requires_capability,
        requested_scope=task.scope,
        reason=reason,
        current_limit_hit=current_limit_hit,
        trace_id=task.trace_id,
        timestamp=now_iso(),
    )


def _build_failure_report(
    task: DelegationTask,
    *,
    status: str,
    findings_summary: str,
    requires_escalation: bool,
) -> ExecutionReport:
    return ExecutionReport(
        report_id=str(uuid.uuid4()),
        task_id=task.task_id,
        worker_id=RUNNER_ID,
        status=status,
        operations_performed=[],
        artifacts={},
        findings_summary=findings_summary,
        confidence=0.0,
        requires_escalation=requires_escalation,
        trace_id=task.trace_id,
        completed_at=now_iso(),
    )


def _persist_events(events: list[WorkerSecurityEvent]) -> list[str]:
    refs: list[str] = []
    for event in events:
        refs.append(persist_worker_security_event(event))
    return refs


def _register_process(task: DelegationTask, process: subprocess.Popen[str]) -> None:
    with _STATE_LOCK:
        _ACTIVE_PROCESSES[process.pid or 0] = {
            "task_id": task.task_id,
            "trace_id": task.trace_id,
            "started_at": now_iso(),
        }


def _unregister_process(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    with _STATE_LOCK:
        _ACTIVE_PROCESSES.pop(process.pid or 0, None)


def get_runner_status() -> dict:
    with _STATE_LOCK:
        active = dict(_ACTIVE_PROCESSES)
    return {
        "active_process_count": len(active),
        "active_processes": active,
        "single_flight": True,
    }


def _finalize_events(events: list[WorkerSecurityEvent]) -> list[WorkerSecurityEvent]:
    enrich_event_window_counts(events)
    apply_security_responses(events)
    _persist_events(events)
    return events


def run_task_in_subprocess(
    task: DelegationTask,
    capability: ExecutionCapability,
) -> tuple[ExecutionReport, EscalationRequest | None, list[WorkerSecurityEvent]]:
    """Execute the bounded worker in a dedicated subprocess."""
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    limits = _limits_for_task(task)
    command = [sys.executable, "-m", "assistant_os.executors.cognitive_worker_runner"]
    events: list[WorkerSecurityEvent] = []
    with _RUN_LOCK:
        with tempfile.TemporaryDirectory(prefix="cognitive-worker-", dir=_RUNTIME_DIR) as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.json"
            output_path = temp_path / "output.json"
            input_path.write_text(
                json.dumps(
                    {
                        "task": asdict(task),
                        "capability": asdict(capability),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            process: subprocess.Popen[str] | None = None
            isolation_result: dict | None = None
            try:
                process = subprocess.Popen(
                    [*command, str(input_path), str(output_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=default_creationflags(),
                )
                _register_process(task, process)
                isolation_result = apply_os_process_hardening(
                    process,
                    memory_limit_bytes=int(task.scope.get("memory_limit_bytes", 64 * 1024 * 1024)),
                )
                events.append(
                    _event(
                        task,
                        event_type="worker_started",
                        lifecycle_state="starting",
                        detail="Worker subprocess started under single-flight control.",
                        process_id=process.pid or 0,
                    )
                )
                events.append(
                    _event(
                        task,
                        event_type="os_hardening_applied",
                        lifecycle_state="running",
                        detail=isolation_result["detail"],
                        severity="low" if isolation_result.get("applied") else "medium",
                        process_id=process.pid or 0,
                        limit_name="memory_limit_bytes",
                    )
                )
                try:
                    stdout, stderr = process.communicate(timeout=max((limits.timeout_ms + _TIMEOUT_BUFFER_MS) / 1000.0, 0.1))
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
                    events.append(
                        _event(
                            task,
                            event_type="worker_forced_kill",
                            lifecycle_state="killed",
                            detail="Worker subprocess was force-killed after timeout.",
                            severity="high",
                            process_id=process.pid or 0,
                            limit_name="timeout_ms",
                        )
                    )
                    events.append(
                        _event(
                            task,
                            event_type="worker_timeout",
                            lifecycle_state="timeout",
                            detail=f"Worker process exceeded timeout budget of {limits.timeout_ms}ms.",
                            severity="high",
                            process_id=process.pid or 0,
                            limit_name="timeout_ms",
                        )
                    )
                    _finalize_events(events)
                    escalation = _build_escalation(
                        task,
                        current_limit_hit="worker_process_timeout",
                        reason=f"Worker process exceeded timeout budget of {limits.timeout_ms}ms.",
                    )
                    return (
                        _build_failure_report(
                            task,
                            status="timeout",
                            findings_summary="Worker process timed out before producing a bounded report.",
                            requires_escalation=True,
                        ),
                        escalation,
                        events,
                    )

                if process.returncode != 0 or not output_path.exists():
                    detail = (stderr or stdout or "").strip()[:300]
                    events.append(
                        _event(
                            task,
                            event_type="worker_crash",
                            lifecycle_state="crashed",
                            detail=f"Worker subprocess failed before producing output. {detail}".strip(),
                            severity="high",
                            process_id=process.pid or 0,
                        )
                    )
                    _finalize_events(events)
                    escalation = _build_escalation(
                        task,
                        current_limit_hit="worker_process_failure",
                        reason=f"Worker process failed before producing output. {detail}".strip(),
                    )
                    return (
                        _build_failure_report(
                            task,
                            status="failed",
                            findings_summary="Worker process failed before bounded cognitive execution completed.",
                            requires_escalation=True,
                        ),
                        escalation,
                        events,
                    )

                try:
                    payload = json.loads(output_path.read_text(encoding="utf-8"))
                    report = ExecutionReport(**payload["report"])
                    escalation = EscalationRequest(**payload["escalation"]) if payload.get("escalation") else None
                    for event_data in payload.get("security_events") or []:
                        events.append(WorkerSecurityEvent(**event_data))
                    events.append(
                        _event(
                            task,
                            event_type="worker_completed",
                            lifecycle_state="completed",
                            detail="Worker subprocess completed and returned a bounded report.",
                            process_id=process.pid or 0,
                        )
                    )
                    _finalize_events(events)
                    return report, escalation, events
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    events.append(
                        _event(
                            task,
                            event_type="worker_crash",
                            lifecycle_state="crashed",
                            detail=f"Worker subprocess returned invalid output: {exc}",
                            severity="high",
                            process_id=process.pid or 0,
                        )
                    )
                    _finalize_events(events)
                    escalation = _build_escalation(
                        task,
                        current_limit_hit="worker_process_failure",
                        reason=f"Worker process returned invalid output: {exc}",
                    )
                    return (
                        _build_failure_report(
                            task,
                            status="failed",
                            findings_summary="Worker process returned invalid output.",
                            requires_escalation=True,
                        ),
                        escalation,
                        events,
                    )
            finally:
                if process is not None and process.poll() is None:
                    process.kill()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                job_handle = int((isolation_result or {}).get("job_handle", 0))
                if job_handle:
                    try:
                        import ctypes

                        ctypes.windll.kernel32.CloseHandle(job_handle)
                    except Exception:
                        pass
                _unregister_process(process)


def _event_from_escalation(task: DelegationTask, escalation: EscalationRequest) -> WorkerSecurityEvent:
    mapping = {
        "invalid_input_ref": ("invalid_input_ref", "blocked", "medium", "input_refs"),
        "max_input_refs_exceeded": ("resource_limit_exceeded", "blocked", "medium", "max_input_refs"),
        "scope_violation": ("scope_violation", "blocked", "medium", "scope"),
        "network_denied": ("network_denied", "blocked", "high", "network"),
        "max_artifact_count_exceeded": ("resource_limit_exceeded", "blocked", "medium", "max_artifact_count"),
        "max_artifact_bytes_exceeded": ("resource_limit_exceeded", "blocked", "medium", "max_artifact_bytes"),
        "timeout": ("worker_timeout", "timeout", "high", "timeout_ms"),
    }
    event_type, lifecycle_state, severity, limit_name = mapping.get(
        escalation.current_limit_hit,
        ("resource_limit_exceeded", "blocked", "medium", escalation.current_limit_hit),
    )
    return _event(
        task,
        event_type=event_type,
        lifecycle_state=lifecycle_state,
        detail=escalation.reason,
        severity=severity,
        limit_name=limit_name,
    )


def _run_cli(input_path: str, output_path: str) -> int:
    from .cognitive_worker import execute_delegation_task

    install_network_deny_hooks()
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    task = DelegationTask(**payload["task"])
    capability = ExecutionCapability(**payload["capability"])
    if task.scope.get("force_runner_crash"):
        raise RuntimeError("forced runner crash")
    if task.scope.get("force_network_attempt"):
        try:
            socket.getaddrinfo("example.com", 80)
        except Exception:
            escalation = _build_escalation(
                task,
                current_limit_hit="network_denied",
                reason="Worker secure execution layer denied an attempted network resolution.",
            )
            report = _build_failure_report(
                task,
                status="blocked",
                findings_summary="Worker blocked a denied network attempt.",
                requires_escalation=True,
            )
            event = _event_from_escalation(task, escalation)
            Path(output_path).write_text(
                json.dumps(
                    {
                        "report": asdict(report),
                        "escalation": asdict(escalation),
                        "security_events": [asdict(event)],
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return 0
    forced_runner_delay_ms = int(task.scope.get("force_runner_delay_ms", 0))
    if forced_runner_delay_ms > 0:
        time.sleep(forced_runner_delay_ms / 1000.0)
    report, escalation = execute_delegation_task(task, capability)
    events: list[dict] = []
    if escalation is not None:
        events.append(asdict(_event_from_escalation(task, escalation)))
    Path(output_path).write_text(
        json.dumps(
            {
                "report": asdict(report),
                "escalation": asdict(escalation) if escalation else None,
                "security_events": events,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(2)
    raise SystemExit(_run_cli(sys.argv[1], sys.argv[2]))
