from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from assistant_os.context_store import clear_store, get_store_size, store_pending_plan
from assistant_os.contracts import (
    EXECUTION_STATUS_PARTIAL,
    EXECUTION_STATUS_REAL,
    EXECUTION_STATUS_STUB,
    EXECUTION_STATUS_UNAVAILABLE,
    make_domain_result,
)
from assistant_os.mso.contracts import DeterministicDecisionTrace, GovernanceDecision, TaskRecord
from assistant_os.mso.outcome_status import build_outcome_status
from assistant_os.mso.task_registry import register_task, reset_task_registry, transition_task
from assistant_os.mso.trace_aggregator import begin_trace_chain, finalize_trace_chain, reset_trace_aggregator


@pytest.fixture(autouse=True)
def _reset_mso_state():
    reset_task_registry()
    reset_trace_aggregator()
    clear_store()
    yield
    reset_task_registry()
    reset_trace_aggregator()
    clear_store()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decision(
    *,
    plan_id: str = "plan-1",
    context_id: str = "ctx-1",
    trace_id: str = "trace-1",
    domain: str = "CODE",
    action: str = "CODE_EXPLAIN",
    execution_mode: str = "auto",
) -> DeterministicDecisionTrace:
    return DeterministicDecisionTrace(
        decision_ref=f"decision:{plan_id}",
        context_id=context_id,
        trace_id=trace_id,
        plan_id=plan_id,
        domain=domain,
        action=action,
        execution_mode=execution_mode,
        operation=action,
        preview="safe preview",
        created_at=_now(),
    )


def _task(
    *,
    task_id: str = "task-1",
    plan_id: str = "plan-1",
    context_id: str = "ctx-1",
    trace_id: str = "trace-1",
    domain: str = "CODE",
    action: str = "CODE_EXPLAIN",
    status: str = "pending",
    execution_mode: str = "auto",
    execution_id: str = "",
    result_type: str = "",
) -> TaskRecord:
    timestamp = _now()
    return TaskRecord(
        task_id=task_id,
        context_id=context_id,
        trace_id=trace_id,
        plan_id=plan_id,
        domain=domain,
        status=status,
        created_at=timestamp,
        updated_at=timestamp,
        last_known_action=action,
        execution_mode=execution_mode,
        execution_id=execution_id,
        result_type=result_type,
        decision_trace_ref=f"decision:{plan_id}",
        governance_trace_ref=f"governance:{plan_id}",
    )


def _begin_chain(
    *,
    task_id: str = "task-1",
    plan_id: str = "plan-1",
    context_id: str = "ctx-1",
    trace_id: str = "trace-1",
    domain: str = "CODE",
    action: str = "CODE_EXPLAIN",
    execution_mode: str = "auto",
    governance_decision: GovernanceDecision | None = None,
):
    decision = _decision(
        plan_id=plan_id,
        context_id=context_id,
        trace_id=trace_id,
        domain=domain,
        action=action,
        execution_mode=execution_mode,
    )
    return begin_trace_chain(
        task_id=task_id,
        context_id=context_id,
        trace_id=trace_id,
        plan_id=plan_id,
        request_text="request",
        operation=action,
        domain=domain,
        action=action,
        execution_mode=execution_mode,
        created_at=_now(),
        advisory_trace=None,
        decision_trace=decision,
        governance_decision=governance_decision,
    )


def test_no_ids_returns_valid_not_found_or_unknown() -> None:
    status = build_outcome_status()

    assert status["ok"] is True
    assert status["found"] is False
    assert status["outcome"]["status"] in {"not_found", "unknown"}
    json.dumps(status)


def test_missing_plan_id_returns_clean_not_found() -> None:
    status = build_outcome_status(plan_id="missing-plan")

    assert status["ok"] is True
    assert status["found"] is False
    assert status["outcome"]["status"] == "not_found"
    assert status["source_errors"] == []


