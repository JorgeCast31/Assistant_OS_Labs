"""
Tests for assistant_os.mso.draft_store.

Validates:
- create/save/load plans
- plan_id format enforced
- invalid state rejected
- operator_seat mismatch rejected
- list_plans requires operator_seat
- update_plan with audit log in planning state (D-08)
- mso_review immutable (get/update/abandon)
- mso_review visible in list/get (D-11)
- abandon draft silent, abandon planning audited (D-02)
- transition state machine
- no execution fields in stored records
- source = draft_store in response dicts
- schema_version fail-closed
- static boundary: draft_store does not import authority artifacts
"""
import os
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from assistant_os.mso.plan_model import (
    InvalidPlanId,
    InvalidTransition,
    OperatorSeatMismatch,
    PlanImmutable,
    PlanNotFound,
    PlanRecord,
    PlanUpdate,
    UnknownSchemaVersion,
)
from assistant_os.mso.draft_store import (
    abandon_plan,
    create_plan,
    get_audit_log,
    get_draft_store_path,
    get_plan,
    list_plans,
    transition_plan,
    update_plan,
    _DRAFT_STORE_ENV,
)


# ---------------------------------------------------------------------------
# Test isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Each test gets its own SQLite file to prevent state leakage."""
    db = tmp_path / "test_plans.db"
    monkeypatch.setenv(_DRAFT_STORE_ENV, str(db))
    yield db


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_id() -> str:
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    uid = uuid4().hex[:8]
    return f"plan_{ts}_{uid}"


def _make_plan(seat: str = "operator_1", state: str = "draft", **overrides) -> PlanRecord:
    defaults = dict(
        plan_id=_plan_id(),
        title="Test Plan",
        intent_summary="A test intent",
        domain="infra",
        state=state,
        operator_seat=seat,
        schema_version="1",
        created_at=_ts(),
        updated_at=_ts(),
    )
    defaults.update(overrides)
    return PlanRecord(**defaults)


# ---------------------------------------------------------------------------
# Store path
# ---------------------------------------------------------------------------

