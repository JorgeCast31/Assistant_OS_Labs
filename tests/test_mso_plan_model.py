"""
Tests for assistant_os.mso.plan_model.

Validates:
- PlanRecord construction and validation
- PlanUpdate contract
- PlanAuditEntry contract
- State and schema invariants
- Prohibited fields are absent
- Transition table correctness
- plan_id format enforcement
- Serialization round-trip
"""
import pytest

from assistant_os.mso.plan_model import (
    AUDIT_EVENTS,
    InvalidPlanId,
    InvalidPlanState,
    InvalidTransition,
    OperatorSeatMismatch,
    PlanAuditEntry,
    PlanImmutable,
    PlanNotFound,
    PlanRecord,
    PlanUpdate,
    UnknownSchemaVersion,
    is_transition_allowed,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_plan(**overrides) -> PlanRecord:
    defaults = dict(
        plan_id="plan_1748476800000_a3f9c2e1",
        title="Test Plan",
        intent_summary="Describe the intent",
        domain="infra",
        state="draft",
        operator_seat="operator_1",
        schema_version="1",
        created_at="2026-05-28T00:00:00+00:00",
        updated_at="2026-05-28T00:00:00+00:00",
    )
    defaults.update(overrides)
    return PlanRecord(**defaults)


# ---------------------------------------------------------------------------
# PlanRecord construction
# ---------------------------------------------------------------------------

class TestPlanRecordConstruction:
    def test_valid_draft(self):
        plan = _make_plan(state="draft")
        assert plan.state == "draft"
        assert plan.schema_version == "1"

    def test_valid_planning(self):
        plan = _make_plan(state="planning")
        assert plan.state == "planning"

    def test_valid_mso_review(self):
        plan = _make_plan(state="mso_review")
        assert plan.state == "mso_review"

    def test_optional_fields_default_none(self):
        plan = _make_plan()
        assert plan.risk_level is None
        assert plan.target_actions == ()
        assert plan.notes is None

    def test_target_actions_tuple(self):
        plan = _make_plan(target_actions=("deploy", "restart"))
        assert plan.target_actions == ("deploy", "restart")

    def test_risk_level_valid(self):
        for level in ("low", "medium", "high", "critical"):
            plan = _make_plan(risk_level=level)
            assert plan.risk_level == level

    def test_notes_stored(self):
        plan = _make_plan(notes="some notes")
        assert plan.notes == "some notes"

    def test_immutable(self):
        plan = _make_plan()
        with pytest.raises((AttributeError, TypeError)):
            plan.title = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Schema version enforcement
# ---------------------------------------------------------------------------

class TestSchemaVersionEnforcement:
    def test_schema_version_1_accepted(self):
        plan = _make_plan(schema_version="1")
        assert plan.schema_version == "1"

    def test_schema_version_2_rejected(self):
        with pytest.raises(UnknownSchemaVersion):
            _make_plan(schema_version="2")

    def test_schema_version_empty_rejected(self):
        with pytest.raises(UnknownSchemaVersion):
            _make_plan(schema_version="")

    def test_schema_version_unknown_rejected(self):
        with pytest.raises(UnknownSchemaVersion):
            _make_plan(schema_version="v1")


# ---------------------------------------------------------------------------
# State validation
# ---------------------------------------------------------------------------

class TestStateValidation:
    def test_invalid_state_executing_rejected(self):
        with pytest.raises(InvalidPlanState):
            _make_plan(state="executing")  # type: ignore[arg-type]

    def test_invalid_state_running_rejected(self):
        with pytest.raises(InvalidPlanState):
            _make_plan(state="running")  # type: ignore[arg-type]

    def test_invalid_state_completed_rejected(self):
        with pytest.raises(InvalidPlanState):
            _make_plan(state="completed")  # type: ignore[arg-type]

    def test_invalid_state_approved_rejected(self):
        with pytest.raises(InvalidPlanState):
            _make_plan(state="approved")  # type: ignore[arg-type]

    def test_invalid_state_cancelled_rejected(self):
        with pytest.raises(InvalidPlanState):
            _make_plan(state="cancelled")  # type: ignore[arg-type]

    def test_invalid_state_empty_rejected(self):
        with pytest.raises(InvalidPlanState):
            _make_plan(state="")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# plan_id format enforcement
# ---------------------------------------------------------------------------

class TestPlanIdFormat:
    def test_valid_plan_id_accepted(self):
        plan = _make_plan(plan_id="plan_1748476800000_a3f9c2e1")
        assert plan.plan_id.startswith("plan_")

    def test_missing_prefix_rejected(self):
        with pytest.raises(InvalidPlanId):
            _make_plan(plan_id="1748476800000_a3f9c2e1")

    def test_wrong_prefix_rejected(self):
        with pytest.raises(InvalidPlanId):
            _make_plan(plan_id="draft_1748476800000_a3f9c2e1")

    def test_uuid_alone_rejected(self):
        with pytest.raises(InvalidPlanId):
            _make_plan(plan_id="a3f9c2e1-b2d3-4e5f-6789")

    def test_action_id_prefix_rejected(self):
        with pytest.raises(InvalidPlanId):
            _make_plan(plan_id="action_1748476800000_a3f9c2e1")


# ---------------------------------------------------------------------------
# Prohibited fields absent from PlanRecord
# ---------------------------------------------------------------------------

class TestProhibitedFieldsAbsent:
    def test_no_execution_allowed(self):
        plan = _make_plan()
        assert not hasattr(plan, "execution_allowed")

    def test_no_execution_status(self):
        plan = _make_plan()
        assert not hasattr(plan, "execution_status")

    def test_no_execution_state(self):
        plan = _make_plan()
        assert not hasattr(plan, "executionState")

    def test_no_used_execution(self):
        plan = _make_plan()
        assert not hasattr(plan, "used_execution")

    def test_no_policy_decision_ref(self):
        plan = _make_plan()
        assert not hasattr(plan, "policy_decision_ref")

    def test_no_governance_ref(self):
        plan = _make_plan()
        assert not hasattr(plan, "governance_ref")

    def test_no_capability_token_ref(self):
        plan = _make_plan()
        assert not hasattr(plan, "capability_token_ref")

    def test_no_authority_artifact_ref(self):
        plan = _make_plan()
        assert not hasattr(plan, "authority_artifact_ref")

    def test_no_runner_ref(self):
        plan = _make_plan()
        assert not hasattr(plan, "runner_ref")

    def test_no_mission_id(self):
        plan = _make_plan()
        assert not hasattr(plan, "mission_id")

    def test_no_prepared_action_id(self):
        plan = _make_plan()
        assert not hasattr(plan, "prepared_action_id")

    def test_no_can_execute_now(self):
        plan = _make_plan()
        assert not hasattr(plan, "can_execute_now")


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict_round_trip(self):
        original = _make_plan(
            risk_level="high",
            target_actions=("deploy", "migrate"),
            notes="test notes",
        )
        d = original.to_dict()
        restored = PlanRecord.from_dict(d)
        assert restored == original

    def test_to_dict_no_execution_fields(self):
        plan = _make_plan()
        d = plan.to_dict()
        forbidden = {
            "execution_allowed", "execution_status", "executionState",
            "used_execution", "policy_decision_ref", "governance_ref",
            "capability_token_ref", "authority_artifact_ref", "runner_ref",
            "mission_id", "prepared_action_id", "can_execute_now",
        }
        assert not forbidden.intersection(d.keys())

    def test_from_dict_unknown_schema_raises(self):
        d = _make_plan().to_dict()
        d["schema_version"] = "99"
        with pytest.raises(UnknownSchemaVersion):
            PlanRecord.from_dict(d)

    def test_target_actions_serialized_as_list(self):
        plan = _make_plan(target_actions=("a", "b", "c"))
        d = plan.to_dict()
        assert isinstance(d["target_actions"], list)
        assert d["target_actions"] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# PlanUpdate
# ---------------------------------------------------------------------------

class TestPlanUpdate:
    def test_empty_update(self):
        u = PlanUpdate()
        assert u.is_empty()

    def test_partial_update_not_empty(self):
        u = PlanUpdate(title="new title")
        assert not u.is_empty()

    def test_no_state_field(self):
        u = PlanUpdate()
        assert not hasattr(u, "state")

    def test_no_execution_fields(self):
        u = PlanUpdate()
        for field in ("execution_allowed", "execution_status", "policy_decision_ref",
                      "mission_id", "runner_ref"):
            assert not hasattr(u, field)


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------

class TestTransitionTable:
    def test_draft_to_planning_allowed(self):
        assert is_transition_allowed("draft", "planning")

    def test_planning_to_draft_allowed(self):
        assert is_transition_allowed("planning", "draft")

    def test_planning_to_mso_review_allowed(self):
        assert is_transition_allowed("planning", "mso_review")

    def test_draft_to_mso_review_blocked(self):
        assert not is_transition_allowed("draft", "mso_review")

    def test_mso_review_to_draft_blocked(self):
        assert not is_transition_allowed("mso_review", "draft")

    def test_mso_review_to_planning_blocked(self):
        assert not is_transition_allowed("mso_review", "planning")

    def test_mso_review_to_mso_review_blocked(self):
        assert not is_transition_allowed("mso_review", "mso_review")

    def test_same_state_transition_blocked(self):
        assert not is_transition_allowed("draft", "draft")
        assert not is_transition_allowed("planning", "planning")

    def test_invalid_states_blocked(self):
        assert not is_transition_allowed("executing", "planning")
        assert not is_transition_allowed("draft", "running")


# ---------------------------------------------------------------------------
# AUDIT_EVENTS completeness
# ---------------------------------------------------------------------------

class TestAuditEvents:
    def test_required_events_present(self):
        required = {
            "created", "state_transition", "updated",
            "abandoned_from_planning", "escalated_to_mso_review",
        }
        assert required.issubset(AUDIT_EVENTS)


# ---------------------------------------------------------------------------
# Static boundary checks — plan_model imports nothing from execution layer
# ---------------------------------------------------------------------------

class TestStaticBoundaryChecks:
    def test_plan_model_does_not_import_runner(self):
        import ast
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "assistant_os" / "mso" / "plan_model.py"
        tree = ast.parse(src.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [n.name for n in node.names]
                    if isinstance(node, ast.Import)
                    else ([node.module or ""] if node.module else [])
                )
                for name in names:
                    assert "runner" not in name.lower(), \
                        f"plan_model must not import runner-related modules, found: {name}"
                    assert "police" not in name.lower(), \
                        f"plan_model must not import police modules, found: {name}"
                    assert "authority_preparation" not in name, \
                        f"plan_model must not import authority_preparation, found: {name}"
                    assert "prepared_action_queue" not in name, \
                        f"plan_model must not import prepared_action_queue, found: {name}"
                    assert "machine_operator" not in name.lower(), \
                        f"plan_model must not import machine_operator, found: {name}"

    def test_plan_model_does_not_import_execution_proposal(self):
        import ast
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "assistant_os" / "mso" / "plan_model.py"
        tree = ast.parse(src.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = node.module if isinstance(node, ast.ImportFrom) else ""
                assert "execution_proposal" not in (module or ""), \
                    "plan_model must not import execution_proposal"
