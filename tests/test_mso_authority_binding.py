"""Tests for MSOAuthorityBindingDraft and create_mso_authority_binding.

Covers:
- Invariant enforcement (execution_allowed, can_execute_now, used_execution, authority_binding_id)
- Core logic: approved/approved_confirm_only → binding, denied → raises, entry_id mismatch → raises
- Idempotency: duplicate calls return same artifact
- Store: persist, retrieve None, clear
- Merge: overlay fields on dict, no-op when no binding
- Endpoint: missing fields, unknown entry, no policy review, denied, success, duplicate
"""
from __future__ import annotations

import pytest

from assistant_os.mso.authority_binding import (
    MSOAuthorityBindingDraft,
    clear_mso_authority_binding_store_for_tests,
    create_mso_authority_binding,
    get_mso_authority_binding,
    merge_authority_binding_into_dict,
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
# Helpers
# ---------------------------------------------------------------------------

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


def _make_policy_review(entry, *, confirmed=True):
    confirmation = record_human_confirmation(
        entry_id=entry.queue_entry_id,
        action_id=entry.prepared_action_id,
        confirmed=confirmed,
    )
    return evaluate_mso_policy_for_prepared_action(entry, confirmation)


def _make_approved_pair(action="CODE_REVIEW", domain="CODE", capability_name="code_review"):
    """Return (entry, policy_review) with an approved or approved_confirm_only outcome."""
    entry = _make_queue_entry(action=action, domain=domain, capability_name=capability_name)
    review = _make_policy_review(entry)
    return entry, review


# ---------------------------------------------------------------------------
# Invariant tests
# ---------------------------------------------------------------------------

class TestMSOAuthorityBindingDraftInvariants:
    def setup_method(self):
        clear_mso_authority_binding_store_for_tests()
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_execution_allowed_invariant_raises_on_true(self):
        with pytest.raises(ValueError, match="execution_allowed"):
            MSOAuthorityBindingDraft(
                authority_binding_id="ab-test",
                entry_id="e1",
                action_id="a1",
                policy_review_id="prd-1",
                execution_allowed=True,
            )

    def test_can_execute_now_invariant_raises_on_true(self):
        with pytest.raises(ValueError, match="can_execute_now"):
            MSOAuthorityBindingDraft(
                authority_binding_id="ab-test",
                entry_id="e1",
                action_id="a1",
                policy_review_id="prd-1",
                can_execute_now=True,
            )

    def test_used_execution_invariant_raises_on_true(self):
        with pytest.raises(ValueError, match="used_execution"):
            MSOAuthorityBindingDraft(
                authority_binding_id="ab-test",
                entry_id="e1",
                action_id="a1",
                policy_review_id="prd-1",
                used_execution=True,
            )

    def test_authority_binding_id_must_be_non_empty(self):
        with pytest.raises(ValueError, match="authority_binding_id"):
            MSOAuthorityBindingDraft(
                authority_binding_id="",
                entry_id="e1",
                action_id="a1",
                policy_review_id="prd-1",
            )

    def test_binding_status_defaults_to_drafted(self):
        b = MSOAuthorityBindingDraft(
            authority_binding_id="ab-x",
            entry_id="e1",
            action_id="a1",
            policy_review_id="prd-1",
        )
        assert b.binding_status == "drafted"

    def test_requires_authorized_plan_defaults_to_true(self):
        b = MSOAuthorityBindingDraft(
            authority_binding_id="ab-x",
            entry_id="e1",
            action_id="a1",
            policy_review_id="prd-1",
        )
        assert b.requires_authorized_plan is True

    def test_requires_police_gate_defaults_to_true(self):
        b = MSOAuthorityBindingDraft(
            authority_binding_id="ab-x",
            entry_id="e1",
            action_id="a1",
            policy_review_id="prd-1",
        )
        assert b.requires_police_gate is True

    def test_artifact_type_is_mso_authority_binding_draft(self):
        b = MSOAuthorityBindingDraft(
            authority_binding_id="ab-x",
            entry_id="e1",
            action_id="a1",
            policy_review_id="prd-1",
        )
        assert b.artifact_type == "mso_authority_binding_draft"


# ---------------------------------------------------------------------------
# Core logic tests
# ---------------------------------------------------------------------------

class TestCreateMSOAuthorityBinding:
    def setup_method(self):
        clear_mso_authority_binding_store_for_tests()
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_approved_creates_binding(self):
        entry, review = _make_approved_pair()
        binding = create_mso_authority_binding(entry, review)
        assert binding.authority_binding_id.startswith("ab-")
        assert binding.policy_review_id == review.policy_review_id
        assert binding.entry_id == entry.queue_entry_id

    def test_approved_confirm_only_creates_binding(self):
        # WORK_CREATE is confirm_only in the capability registry
        entry, review = _make_approved_pair(
            action="WORK_CREATE", domain="WORK", capability_name="work_create"
        )
        assert review.policy_outcome in ("approved", "approved_confirm_only")
        binding = create_mso_authority_binding(entry, review)
        assert binding.authority_binding_id.startswith("ab-")

    def test_denied_raises_value_error(self):
        entry = _make_queue_entry(action="ACTION_UNKNOWN", domain="UNKNOWN", capability_name="")
        review = _make_policy_review(entry)
        assert review.policy_outcome == "denied"
        with pytest.raises(ValueError, match="denied"):
            create_mso_authority_binding(entry, review)

    def test_entry_id_mismatch_raises(self):
        entry1, review1 = _make_approved_pair()
        entry2 = _make_queue_entry()
        with pytest.raises(ValueError, match="entry_id mismatch"):
            create_mso_authority_binding(entry2, review1)

    def test_idempotent_same_id_on_duplicate_call(self):
        entry, review = _make_approved_pair()
        b1 = create_mso_authority_binding(entry, review)
        b2 = create_mso_authority_binding(entry, review)
        assert b1.authority_binding_id == b2.authority_binding_id

    def test_execution_always_false(self):
        entry, review = _make_approved_pair()
        binding = create_mso_authority_binding(entry, review)
        assert binding.execution_allowed is False
        assert binding.can_execute_now is False
        assert binding.used_execution is False

    def test_requires_authorized_plan_and_police_gate_always_true(self):
        entry, review = _make_approved_pair()
        binding = create_mso_authority_binding(entry, review)
        assert binding.requires_authorized_plan is True
        assert binding.requires_police_gate is True

    def test_binding_status_is_drafted(self):
        entry, review = _make_approved_pair()
        binding = create_mso_authority_binding(entry, review)
        assert binding.binding_status == "drafted"


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------

class TestMSOAuthorityBindingStore:
    def setup_method(self):
        clear_mso_authority_binding_store_for_tests()
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_store_persists_binding(self):
        entry, review = _make_approved_pair()
        binding = create_mso_authority_binding(entry, review)
        retrieved = get_mso_authority_binding(entry.queue_entry_id)
        assert retrieved is not None
        assert retrieved.authority_binding_id == binding.authority_binding_id

    def test_retrieve_returns_none_for_unknown(self):
        assert get_mso_authority_binding("no-such-entry") is None

    def test_clear_empties_store(self):
        entry, review = _make_approved_pair()
        create_mso_authority_binding(entry, review)
        clear_mso_authority_binding_store_for_tests()
        assert get_mso_authority_binding(entry.queue_entry_id) is None

    def test_idempotency_does_not_overwrite_store(self):
        entry, review = _make_approved_pair()
        b1 = create_mso_authority_binding(entry, review)
        b2 = create_mso_authority_binding(entry, review)
        stored = get_mso_authority_binding(entry.queue_entry_id)
        assert stored.authority_binding_id == b1.authority_binding_id == b2.authority_binding_id


# ---------------------------------------------------------------------------
# Merge into read model tests
# ---------------------------------------------------------------------------

class TestMergeAuthorityBindingIntoDict:
    def setup_method(self):
        clear_mso_authority_binding_store_for_tests()
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_merge_overlays_authority_binding_fields(self):
        entry, review = _make_approved_pair()
        create_mso_authority_binding(entry, review)
        item = {"queue_entry_id": entry.queue_entry_id, "domain": "CODE"}
        merged = merge_authority_binding_into_dict(item)
        assert "authority_binding_id" in merged
        assert "authority_binding_status" in merged
        assert "authority_binding_created_at" in merged
        assert "requires_authorized_plan" in merged
        assert "requires_police_gate" in merged

    def test_merge_preserves_original_fields(self):
        entry, review = _make_approved_pair()
        create_mso_authority_binding(entry, review)
        item = {"queue_entry_id": entry.queue_entry_id, "domain": "CODE", "extra": "keep"}
        merged = merge_authority_binding_into_dict(item)
        assert merged["domain"] == "CODE"
        assert merged["extra"] == "keep"

    def test_merge_noop_when_no_binding_exists(self):
        item = {"queue_entry_id": "no-such-entry", "domain": "CODE"}
        merged = merge_authority_binding_into_dict(item)
        assert merged == item

    def test_merge_execution_fields_unchanged(self):
        entry, review = _make_approved_pair()
        create_mso_authority_binding(entry, review)
        item = {
            "queue_entry_id": entry.queue_entry_id,
            "execution_allowed": False,
            "can_execute_now": False,
        }
        merged = merge_authority_binding_into_dict(item)
        assert merged["execution_allowed"] is False
        assert merged["can_execute_now"] is False

    def test_merge_noop_when_no_queue_entry_id(self):
        item = {"domain": "CODE"}
        merged = merge_authority_binding_into_dict(item)
        assert merged == item


# ---------------------------------------------------------------------------
# Endpoint logic tests
# ---------------------------------------------------------------------------

class TestMSOAuthorityBindingEndpoint:
    def setup_method(self):
        clear_mso_authority_binding_store_for_tests()
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_missing_entry_id_returns_400(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        body = json.dumps({"action_id": "a1"}).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 400
        assert data["ok"] is False

    def test_missing_action_id_returns_400(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        body = json.dumps({"entry_id": "e1"}).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 400
        assert data["ok"] is False

    def test_unknown_entry_returns_404(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        body = json.dumps({"entry_id": "no-such", "action_id": "no-action"}).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 404
        assert data["ok"] is False

    def test_action_id_mismatch_returns_400(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": "wrong-action-id",
        }).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 400
        assert data["ok"] is False

    def test_no_policy_review_returns_422(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry = _make_queue_entry()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 422
        assert "policy_review_required" in data.get("error", "")

    def test_denied_policy_review_returns_422(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry = _make_queue_entry(action="ACTION_UNKNOWN", domain="UNKNOWN", capability_name="")
        _make_policy_review(entry)
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 422
        assert "policy_denied" in data.get("error", "")

    def test_approved_returns_200_with_binding_id(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 200
        assert data["ok"] is True
        assert data["authority_binding_id"].startswith("ab-")

    def test_approved_confirm_only_returns_200(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair(
            action="WORK_CREATE", domain="WORK", capability_name="work_create"
        )
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 200
        assert data["ok"] is True

    def test_success_requires_authorized_plan_true(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        _, data = _process_mso_authority_binding_request(body)
        assert data["requires_authorized_plan"] is True

    def test_success_requires_police_gate_true(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        _, data = _process_mso_authority_binding_request(body)
        assert data["requires_police_gate"] is True

    def test_success_execution_always_closed(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        _, data = _process_mso_authority_binding_request(body)
        assert data["execution_allowed"] is False
        assert data["can_execute_now"] is False
        assert data["used_execution"] is False

    def test_duplicate_post_returns_same_binding_id(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        _, data1 = _process_mso_authority_binding_request(body)
        _, data2 = _process_mso_authority_binding_request(body)
        assert data1["authority_binding_id"] == data2["authority_binding_id"]

    def test_invalid_json_returns_400(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        status, data = _process_mso_authority_binding_request(b"not-json")
        assert status == 400
        assert data["ok"] is False

    def test_no_authorized_plan_field_in_response(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        _, data = _process_mso_authority_binding_request(body)
        assert "authorized_plan" not in data
        assert "authorized_plan_id" not in data

    def test_no_runner_field_in_response(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        _, data = _process_mso_authority_binding_request(body)
        assert "runner" not in data
        assert "execution_id" not in data
