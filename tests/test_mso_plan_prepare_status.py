"""
Tests for assistant_os.mso.plan_prepare_status (read-model).

Validates:
- no_plan when plan_id not found
- draft state returned when Plan is in draft
- planning state returned when Plan is in planning
- mso_review_ack_pending when Plan in mso_review with no ACK
- mso_review_ack_rejected when ACK status is rejected_for_review
- acked_prepare_not_requested when ACK acknowledged but no PrepareRequest
- prepared_awaiting_confirmation after successful prepare
- prepare_rejected after rejected prepare
- operator_seat mismatch rejected
- response always has execution_allowed=False, used_execution=False, runner_reachable_from_ui=False
- response source is "prepare_status"
- correlation_id equals plan_id
- missing_requirements is a list of strings
- authority_stage reflects current stage
- no running/executing/completed/live/authorized labels anywhere
- static boundary: plan_prepare_status does not import Runner/MachineOperator
"""
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from assistant_os.mso.plan_model import PlanRecord
from assistant_os.mso.draft_store import create_plan, _DRAFT_STORE_ENV
from assistant_os.mso.plan_ack import PlanMSOAck, create_ack, _PREPARE_STORE_ENV
from assistant_os.mso.prepare_contract import prepare_plan
from assistant_os.mso.prepared_action_queue import clear_confirmable_action_queue_for_tests
from assistant_os.mso.plan_prepare_status import (
    get_plan_prepare_status,
    PlanPrepareStatus,
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


def _make_plan(state: str = "mso_review", seat: str = "op_1", **kw) -> PlanRecord:
    return PlanRecord(
        plan_id=_plan_id(),
        title=kw.get("title", "T"),
        intent_summary=kw.get("intent_summary", "I"),
        domain=kw.get("domain", "CODE"),
        state=state,
        operator_seat=seat,
        schema_version="1",
        created_at=_now(),
        updated_at=_now(),
        risk_level=kw.get("risk_level", "low"),
        target_actions=kw.get("target_actions", ("CODE_REVIEW",)),
    )


def _seed(plan: PlanRecord) -> PlanRecord:
    create_plan(plan)
    return plan


def _ack(plan_id: str, seat: str = "op_1", status: str = "acknowledged") -> PlanMSOAck:
    a = PlanMSOAck(plan_id=plan_id, operator_seat=seat,
                   ack_status=status, acknowledged_by="mso_sim")
    create_ack(a)
    return a


# ---------------------------------------------------------------------------
# Status resolution
# ---------------------------------------------------------------------------

class TestGetPlanPrepareStatus:

    def test_no_plan_unknown_id(self):
        result = get_plan_prepare_status("plan_9999_notexist", "op_1")
        assert result.status == "no_plan"
        assert result.ok is False

    def test_draft_plan(self):
        plan = _seed(_make_plan(state="draft"))
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.status == "draft"
        assert "mso_review" in " ".join(result.missing_requirements).lower()

    def test_planning_plan(self):
        plan = _seed(_make_plan(state="planning"))
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.status == "planning"
        assert len(result.missing_requirements) > 0

    def test_mso_review_no_ack(self):
        plan = _seed(_make_plan(state="mso_review"))
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.status == "mso_review_ack_pending"
        assert any("ack" in r.lower() for r in result.missing_requirements)

    def test_mso_review_ack_rejected(self):
        plan = _seed(_make_plan(state="mso_review"))
        _ack(plan.plan_id, status="rejected_for_review")
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.status == "mso_review_ack_rejected"
        assert result.ack_status == "rejected_for_review"

    def test_acked_no_prepare(self):
        plan = _seed(_make_plan(state="mso_review"))
        _ack(plan.plan_id)
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.status == "acked_prepare_not_requested"
        assert any("prepare" in r.lower() for r in result.missing_requirements)

    def test_prepared_awaiting_confirmation(self):
        plan = _seed(_make_plan(state="mso_review"))
        _ack(plan.plan_id)
        prepare_plan(
            plan_id=plan.plan_id, operator_seat="op_1",
            requested_by="op_1", confirmation_acknowledged=True,
        )
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.status == "prepared_awaiting_confirmation"
        assert result.prepared_action_id is not None
        assert result.confirm_queue_status == "pending_review"

    def test_prepare_rejected(self):
        # Plan with deny-listed action → prepare rejected → status shows rejected
        plan = _seed(_make_plan(state="mso_review", target_actions=("WORK_TEST_RESET",)))
        _ack(plan.plan_id)
        prepare_plan(
            plan_id=plan.plan_id, operator_seat="op_1",
            requested_by="op_1", confirmation_acknowledged=True,
        )
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.status == "prepare_rejected"
        assert result.prepare_request_id is not None

    def test_operator_mismatch_fails(self):
        plan = _seed(_make_plan(seat="op_1"))
        result = get_plan_prepare_status(plan.plan_id, "op_WRONG")
        assert result.ok is False
        assert "seat" in result.status or "mismatch" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# Response invariants
# ---------------------------------------------------------------------------

class TestPlanPrepareStatusInvariants:

    def test_execution_allowed_always_false_on_success(self):
        plan = _seed(_make_plan(state="mso_review"))
        _ack(plan.plan_id)
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.execution_allowed is False

    def test_execution_allowed_always_false_on_no_plan(self):
        result = get_plan_prepare_status("plan_9999_x", "op_1")
        assert result.execution_allowed is False

    def test_used_execution_always_false(self):
        plan = _seed(_make_plan(state="mso_review"))
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.used_execution is False

    def test_runner_reachable_always_false(self):
        plan = _seed(_make_plan(state="mso_review"))
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.runner_reachable_from_ui is False

    def test_source_is_prepare_status(self):
        plan = _seed(_make_plan(state="mso_review"))
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.source == "prepare_status"

    def test_correlation_id_equals_plan_id(self):
        plan = _seed(_make_plan(state="mso_review"))
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.correlation_id == plan.plan_id

    def test_plan_state_present(self):
        plan = _seed(_make_plan(state="mso_review"))
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.plan_state == "mso_review"

    def test_missing_requirements_is_list(self):
        plan = _seed(_make_plan(state="draft"))
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert isinstance(result.missing_requirements, list)

    def test_to_dict_no_forbidden_fields(self):
        plan = _seed(_make_plan(state="mso_review"))
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        d = result.to_dict()
        forbidden = {
            "capability_token_ref", "authority_artifact_ref", "runner_ref",
            "execution_status", "executionState", "mission_id",
        }
        for key in forbidden:
            assert key not in d, f"Forbidden field '{key}' in PlanPrepareStatus.to_dict()"


# ---------------------------------------------------------------------------
# Forbidden labels
# ---------------------------------------------------------------------------

_FORBIDDEN_STATUSES = {"running", "executing", "completed", "live", "authorized", "approved"}

class TestForbiddenLabels:

    def test_status_never_execution_implying_on_draft(self):
        plan = _seed(_make_plan(state="draft"))
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.status not in _FORBIDDEN_STATUSES

    def test_status_never_execution_implying_on_prepared(self):
        plan = _seed(_make_plan(state="mso_review"))
        _ack(plan.plan_id)
        prepare_plan(
            plan_id=plan.plan_id, operator_seat="op_1",
            requested_by="op_1", confirmation_acknowledged=True,
        )
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.status not in _FORBIDDEN_STATUSES

    def test_authority_stage_never_execution_implying(self):
        plan = _seed(_make_plan(state="mso_review"))
        _ack(plan.plan_id)
        prepare_plan(
            plan_id=plan.plan_id, operator_seat="op_1",
            requested_by="op_1", confirmation_acknowledged=True,
        )
        result = get_plan_prepare_status(plan.plan_id, "op_1")
        assert result.authority_stage not in _FORBIDDEN_STATUSES


# ---------------------------------------------------------------------------
# Static boundary
# ---------------------------------------------------------------------------

class TestStaticBoundary:

    def test_no_runner_import(self):
        import inspect
        import assistant_os.mso.plan_prepare_status as m
        src = inspect.getsource(m)
        forbidden = ["from .runner", "import runner", "machine_operator_adapter"]
        for token in forbidden:
            assert token not in src, f"'{token}' found in plan_prepare_status.py"

    def test_no_auto_ref(self):
        import inspect
        import assistant_os.mso.plan_prepare_status as m
        src = inspect.getsource(m)
        assert "auto:" not in src

    def test_no_execution_allowed_true_in_source(self):
        import inspect
        import assistant_os.mso.plan_prepare_status as m
        src = inspect.getsource(m)
        assert "execution_allowed=True" not in src
        assert "used_execution=True" not in src
