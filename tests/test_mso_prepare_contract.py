"""
Tests for assistant_os.mso.prepare_contract (PrepareRequest model + contract).

Validates:
- prepare rejects Plan in draft state
- prepare rejects Plan in planning state
- prepare accepts only mso_review
- prepare requires operator_seat
- prepare rejects operator_seat mismatch
- prepare requires valid ACK (ack_status=acknowledged)
- prepare rejects ACK with ack_status=rejected_for_review
- prepare requires confirmation_acknowledged=True
- prepare creates PrepareRequest with plan_id and correlation_id
- duplicate prepare rejected with DuplicatePrepareRequest
- prepare enqueues PreparedAction in queue
- prepare does not execute
- prepare does not call Runner
- prepare does not emit tokens
- prepare does not create AuthorityArtifact from UI
- prepare does not use auto refs
- unmappable target_actions fail-closed
- policy deny fail-closed (check_capability returns deny)
- governance blocked fail-closed (FROZEN mode)
- correlation_id propagates (PrepareRequest.correlation_id == plan_id)
- PreparedAction carries plan_id in metadata
- plan state unchanged after prepare (still mso_review)
- static boundary: prepare_contract does not import runner/machine_operator
"""
import os
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import patch

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
    DuplicatePrepareRequest,
    PrepareContractError,
    prepare_plan,
    map_target_actions_to_capability_scope,
    UnmappableTargetAction,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_stores(tmp_path, monkeypatch):
    draft_db = tmp_path / "test_plans.db"
    prepare_db = tmp_path / "test_prepare.db"
    monkeypatch.setenv(_DRAFT_STORE_ENV, str(draft_db))
    monkeypatch.setenv(_PREPARE_STORE_ENV, str(prepare_db))
    clear_confirmable_action_queue_for_tests()
    yield
    clear_confirmable_action_queue_for_tests()


def _plan_id() -> str:
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    uid = uuid4().hex[:8]
    return f"plan_{ts}_{uid}"


def _make_plan(state: str = "mso_review", seat: str = "operator_1", **kw) -> PlanRecord:
    now = datetime.now(timezone.utc).isoformat()
    pid = _plan_id()
    return PlanRecord(
        plan_id=pid,
        title=kw.get("title", "Test Plan"),
        intent_summary=kw.get("intent_summary", "Test intent"),
        domain=kw.get("domain", "CODE"),
        state=state,
        operator_seat=seat,
        schema_version="1",
        created_at=now,
        updated_at=now,
        risk_level=kw.get("risk_level", "low"),
        target_actions=kw.get("target_actions", ("CODE_REVIEW",)),
    )


def _seed_plan(plan: PlanRecord) -> PlanRecord:
    """Persist plan to draft store."""
    create_plan(plan)
    return plan


def _seed_ack(plan_id: str, seat: str = "operator_1", status: str = "acknowledged") -> PlanMSOAck:
    ack = PlanMSOAck(
        plan_id=plan_id,
        operator_seat=seat,
        ack_status=status,
        acknowledged_by="mso_sim",
    )
    create_ack(ack)
    return ack


# ---------------------------------------------------------------------------
# Mapper tests
# ---------------------------------------------------------------------------

class TestMapTargetActions:
    def test_known_canonical_action_maps(self):
        scope = map_target_actions_to_capability_scope(["CODE_REVIEW"])
        assert len(scope) == 1
        assert scope[0][0] == "CODE_REVIEW"

    def test_lowercase_variant_maps(self):
        scope = map_target_actions_to_capability_scope(["code_review"])
        assert scope[0][0] == "CODE_REVIEW"

    def test_multiple_actions_all_mapped(self):
        scope = map_target_actions_to_capability_scope(["CODE_REVIEW", "CODE_EXPLAIN"])
        actions = [s[0] for s in scope]
        assert "CODE_REVIEW" in actions
        assert "CODE_EXPLAIN" in actions

    def test_unmappable_action_raises(self):
        with pytest.raises(UnmappableTargetAction) as exc_info:
            map_target_actions_to_capability_scope(["fly_to_the_moon"])
        assert "fly_to_the_moon" in str(exc_info.value)

    def test_empty_list_raises(self):
        with pytest.raises((UnmappableTargetAction, ValueError)):
            map_target_actions_to_capability_scope([])

    def test_mixed_known_unknown_fails_closed(self):
        with pytest.raises(UnmappableTargetAction):
            map_target_actions_to_capability_scope(["CODE_REVIEW", "unknown_action"])

    def test_work_query_maps(self):
        scope = map_target_actions_to_capability_scope(["WORK_QUERY"])
        assert scope[0][0] == "WORK_QUERY"
        assert scope[0][1] == "WORK"

    def test_fin_expense_maps(self):
        scope = map_target_actions_to_capability_scope(["FIN_EXPENSE"])
        assert scope[0][0] == "FIN_EXPENSE"
        assert scope[0][1] == "FIN"


