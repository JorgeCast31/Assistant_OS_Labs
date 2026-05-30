"""
Tests for plan-correlated authority trace (build_authority_trace_for_plan).

Validates:
- Returns a dict with plan_id included
- Reflects plan/ack/prepare/queue stages honestly
- Backward-compatible: existing build_authority_trace_snapshot still works
- Never calls Runner, never emits tokens, never creates AuthorityArtifact
- All stages marked correctly when data is missing vs present
- execution_allowed, used_execution, can_execute_now always False in result
- runner_closed_from_ui always True
- Static boundary: no Runner/MachineOperator imports
"""
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from assistant_os.mso.plan_model import PlanRecord
from assistant_os.mso.draft_store import create_plan, _DRAFT_STORE_ENV
from assistant_os.mso.plan_ack import PlanMSOAck, create_ack, _PREPARE_STORE_ENV
from assistant_os.mso.prepare_contract import prepare_plan
from assistant_os.mso.prepared_action_queue import clear_confirmable_action_queue_for_tests
from assistant_os.mso.authority_trace import (
    build_authority_trace_snapshot,
    build_authority_trace_for_plan,
    AUTHORITY_CHAIN,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_stores(tmp_path, monkeypatch):
    draft_db = tmp_path / "plans.db"
    prepare_db = tmp_path / "prepare.db"
    monkeypatch.setenv(_DRAFT_STORE_ENV, str(draft_db))
    monkeypatch.setenv(_PREPARE_STORE_ENV, str(prepare_db))
    clear_confirmable_action_queue_for_tests()
    yield
    clear_confirmable_action_queue_for_tests()


def _plan_id() -> str:
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    return f"plan_{ts}_{uuid4().hex[:8]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_plan(state: str = "mso_review", seat: str = "op_1", **kw) -> PlanRecord:
    plan = PlanRecord(
        plan_id=_plan_id(),
        title="T", intent_summary="I", domain="CODE",
        state=state, operator_seat=seat, schema_version="1",
        created_at=_now(), updated_at=_now(),
        risk_level="low",
        target_actions=kw.get("target_actions", ("CODE_REVIEW",)),
    )
    create_plan(plan)
    return plan


def _ack(plan_id: str, seat: str = "op_1", status: str = "acknowledged") -> None:
    a = PlanMSOAck(plan_id=plan_id, operator_seat=seat,
                   ack_status=status, acknowledged_by="mso_sim")
    create_ack(a)


# ---------------------------------------------------------------------------
# Backward compatibility: existing snapshot still works
# ---------------------------------------------------------------------------

class TestSnapshotBackwardCompatibility:

    def test_snapshot_without_plan_id_still_works(self):
        result = build_authority_trace_snapshot()
        assert "chain" in result
        assert result["chain"] == AUTHORITY_CHAIN
        assert result["execution_allowed"] is False

    def test_snapshot_with_context_dict_still_works(self):
        result = build_authority_trace_snapshot({"ok": True, "domain": "CODE"})
        assert "chain" in result
        assert result["execution_allowed"] is False

    def test_snapshot_trace_version_present(self):
        result = build_authority_trace_snapshot()
        assert "trace_version" in result


# ---------------------------------------------------------------------------
# Plan-correlated trace
# ---------------------------------------------------------------------------

class TestBuildAuthorityTraceForPlan:

    def test_returns_dict(self):
        plan = _seed_plan()
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        assert isinstance(result, dict)

    def test_includes_plan_id(self):
        plan = _seed_plan()
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        assert result["plan_id"] == plan.plan_id

    def test_includes_correlation_id(self):
        plan = _seed_plan()
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        assert result.get("correlation_id") == plan.plan_id

    def test_includes_authority_chain(self):
        plan = _seed_plan()
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        assert "chain" in result
        assert result["chain"] == AUTHORITY_CHAIN

    def test_execution_allowed_always_false(self):
        plan = _seed_plan()
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        assert result.get("execution_allowed") is False

    def test_used_execution_always_false(self):
        plan = _seed_plan()
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        assert result.get("used_execution") is False

    def test_runner_closed_from_ui_always_true(self):
        plan = _seed_plan()
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        assert result.get("runner_closed_from_ui") is True

    def test_plan_stage_present_when_plan_exists(self):
        plan = _seed_plan(state="mso_review")
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        plan_stage = result.get("plan_stage", {})
        assert plan_stage.get("exists") is True
        assert plan_stage.get("state") == "mso_review"

    def test_plan_stage_absent_when_no_plan(self):
        result = build_authority_trace_for_plan("plan_9999_notexist", "op_1")
        plan_stage = result.get("plan_stage", {})
        assert plan_stage.get("exists") is False

    def test_ack_stage_absent_when_no_ack(self):
        plan = _seed_plan(state="mso_review")
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        ack_stage = result.get("ack_stage", {})
        assert ack_stage.get("exists") is False

    def test_ack_stage_present_after_ack(self):
        plan = _seed_plan(state="mso_review")
        _ack(plan.plan_id)
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        ack_stage = result.get("ack_stage", {})
        assert ack_stage.get("exists") is True
        assert ack_stage.get("ack_status") == "acknowledged"

    def test_prepare_stage_absent_when_no_prepare(self):
        plan = _seed_plan(state="mso_review")
        _ack(plan.plan_id)
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        prep_stage = result.get("prepare_stage", {})
        assert prep_stage.get("exists") is False

    def test_prepare_stage_present_after_prepare(self):
        plan = _seed_plan(state="mso_review")
        _ack(plan.plan_id)
        prepare_plan(
            plan_id=plan.plan_id, operator_seat="op_1",
            requested_by="op_1", confirmation_acknowledged=True,
        )
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        prep_stage = result.get("prepare_stage", {})
        assert prep_stage.get("exists") is True
        assert prep_stage.get("status") == "prepared"

    def test_prepared_action_stage_present_after_prepare(self):
        plan = _seed_plan(state="mso_review")
        _ack(plan.plan_id)
        prepare_plan(
            plan_id=plan.plan_id, operator_seat="op_1",
            requested_by="op_1", confirmation_acknowledged=True,
        )
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        pa_stage = result.get("prepared_action_stage", {})
        assert pa_stage.get("exists") is True
        assert pa_stage.get("queue_status") == "pending_review"

    def test_next_step_is_meaningful(self):
        plan = _seed_plan(state="mso_review")
        _ack(plan.plan_id)
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        assert "next_step" in result
        assert result["next_step"]  # not empty

    def test_runner_stage_always_closed(self):
        plan = _seed_plan(state="mso_review")
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        runner_stage = result.get("runner_stage", {})
        assert runner_stage.get("closed_from_ui") is True
        assert runner_stage.get("executed") is False

    def test_trace_is_snapshot_not_live(self):
        plan = _seed_plan(state="mso_review")
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        assert result.get("trace_type") == "snapshot"
        assert "live" not in str(result.get("trace_type", "")).lower()

    def test_no_forbidden_labels_in_result_values(self):
        plan = _seed_plan(state="mso_review")
        _ack(plan.plan_id)
        prepare_plan(
            plan_id=plan.plan_id, operator_seat="op_1",
            requested_by="op_1", confirmation_acknowledged=True,
        )
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        # Flatten all string values and check for forbidden labels
        all_values = str(result)
        for label in ("executing", "completed", "live_trace", "authorized_for_execution"):
            assert label not in all_values, f"Forbidden label '{label}' found in trace result"


# ---------------------------------------------------------------------------
# Static boundary
# ---------------------------------------------------------------------------

class TestAuthorityTraceStaticBoundary:

    def test_no_runner_import_added(self):
        import inspect
        import assistant_os.mso.authority_trace as m
        src = inspect.getsource(m)
        assert "from .runner" not in src
        assert "machine_operator_adapter" not in src

    def test_no_auto_ref_added(self):
        import inspect
        import assistant_os.mso.authority_trace as m
        src = inspect.getsource(m)
        assert "auto:" not in src
