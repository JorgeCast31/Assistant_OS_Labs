"""
UI contract tests for the prepare contract surface.

Validates:
- All prepare contract responses carry execution_allowed=False, used_execution=False,
  runner_reachable_from_ui=False — including failure responses
- PreparedAction produced by prepare is review-only (waiting_for_human_confirmation)
- prepare_status labels are safe (never running/executing/live/completed/approved/authorized)
- Static boundary: no runner/machine_operator in prepare modules
- Static boundary: no /api/agent/execute reference in prepare modules
- Static boundary: no auto: pattern as policy ref in prepare modules
- Static boundary: plan_ack does not import execution artifacts
- PlanMSOAck.to_dict() is safe for UI transport (no forbidden fields)
- PrepareContractResponse.to_dict() is safe for UI transport (no forbidden fields)
- PrepareRequest.to_dict() is safe for UI transport (no forbidden fields)
- Prepare requires explicit confirmation (cannot be called with confirmation_acknowledged=False)
- UI label contract: prepare_status never equals execution-implying states
"""
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from assistant_os.mso.plan_model import PlanRecord
from assistant_os.mso.draft_store import create_plan, _DRAFT_STORE_ENV
from assistant_os.mso.plan_ack import (
    PlanMSOAck, create_ack, _PREPARE_STORE_ENV,
)
from assistant_os.mso.prepared_action_queue import (
    clear_confirmable_action_queue_for_tests,
    list_pending_confirmable_actions,
)
from assistant_os.mso.prepare_contract import (
    PrepareRequest,
    PrepareContractResponse,
    prepare_plan,
    get_prepare_request,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_stores(tmp_path, monkeypatch):
    draft_db = tmp_path / "ui_plans.db"
    prepare_db = tmp_path / "ui_prepare.db"
    monkeypatch.setenv(_DRAFT_STORE_ENV, str(draft_db))
    monkeypatch.setenv(_PREPARE_STORE_ENV, str(prepare_db))
    clear_confirmable_action_queue_for_tests()
    yield
    clear_confirmable_action_queue_for_tests()


def _plan_id() -> str:
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    return f"plan_{ts}_{uuid4().hex[:8]}"


def _seed_plan(state: str = "mso_review", seat: str = "op_1") -> PlanRecord:
    now = datetime.now(timezone.utc).isoformat()
    plan = PlanRecord(
        plan_id=_plan_id(),
        title="UI Contract Test Plan",
        intent_summary="Test intent for UI contracts",
        domain="CODE",
        state=state,
        operator_seat=seat,
        schema_version="1",
        created_at=now,
        updated_at=now,
        risk_level="low",
        target_actions=("CODE_REVIEW",),
    )
    create_plan(plan)
    return plan


def _seed_ack(plan_id: str, seat: str = "op_1", status: str = "acknowledged") -> PlanMSOAck:
    ack = PlanMSOAck(
        plan_id=plan_id, operator_seat=seat,
        ack_status=status, acknowledged_by="mso_sim",
    )
    create_ack(ack)
    return ack


def _do_prepare(plan_id: str, seat: str = "op_1") -> PrepareContractResponse:
    return prepare_plan(
        plan_id=plan_id,
        operator_seat=seat,
        requested_by=seat,
        confirmation_acknowledged=True,
    )


# ---------------------------------------------------------------------------
# Response contract: safety invariants always present
# ---------------------------------------------------------------------------

class TestResponseSafetyInvariants:
    def test_success_response_has_execution_allowed_false(self):
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = _do_prepare(plan.plan_id)
        assert r.execution_allowed is False

    def test_success_response_has_used_execution_false(self):
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = _do_prepare(plan.plan_id)
        assert r.used_execution is False

    def test_success_response_has_runner_reachable_false(self):
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = _do_prepare(plan.plan_id)
        assert r.runner_reachable_from_ui is False

    def test_failure_response_has_execution_allowed_false(self):
        r = prepare_plan(
            plan_id="plan_9999_notfound",
            operator_seat="op_1",
            requested_by="op_1",
            confirmation_acknowledged=True,
        )
        assert r.execution_allowed is False

    def test_failure_response_has_used_execution_false(self):
        r = prepare_plan(
            plan_id="plan_9999_notfound",
            operator_seat="op_1",
            requested_by="op_1",
            confirmation_acknowledged=True,
        )
        assert r.used_execution is False

    def test_failure_response_has_runner_reachable_false(self):
        r = prepare_plan(
            plan_id="plan_9999_notfound",
            operator_seat="op_1",
            requested_by="op_1",
            confirmation_acknowledged=True,
        )
        assert r.runner_reachable_from_ui is False

    def test_confirmation_not_acknowledged_gives_safe_response(self):
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="op_1",
            requested_by="op_1",
            confirmation_acknowledged=False,
        )
        assert r.ok is False
        assert r.execution_allowed is False
        assert r.used_execution is False
        assert r.runner_reachable_from_ui is False