# ---------------------------------------------------------------------------
# prepare_plan: state validation
# ---------------------------------------------------------------------------

class TestPreparePlanStateValidation:
    def test_prepare_rejects_draft_state(self):
        plan = _seed_plan(_make_plan(state="draft"))
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.ok is False
        assert "draft" in result.fail_closed_reason.lower() or "mso_review" in result.fail_closed_reason.lower()

    def test_prepare_rejects_planning_state(self):
        plan = _seed_plan(_make_plan(state="planning"))
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.ok is False
        assert "planning" in result.fail_closed_reason.lower() or "mso_review" in result.fail_closed_reason.lower()

    def test_prepare_accepts_mso_review(self):
        plan = _seed_plan(_make_plan(state="mso_review"))
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.ok is True
        assert result.prepare_status == "prepared"

    def test_plan_state_unchanged_after_prepare(self):
        from assistant_os.mso.draft_store import get_plan
        plan = _seed_plan(_make_plan(state="mso_review"))
        _seed_ack(plan.plan_id)
        prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        current = get_plan(plan.plan_id, "operator_1")
        assert current.state == "mso_review"


# ---------------------------------------------------------------------------
# prepare_plan: authorization/identity validation
# ---------------------------------------------------------------------------

class TestPreparePlanAuth:
    def test_prepare_requires_confirmation_acknowledged(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=False,
        )
        assert result.ok is False
        assert "confirmation" in result.fail_closed_reason.lower()

    def test_prepare_rejects_operator_mismatch(self):
        plan = _seed_plan(_make_plan(seat="operator_1"))
        _seed_ack(plan.plan_id, seat="operator_1")
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_WRONG",
            requested_by="operator_WRONG",
            confirmation_acknowledged=True,
        )
        assert result.ok is False
        assert "seat" in result.fail_closed_reason.lower() or "mismatch" in result.fail_closed_reason.lower()

    def test_prepare_requires_ack(self):
        plan = _seed_plan(_make_plan())
        # No ACK created
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.ok is False
        assert "ack" in result.fail_closed_reason.lower()

    def test_prepare_rejects_rejected_for_review_ack(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id, status="rejected_for_review")
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.ok is False
        assert "rejected" in result.fail_closed_reason.lower()

    def test_prepare_unknown_plan_id(self):
        result = prepare_plan(
            plan_id="plan_9999_nonexistent",
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.ok is False
        assert "not found" in result.fail_closed_reason.lower() or "plan" in result.fail_closed_reason.lower()


# ---------------------------------------------------------------------------
# prepare_plan: duplicate request
# ---------------------------------------------------------------------------

class TestPreparePlanDuplicate:
    def test_duplicate_prepare_rejected(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        r1 = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert r1.ok is True
        r2 = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert r2.ok is False
        assert "duplicate" in r2.fail_closed_reason.lower() or "exists" in r2.fail_closed_reason.lower()


# ---------------------------------------------------------------------------
# prepare_plan: correlation
# ---------------------------------------------------------------------------

class TestPreparePlanCorrelation:
    def test_correlation_id_equals_plan_id(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.ok is True
        assert result.correlation_id == plan.plan_id

    def test_prepare_request_id_is_present(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.prepare_request_id
        assert result.prepare_request_id.startswith("prep_req_")

    def test_prepared_action_id_is_present(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.prepared_action_id is not None


# ---------------------------------------------------------------------------
# prepare_plan: queue integration
# ---------------------------------------------------------------------------

class TestPreparePlanQueueIntegration:
    def test_prepare_enqueues_prepared_action(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.ok is True
        pending = list_pending_confirmable_actions()
        assert len(pending) > 0
        entry = next((e for e in pending if e.prepared_action_id == result.prepared_action_id), None)
        assert entry is not None

    def test_prepared_action_is_review_only(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        pending = list_pending_confirmable_actions()
        entry = next(e for e in pending if e.prepared_action_id == result.prepared_action_id)
        assert entry.review_only is True
        assert entry.execution_allowed is False
        assert entry.can_execute_now is False


# ---------------------------------------------------------------------------
# prepare_plan: safety invariants
# ---------------------------------------------------------------------------

class TestPreparePlanSafetyInvariants:
    def test_response_execution_allowed_always_false(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.execution_allowed is False

    def test_response_used_execution_always_false(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.used_execution is False

    def test_response_runner_reachable_always_false(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.runner_reachable_from_ui is False

    def test_failure_response_also_false(self):
        result = prepare_plan(
            plan_id="plan_9999_nonexistent",
            operator_seat="op",
            requested_by="op",
            confirmation_acknowledged=True,
        )
        assert result.execution_allowed is False
        assert result.used_execution is False
        assert result.runner_reachable_from_ui is False


# ---------------------------------------------------------------------------
# prepare_plan: policy enforcement
# ---------------------------------------------------------------------------

class TestPreparePlanPolicyEnforcement:
    def test_unmappable_target_actions_fail_closed(self):
        plan = _seed_plan(_make_plan(target_actions=("fly_to_the_moon",)))
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.ok is False
        assert "unmappable" in result.fail_closed_reason.lower() or "fly_to_the_moon" in result.fail_closed_reason.lower()

    def test_policy_deny_fails_closed(self):
        # WORK_TEST_RESET is deny in capability registry
        plan = _seed_plan(_make_plan(target_actions=("WORK_TEST_RESET",)))
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        assert result.ok is False
        assert "denied" in result.fail_closed_reason.lower() or "policy" in result.fail_closed_reason.lower()

    def test_governance_frozen_fails_closed(self):
        from assistant_os.mso.system_state import set_operational_mode, clear_operational_mode_override
        try:
            set_operational_mode("FROZEN", reason="test")
            plan = _seed_plan(_make_plan(target_actions=("CODE_FIX",), risk_level="high"))
            _seed_ack(plan.plan_id)
            result = prepare_plan(
                plan_id=plan.plan_id,
                operator_seat="operator_1",
                requested_by="operator_1",
                confirmation_acknowledged=True,
            )
            assert result.ok is False
            assert "frozen" in result.fail_closed_reason.lower() or "governance" in result.fail_closed_reason.lower()
        finally:
            clear_operational_mode_override()


# ---------------------------------------------------------------------------
# Static boundary: prepare_contract must not import execution primitives
# ---------------------------------------------------------------------------

class TestPrepareContractStaticBoundary:
    def test_no_runner_import(self):
        import inspect
        import assistant_os.mso.prepare_contract as m
        src = inspect.getsource(m)
        forbidden = ["from .runner", "import runner", "machine_operator_adapter", "machine_operator_execute"]
        for token in forbidden:
            assert token not in src, f"Forbidden import '{token}' found in prepare_contract.py"

    def test_no_api_agent_execute_reference(self):
        import inspect
        import assistant_os.mso.prepare_contract as m
        src = inspect.getsource(m)
        assert "/api/agent/execute" not in src

    def test_no_auto_ref_pattern(self):
        import inspect
        import assistant_os.mso.prepare_contract as m
        src = inspect.getsource(m)
        assert "auto:" not in src

    def test_no_execution_status_field(self):
        from assistant_os.mso.plan_model import PlanRecord
        fields = {f.name for f in PlanRecord.__dataclass_fields__.values()}
        assert "execution_status" not in fields, "execution_status must not be a field on PlanRecord"
        assert "executionState" not in fields, "executionState must not be a field on PlanRecord"


# ---------------------------------------------------------------------------
# PrepareRequest model
# ---------------------------------------------------------------------------

class TestPrepareRequestModel:
    def test_prepare_request_has_plan_id(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        # Retrieve PrepareRequest from store
        from assistant_os.mso.prepare_contract import get_prepare_request
        req = get_prepare_request(result.prepare_request_id)
        assert req.plan_id == plan.plan_id

    def test_prepare_request_correlation_id_equals_plan_id(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        from assistant_os.mso.prepare_contract import get_prepare_request
        req = get_prepare_request(result.prepare_request_id)
        assert req.correlation_id == plan.plan_id

    def test_prepare_request_no_execution_fields(self):
        plan = _seed_plan(_make_plan())
        _seed_ack(plan.plan_id)
        result = prepare_plan(
            plan_id=plan.plan_id,
            operator_seat="operator_1",
            requested_by="operator_1",
            confirmation_acknowledged=True,
        )
        from assistant_os.mso.prepare_contract import get_prepare_request
        req = get_prepare_request(result.prepare_request_id)
        d = req.to_dict()
        assert d["execution_allowed"] is False
        assert d["used_execution"] is False
        assert d["runner_reachable_from_ui"] is False
        forbidden_keys = {"capability_token_ref", "authority_artifact_ref", "runner_ref", "mission_id"}
        for key in forbidden_keys:
            assert key not in d, f"Forbidden field '{key}' in PrepareRequest.to_dict()"
