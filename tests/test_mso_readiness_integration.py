"""SPRINT-MSO-06.2: Police Readiness Integration — read-model enrichment tests.

Covers:
1. get_police_readiness_for_item() — compact sub-dict for embedding
2. build_readiness_summary() — status count aggregation
3. Pending read model: each item carries police_readiness sub-dict
4. Unconfirmed action shows awaiting_human_confirmation
5. Policy-denied action shows policy_denied with blocking reason
6. Authority binding draft complete shows authority_chain_draft_complete,
   execution_allowed=False, downstream requirements listed
7. Validation mode response includes readiness_summary field
8. Orchestration mode response includes readiness_summary field
9. Validation mode items carry police_readiness per item
10. No forbidden imports in new helper code
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from assistant_os.mso.police_readiness import (
    build_readiness_summary,
    clear_police_readiness_reports_for_tests,
    get_police_readiness_for_item,
)
from assistant_os.mso.authority_binding import (
    clear_mso_authority_binding_store_for_tests,
    create_mso_authority_binding,
)
from assistant_os.mso.policy_review import (
    clear_mso_policy_review_store_for_tests,
    evaluate_mso_policy_for_prepared_action,
)
from assistant_os.mso.human_confirmation import (
    clear_human_confirmation_store_for_tests,
    record_human_confirmation,
)
from assistant_os.mso.prepared_action_queue import (
    clear_confirmable_action_queue_for_tests,
    enqueue_confirmable_prepared_action,
    list_pending_confirmable_action_dicts,
)
from assistant_os.surface_behavior import get_surface_behavior_response
from assistant_os.mso.task_registry import reset_task_registry
from assistant_os.mso.capability_registry import reset_dynamic_capabilities


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _AuditStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_audit_dict(self) -> dict:
        return dict(self._payload)


@pytest.fixture(autouse=True)
def clear_all_stores():
    clear_police_readiness_reports_for_tests()
    clear_mso_authority_binding_store_for_tests()
    clear_mso_policy_review_store_for_tests()
    clear_human_confirmation_store_for_tests()
    clear_confirmable_action_queue_for_tests()
    reset_dynamic_capabilities()
    reset_task_registry()
    try:
        from assistant_os.context_store import clear_store
        clear_store()
    except Exception:
        pass
    yield
    clear_police_readiness_reports_for_tests()
    clear_mso_authority_binding_store_for_tests()
    clear_mso_policy_review_store_for_tests()
    clear_human_confirmation_store_for_tests()
    clear_confirmable_action_queue_for_tests()
    reset_dynamic_capabilities()
    reset_task_registry()
    try:
        from assistant_os.context_store import clear_store
        clear_store()
    except Exception:
        pass


def _make_queue_entry(*, action="CODE_REVIEW", domain="CODE", capability_name="code_review"):
    from assistant_os.mso.execution_proposal import build_execution_proposal
    from assistant_os.mso.authority_preparation import prepare_authority_from_proposal
    from assistant_os.mso.confirmable_prepared_action import build_confirmable_from_preparation
    proposal = build_execution_proposal(
        user_intent="test intent", domain=domain,
        requested_action=action, capability_name=capability_name,
    )
    preparation = prepare_authority_from_proposal(proposal)
    confirmable = build_confirmable_from_preparation(preparation)
    return enqueue_confirmable_prepared_action(confirmable)


def _confirm(entry, *, confirmed=True):
    return record_human_confirmation(
        entry_id=entry.queue_entry_id,
        action_id=entry.prepared_action_id,
        confirmed=confirmed,
    )


def _route_validation():
    return get_surface_behavior_response(
        surface="mso_direct",
        text="Revisa la cola actual",
        context_id="ctx-readiness-integration-test",
        identity=_AuditStub({"principal": "anon"}),
        guard_result=_AuditStub({"decision": "allow"}),
        mso_context={"agent_seat": "mso", "interaction_mode": "validation", "cognition_tier": "economic"},
    )


def _route_orchestration():
    return get_surface_behavior_response(
        surface="mso_direct",
        text="Ejecuta una revisión del repo",
        context_id="ctx-readiness-integration-test",
        identity=_AuditStub({"principal": "anon"}),
        guard_result=_AuditStub({"decision": "allow"}),
        mso_context={"agent_seat": "mso", "interaction_mode": "orchestration", "cognition_tier": "economic"},
    )


# ---------------------------------------------------------------------------
# 1. get_police_readiness_for_item — compact sub-dict
# ---------------------------------------------------------------------------

class TestGetPoliceReadinessForItem:
    def test_unknown_entry_returns_missing_status(self):
        result = get_police_readiness_for_item("no-entry", "no-action")
        assert result.get("readiness_status") == "missing_prepared_action"

    def test_result_is_dict(self):
        result = get_police_readiness_for_item("no-entry", "no-action")
        assert isinstance(result, dict)

    def test_empty_entry_id_returns_empty_dict(self):
        result = get_police_readiness_for_item("", "some-action")
        assert result == {}

    def test_empty_action_id_returns_empty_dict(self):
        result = get_police_readiness_for_item("some-entry", "")
        assert result == {}

    def test_result_contains_required_fields(self):
        result = get_police_readiness_for_item("no-entry", "no-action")
        required = [
            "readiness_status", "current_chain_stage",
            "missing_requirements", "blocking_reasons",
            "next_safe_step", "execution_allowed", "can_execute_now", "used_execution",
        ]
        for field in required:
            assert field in result, f"Missing field: {field!r}"

    def test_execution_allowed_always_false(self):
        result = get_police_readiness_for_item("no-entry", "no-action")
        assert result["execution_allowed"] is False

    def test_can_execute_now_always_false(self):
        result = get_police_readiness_for_item("no-entry", "no-action")
        assert result["can_execute_now"] is False

    def test_used_execution_always_false(self):
        result = get_police_readiness_for_item("no-entry", "no-action")
        assert result["used_execution"] is False

    def test_missing_requirements_is_list(self):
        result = get_police_readiness_for_item("no-entry", "no-action")
        assert isinstance(result["missing_requirements"], list)

    def test_blocking_reasons_is_list(self):
        result = get_police_readiness_for_item("no-entry", "no-action")
        assert isinstance(result["blocking_reasons"], list)

    def test_existing_entry_unconfirmed_shows_awaiting_confirmation(self):
        entry = _make_queue_entry()
        result = get_police_readiness_for_item(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert result["readiness_status"] == "awaiting_human_confirmation"

    def test_confirmed_entry_shows_awaiting_policy_review(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        result = get_police_readiness_for_item(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert result["readiness_status"] == "awaiting_policy_review"


# ---------------------------------------------------------------------------
# 2. build_readiness_summary — status count aggregation
# ---------------------------------------------------------------------------

class TestBuildReadinessSummary:
    def test_empty_list_returns_zero_counts(self):
        summary = build_readiness_summary([])
        assert summary["total"] == 0
        assert summary["awaiting_human_confirmation"] == 0
        assert summary["awaiting_policy_review"] == 0
        assert summary["awaiting_authority_binding"] == 0
        assert summary["authority_chain_draft_complete"] == 0

    def test_summary_execution_allowed_always_false(self):
        summary = build_readiness_summary([])
        assert summary["execution_allowed"] is False
        assert summary["can_execute_now"] is False
        assert summary["used_execution"] is False

    def test_unconfirmed_entry_counted_awaiting_confirmation(self):
        entry = _make_queue_entry()
        items = list_pending_confirmable_action_dicts()
        summary = build_readiness_summary(items)
        assert summary["awaiting_human_confirmation"] == 1
        assert summary["total"] == 1

    def test_confirmed_entry_counted_awaiting_policy(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        items = list_pending_confirmable_action_dicts()
        summary = build_readiness_summary(items)
        assert summary["awaiting_policy_review"] == 1

    def test_multiple_entries_counted_correctly(self):
        e1 = _make_queue_entry(action="CODE_REVIEW", domain="CODE")
        e2 = _make_queue_entry(action="WORK_QUERY", domain="WORK")
        _confirm(e1, confirmed=True)
        # e2 is unconfirmed
        items = list_pending_confirmable_action_dicts()
        summary = build_readiness_summary(items)
        assert summary["total"] == 2
        assert summary["awaiting_human_confirmation"] == 1
        assert summary["awaiting_policy_review"] == 1

    def test_next_safe_operator_actions_is_list(self):
        entry = _make_queue_entry()
        items = list_pending_confirmable_action_dicts()
        summary = build_readiness_summary(items)
        assert isinstance(summary["next_safe_operator_actions"], list)

    def test_items_missing_ids_counted_as_unknown(self):
        items = [{"no_queue_entry_id": "x"}]
        summary = build_readiness_summary(items)
        assert summary["unknown"] == 1
        assert summary["total"] == 1

    def test_authority_chain_complete_counted(self):
        entry = _make_queue_entry()
        conf = _confirm(entry, confirmed=True)
        review = evaluate_mso_policy_for_prepared_action(entry, conf)
        create_mso_authority_binding(entry, review)
        items = list_pending_confirmable_action_dicts()
        summary = build_readiness_summary(items)
        assert summary["authority_chain_draft_complete"] == 1
        assert summary["execution_allowed"] is False


# ---------------------------------------------------------------------------
# 3. Pending read model: items carry police_readiness sub-dict
# ---------------------------------------------------------------------------

class TestPendingReadModelEnrichment:
    """Tests for the enrichment logic called by _handle_mso_prepared_actions_pending_get."""

    def test_empty_queue_enrichment_returns_no_items(self):
        items = list_pending_confirmable_action_dicts()
        assert len(items) == 0

    def test_queued_item_gets_police_readiness(self):
        entry = _make_queue_entry()
        items = list_pending_confirmable_action_dicts()
        assert len(items) == 1
        item = items[0]
        readiness = get_police_readiness_for_item(
            item.get("queue_entry_id", ""),
            item.get("prepared_action_id", ""),
        )
        assert "readiness_status" in readiness
        assert readiness["readiness_status"] == "awaiting_human_confirmation"

    def test_unconfirmed_item_readiness_status(self):
        entry = _make_queue_entry()
        items = list_pending_confirmable_action_dicts()
        item = items[0]
        readiness = get_police_readiness_for_item(
            item["queue_entry_id"], item["prepared_action_id"]
        )
        assert readiness["readiness_status"] == "awaiting_human_confirmation"
        assert "human_confirmation" in readiness["missing_requirements"]

    def test_confirmed_item_readiness_status(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        items = list_pending_confirmable_action_dicts()
        item = items[0]
        readiness = get_police_readiness_for_item(
            item["queue_entry_id"], item["prepared_action_id"]
        )
        assert readiness["readiness_status"] == "awaiting_policy_review"

    def test_readiness_execution_allowed_false_for_all_stages(self):
        entry = _make_queue_entry()
        items = list_pending_confirmable_action_dicts()
        item = items[0]
        readiness = get_police_readiness_for_item(
            item["queue_entry_id"], item["prepared_action_id"]
        )
        assert readiness["execution_allowed"] is False
        assert readiness["can_execute_now"] is False
        assert readiness["used_execution"] is False

    def test_readiness_summary_from_pending_items(self):
        _make_queue_entry()
        items = list_pending_confirmable_action_dicts()
        summary = build_readiness_summary(items)
        assert summary["total"] == 1
        assert summary["awaiting_human_confirmation"] == 1
        assert summary["execution_allowed"] is False


# ---------------------------------------------------------------------------
# 4. Policy-denied action in read model
# ---------------------------------------------------------------------------

class TestPolicyDeniedReadModel:
    def test_denied_action_shows_policy_denied(self):
        entry = _make_queue_entry(
            action="WORK_TEST_RESET", domain="WORK", capability_name="work_test_reset"
        )
        conf = _confirm(entry, confirmed=True)
        evaluate_mso_policy_for_prepared_action(entry, conf)
        readiness = get_police_readiness_for_item(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert readiness["readiness_status"] == "policy_denied"

    def test_denied_action_has_blocking_reason(self):
        entry = _make_queue_entry(
            action="WORK_TEST_RESET", domain="WORK", capability_name="work_test_reset"
        )
        conf = _confirm(entry, confirmed=True)
        evaluate_mso_policy_for_prepared_action(entry, conf)
        readiness = get_police_readiness_for_item(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert len(readiness["blocking_reasons"]) > 0
        combined = " ".join(readiness["blocking_reasons"])
        assert "denied" in combined.lower()

    def test_denied_action_execution_allowed_false(self):
        entry = _make_queue_entry(
            action="WORK_TEST_RESET", domain="WORK", capability_name="work_test_reset"
        )
        conf = _confirm(entry, confirmed=True)
        evaluate_mso_policy_for_prepared_action(entry, conf)
        readiness = get_police_readiness_for_item(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert readiness["execution_allowed"] is False

    def test_denied_summary_counted(self):
        entry = _make_queue_entry(
            action="WORK_TEST_RESET", domain="WORK", capability_name="work_test_reset"
        )
        conf = _confirm(entry, confirmed=True)
        evaluate_mso_policy_for_prepared_action(entry, conf)
        items = list_pending_confirmable_action_dicts()
        summary = build_readiness_summary(items)
        assert summary["policy_denied"] == 1


# ---------------------------------------------------------------------------
# 5. Authority binding draft complete in read model
# ---------------------------------------------------------------------------

class TestAuthorityBindingCompleteReadModel:
    def _setup_full_chain(self):
        entry = _make_queue_entry()
        conf = _confirm(entry, confirmed=True)
        review = evaluate_mso_policy_for_prepared_action(entry, conf)
        create_mso_authority_binding(entry, review)
        return entry

    def test_draft_complete_shows_correct_status(self):
        entry = self._setup_full_chain()
        readiness = get_police_readiness_for_item(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert readiness["readiness_status"] == "authority_chain_draft_complete"

    def test_draft_complete_execution_allowed_false(self):
        entry = self._setup_full_chain()
        readiness = get_police_readiness_for_item(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert readiness["execution_allowed"] is False

    def test_draft_complete_can_execute_now_false(self):
        entry = self._setup_full_chain()
        readiness = get_police_readiness_for_item(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert readiness["can_execute_now"] is False

    def test_draft_complete_missing_downstream_requirements(self):
        entry = self._setup_full_chain()
        readiness = get_police_readiness_for_item(
            entry.queue_entry_id, entry.prepared_action_id
        )
        missing = set(readiness["missing_requirements"])
        assert "CapabilityToken" in missing
        assert "OperationBinding" in missing
        assert "AuthorizedPlan" in missing
        assert "PoliceGate" in missing
        assert "Runner" in missing

    def test_draft_complete_counted_in_summary(self):
        self._setup_full_chain()
        items = list_pending_confirmable_action_dicts()
        summary = build_readiness_summary(items)
        assert summary["authority_chain_draft_complete"] == 1
        assert summary["execution_allowed"] is False


# ---------------------------------------------------------------------------
# 6. Validation mode includes readiness_summary
# ---------------------------------------------------------------------------

class TestValidationModeReadinessSummary:
    def test_validation_response_has_readiness_summary(self):
        resp = _route_validation()
        assert resp is not None
        assert "readiness_summary" in resp

    def test_validation_readiness_summary_is_dict(self):
        resp = _route_validation()
        assert isinstance(resp.get("readiness_summary"), dict)

    def test_validation_readiness_summary_has_total(self):
        resp = _route_validation()
        summary = resp.get("readiness_summary", {})
        assert "total" in summary

    def test_validation_readiness_summary_execution_allowed_false(self):
        resp = _route_validation()
        summary = resp.get("readiness_summary", {})
        assert summary.get("execution_allowed") is False
        assert summary.get("can_execute_now") is False
        assert summary.get("used_execution") is False

    def test_validation_with_unconfirmed_entry_summary_counts(self):
        _make_queue_entry()
        resp = _route_validation()
        summary = resp.get("readiness_summary", {})
        assert summary.get("total", 0) == 1
        assert summary.get("awaiting_human_confirmation", 0) == 1

    def test_validation_items_carry_police_readiness(self):
        _make_queue_entry()
        resp = _route_validation()
        items = resp.get("pending_review_items", [])
        assert len(items) == 1
        item = items[0]
        assert "police_readiness" in item

    def test_validation_item_police_readiness_shows_awaiting_confirmation(self):
        _make_queue_entry()
        resp = _route_validation()
        items = resp.get("pending_review_items", [])
        pr = items[0].get("police_readiness", {})
        assert pr.get("readiness_status") == "awaiting_human_confirmation"

    def test_validation_item_police_readiness_execution_allowed_false(self):
        _make_queue_entry()
        resp = _route_validation()
        items = resp.get("pending_review_items", [])
        pr = items[0].get("police_readiness", {})
        assert pr.get("execution_allowed") is False
        assert pr.get("can_execute_now") is False

    def test_validation_execution_invariants_unchanged(self):
        resp = _route_validation()
        assert resp.get("execution_allowed") is False
        assert resp.get("can_execute_now") is False
        assert resp.get("intent") == "review_queue_status"
        assert resp.get("response_source") == "mso_mode_validation_read_only"

    def test_validation_readiness_summary_empty_queue(self):
        resp = _route_validation()
        summary = resp.get("readiness_summary", {})
        assert summary.get("total", -1) == 0


# ---------------------------------------------------------------------------
# 7. Orchestration mode includes readiness_summary
# ---------------------------------------------------------------------------

class TestOrchestrationModeReadinessSummary:
    def test_orchestration_response_has_readiness_summary(self):
        resp = _route_orchestration()
        assert resp is not None
        assert "readiness_summary" in resp

    def test_orchestration_readiness_summary_is_dict(self):
        resp = _route_orchestration()
        assert isinstance(resp.get("readiness_summary"), dict)

    def test_orchestration_readiness_summary_has_total(self):
        resp = _route_orchestration()
        summary = resp.get("readiness_summary", {})
        assert "total" in summary

    def test_orchestration_readiness_summary_execution_allowed_false(self):
        resp = _route_orchestration()
        summary = resp.get("readiness_summary", {})
        assert summary.get("execution_allowed") is False
        assert summary.get("can_execute_now") is False
        assert summary.get("used_execution") is False

    def test_orchestration_execution_invariants_unchanged(self):
        resp = _route_orchestration()
        assert resp.get("execution_allowed") is False
        assert resp.get("can_execute_now") is False
        assert resp.get("intent") == "orchestration_mode_governed"
        assert resp.get("response_source") == "mso_mode_orchestration_governed"
        ot = resp.get("operation_trace", {})
        assert ot.get("governed_explanation") is True

    def test_orchestration_with_pending_entry_summary_counts(self):
        _make_queue_entry()
        resp = _route_orchestration()
        summary = resp.get("readiness_summary", {})
        assert summary.get("total", 0) == 1
        assert summary.get("awaiting_human_confirmation", 0) == 1


# ---------------------------------------------------------------------------
# 8. No forbidden imports in police_readiness.py
# ---------------------------------------------------------------------------

class TestForbiddenImportsInReadinessModule:
    _SRC_PATH = (
        Path(__file__).parent.parent
        / "assistant_os" / "mso" / "police_readiness.py"
    )

    def _ast_imports(self):
        tree = ast.parse(self._SRC_PATH.read_text(encoding="utf-8"))
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                found.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    found.append(alias.name)
        return found

    def _code_tokens(self):
        tree = ast.parse(self._SRC_PATH.read_text(encoding="utf-8"))
        tokens: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                tokens.add(node.id)
            elif isinstance(node, ast.Attribute):
                tokens.add(node.attr)
        return tokens

    def test_no_police_import(self):
        for mod in self._ast_imports():
            assert not mod.startswith("assistant_os.police"), (
                f"police_readiness.py must not import from assistant_os.police: {mod!r}"
            )

    def test_no_capabilities_import(self):
        for mod in self._ast_imports():
            assert not mod.startswith("assistant_os.capabilities"), (
                f"police_readiness.py must not import from assistant_os.capabilities: {mod!r}"
            )

    def test_no_sandbox_import(self):
        for mod in self._ast_imports():
            assert not mod.startswith("assistant_os.sandbox"), (
                f"police_readiness.py must not import from assistant_os.sandbox: {mod!r}"
            )

    def test_no_issue_token_in_code(self):
        assert "issue_token" not in self._code_tokens(), (
            "police_readiness.py must not reference issue_token in code"
        )

    def test_no_police_gate_in_code(self):
        assert "PoliceGate" not in self._code_tokens(), (
            "police_readiness.py must not reference PoliceGate in code"
        )

    def test_no_runner_api_in_code(self):
        assert "RunnerAPI" not in self._code_tokens(), (
            "police_readiness.py must not reference RunnerAPI in code"
        )