# ---------------------------------------------------------------------------
# UI label contract: forbidden status values
# ---------------------------------------------------------------------------

_FORBIDDEN_LABELS = {
    "running", "executing", "completed", "live", "approved",
    "authorized", "ready_to_execute", "execute", "active",
}

class TestUILabelContract:
    def test_prepare_status_is_not_execution_implying(self):
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = _do_prepare(plan.plan_id)
        assert r.prepare_status not in _FORBIDDEN_LABELS, (
            f"prepare_status '{r.prepare_status}' is an execution-implying label"
        )

    def test_prepare_status_is_prepared(self):
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = _do_prepare(plan.plan_id)
        assert r.prepare_status == "prepared"

    def test_prepare_status_rejected_is_not_execution_implying(self):
        plan = _seed_plan(state="draft")
        _seed_ack(plan.plan_id)
        r = _do_prepare(plan.plan_id)
        assert r.prepare_status not in _FORBIDDEN_LABELS

    def test_prepared_action_status_is_pending_review(self):
        """Queue entry status is 'pending_review' — not an execution-implying label."""
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = _do_prepare(plan.plan_id)
        pending = list_pending_confirmable_actions()
        entry = next(e for e in pending if e.prepared_action_id == r.prepared_action_id)
        # Queue entry status is always pending_review (ConfirmablePreparedActionQueueEntry)
        assert entry.status == "pending_review"
        assert entry.status not in _FORBIDDEN_LABELS

    def test_source_label_is_prepare_contract(self):
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = _do_prepare(plan.plan_id)
        assert r.source == "prepare_contract"


# ---------------------------------------------------------------------------
# to_dict() transport safety
# ---------------------------------------------------------------------------

_TRANSPORT_FORBIDDEN = {
    "capability_token_ref", "authority_artifact_ref", "runner_ref",
    "mission_id", "execution_status", "executionState",
}

