"""Tests for MSOPolicyDecisionDraft and evaluate_mso_policy_for_prepared_action.

Covers:
- Invariant enforcement (execution_allowed, can_execute_now, used_execution, policy_review_id)
- Deterministic policy outcomes (allow → approved, confirm_only → approved_confirm_only, deny → denied)
- Fail-closed: rejected confirmation raises, unconfirmed missing raises, action_id mismatch raises
- Store: store persists, retrieve returns stored record, clear works
- Merge: overlay fields on dict, no-op when no review exists
- Endpoint logic: missing entry → 404, not confirmed → 422, success → 200 with correct fields
- No execution path opens under any condition
"""
from __future__ import annotations

import pytest

from assistant_os.mso.policy_review import (
    MSOPolicyDecisionDraft,
    clear_mso_policy_review_store_for_tests,
    evaluate_mso_policy_for_prepared_action,
    get_mso_policy_review,
    merge_policy_review_into_dict,
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
# Helpers
# ---------------------------------------------------------------------------

def _make_queue_entry(
    *,
    action: str = "CODE_REVIEW",
    domain: str = "CODE",
    capability_name: str = "code_review",
):
    """Build a full chain: proposal → preparation → confirmable → queue entry."""
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
    # enqueue returns the ConfirmablePreparedActionQueueEntry directly
    return enqueue_confirmable_prepared_action(confirmable)


def _make_confirmation(entry, *, confirmed: bool = True):
    return record_human_confirmation(
        entry_id=entry.queue_entry_id,
        action_id=entry.prepared_action_id,
        confirmed=confirmed,
    )


def _make_confirmed_entry(**kwargs):
    """Build a queue entry and record a confirmed human confirmation signal."""
    entry = _make_queue_entry(**kwargs)
    _make_confirmation(entry, confirmed=True)
    return entry


# ---------------------------------------------------------------------------
# MSOPolicyDecisionDraft invariant tests
# ---------------------------------------------------------------------------

class TestMSOPolicyDecisionDraftInvariants:
    """All safety invariants are enforced by __post_init__."""

    def test_execution_allowed_invariant_raises_on_true(self):
        with pytest.raises(ValueError, match="execution_allowed"):
            MSOPolicyDecisionDraft(
                policy_review_id="prd-test",
                entry_id="e1",
                action_id="a1",
                execution_allowed=True,
                can_execute_now=False,
                used_execution=False,
            )

    def test_can_execute_now_invariant_raises_on_true(self):
        with pytest.raises(ValueError, match="can_execute_now"):
            MSOPolicyDecisionDraft(
                policy_review_id="prd-test",
                entry_id="e1",
                action_id="a1",
                execution_allowed=False,
                can_execute_now=True,
                used_execution=False,
            )

    def test_used_execution_invariant_raises_on_true(self):
        with pytest.raises(ValueError, match="used_execution"):
            MSOPolicyDecisionDraft(
                policy_review_id="prd-test",
                entry_id="e1",
                action_id="a1",
                execution_allowed=False,
                can_execute_now=False,
                used_execution=True,
            )

    def test_empty_policy_review_id_raises(self):
        with pytest.raises(ValueError, match="policy_review_id"):
            MSOPolicyDecisionDraft(
                policy_review_id="",
                entry_id="e1",
                action_id="a1",
                execution_allowed=False,
                can_execute_now=False,
                used_execution=False,
            )

    def test_valid_draft_constructs(self):
        draft = MSOPolicyDecisionDraft(
            policy_review_id="prd-ok",
            entry_id="e1",
            action_id="a1",
            execution_allowed=False,
            can_execute_now=False,
            used_execution=False,
        )
        assert draft.execution_allowed is False
        assert draft.can_execute_now is False
        assert draft.used_execution is False
        assert draft.policy_review_id == "prd-ok"

    def test_artifact_type_constant(self):
        draft = MSOPolicyDecisionDraft(
            policy_review_id="prd-ok",
            entry_id="e1",
            action_id="a1",
            execution_allowed=False,
            can_execute_now=False,
            used_execution=False,
        )
        assert draft.artifact_type == "mso_policy_decision_draft"

    def test_to_dict_execution_fields_false(self):
        draft = MSOPolicyDecisionDraft(
            policy_review_id="prd-ok",
            entry_id="e1",
            action_id="a1",
            execution_allowed=False,
            can_execute_now=False,
            used_execution=False,
        )
        d = draft.to_dict()
        assert d["execution_allowed"] is False
        assert d["can_execute_now"] is False
        assert d["used_execution"] is False


# ---------------------------------------------------------------------------
# Evaluate — policy outcomes
# ---------------------------------------------------------------------------

class TestEvaluateMSOPolicyOutcomes:
    def setup_method(self):
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_allow_mode_produces_approved(self):
        # CODE_REVIEW is mode="allow" in capability registry
        entry = _make_queue_entry(action="CODE_REVIEW", domain="CODE")
        confirmation = _make_confirmation(entry)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        assert draft.policy_outcome == "approved"
        assert draft.capability_mode == "allow"

    def test_confirm_only_mode_produces_approved_confirm_only(self):
        # CODE_FIX is mode="confirm_only" in capability registry
        entry = _make_queue_entry(action="CODE_FIX", domain="CODE", capability_name="code_fix")
        confirmation = _make_confirmation(entry)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        assert draft.policy_outcome == "approved_confirm_only"
        assert draft.capability_mode == "confirm_only"

    def test_deny_mode_produces_denied(self):
        # ACTION_UNKNOWN maps to "deny"
        entry = _make_queue_entry(action="ACTION_UNKNOWN", domain="UNKNOWN", capability_name="")
        confirmation = _make_confirmation(entry)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        assert draft.policy_outcome == "denied"

    def test_unregistered_action_produces_denied(self):
        # Unregistered action → deny fallback in capability registry
        entry = _make_queue_entry(action="TOTALLY_UNKNOWN_ACTION", domain="CODE", capability_name="")
        confirmation = _make_confirmation(entry)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        assert draft.policy_outcome == "denied"

    def test_execution_always_closed_after_evaluation(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        assert draft.execution_allowed is False
        assert draft.can_execute_now is False
        assert draft.used_execution is False

    def test_human_confirmation_satisfied_true_after_confirmed(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry, confirmed=True)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        assert draft.human_confirmation_satisfied is True

    def test_policy_review_id_is_auto_generated_and_non_empty(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        assert draft.policy_review_id
        assert draft.policy_review_id.startswith("prd-")

    def test_entry_id_matches_queue_entry(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        assert draft.entry_id == entry.queue_entry_id

    def test_action_id_matches_prepared_action(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        assert draft.action_id == entry.prepared_action_id


# ---------------------------------------------------------------------------
# Evaluate — fail-closed cases
# ---------------------------------------------------------------------------

class TestEvaluateMSOPolicyFailClosed:
    def setup_method(self):
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_rejected_confirmation_raises_value_error(self):
        entry = _make_queue_entry()
        rejection = _make_confirmation(entry, confirmed=False)
        with pytest.raises(ValueError, match="rejected action"):
            evaluate_mso_policy_for_prepared_action(entry, rejection)

    def test_rejected_confirmation_does_not_store_review(self):
        entry = _make_queue_entry()
        rejection = _make_confirmation(entry, confirmed=False)
        with pytest.raises(ValueError):
            evaluate_mso_policy_for_prepared_action(entry, rejection)
        assert get_mso_policy_review(entry.queue_entry_id) is None

    def test_action_id_mismatch_raises_value_error(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry, confirmed=True)
        # Create a confirmation for a different action_id
        from dataclasses import replace
        bad_confirmation = replace(confirmation, action_id="wrong-action-id")
        with pytest.raises(ValueError, match="action_id mismatch"):
            evaluate_mso_policy_for_prepared_action(entry, bad_confirmation)

    def test_action_id_mismatch_does_not_store_review(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry, confirmed=True)
        from dataclasses import replace
        bad_confirmation = replace(confirmation, action_id="wrong-action-id")
        with pytest.raises(ValueError):
            evaluate_mso_policy_for_prepared_action(entry, bad_confirmation)
        assert get_mso_policy_review(entry.queue_entry_id) is None

    def test_rejected_confirmation_execution_never_opens(self):
        entry = _make_queue_entry()
        rejection = _make_confirmation(entry, confirmed=False)
        try:
            evaluate_mso_policy_for_prepared_action(entry, rejection)
        except ValueError:
            pass
        review = get_mso_policy_review(entry.queue_entry_id)
        assert review is None  # nothing stored


# ---------------------------------------------------------------------------
# Store operations
# ---------------------------------------------------------------------------

class TestMSOPolicyReviewStore:
    def setup_method(self):
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_review_persists_after_evaluation(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        retrieved = get_mso_policy_review(entry.queue_entry_id)
        assert retrieved is not None
        assert retrieved.policy_review_id == draft.policy_review_id

    def test_retrieve_unknown_entry_returns_none(self):
        assert get_mso_policy_review("no-such-entry-id") is None

    def test_clear_empties_store(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry)
        evaluate_mso_policy_for_prepared_action(entry, confirmation)
        clear_mso_policy_review_store_for_tests()
        assert get_mso_policy_review(entry.queue_entry_id) is None

    def test_second_evaluation_overwrites_previous(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry)
        draft1 = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        draft2 = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        retrieved = get_mso_policy_review(entry.queue_entry_id)
        assert retrieved.policy_review_id == draft2.policy_review_id
        assert retrieved.policy_review_id != draft1.policy_review_id


# ---------------------------------------------------------------------------
# Merge into read model
# ---------------------------------------------------------------------------

class TestMergePolicyReviewIntoDict:
    def setup_method(self):
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_merge_overlays_policy_fields(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry)
        evaluate_mso_policy_for_prepared_action(entry, confirmation)
        item = {"queue_entry_id": entry.queue_entry_id, "domain": "CODE"}
        merged = merge_policy_review_into_dict(item)
        assert "policy_review_id" in merged
        assert "policy_outcome" in merged
        assert "capability_mode" in merged
        assert "policy_review_created_at" in merged

    def test_merge_preserves_original_fields(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry)
        evaluate_mso_policy_for_prepared_action(entry, confirmation)
        item = {"queue_entry_id": entry.queue_entry_id, "domain": "CODE", "user_intent": "test"}
        merged = merge_policy_review_into_dict(item)
        assert merged["domain"] == "CODE"
        assert merged["user_intent"] == "test"

    def test_merge_no_review_returns_dict_unchanged(self):
        item = {"queue_entry_id": "no-review-here", "domain": "CODE"}
        merged = merge_policy_review_into_dict(item)
        assert "policy_review_id" not in merged
        assert merged == item

    def test_merge_empty_queue_entry_id_returns_dict_unchanged(self):
        item = {"queue_entry_id": "", "domain": "CODE"}
        merged = merge_policy_review_into_dict(item)
        assert "policy_review_id" not in merged

    def test_merge_missing_queue_entry_id_returns_dict_unchanged(self):
        item = {"domain": "CODE"}
        merged = merge_policy_review_into_dict(item)
        assert "policy_review_id" not in merged

    def test_merge_execution_fields_not_changed_to_true(self):
        entry = _make_queue_entry()
        confirmation = _make_confirmation(entry)
        evaluate_mso_policy_for_prepared_action(entry, confirmation)
        item = {
            "queue_entry_id": entry.queue_entry_id,
            "execution_allowed": False,
            "can_execute_now": False,
        }
        merged = merge_policy_review_into_dict(item)
        assert merged["execution_allowed"] is False
        assert merged["can_execute_now"] is False


# ---------------------------------------------------------------------------
# Endpoint logic (module-level function)
# ---------------------------------------------------------------------------

class TestMSOPolicyReviewEndpoint:
    def setup_method(self):
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def _make_confirmed_entry(self, *, action="CODE_REVIEW", domain="CODE"):
        entry = _make_queue_entry(action=action, domain=domain)
        _make_confirmation(entry, confirmed=True)
        return entry

    def test_missing_entry_id_returns_400(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        import json
        body = json.dumps({"action_id": "a1"}).encode()
        status, data = _process_mso_policy_review_request(body)
        assert status == 400
        assert data["ok"] is False

    def test_missing_action_id_returns_400(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        import json
        body = json.dumps({"entry_id": "e1"}).encode()
        status, data = _process_mso_policy_review_request(body)
        assert status == 400
        assert data["ok"] is False

    def test_missing_entry_returns_404(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        import json
        body = json.dumps({"entry_id": "no-such-entry", "action_id": "no-action"}).encode()
        status, data = _process_mso_policy_review_request(body)
        assert status == 404
        assert data["ok"] is False

    def test_no_confirmation_record_returns_422(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        import json
        entry = _make_queue_entry()
        # No confirmation recorded
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_policy_review_request(body)
        assert status == 422
        assert "confirmation_required" in data.get("error", "")

    def test_rejected_confirmation_returns_422(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        import json
        entry = _make_queue_entry()
        _make_confirmation(entry, confirmed=False)
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_policy_review_request(body)
        assert status == 422
        assert "action_rejected" in data.get("error", "")

    def test_action_id_mismatch_returns_400(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        import json
        entry = _make_confirmed_entry()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": "wrong-action-id",
        }).encode()
        status, data = _process_mso_policy_review_request(body)
        assert status == 400
        assert data["ok"] is False

    def test_success_returns_200_with_policy_review_id(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        import json
        entry = _make_confirmed_entry()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_policy_review_request(body)
        assert status == 200
        assert data["ok"] is True
        assert "policy_review_id" in data
        assert data["policy_review_id"].startswith("prd-")

    def test_success_execution_always_closed(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        import json
        entry = _make_confirmed_entry()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_policy_review_request(body)
        assert status == 200
        assert data["execution_allowed"] is False
        assert data["can_execute_now"] is False

    def test_success_policy_outcome_present(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        import json
        entry = _make_confirmed_entry()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_policy_review_request(body)
        assert data["policy_outcome"] in ("approved", "approved_confirm_only", "denied")

    def test_invalid_json_returns_400(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        status, data = _process_mso_policy_review_request(b"not-json")
        assert status == 400
        assert data["ok"] is False

    def test_no_execution_path_opens_for_deny_outcome(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        import json
        # Use an action that maps to deny in capability registry
        entry = _make_queue_entry(action="ACTION_UNKNOWN", domain="UNKNOWN", capability_name="")
        _make_confirmation(entry, confirmed=True)
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_policy_review_request(body)
        assert status == 200
        assert data["policy_outcome"] == "denied"
        assert data["execution_allowed"] is False
        assert data["can_execute_now"] is False