def test_pending_plan_in_context_store_returns_pending_without_consuming() -> None:
    store_pending_plan(
        "ctx-pending",
        {
            "plan_id": "plan-pending",
            "trace_id": "trace-pending",
            "domain": "WORK",
            "action": "WORK_CREATE",
            "_authority_context": {
                "policy_decision_ref": "decision:pending",
                "governance_ref": "governance:pending",
                "execution_mode": "confirm",
            },
        },
        operation="WORK_CREATE",
        raw_text="do not expose this raw_text token=abc",
    )

    status = build_outcome_status(context_id="ctx-pending")

    assert status["found"] is True
    assert status["outcome"]["status"] == "pending"
    assert status["correlation"]["plan_id"] == "plan-pending"
    assert status["correlation"]["execution_mode"] == "confirm"
    assert status["sources"]["context_store_pending"] is True


def test_pending_context_store_entry_remains_after_outcome_lookup() -> None:
    store_pending_plan(
        "ctx-still-pending",
        {
            "plan_id": "plan-still-pending",
            "trace_id": "trace-still-pending",
            "domain": "WORK",
            "action": "WORK_CREATE",
        },
        operation="WORK_CREATE",
        raw_text="pending confirmation must remain stored",
    )
    before = get_store_size()

    with patch("assistant_os.context_store.remove_pending_plan", side_effect=AssertionError("must not consume pending")):
        status = build_outcome_status(context_id="ctx-still-pending")

    after = get_store_size()
    assert status["outcome"]["status"] == "pending"
    assert before == 1
    assert after == before


@pytest.mark.parametrize("bad_execution_id", ["../etc/passwd", "../../secret", "a/b", "a\\b", ".."])
def test_runner_metadata_rejects_path_traversal_execution_ids(bad_execution_id: str) -> None:
    status = build_outcome_status(execution_id=bad_execution_id)

    assert status["ok"] is True
    assert status["sources"]["runner_metadata"] is False
    assert status["outcome"]["status"] != "completed"


def test_pending_context_store_raw_text_is_not_exposed() -> None:
    raw_text = "secret token=abc credential=xyz"
    store_pending_plan(
        "ctx-sensitive-raw",
        {
            "plan_id": "plan-sensitive-raw",
            "trace_id": "trace-sensitive-raw",
            "domain": "WORK",
            "action": "WORK_CREATE",
        },
        operation="WORK_CREATE",
        raw_text=raw_text,
    )

    status = build_outcome_status(context_id="ctx-sensitive-raw")
    dumped = json.dumps(status).lower()

    assert "token=abc" not in dumped
    assert "credential=xyz" not in dumped
    assert raw_text not in dumped


def test_trace_domain_result_ok_true_returns_completed() -> None:
    _begin_chain()
    result = make_domain_result(
        True,
        "code_explain",
        "CODE",
        "completed",
        trace_id="trace-1",
        plan_id="plan-1",
        execution_status=EXECUTION_STATUS_REAL,
    )
    finalize_trace_chain("plan-1", executed=True, result=result, execution_id="exec-1")

    status = build_outcome_status(plan_id="plan-1")

    assert status["found"] is True
    assert status["outcome"]["status"] == "completed"
    assert status["outcome"]["execution_status"] == "real"
    assert status["correlation"]["execution_id"] == "exec-1"


def test_trace_domain_result_ok_false_returns_failed() -> None:
    _begin_chain()
    result = make_domain_result(
        False,
        "code_apply",
        "CODE",
        "failed",
        error={"code": "apply_failed", "message": "could not apply"},
        trace_id="trace-1",
        plan_id="plan-1",
        execution_status=EXECUTION_STATUS_UNAVAILABLE,
    )
    finalize_trace_chain("plan-1", executed=True, result=result, execution_id="exec-1")

    status = build_outcome_status(plan_id="plan-1")

    assert status["outcome"]["status"] == "failed"
    assert status["outcome"]["execution_status"] == "unavailable"
    assert status["outcome"]["error_type"] == "apply_failed"


def test_blocked_evidence_returns_blocked() -> None:
    _begin_chain(execution_mode="blocked")
    result = make_domain_result(
        False,
        "blocked",
        "CODE",
        "blocked by governance",
        data={"governance_blocked": True},
        error={"code": "governance_blocked", "message": "blocked"},
        trace_id="trace-1",
        plan_id="plan-1",
    )
    finalize_trace_chain("plan-1", executed=False, result=result)

    status = build_outcome_status(plan_id="plan-1")

    assert status["outcome"]["status"] == "blocked"
    assert status["correlation"]["execution_mode"] == "blocked"