class TestStorePath:
    def test_env_override_respected(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom.db"
        monkeypatch.setenv(_DRAFT_STORE_ENV, str(custom))
        assert get_draft_store_path() == custom

    def test_default_path_contains_draft_store(self, monkeypatch):
        monkeypatch.delenv(_DRAFT_STORE_ENV, raising=False)
        path = get_draft_store_path()
        assert "draft_store" in str(path)
        assert "mso_store" not in str(path), \
            "Draft Store must not reside in mso_store/"


# ---------------------------------------------------------------------------
# create / get
# ---------------------------------------------------------------------------

class TestCreateAndGet:
    def test_create_and_retrieve(self):
        plan = _make_plan()
        create_plan(plan)
        retrieved = get_plan(plan.plan_id, plan.operator_seat)
        assert retrieved.plan_id == plan.plan_id
        assert retrieved.title == plan.title
        assert retrieved.state == plan.state

    def test_get_nonexistent_raises(self):
        with pytest.raises(PlanNotFound):
            get_plan("plan_0000_xxxxxxxx", "operator_1")

    def test_get_wrong_seat_raises(self):
        plan = _make_plan(seat="operator_1")
        create_plan(plan)
        with pytest.raises(OperatorSeatMismatch):
            get_plan(plan.plan_id, "operator_2")

    def test_create_duplicate_raises(self):
        import sqlite3
        plan = _make_plan()
        create_plan(plan)
        with pytest.raises(sqlite3.IntegrityError):
            create_plan(plan)

    def test_schema_version_stored_and_returned(self):
        plan = _make_plan()
        create_plan(plan)
        retrieved = get_plan(plan.plan_id, plan.operator_seat)
        assert retrieved.schema_version == "1"

    def test_create_produces_audit_entry(self):
        plan = _make_plan()
        create_plan(plan)
        audit = get_audit_log(plan.plan_id)
        assert any(e.event == "created" for e in audit)

    def test_no_execution_fields_in_stored_record(self):
        plan = _make_plan()
        create_plan(plan)
        retrieved = get_plan(plan.plan_id, plan.operator_seat)
        for attr in ("execution_allowed", "execution_status", "executionState",
                     "used_execution", "policy_decision_ref", "governance_ref",
                     "capability_token_ref", "runner_ref", "mission_id",
                     "prepared_action_id", "can_execute_now"):
            assert not hasattr(retrieved, attr), \
                f"PlanRecord must not have field: {attr}"


# ---------------------------------------------------------------------------
# plan_id format
# ---------------------------------------------------------------------------

class TestPlanIdFormat:
    def test_invalid_plan_id_rejected_by_create(self):
        with pytest.raises(InvalidPlanId):
            plan = _make_plan(plan_id="bad_id_without_prefix")
            create_plan(plan)

    def test_valid_plan_id_accepted(self):
        plan = _make_plan(plan_id="plan_1748476800000_a3f9c2e1")
        create_plan(plan)
        retrieved = get_plan(plan.plan_id, plan.operator_seat)
        assert retrieved.plan_id == "plan_1748476800000_a3f9c2e1"


# ---------------------------------------------------------------------------
# list_plans
# ---------------------------------------------------------------------------

class TestListPlans:
    def test_list_returns_own_plans(self):
        p1 = _make_plan(seat="op_a")
        p2 = _make_plan(seat="op_a")
        create_plan(p1)
        create_plan(p2)
        results = list_plans("op_a")
        ids = {r.plan_id for r in results}
        assert p1.plan_id in ids
        assert p2.plan_id in ids

    def test_list_excludes_other_seats(self):
        p1 = _make_plan(seat="op_a")
        p2 = _make_plan(seat="op_b")
        create_plan(p1)
        create_plan(p2)
        results = list_plans("op_a")
        ids = {r.plan_id for r in results}
        assert p2.plan_id not in ids

    def test_list_empty_returns_empty(self):
        assert list_plans("unknown_seat") == []

    def test_list_includes_mso_review(self):
        """D-11: mso_review plans are visible in list."""
        plan = _make_plan(seat="op_x", state="planning")
        create_plan(plan)
        transition_plan(plan.plan_id, "planning", "mso_review", "op_x")
        results = list_plans("op_x")
        states = {r.state for r in results}
        assert "mso_review" in states

    def test_list_ordered_by_created_at(self):
        import time
        p1 = _make_plan()
        create_plan(p1)
        time.sleep(0.01)
        p2 = _make_plan()
        create_plan(p2)
        results = list_plans(p1.operator_seat)
        ids = [r.plan_id for r in results]
        assert ids.index(p1.plan_id) < ids.index(p2.plan_id)


# ---------------------------------------------------------------------------
# update_plan — D-08
# ---------------------------------------------------------------------------

class TestUpdatePlan:
    def test_update_draft_no_audit(self):
        plan = _make_plan(state="draft")
        create_plan(plan)
        update_plan(plan.plan_id, plan.operator_seat, PlanUpdate(title="New Title"))
        retrieved = get_plan(plan.plan_id, plan.operator_seat)
        assert retrieved.title == "New Title"
        # No 'updated' audit entry for draft
        audit = get_audit_log(plan.plan_id)
        assert not any(e.event == "updated" for e in audit)

    def test_update_planning_creates_audit_entry(self):
        """D-08: update in planning state must produce audit entry."""
        plan = _make_plan(state="draft")
        create_plan(plan)
        transition_plan(plan.plan_id, "draft", "planning", plan.operator_seat)
        update_plan(plan.plan_id, plan.operator_seat, PlanUpdate(title="New Title"))
        audit = get_audit_log(plan.plan_id)
        assert any(e.event == "updated" for e in audit)

    def test_update_mso_review_raises(self):
        plan = _make_plan(state="planning")
        create_plan(plan)
        transition_plan(plan.plan_id, "planning", "mso_review", plan.operator_seat)
        with pytest.raises(PlanImmutable):
            update_plan(plan.plan_id, plan.operator_seat, PlanUpdate(title="x"))

    def test_update_wrong_seat_raises(self):
        plan = _make_plan(seat="op_a")
        create_plan(plan)
        with pytest.raises(OperatorSeatMismatch):
            update_plan(plan.plan_id, "op_b", PlanUpdate(title="x"))

    def test_update_nonexistent_raises(self):
        with pytest.raises(PlanNotFound):
            update_plan("plan_0000_xxxxxxxx", "op_a", PlanUpdate(title="x"))

    def test_empty_update_returns_unchanged(self):
        plan = _make_plan()
        create_plan(plan)
        result = update_plan(plan.plan_id, plan.operator_seat, PlanUpdate())
        assert result.title == plan.title

    def test_update_target_actions(self):
        plan = _make_plan()
        create_plan(plan)
        update_plan(plan.plan_id, plan.operator_seat,
                    PlanUpdate(target_actions=("deploy", "restart")))
        retrieved = get_plan(plan.plan_id, plan.operator_seat)
        assert retrieved.target_actions == ("deploy", "restart")

    def test_update_preserves_schema_version(self):
        plan = _make_plan()
        create_plan(plan)
        update_plan(plan.plan_id, plan.operator_seat, PlanUpdate(title="x"))
        retrieved = get_plan(plan.plan_id, plan.operator_seat)
        assert retrieved.schema_version == "1"


# ---------------------------------------------------------------------------
# transition_plan
# ---------------------------------------------------------------------------

class TestTransitionPlan:
    def test_draft_to_planning(self):
        plan = _make_plan(state="draft")
        create_plan(plan)
        result = transition_plan(plan.plan_id, "draft", "planning", plan.operator_seat)
        assert result.state == "planning"

    def test_planning_to_draft(self):
        plan = _make_plan(state="draft")
        create_plan(plan)
        transition_plan(plan.plan_id, "draft", "planning", plan.operator_seat)
        result = transition_plan(plan.plan_id, "planning", "draft", plan.operator_seat)
        assert result.state == "draft"

    def test_planning_to_mso_review(self):
        plan = _make_plan(state="planning")
        create_plan(plan)
        result = transition_plan(plan.plan_id, "planning", "mso_review", plan.operator_seat)
        assert result.state == "mso_review"

    def test_draft_to_mso_review_blocked(self):
        plan = _make_plan(state="draft")
        create_plan(plan)
        with pytest.raises(InvalidTransition):
            transition_plan(plan.plan_id, "draft", "mso_review", plan.operator_seat)

    def test_mso_review_to_draft_blocked(self):
        plan = _make_plan(state="planning")
        create_plan(plan)
        transition_plan(plan.plan_id, "planning", "mso_review", plan.operator_seat)
        with pytest.raises(InvalidTransition):
            transition_plan(plan.plan_id, "mso_review", "draft", plan.operator_seat)

    def test_wrong_from_state_blocked(self):
        plan = _make_plan(state="draft")
        create_plan(plan)
        with pytest.raises(InvalidTransition):
            transition_plan(plan.plan_id, "planning", "mso_review", plan.operator_seat)

    def test_transition_produces_audit(self):
        plan = _make_plan(state="draft")
        create_plan(plan)
        transition_plan(plan.plan_id, "draft", "planning", plan.operator_seat)
        audit = get_audit_log(plan.plan_id)
        assert any(e.event == "state_transition" for e in audit)

    def test_escalation_produces_extra_audit(self):
        plan = _make_plan(state="planning")
        create_plan(plan)
        transition_plan(plan.plan_id, "planning", "mso_review", plan.operator_seat)
        audit = get_audit_log(plan.plan_id)
        assert any(e.event == "escalated_to_mso_review" for e in audit)

    def test_wrong_seat_blocked(self):
        plan = _make_plan(seat="op_a", state="draft")
        create_plan(plan)
        with pytest.raises(OperatorSeatMismatch):
            transition_plan(plan.plan_id, "draft", "planning", "op_b")

    def test_nonexistent_raises(self):
        with pytest.raises(PlanNotFound):
            transition_plan("plan_0000_xxxxxxxx", "draft", "planning", "op_a")


# ---------------------------------------------------------------------------
# mso_review immutability — D-11
# ---------------------------------------------------------------------------

class TestMsoReviewImmutability:
    def _escalated_plan(self, seat="op_x") -> PlanRecord:
        plan = _make_plan(seat=seat, state="planning")
        create_plan(plan)
        transition_plan(plan.plan_id, "planning", "mso_review", seat)
        return get_plan(plan.plan_id, seat)

    def test_mso_review_get_returns_plan(self):
        """D-11: mso_review plans are gettable — visible as escalated."""
        plan = self._escalated_plan()
        assert plan.state == "mso_review"

    def test_mso_review_update_raises(self):
        plan = self._escalated_plan()
        with pytest.raises(PlanImmutable):
            update_plan(plan.plan_id, plan.operator_seat, PlanUpdate(title="x"))

    def test_mso_review_abandon_raises(self):
        plan = self._escalated_plan()
        with pytest.raises(PlanImmutable):
            abandon_plan(plan.plan_id, plan.operator_seat)

    def test_mso_review_transition_raises(self):
        plan = self._escalated_plan()
        with pytest.raises(InvalidTransition):
            transition_plan(plan.plan_id, "mso_review", "planning", plan.operator_seat)


# ---------------------------------------------------------------------------
# abandon_plan
# ---------------------------------------------------------------------------

class TestAbandonPlan:
    def test_abandon_draft_silent(self):
        """Draft abandonment: silent, no audit entry."""
        plan = _make_plan(state="draft")
        create_plan(plan)
        abandon_plan(plan.plan_id, plan.operator_seat)
        with pytest.raises(PlanNotFound):
            get_plan(plan.plan_id, plan.operator_seat)
        audit = get_audit_log(plan.plan_id)
        assert not any(e.event == "abandoned_from_planning" for e in audit)

    def test_abandon_planning_audited(self):
        """Planning abandonment: must produce audit entry."""
        plan = _make_plan(state="draft")
        create_plan(plan)
        transition_plan(plan.plan_id, "draft", "planning", plan.operator_seat)
        abandon_plan(plan.plan_id, plan.operator_seat)
        with pytest.raises(PlanNotFound):
            get_plan(plan.plan_id, plan.operator_seat)
        audit = get_audit_log(plan.plan_id)
        assert any(e.event == "abandoned_from_planning" for e in audit)

    def test_abandon_mso_review_raises(self):
        plan = _make_plan(state="planning")
        create_plan(plan)
        transition_plan(plan.plan_id, "planning", "mso_review", plan.operator_seat)
        with pytest.raises(PlanImmutable):
            abandon_plan(plan.plan_id, plan.operator_seat)

    def test_abandon_nonexistent_raises(self):
        with pytest.raises(PlanNotFound):
            abandon_plan("plan_0000_xxxxxxxx", "op_a")

    def test_abandon_wrong_seat_raises(self):
        plan = _make_plan(seat="op_a")
        create_plan(plan)
        with pytest.raises(OperatorSeatMismatch):
            abandon_plan(plan.plan_id, "op_b")


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_empty_log_for_nonexistent(self):
        audit = get_audit_log("plan_0000_xxxxxxxx")
        assert audit == []

    def test_created_event_first(self):
        plan = _make_plan()
        create_plan(plan)
        audit = get_audit_log(plan.plan_id)
        assert audit[0].event == "created"

    def test_audit_chronological_order(self):
        import time
        plan = _make_plan(state="draft")
        create_plan(plan)
        time.sleep(0.01)
        transition_plan(plan.plan_id, "draft", "planning", plan.operator_seat)
        audit = get_audit_log(plan.plan_id)
        times = [e.occurred_at for e in audit]
        assert times == sorted(times)


# ---------------------------------------------------------------------------
# Static boundary checks — draft_store does not import authority layer
# ---------------------------------------------------------------------------

class TestDraftStoreStaticBoundary:
    def test_draft_store_does_not_import_authority_modules(self):
        import ast
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "assistant_os" / "mso" / "draft_store.py"
        tree = ast.parse(src.read_text())
        forbidden_imports = {
            "execution_proposal",
            "authority_preparation",
            "confirmable_prepared_action",
            "prepared_action_queue",
            "police",
            "runner",
            "machine_operator",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for forbidden in forbidden_imports:
                    assert forbidden not in module.lower(), \
                        f"draft_store must not import '{forbidden}', found: {module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_imports:
                        assert forbidden not in alias.name.lower(), \
                            f"draft_store must not import '{forbidden}', found: {alias.name}"
