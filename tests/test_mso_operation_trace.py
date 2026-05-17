"""Tests for build_operation_trace_v0 and _build_trace_steps_from_report.

Covers:
1. missing_prepared_action → prepared_action step = missing, execution always blocked_by_design
2. awaiting_human_confirmation → prepared_action complete, human_confirmation pending
3. awaiting_policy_review → human_confirmation complete, policy_review pending
4. awaiting_authority_binding → policy_review complete, authority_binding pending
5. authority_chain_draft_complete → police_readiness = draft_complete, prior steps complete
6. blocked_by_governance → police_readiness = blocked
7. Invariants: execution_allowed/can_execute_now/used_execution always False
8. Fail-soft: empty entry_id returns minimal trace, not an exception
9. Forbidden imports — operation_trace functions must not import police/capabilities/sandbox
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from assistant_os.mso.police_readiness import (
    build_operation_trace_v0,
    clear_police_readiness_reports_for_tests,
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
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_all_stores():
    clear_police_readiness_reports_for_tests()
    clear_mso_authority_binding_store_for_tests()
    clear_mso_policy_review_store_for_tests()
    clear_human_confirmation_store_for_tests()
    clear_confirmable_action_queue_for_tests()
    yield
    clear_police_readiness_reports_for_tests()
    clear_mso_authority_binding_store_for_tests()
    clear_mso_policy_review_store_for_tests()
    clear_human_confirmation_store_for_tests()
    clear_confirmable_action_queue_for_tests()


def _make_queue_entry(*, action="CODE_REVIEW", domain="CODE", capability_name="code_review"):
    from assistant_os.mso.execution_proposal import build_execution_proposal
    from assistant_os.mso.authority_preparation import prepare_authority_from_proposal
    from assistant_os.mso.confirmable_prepared_action import build_confirmable_from_preparation

    proposal = build_execution_proposal(
        user_intent="test intent",
        domain=domain,
        requested_action=action,
        capability_name=capability_name,
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


def _policy_review(entry, confirmation):
    return evaluate_mso_policy_for_prepared_action(entry, confirmation)


def _authority_binding(entry, review):
    return create_mso_authority_binding(entry, review)


def _step(trace: dict, name: str) -> dict:
    for s in trace["steps"]:
        if s["step"] == name:
            return s
    raise KeyError(f"Step {name!r} not found in trace")


# ---------------------------------------------------------------------------
# 1. Missing prepared action
# ---------------------------------------------------------------------------

class TestMissingPreparedAction:
    def test_prepared_action_step_is_missing(self):
        trace = build_operation_trace_v0("no-entry", "no-action")
        assert _step(trace, "prepared_action")["status"] == "missing"

    def test_execution_step_always_blocked_by_design(self):
        trace = build_operation_trace_v0("no-entry", "no-action")
        assert _step(trace, "execution")["status"] == "blocked_by_design"

    def test_execution_step_completed_false(self):
        trace = build_operation_trace_v0("no-entry", "no-action")
        assert _step(trace, "execution")["completed"] is False

    def test_trace_has_six_steps(self):
        trace = build_operation_trace_v0("no-entry", "no-action")
        assert len(trace["steps"]) == 6

    def test_trace_version_is_v0(self):
        trace = build_operation_trace_v0("no-entry", "no-action")
        assert trace["trace_version"] == "v0"

    def test_execution_allowed_false(self):
        trace = build_operation_trace_v0("no-entry", "no-action")
        assert trace["execution_allowed"] is False

    def test_can_execute_now_false(self):
        trace = build_operation_trace_v0("no-entry", "no-action")
        assert trace["can_execute_now"] is False

    def test_used_execution_false(self):
        trace = build_operation_trace_v0("no-entry", "no-action")
        assert trace["used_execution"] is False


# ---------------------------------------------------------------------------
# 2. Awaiting human confirmation
# ---------------------------------------------------------------------------

class TestAwaitingHumanConfirmation:
    def test_prepared_action_step_complete(self):
        entry = _make_queue_entry()
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "prepared_action")["status"] == "complete"
        assert _step(trace, "prepared_action")["completed"] is True

    def test_human_confirmation_step_pending(self):
        entry = _make_queue_entry()
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "human_confirmation")["status"] == "pending"

    def test_policy_review_step_missing(self):
        entry = _make_queue_entry()
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "policy_review")["status"] == "missing"

    def test_authority_binding_step_missing(self):
        entry = _make_queue_entry()
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "authority_binding")["status"] == "missing"

    def test_execution_step_blocked_by_design(self):
        entry = _make_queue_entry()
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "execution")["status"] == "blocked_by_design"

    def test_invariants(self):
        entry = _make_queue_entry()
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert trace["execution_allowed"] is False
        assert trace["can_execute_now"] is False
        assert trace["used_execution"] is False


# ---------------------------------------------------------------------------
# 3. Awaiting policy review
# ---------------------------------------------------------------------------

class TestAwaitingPolicyReview:
    def test_human_confirmation_step_complete(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "human_confirmation")["status"] == "complete"
        assert _step(trace, "human_confirmation")["completed"] is True

    def test_policy_review_step_pending(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "policy_review")["status"] == "pending"

    def test_authority_binding_step_missing(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "authority_binding")["status"] == "missing"

    def test_police_readiness_step_not_ready(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "police_readiness")["status"] == "not_ready"


# ---------------------------------------------------------------------------
# 4. Awaiting authority binding
# ---------------------------------------------------------------------------

class TestAwaitingAuthorityBinding:
    def test_policy_review_step_complete(self):
        entry = _make_queue_entry()
        conf = _confirm(entry, confirmed=True)
        _policy_review(entry, conf)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "policy_review")["status"] == "complete"
        assert _step(trace, "policy_review")["completed"] is True

    def test_authority_binding_step_pending(self):
        entry = _make_queue_entry()
        conf = _confirm(entry, confirmed=True)
        _policy_review(entry, conf)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "authority_binding")["status"] == "pending"

    def test_police_readiness_step_not_ready(self):
        entry = _make_queue_entry()
        conf = _confirm(entry, confirmed=True)
        _policy_review(entry, conf)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "police_readiness")["status"] == "not_ready"


# ---------------------------------------------------------------------------
# 5. Authority chain draft complete
# ---------------------------------------------------------------------------

class TestAuthorityChainDraftComplete:
    def test_authority_binding_step_complete(self):
        entry = _make_queue_entry()
        conf = _confirm(entry, confirmed=True)
        review = _policy_review(entry, conf)
        _authority_binding(entry, review)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "authority_binding")["status"] == "complete"
        assert _step(trace, "authority_binding")["completed"] is True

    def test_police_readiness_step_draft_complete(self):
        entry = _make_queue_entry()
        conf = _confirm(entry, confirmed=True)
        review = _policy_review(entry, conf)
        _authority_binding(entry, review)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "police_readiness")["status"] == "draft_complete"

    def test_police_readiness_step_completed_false(self):
        # draft_complete ≠ fully complete — downstream still missing
        entry = _make_queue_entry()
        conf = _confirm(entry, confirmed=True)
        review = _policy_review(entry, conf)
        _authority_binding(entry, review)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "police_readiness")["completed"] is False

    def test_execution_always_blocked_by_design(self):
        entry = _make_queue_entry()
        conf = _confirm(entry, confirmed=True)
        review = _policy_review(entry, conf)
        _authority_binding(entry, review)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert _step(trace, "execution")["status"] == "blocked_by_design"

    def test_all_prior_steps_complete(self):
        entry = _make_queue_entry()
        conf = _confirm(entry, confirmed=True)
        review = _policy_review(entry, conf)
        _authority_binding(entry, review)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        for name in ("prepared_action", "human_confirmation", "policy_review", "authority_binding"):
            assert _step(trace, name)["completed"] is True, f"{name} should be complete"

    def test_missing_requirements_present_in_trace(self):
        entry = _make_queue_entry()
        conf = _confirm(entry, confirmed=True)
        review = _policy_review(entry, conf)
        _authority_binding(entry, review)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert isinstance(trace["missing_requirements"], list)

    def test_invariants(self):
        entry = _make_queue_entry()
        conf = _confirm(entry, confirmed=True)
        review = _policy_review(entry, conf)
        _authority_binding(entry, review)
        trace = build_operation_trace_v0(entry.queue_entry_id, entry.prepared_action_id)
        assert trace["execution_allowed"] is False
        assert trace["can_execute_now"] is False
        assert trace["used_execution"] is False


# ---------------------------------------------------------------------------
# 6. Blocked by governance
# ---------------------------------------------------------------------------

class TestBlockedByGovernance:
    def setup_method(self):
        from assistant_os.mso.system_state import clear_operational_mode_override
        clear_operational_mode_override()

    def teardown_method(self):
        from assistant_os.mso.system_state import clear_operational_mode_override
        clear_operational_mode_override()

    def test_police_readiness_step_blocked(self):
        from assistant_os.mso.system_state import set_operational_mode
        set_operational_mode("FROZEN", reason="test governance freeze")
        trace = build_operation_trace_v0("gov-entry", "gov-action")
        assert _step(trace, "police_readiness")["status"] == "blocked"

    def test_execution_still_blocked_by_design(self):
        from assistant_os.mso.system_state import set_operational_mode
        set_operational_mode("FROZEN", reason="test governance freeze")
        trace = build_operation_trace_v0("gov-entry", "gov-action")
        assert _step(trace, "execution")["status"] == "blocked_by_design"

    def test_invariants_under_governance_freeze(self):
        from assistant_os.mso.system_state import set_operational_mode
        set_operational_mode("FROZEN", reason="test governance freeze")
        trace = build_operation_trace_v0("gov-entry", "gov-action")
        assert trace["execution_allowed"] is False
        assert trace["can_execute_now"] is False
        assert trace["used_execution"] is False


# ---------------------------------------------------------------------------
# 7. Fail-soft: empty IDs
# ---------------------------------------------------------------------------

class TestFailSoft:
    def test_empty_entry_id_returns_dict_not_exception(self):
        result = build_operation_trace_v0("", "some-action")
        assert isinstance(result, dict)

    def test_empty_action_id_returns_dict_not_exception(self):
        result = build_operation_trace_v0("some-entry", "")
        assert isinstance(result, dict)

    def test_both_empty_returns_empty_steps(self):
        result = build_operation_trace_v0("", "")
        assert result["steps"] == []

    def test_empty_ids_invariants(self):
        result = build_operation_trace_v0("", "")
        assert result["execution_allowed"] is False
        assert result["can_execute_now"] is False
        assert result["used_execution"] is False

    def test_empty_ids_trace_version(self):
        result = build_operation_trace_v0("", "")
        assert result["trace_version"] == "v0"


# ---------------------------------------------------------------------------
# 8. Forbidden imports — police_readiness.py must not import police/capabilities/sandbox
# ---------------------------------------------------------------------------

_SOURCE_PATH = pathlib.Path(__file__).parent.parent / "assistant_os" / "mso" / "police_readiness.py"


def _code_tokens() -> set[str]:
    """Extract all Name/Attribute identifiers from actual code AST nodes."""
    source = _SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_SOURCE_PATH))
    tokens: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            tokens.add(node.id)
        elif isinstance(node, ast.Attribute):
            tokens.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                tokens.add(node.module)
            for alias in node.names:
                tokens.add(alias.name)
                if alias.asname:
                    tokens.add(alias.asname)
    return tokens


class TestForbiddenImportsInOperationTraceModule:
    def test_no_police_import(self):
        source = _SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "police" not in node.module.split("."), (
                    f"police_readiness.py must not import from police.*: {node.module}"
                )

    def test_no_capabilities_import(self):
        source = _SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "capabilities" not in node.module.split("."), (
                    f"police_readiness.py must not import from capabilities.*: {node.module}"
                )

    def test_no_sandbox_import(self):
        source = _SOURCE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "sandbox" not in node.module.split("."), (
                    f"police_readiness.py must not import from sandbox.*: {node.module}"
                )

    def test_issue_token_not_in_code_tokens(self):
        assert "issue_token" not in _code_tokens()

    def test_PoliceGate_not_in_code_tokens(self):
        assert "PoliceGate" not in _code_tokens()

    def test_RunnerAPI_not_in_code_tokens(self):
        assert "RunnerAPI" not in _code_tokens()