@pytest.mark.parametrize(
    ("execution_status", "expected"),
    [
        (EXECUTION_STATUS_REAL, "real"),
        (EXECUTION_STATUS_STUB, "stub"),
        (EXECUTION_STATUS_PARTIAL, "partial"),
        (EXECUTION_STATUS_UNAVAILABLE, "unavailable"),
    ],
)
def test_execution_status_values_are_preserved(execution_status: str, expected: str) -> None:
    _begin_chain()
    result = make_domain_result(
        True,
        "code_explain",
        "CODE",
        "done",
        trace_id="trace-1",
        plan_id="plan-1",
        execution_status=execution_status,
    )
    finalize_trace_chain("plan-1", executed=True, result=result)

    status = build_outcome_status(plan_id="plan-1")

    assert status["outcome"]["execution_status"] == expected


def test_forbidden_fields_are_not_exposed() -> None:
    _begin_chain()
    result = make_domain_result(
        False,
        "code_apply",
        "CODE",
        "stdout token secret signature env diff raw_text prompt should be hidden",
        data={
            "stdout": "full output",
            "stderr": "full error",
            "token": "abc",
            "secret": "def",
            "diff": "patch",
            "safe": "visible",
        },
        error={
            "code": "failed",
            "message": "stderr token signature secret env diff raw_prompt leaked",
        },
        trace_id="trace-1",
        plan_id="plan-1",
    )
    finalize_trace_chain("plan-1", executed=True, result=result)

    status = build_outcome_status(plan_id="plan-1")
    dumped = json.dumps(status).lower()

    for forbidden in (
        "stdout",
        "stderr",
        "token",
        "secret",
        "signature",
        "raw_text",
        "raw_prompt",
        "prompt",
        "env",
        "diff",
        "patch",
        "full output",
        "full error",
    ):
        assert forbidden not in dumped


def test_source_failure_is_fail_soft() -> None:
    with patch("assistant_os.mso.outcome_status._read_tasks", side_effect=RuntimeError("task registry token boom")):
        status = build_outcome_status(plan_id="plan-1")

    assert status["ok"] is True
    assert status["found"] is False
    assert status["outcome"]["status"] == "unknown"
    assert status["source_errors"]
    assert "token" not in json.dumps(status).lower()


def test_lookup_by_plan_id_from_task_registry() -> None:
    register_task(_task(plan_id="plan-task", status="completed", result_type="code_explain", execution_id="exec-task"))

    status = build_outcome_status(plan_id="plan-task")

    assert status["found"] is True
    assert status["outcome"]["status"] == "completed"
    assert status["outcome"]["result_type"] == "code_explain"
    assert status["correlation"]["execution_id"] == "exec-task"
    assert status["sources"]["task_registry"] is True


def test_lookup_by_context_id_and_trace_id_from_trace_chain() -> None:
    _begin_chain(plan_id="plan-multi", context_id="ctx-multi", trace_id="trace-multi")
    result = make_domain_result(
        True,
        "code_explain",
        "CODE",
        "done",
        trace_id="trace-multi",
        plan_id="plan-multi",
    )
    finalize_trace_chain("plan-multi", executed=True, result=result)

    by_context = build_outcome_status(context_id="ctx-multi")
    by_trace = build_outcome_status(trace_id="trace-multi")

    assert by_context["found"] is True
    assert by_context["correlation"]["plan_id"] == "plan-multi"
    assert by_trace["found"] is True
    assert by_trace["correlation"]["context_id"] == "ctx-multi"


def test_task_transition_failure_maps_failed() -> None:
    register_task(_task(task_id="task-failed", plan_id="plan-failed", status="pending"))
    transition_task(
        "task-failed",
        to_status="failed",
        result_type="code_apply",
        error_type="ApplyFailed",
        error_message="apply failed",
        execution_id="exec-failed",
    )

    status = build_outcome_status(plan_id="plan-failed")

    assert status["outcome"]["status"] == "failed"
    assert status["outcome"]["error_type"] == "ApplyFailed"
    assert status["correlation"]["execution_id"] == "exec-failed"
