"""
UI contract tests for plan prepare status surface.

Validates:
- response is always safe for UI transport (no forbidden fields)
- execution_allowed, used_execution, runner_reachable_from_ui always False
- status label is never execution-implying
- authority_stage is never execution-implying
- to_dict() is safe for JSON serialization
- backward-compatible snapshot still passes mission_control_truth_contracts
- no runner/machine_operator imports in plan_prepare_status
- no auto: pattern in plan_prepare_status
- trace_type is "snapshot" never "live"
"""
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from assistant_os.mso.plan_model import PlanRecord
from assistant_os.mso.draft_store import create_plan, _DRAFT_STORE_ENV
from assistant_os.mso.plan_ack import PlanMSOAck, create_ack, _PREPARE_STORE_ENV
from assistant_os.mso.prepare_contract import prepare_plan
from assistant_os.mso.prepared_action_queue import clear_confirmable_action_queue_for_tests
from assistant_os.mso.plan_prepare_status import get_plan_prepare_status
from assistant_os.mso.authority_trace import build_authority_trace_for_plan, build_authority_trace_snapshot


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_stores(tmp_path, monkeypatch):
    monkeypatch.setenv(_DRAFT_STORE_ENV, str(tmp_path / "plans.db"))
    monkeypatch.setenv(_PREPARE_STORE_ENV, str(tmp_path / "prepare.db"))
    clear_confirmable_action_queue_for_tests()
    yield
    clear_confirmable_action_queue_for_tests()


def _plan_id() -> str:
    return f"plan_{int(datetime.now(timezone.utc).timestamp()*1000)}_{uuid4().hex[:8]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed(state: str = "mso_review", seat: str = "op_1") -> PlanRecord:
    plan = PlanRecord(
        plan_id=_plan_id(), title="T", intent_summary="I", domain="CODE",
        state=state, operator_seat=seat, schema_version="1",
        created_at=_now(), updated_at=_now(), risk_level="low",
        target_actions=("CODE_REVIEW",),
    )
    create_plan(plan)
    return plan


def _ack(plan_id: str, seat: str = "op_1") -> None:
    create_ack(PlanMSOAck(plan_id=plan_id, operator_seat=seat,
                          ack_status="acknowledged", acknowledged_by="mso_sim"))


_FORBIDDEN = {
    "running", "executing", "completed", "live", "authorized", "approved",
    "execute", "active",
}

_FORBIDDEN_FIELDS = {
    "capability_token_ref", "authority_artifact_ref", "runner_ref",
    "execution_status", "executionState", "mission_id",
}


# ---------------------------------------------------------------------------
# to_dict() transport safety
# ---------------------------------------------------------------------------

class TestTransportSafety:

    def test_to_dict_no_forbidden_fields_on_no_plan(self):
        result = get_plan_prepare_status("plan_0_notfound", "op_1")
        d = result.to_dict()
        for key in _FORBIDDEN_FIELDS:
            assert key not in d

    def test_to_dict_no_forbidden_fields_on_prepared(self):
        plan = _seed()
        _ack(plan.plan_id)
        prepare_plan(plan_id=plan.plan_id, operator_seat="op_1",
                     requested_by="op_1", confirmation_acknowledged=True)
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        d = result.to_dict()
        for key in _FORBIDDEN_FIELDS:
            assert key not in d

    def test_to_dict_invariants_present(self):
        plan = _seed()
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        d = result.to_dict()
        assert d["execution_allowed"] is False
        assert d["used_execution"] is False
        assert d["runner_reachable_from_ui"] is False

    def test_to_dict_source_label(self):
        plan = _seed()
        d = get_plan_prepare_status(plan.plan_id, "op_1").to_dict()
        assert d["source"] == "prepare_status"

    def test_trace_to_dict_no_forbidden_fields(self):
        plan = _seed()
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        for key in _FORBIDDEN_FIELDS:
            assert key not in result

    def test_trace_invariants(self):
        plan = _seed()
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        assert result["execution_allowed"] is False
        assert result["used_execution"] is False
        assert result["runner_closed_from_ui"] is True


# ---------------------------------------------------------------------------
# Label contract
# ---------------------------------------------------------------------------

class TestLabelContract:

    def test_status_never_forbidden_on_draft(self):
        plan = _seed(state="draft")
        assert get_plan_prepare_status(plan.plan_id, "op_1").status not in _FORBIDDEN

    def test_status_never_forbidden_on_prepared(self):
        plan = _seed()
        _ack(plan.plan_id)
        prepare_plan(plan_id=plan.plan_id, operator_seat="op_1",
                     requested_by="op_1", confirmation_acknowledged=True)
        assert get_plan_prepare_status(plan.plan_id, "op_1").status not in _FORBIDDEN

    def test_authority_stage_never_forbidden(self):
        plan = _seed()
        _ack(plan.plan_id)
        prepare_plan(plan_id=plan.plan_id, operator_seat="op_1",
                     requested_by="op_1", confirmation_acknowledged=True)
        stage = get_plan_prepare_status(plan.plan_id, "op_1").authority_stage
        assert stage not in _FORBIDDEN

    def test_trace_type_is_snapshot(self):
        plan = _seed()
        result = build_authority_trace_for_plan(plan.plan_id, "op_1")
        assert result["trace_type"] == "snapshot"
        assert "live" not in result["trace_type"]

    def test_prepared_awaiting_confirmation_label(self):
        plan = _seed()
        _ack(plan.plan_id)
        prepare_plan(plan_id=plan.plan_id, operator_seat="op_1",
                     requested_by="op_1", confirmation_acknowledged=True)
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.status == "prepared_awaiting_confirmation"
        # "Prepared — Awaiting Confirmation" is the label intent
        assert "prepared" in result.status
        assert "confirmation" in result.status


# ---------------------------------------------------------------------------
# Snapshot backward compatibility (existing mission_control truth contracts)
# ---------------------------------------------------------------------------

class TestSnapshotBackwardCompatibility:

    def test_existing_snapshot_still_returns_chain(self):
        result = build_authority_trace_snapshot()
        assert "chain" in result
        assert len(result["chain"]) == 9

    def test_existing_snapshot_execution_allowed_false(self):
        assert build_authority_trace_snapshot()["execution_allowed"] is False

    def test_existing_snapshot_available_true(self):
        assert build_authority_trace_snapshot()["available"] is True


# ---------------------------------------------------------------------------
# Static boundary
# ---------------------------------------------------------------------------

class TestStaticBoundary:

    def test_plan_prepare_status_no_runner(self):
        import inspect
        import assistant_os.mso.plan_prepare_status as m
        src = inspect.getsource(m)
        for token in ["from .runner", "import runner", "machine_operator_adapter"]:
            assert token not in src

    def test_plan_prepare_status_no_auto_ref(self):
        import inspect
        import assistant_os.mso.plan_prepare_status as m
        assert "auto:" not in inspect.getsource(m)

    def test_authority_trace_no_runner_import_added(self):
        import inspect
        import assistant_os.mso.authority_trace as m
        src = inspect.getsource(m)
        assert "from .runner" not in src
        assert "machine_operator_adapter" not in src
