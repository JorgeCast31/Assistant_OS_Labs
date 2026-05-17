"""Tests for MSOPoliceReadinessReport and evaluate_police_readiness_for_prepared_action.

Covers:
1. Missing prepared action → readiness_status = missing_prepared_action
2. Prepared action exists, no human confirmation → awaiting_human_confirmation
3. Confirmation exists (confirmed=True) but no policy review → awaiting_policy_review
4. Policy denied → policy_denied
5. Policy approved but no authority binding draft → awaiting_authority_binding
6. Authority binding draft present → authority_chain_draft_complete
7. Governance FROZEN → blocked_by_governance
8. Idempotency — repeated evaluations do not mutate authority chain
9. Forbidden imports — police_readiness.py must not import police/capabilities/sandbox
10. Forbidden calls — issue_token, PoliceGate.check, RunnerAPI.execute not invoked
"""
from __future__ import annotations

import json

import pytest

from assistant_os.mso.police_readiness import (
    MSOPoliceReadinessReport,
    clear_police_readiness_reports_for_tests,
    evaluate_police_readiness_for_prepared_action,
    list_recent_police_readiness_reports,
)
from assistant_os.mso.authority_binding import (
    clear_mso_authority_binding_store_for_tests,
    create_mso_authority_binding,
    get_mso_authority_binding,
)
from assistant_os.mso.policy_review import (
    clear_mso_policy_review_store_for_tests,
    evaluate_mso_policy_for_prepared_action,
    get_mso_policy_review,
)
from assistant_os.mso.human_confirmation import (
    clear_human_confirmation_store_for_tests,
    get_human_confirmation,
    record_human_confirmation,
)
from assistant_os.mso.prepared_action_queue import (
    clear_confirmable_action_queue_for_tests,
    enqueue_confirmable_prepared_action,
    get_confirmable_action_queue_entry,
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
    """Build and enqueue a prepared action, return the queue entry."""
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


# ---------------------------------------------------------------------------
# 1. Missing prepared action
# ---------------------------------------------------------------------------

class TestMissingPreparedAction:
    def test_readiness_status_is_missing_prepared_action(self):
        report = evaluate_police_readiness_for_prepared_action(
            "nonexistent-entry", "nonexistent-action"
        )
        assert report.readiness_status == "missing_prepared_action"

    def test_prepared_action_present_is_false(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        assert report.prepared_action_present is False

    def test_execution_allowed_false(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        assert report.execution_allowed is False

    def test_can_execute_now_false(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        assert report.can_execute_now is False

    def test_used_execution_false(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        assert report.used_execution is False

    def test_police_check_performed_false(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        assert report.police_check_performed is False

    def test_runner_check_performed_false(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        assert report.runner_check_performed is False

    def test_missing_requirements_includes_prepared_action(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        assert "prepared_action" in report.missing_requirements

    def test_blocking_reasons_not_empty(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        assert len(report.blocking_reasons) > 0

    def test_next_safe_step_not_empty(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        assert report.next_safe_step != ""

    def test_downstream_flags_all_false(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        assert report.capability_token_present is False
        assert report.operation_binding_present is False
        assert report.authorized_plan_present is False


# ---------------------------------------------------------------------------
# 2. Prepared action exists, no human confirmation
# ---------------------------------------------------------------------------

class TestNoHumanConfirmation:
    def test_readiness_status_awaiting_human_confirmation(self):
        entry = _make_queue_entry()
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.readiness_status == "awaiting_human_confirmation"

    def test_prepared_action_present_true(self):
        entry = _make_queue_entry()
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.prepared_action_present is True

    def test_human_confirmation_status_is_pending(self):
        entry = _make_queue_entry()
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.human_confirmation_status == "pending"

    def test_human_confirmation_satisfied_false(self):
        entry = _make_queue_entry()
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.human_confirmation_satisfied is False

    def test_missing_requirements_includes_human_confirmation(self):
        entry = _make_queue_entry()
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert "human_confirmation" in report.missing_requirements

    def test_execution_allowed_false(self):
        entry = _make_queue_entry()
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.execution_allowed is False

    def test_can_execute_now_false(self):
        entry = _make_queue_entry()
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.can_execute_now is False

    def test_rejected_confirmation_also_awaiting(self):
        """A rejected confirmation should keep status as awaiting_human_confirmation."""
        entry = _make_queue_entry()
        _confirm(entry, confirmed=False)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.readiness_status == "awaiting_human_confirmation"
        assert report.human_confirmation_status == "human_rejected"
        assert report.human_confirmation_satisfied is False


# ---------------------------------------------------------------------------
# 3. Confirmed but no policy review
# ---------------------------------------------------------------------------

class TestNoPoliceReview:
    def test_readiness_status_awaiting_policy_review(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.readiness_status == "awaiting_policy_review"

    def test_human_confirmation_satisfied_true(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.human_confirmation_satisfied is True

    def test_human_confirmation_status_human_confirmed(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.human_confirmation_status == "human_confirmed"

    def test_policy_review_present_false(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.policy_review_present is False

    def test_missing_requirements_includes_policy_review(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert "policy_review" in report.missing_requirements

    def test_execution_allowed_false(self):
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.execution_allowed is False


# ---------------------------------------------------------------------------
# 4. Policy denied
# ---------------------------------------------------------------------------

class TestPolicyDenied:
    def test_readiness_status_policy_denied(self):
        # Use WORK_TEST_RESET which is deny in the capability registry
        entry = _make_queue_entry(
            action="WORK_TEST_RESET", domain="WORK", capability_name="work_test_reset"
        )
        confirmation = _confirm(entry, confirmed=True)
        _policy_review(entry, confirmation)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.readiness_status == "policy_denied"

    def test_policy_outcome_is_denied(self):
        entry = _make_queue_entry(
            action="WORK_TEST_RESET", domain="WORK", capability_name="work_test_reset"
        )
        confirmation = _confirm(entry, confirmed=True)
        _policy_review(entry, confirmation)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.policy_outcome == "denied"

    def test_blocking_reasons_include_denied(self):
        entry = _make_queue_entry(
            action="WORK_TEST_RESET", domain="WORK", capability_name="work_test_reset"
        )
        confirmation = _confirm(entry, confirmed=True)
        _policy_review(entry, confirmation)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert any("denied" in r for r in report.blocking_reasons)

    def test_execution_allowed_false(self):
        entry = _make_queue_entry(
            action="WORK_TEST_RESET", domain="WORK", capability_name="work_test_reset"
        )
        confirmation = _confirm(entry, confirmed=True)
        _policy_review(entry, confirmation)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.execution_allowed is False

    def test_can_execute_now_false(self):
        entry = _make_queue_entry(
            action="WORK_TEST_RESET", domain="WORK", capability_name="work_test_reset"
        )
        confirmation = _confirm(entry, confirmed=True)
        _policy_review(entry, confirmation)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.can_execute_now is False


# ---------------------------------------------------------------------------
# 5. Policy approved but no authority binding draft
# ---------------------------------------------------------------------------

class TestNoAuthorityBinding:
    def test_readiness_status_awaiting_authority_binding(self):
        entry = _make_queue_entry()  # CODE_REVIEW → allow → approved
        confirmation = _confirm(entry, confirmed=True)
        _policy_review(entry, confirmation)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.readiness_status == "awaiting_authority_binding"

    def test_policy_review_present_true(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        _policy_review(entry, confirmation)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.policy_review_present is True

    def test_authority_binding_draft_present_false(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        _policy_review(entry, confirmation)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.authority_binding_draft_present is False

    def test_missing_requirements_includes_authority_binding_draft(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        _policy_review(entry, confirmation)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert "authority_binding_draft" in report.missing_requirements

    def test_execution_allowed_false(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        _policy_review(entry, confirmation)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.execution_allowed is False


# ---------------------------------------------------------------------------
# 6. Authority binding draft present
# ---------------------------------------------------------------------------

class TestAuthorityBindingDraftPresent:
    def test_readiness_status_authority_chain_draft_complete(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.readiness_status == "authority_chain_draft_complete"

    def test_authority_binding_draft_present_true(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.authority_binding_draft_present is True

    def test_missing_requirements_includes_downstream_artifacts(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        missing = set(report.missing_requirements)
        assert "CapabilityToken" in missing
        assert "OperationBinding" in missing
        assert "AuthorizedPlan" in missing
        assert "PoliceGate" in missing
        assert "Runner" in missing

    def test_execution_allowed_false(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.execution_allowed is False

    def test_can_execute_now_false(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.can_execute_now is False

    def test_used_execution_false(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.used_execution is False

    def test_capability_token_present_false(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.capability_token_present is False

    def test_operation_binding_present_false(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.operation_binding_present is False

    def test_authorized_plan_present_false(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.authorized_plan_present is False

    def test_police_check_performed_false(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.police_check_performed is False

    def test_runner_check_performed_false(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.runner_check_performed is False

    def test_blocking_reasons_mention_downstream(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        combined = " ".join(report.blocking_reasons)
        assert "CapabilityToken" in combined or "downstream" in combined.lower()


# ---------------------------------------------------------------------------
# 7. Governance FROZEN
# ---------------------------------------------------------------------------

class TestGovernanceFrozen:
    def setup_method(self):
        from assistant_os.mso.system_state import clear_operational_mode_override
        clear_operational_mode_override()

    def teardown_method(self):
        from assistant_os.mso.system_state import clear_operational_mode_override
        clear_operational_mode_override()

    def test_frozen_blocks_readiness(self):
        from assistant_os.mso.system_state import set_operational_mode
        set_operational_mode("FROZEN", reason="test freeze")
        report = evaluate_police_readiness_for_prepared_action("any-entry", "any-action")
        assert report.readiness_status == "blocked_by_governance"

    def test_frozen_sets_blocking_reason(self):
        from assistant_os.mso.system_state import set_operational_mode
        set_operational_mode("FROZEN", reason="test freeze")
        report = evaluate_police_readiness_for_prepared_action("any-entry", "any-action")
        assert len(report.blocking_reasons) > 0
        combined = " ".join(report.blocking_reasons)
        assert "FROZEN" in combined or "frozen" in combined.lower()

    def test_frozen_execution_allowed_false(self):
        from assistant_os.mso.system_state import set_operational_mode
        set_operational_mode("FROZEN", reason="test freeze")
        report = evaluate_police_readiness_for_prepared_action("any-entry", "any-action")
        assert report.execution_allowed is False

    def test_frozen_can_execute_now_false(self):
        from assistant_os.mso.system_state import set_operational_mode
        set_operational_mode("FROZEN", reason="test freeze")
        report = evaluate_police_readiness_for_prepared_action("any-entry", "any-action")
        assert report.can_execute_now is False

    def test_non_frozen_mode_does_not_block(self):
        """DEGRADED or RESTRICTED mode should not trigger blocked_by_governance."""
        from assistant_os.mso.system_state import set_operational_mode
        entry = _make_queue_entry()
        set_operational_mode("DEGRADED", reason="degraded mode test")
        report = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report.readiness_status != "blocked_by_governance"

    def test_cleared_mode_does_not_block(self):
        """After clearing a FROZEN mode, the diagnostic should proceed normally."""
        from assistant_os.mso.system_state import set_operational_mode, clear_operational_mode_override
        set_operational_mode("FROZEN", reason="test")
        clear_operational_mode_override()
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        assert report.readiness_status == "missing_prepared_action"


# ---------------------------------------------------------------------------
# 8. Idempotency — repeated evaluations do not mutate authority chain
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_repeated_calls_same_conclusion(self):
        """Calling evaluate twice returns the same readiness_status."""
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)

        report1 = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        report2 = evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert report1.readiness_status == report2.readiness_status
        assert report1.readiness_status == "awaiting_authority_binding"

    def test_repeated_calls_do_not_create_authority_binding(self):
        """Calling evaluate does not create an authority binding."""
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        _policy_review(entry, confirmation)

        evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        # Authority binding should still not exist
        assert get_mso_authority_binding(entry.queue_entry_id) is None

    def test_repeated_calls_do_not_create_policy_review(self):
        """Calling evaluate does not create a policy review."""
        entry = _make_queue_entry()
        _confirm(entry, confirmed=True)

        evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert get_mso_policy_review(entry.queue_entry_id) is None

    def test_repeated_calls_do_not_create_human_confirmation(self):
        """Calling evaluate does not create a human confirmation."""
        entry = _make_queue_entry()

        evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        evaluate_police_readiness_for_prepared_action(
            entry.queue_entry_id, entry.prepared_action_id
        )
        assert get_human_confirmation(entry.queue_entry_id) is None

    def test_each_call_stores_report(self):
        """Each evaluation call stores a separate report snapshot."""
        evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        reports = list_recent_police_readiness_reports(limit=10)
        assert len(reports) == 2

    def test_stored_reports_have_unique_ids(self):
        evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        reports = list_recent_police_readiness_reports(limit=10)
        ids = {r.report_id for r in reports}
        assert len(ids) == 2


# ---------------------------------------------------------------------------
# 9. Forbidden imports in police_readiness.py
# ---------------------------------------------------------------------------

class TestForbiddenImports:
    def test_no_police_import(self):
        import ast
        import pathlib
        source_path = pathlib.Path(
            __file__
        ).parent.parent / "assistant_os" / "mso" / "police_readiness.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("assistant_os.police"), (
                        f"police_readiness.py must not import from assistant_os.police, "
                        f"found: {node.module}"
                    )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("assistant_os.police"), (
                            f"police_readiness.py must not import assistant_os.police, "
                            f"found: {alias.name}"
                        )

    def test_no_capabilities_import(self):
        import ast
        import pathlib
        source_path = pathlib.Path(
            __file__
        ).parent.parent / "assistant_os" / "mso" / "police_readiness.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("assistant_os.capabilities"), (
                    f"police_readiness.py must not import from assistant_os.capabilities, "
                    f"found: {node.module}"
                )

    def test_no_sandbox_import(self):
        import ast
        import pathlib
        source_path = pathlib.Path(
            __file__
        ).parent.parent / "assistant_os" / "mso" / "police_readiness.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("assistant_os.sandbox"), (
                    f"police_readiness.py must not import from assistant_os.sandbox, "
                    f"found: {node.module}"
                )

    def _code_tokens(self) -> set[str]:
        """Return all Name and Attribute identifiers in non-comment, non-docstring code nodes."""
        import ast
        import pathlib
        source_path = pathlib.Path(
            __file__
        ).parent.parent / "assistant_os" / "mso" / "police_readiness.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        tokens: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                tokens.add(node.id)
            elif isinstance(node, ast.Attribute):
                tokens.add(node.attr)
        return tokens

    def test_no_token_issuer_call_in_source(self):
        tokens = self._code_tokens()
        assert "issue_token" not in tokens, (
            "police_readiness.py must not call token_issuer.issue_token() in code"
        )

    def test_no_police_gate_call_in_source(self):
        tokens = self._code_tokens()
        assert "PoliceGate" not in tokens, (
            "police_readiness.py must not reference PoliceGate in code"
        )

    def test_no_runner_execute_call_in_source(self):
        tokens = self._code_tokens()
        assert "RunnerAPI" not in tokens, (
            "police_readiness.py must not reference RunnerAPI in code"
        )


# ---------------------------------------------------------------------------
# 10. Forbidden calls — source inspection (no pytest-mock required)
# ---------------------------------------------------------------------------

class TestForbiddenCallsNotInvoked:
    """Verify no productive authority calls are made during readiness evaluation.

    Since police_readiness.py must not import assistant_os.police.*,
    assistant_os.capabilities.*, or assistant_os.sandbox.*, patching those
    import paths would force importing forbidden modules into the test process.
    Instead we verify by AST inspection that forbidden call targets are absent
    from actual code nodes (Name/Attribute), excluding comments and docstrings.
    """

    @staticmethod
    def _code_tokens() -> set[str]:
        """Collect all Name/Attribute identifiers from police_readiness.py code nodes."""
        import ast
        from pathlib import Path
        src = (
            Path(__file__).parent.parent
            / "assistant_os" / "mso" / "police_readiness.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(src)
        tokens: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                tokens.add(node.id)
            elif isinstance(node, ast.Attribute):
                tokens.add(node.attr)
        return tokens

    def test_issue_token_not_called(self):
        """issue_token must not appear as a code identifier in police_readiness.py."""
        tokens = self._code_tokens()
        assert "issue_token" not in tokens, (
            "police_readiness.py must not reference issue_token() in code — "
            "token issuance is forbidden in this diagnostic module"
        )

    def test_runner_execute_not_called(self):
        """RunnerAPI must not appear as a code identifier in police_readiness.py."""
        tokens = self._code_tokens()
        assert "RunnerAPI" not in tokens, (
            "police_readiness.py must not reference RunnerAPI in code — "
            "runner invocation is forbidden in this diagnostic module"
        )


# ---------------------------------------------------------------------------
# Report structure validation
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_report_has_required_fields(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        d = report.to_dict()
        required_fields = [
            "report_id", "created_at", "entry_id", "action_id",
            "domain", "requested_action", "current_chain_stage",
            "prepared_action_present", "human_confirmation_status",
            "human_confirmation_satisfied", "policy_review_present",
            "policy_outcome", "authority_binding_draft_present",
            "capability_token_present", "operation_binding_present",
            "authorized_plan_present", "police_check_performed",
            "runner_check_performed", "readiness_status",
            "missing_requirements", "blocking_reasons", "next_safe_step",
            "execution_allowed", "can_execute_now", "used_execution",
        ]
        for field in required_fields:
            assert field in d, f"Missing field in to_dict(): {field!r}"

    def test_invariant_fields_always_false_in_dict(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        d = report.to_dict()
        assert d["execution_allowed"] is False
        assert d["can_execute_now"] is False
        assert d["used_execution"] is False
        assert d["police_check_performed"] is False
        assert d["runner_check_performed"] is False
        assert d["capability_token_present"] is False
        assert d["operation_binding_present"] is False
        assert d["authorized_plan_present"] is False

    def test_report_id_starts_with_prr(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        assert report.report_id.startswith("prr-")

    def test_missing_requirements_is_list_in_dict(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        d = report.to_dict()
        assert isinstance(d["missing_requirements"], list)

    def test_blocking_reasons_is_list_in_dict(self):
        report = evaluate_police_readiness_for_prepared_action("no-entry", "no-action")
        d = report.to_dict()
        assert isinstance(d["blocking_reasons"], list)


# ---------------------------------------------------------------------------
# MSOPoliceReadinessReport invariant enforcement
# ---------------------------------------------------------------------------

class TestReportInvariants:
    def test_execution_allowed_invariant_raises(self):
        with pytest.raises(ValueError, match="execution_allowed"):
            MSOPoliceReadinessReport(
                entry_id="e1", action_id="a1", readiness_status="test",
                execution_allowed=True,
            )

    def test_can_execute_now_invariant_raises(self):
        with pytest.raises(ValueError, match="can_execute_now"):
            MSOPoliceReadinessReport(
                entry_id="e1", action_id="a1", readiness_status="test",
                can_execute_now=True,
            )

    def test_used_execution_invariant_raises(self):
        with pytest.raises(ValueError, match="used_execution"):
            MSOPoliceReadinessReport(
                entry_id="e1", action_id="a1", readiness_status="test",
                used_execution=True,
            )

    def test_police_check_performed_invariant_raises(self):
        with pytest.raises(ValueError, match="police_check_performed"):
            MSOPoliceReadinessReport(
                entry_id="e1", action_id="a1", readiness_status="test",
                police_check_performed=True,
            )

    def test_runner_check_performed_invariant_raises(self):
        with pytest.raises(ValueError, match="runner_check_performed"):
            MSOPoliceReadinessReport(
                entry_id="e1", action_id="a1", readiness_status="test",
                runner_check_performed=True,
            )

    def test_capability_token_present_invariant_raises(self):
        with pytest.raises(ValueError, match="capability_token_present"):
            MSOPoliceReadinessReport(
                entry_id="e1", action_id="a1", readiness_status="test",
                capability_token_present=True,
            )

    def test_operation_binding_present_invariant_raises(self):
        with pytest.raises(ValueError, match="operation_binding_present"):
            MSOPoliceReadinessReport(
                entry_id="e1", action_id="a1", readiness_status="test",
                operation_binding_present=True,
            )

    def test_authorized_plan_present_invariant_raises(self):
        with pytest.raises(ValueError, match="authorized_plan_present"):
            MSOPoliceReadinessReport(
                entry_id="e1", action_id="a1", readiness_status="test",
                authorized_plan_present=True,
            )


# ---------------------------------------------------------------------------
# Endpoint process function
# ---------------------------------------------------------------------------

from assistant_os.webhook_server import _process_mso_police_readiness_request  # noqa: E402


class TestPoliceReadinessEndpoint:
    def test_missing_entry_id_returns_400(self):
        body = json.dumps({"action_id": "a1"}).encode()
        status, resp = _process_mso_police_readiness_request(body)
        assert status == 400
        assert resp["ok"] is False

    def test_missing_action_id_returns_400(self):
        body = json.dumps({"entry_id": "e1"}).encode()
        status, resp = _process_mso_police_readiness_request(body)
        assert status == 400
        assert resp["ok"] is False

    def test_invalid_json_returns_400(self):
        status, resp = _process_mso_police_readiness_request(b"not-json")
        assert status == 400
        assert resp["ok"] is False

    def test_unknown_entry_returns_200_with_missing_report(self):
        body = json.dumps({"entry_id": "no-entry", "action_id": "no-action"}).encode()
        status, resp = _process_mso_police_readiness_request(body)
        assert status == 200
        assert resp["ok"] is True
        assert resp["source"] == "mso_police_readiness"
        assert resp["report"]["readiness_status"] == "missing_prepared_action"

    def test_response_execution_allowed_always_false(self):
        body = json.dumps({"entry_id": "no-entry", "action_id": "no-action"}).encode()
        status, resp = _process_mso_police_readiness_request(body)
        assert resp["execution_allowed"] is False

    def test_response_can_execute_now_always_false(self):
        body = json.dumps({"entry_id": "no-entry", "action_id": "no-action"}).encode()
        status, resp = _process_mso_police_readiness_request(body)
        assert resp["can_execute_now"] is False

    def test_response_used_execution_always_false(self):
        body = json.dumps({"entry_id": "no-entry", "action_id": "no-action"}).encode()
        status, resp = _process_mso_police_readiness_request(body)
        assert resp["used_execution"] is False

    def test_full_chain_returns_authority_chain_draft_complete(self):
        entry = _make_queue_entry()
        confirmation = _confirm(entry, confirmed=True)
        review = _policy_review(entry, confirmation)
        _authority_binding(entry, review)

        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, resp = _process_mso_police_readiness_request(body)
        assert status == 200
        assert resp["ok"] is True
        assert resp["report"]["readiness_status"] == "authority_chain_draft_complete"
        assert resp["execution_allowed"] is False
        assert resp["can_execute_now"] is False
        assert resp["used_execution"] is False

    def test_empty_body_returns_400(self):
        status, resp = _process_mso_police_readiness_request(b"")
        assert status == 400
        assert resp["ok"] is False

    def test_report_dict_includes_all_invariant_false_fields(self):
        body = json.dumps({"entry_id": "no-entry", "action_id": "no-action"}).encode()
        _, resp = _process_mso_police_readiness_request(body)
        report_d = resp["report"]
        assert report_d["execution_allowed"] is False
        assert report_d["can_execute_now"] is False
        assert report_d["used_execution"] is False
        assert report_d["police_check_performed"] is False
        assert report_d["runner_check_performed"] is False
        assert report_d["capability_token_present"] is False
        assert report_d["operation_binding_present"] is False
        assert report_d["authorized_plan_present"] is False