class TestTransportSafety:
    def test_prepare_contract_response_dict_safe(self):
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = _do_prepare(plan.plan_id)
        d = r.to_dict()
        for key in _TRANSPORT_FORBIDDEN:
            assert key not in d, f"Forbidden field '{key}' in PrepareContractResponse.to_dict()"

    def test_prepare_contract_response_dict_has_invariants(self):
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = _do_prepare(plan.plan_id)
        d = r.to_dict()
        assert d["execution_allowed"] is False
        assert d["used_execution"] is False
        assert d["runner_reachable_from_ui"] is False

    def test_prepare_request_dict_safe(self):
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = _do_prepare(plan.plan_id)
        req = get_prepare_request(r.prepare_request_id)
        d = req.to_dict()
        for key in _TRANSPORT_FORBIDDEN:
            assert key not in d, f"Forbidden field '{key}' in PrepareRequest.to_dict()"

    def test_plan_mso_ack_dict_safe(self):
        pid = _plan_id()
        plan = PlanRecord(
            plan_id=pid, title="t", intent_summary="i", domain="d",
            state="mso_review", operator_seat="op_1", schema_version="1",
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        create_plan(plan)
        ack = _seed_ack(pid)
        d = ack.to_dict()
        for key in _TRANSPORT_FORBIDDEN:
            assert key not in d, f"Forbidden field '{key}' in PlanMSOAck.to_dict()"

    def test_plan_mso_ack_dict_has_invariants(self):
        pid = _plan_id()
        plan = PlanRecord(
            plan_id=pid, title="t", intent_summary="i", domain="d",
            state="mso_review", operator_seat="op_1", schema_version="1",
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        create_plan(plan)
        ack = _seed_ack(pid)
        d = ack.to_dict()
        assert d["execution_allowed"] is False
        assert d["used_execution"] is False
        assert d["runner_reachable_from_ui"] is False


# ---------------------------------------------------------------------------
# Static boundary contracts
# ---------------------------------------------------------------------------

class TestStaticBoundary:
    def test_prepare_contract_no_runner_import(self):
        import inspect
        import assistant_os.mso.prepare_contract as m
        src = inspect.getsource(m)
        assert "from .runner" not in src
        assert "import runner" not in src
        assert "machine_operator_adapter" not in src

    def test_prepare_contract_no_api_agent_execute(self):
        import inspect
        import assistant_os.mso.prepare_contract as m
        src = inspect.getsource(m)
        assert "/api/agent/execute" not in src

    def test_prepare_contract_no_auto_ref(self):
        import inspect
        import assistant_os.mso.prepare_contract as m
        src = inspect.getsource(m)
        assert "auto:" not in src

    def test_plan_ack_no_execution_artifacts(self):
        import inspect
        import assistant_os.mso.plan_ack as m
        src = inspect.getsource(m)
        # Check for import statements specifically — "runner" appears in
        # field name runner_reachable_from_ui which is intentional
        forbidden_imports = [
            "from .execution_proposal",
            "from .authority_preparation",
            "from .confirmable_prepared_action",
            "from .prepared_action_queue",
            "from .police",
            "import runner",
            "from .runner",
            "from ..runner",
            "machine_operator",
        ]
        for token in forbidden_imports:
            assert token not in src, f"Forbidden import '{token}' in plan_ack.py"

    def test_prepare_contract_no_execution_proposal_as_input(self):
        """prepare_contract does not require MSOExecutionProposal as input."""
        import inspect
        import assistant_os.mso.prepare_contract as m
        # prepare_contract may import from execution_proposal for REQUIRED_AUTHORITY_CHAIN only
        # but must NOT use build_execution_proposal or MSOExecutionProposal as input type
        src = inspect.getsource(m)
        assert "build_execution_proposal" not in src
        assert "build_safe_fallback_proposal" not in src


# ---------------------------------------------------------------------------
# Prepare requires explicit confirmation
# ---------------------------------------------------------------------------

class TestExplicitConfirmationRequired:
    def test_false_confirmation_rejected(self):
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="op_1",
            requested_by="op_1",
            confirmation_acknowledged=False,
        )
        assert r.ok is False
        assert "confirmation" in r.fail_closed_reason.lower()

    def test_true_confirmation_proceeds(self):
        plan = _seed_plan()
        _seed_ack(plan.plan_id)
        r = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="op_1",
            requested_by="op_1",
            confirmation_acknowledged=True,
        )
        assert r.ok is True

    def test_ack_read_receipt_not_authorization(self):
        """ACK source must be 'plan_mso_ack', not any execution-implying source."""
        pid = _plan_id()
        plan = PlanRecord(
            plan_id=pid, title="t", intent_summary="i", domain="d",
            state="mso_review", operator_seat="op_1", schema_version="1",
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        create_plan(plan)
        ack = _seed_ack(pid)
        assert ack.source == "plan_mso_ack"
        d = ack.to_dict()
        assert "authorized" not in d.get("source", "")
        assert "execution" not in d.get("source", "")
