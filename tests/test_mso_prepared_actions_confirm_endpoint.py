"""Tests for POST /mso/prepared-actions/confirm and GET merge behavior.

Covers:
 - Merge of HumanConfirmationRecord into prepared-action dicts (Task 2)
 - _process_mso_confirm_request() business logic (Task 3)
 - End-to-end flow: enqueue → confirm → status visible (Task 7)

Invariants verified at every step:
 - execution_allowed is False
 - can_execute_now is False
 - No authority chain step is satisfied or called
"""
import json

import pytest

from assistant_os.mso.authority_preparation import prepare_authority_from_proposal
from assistant_os.mso.confirmable_prepared_action import build_confirmable_from_preparation
from assistant_os.mso.execution_proposal import build_execution_proposal
from assistant_os.mso.human_confirmation import (
    clear_human_confirmation_store_for_tests,
    get_human_confirmation,
    merge_confirmation_into_dict,
    record_human_confirmation,
)
from assistant_os.mso.prepared_action_queue import (
    clear_confirmable_action_queue_for_tests,
    enqueue_confirmable_prepared_action,
    list_pending_confirmable_action_dicts,
)


@pytest.fixture(autouse=True)
def clear_stores():
    clear_human_confirmation_store_for_tests()
    clear_confirmable_action_queue_for_tests()
    yield
    clear_human_confirmation_store_for_tests()
    clear_confirmable_action_queue_for_tests()


def _make_queue_entry(intent: str = "plan the architecture docs"):
    """Build and enqueue a ConfirmablePreparedAction, return the queue entry."""
    proposal = build_execution_proposal(
        user_intent=intent,
        domain="CODE",
        requested_action="plan_architecture_docs",
        capability_name="code_docs",
        capability_scope=("read", "write"),
    )
    preparation = prepare_authority_from_proposal(proposal)
    confirmable = build_confirmable_from_preparation(preparation)
    return enqueue_confirmable_prepared_action(confirmable)


# ── Task 2: Merge tests ──────────────────────────────────────────────────────


def test_pending_dicts_show_pending_by_default():
    _make_queue_entry()
    items = list_pending_confirmable_action_dicts()
    assert len(items) == 1
    assert items[0]["human_confirmation_status"] == "pending"
    assert items[0]["execution_allowed"] is False


def test_pending_dicts_reflect_confirmation_after_merge():
    entry = _make_queue_entry()
    record_human_confirmation(
        entry_id=entry.queue_entry_id, action_id=entry.prepared_action_id, confirmed=True
    )
    items = list_pending_confirmable_action_dicts()
    merged = [merge_confirmation_into_dict(i) for i in items]
    assert merged[0]["human_confirmation_status"] == "human_confirmed"
    assert "confirmation_recorded_at" in merged[0]


def test_pending_dicts_reflect_rejection_after_merge():
    entry = _make_queue_entry()
    record_human_confirmation(
        entry_id=entry.queue_entry_id, action_id=entry.prepared_action_id, confirmed=False
    )
    items = list_pending_confirmable_action_dicts()
    merged = [merge_confirmation_into_dict(i) for i in items]
    assert merged[0]["human_confirmation_status"] == "human_rejected"


def test_execution_allowed_stays_false_after_merge():
    entry = _make_queue_entry()
    record_human_confirmation(
        entry_id=entry.queue_entry_id, action_id=entry.prepared_action_id, confirmed=True
    )
    items = list_pending_confirmable_action_dicts()
    merged = merge_confirmation_into_dict(items[0])
    assert merged["execution_allowed"] is False
    assert merged["can_execute_now"] is False


# ── Task 3: Endpoint logic tests ─────────────────────────────────────────────


from assistant_os.webhook_server import _process_mso_confirm_request  # noqa: E402


def test_confirm_endpoint_200_on_valid_confirm():
    entry = _make_queue_entry()
    body = json.dumps(
        {
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
            "confirmed": True,
            "operator_note": "looks good",
        }
    ).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 200
    assert response["ok"] is True
    assert response["human_confirmation_status"] == "human_confirmed"
    assert response["execution_allowed"] is False
    assert response["can_execute_now"] is False
    assert "recorded_at" in response


def test_confirm_endpoint_200_on_valid_reject():
    entry = _make_queue_entry()
    body = json.dumps(
        {
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
            "confirmed": False,
        }
    ).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 200
    assert response["human_confirmation_status"] == "human_rejected"
    assert response["execution_allowed"] is False


def test_confirm_endpoint_writes_to_store():
    entry = _make_queue_entry()
    body = json.dumps(
        {
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
            "confirmed": True,
        }
    ).encode()
    _process_mso_confirm_request(body)
    record = get_human_confirmation(entry.queue_entry_id)
    assert record is not None
    assert record.confirmed is True
    assert record.execution_allowed is False


def test_confirm_endpoint_404_on_unknown_entry():
    body = json.dumps(
        {"entry_id": "does-not-exist", "action_id": "a1", "confirmed": True}
    ).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 404
    assert response["ok"] is False


def test_confirm_endpoint_400_missing_entry_id():
    body = json.dumps({"action_id": "a1", "confirmed": True}).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 400
    assert "entry_id" in response["error"]


def test_confirm_endpoint_400_missing_action_id():
    entry = _make_queue_entry()
    body = json.dumps({"entry_id": entry.queue_entry_id, "confirmed": True}).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 400
    assert "action_id" in response["error"]


def test_confirm_endpoint_400_confirmed_not_bool():
    entry = _make_queue_entry()
    body = json.dumps(
        {
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
            "confirmed": "yes",
        }
    ).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 400
    assert "bool" in response["error"]


def test_confirm_endpoint_400_invalid_json():
    status, response = _process_mso_confirm_request(b"not json{{{")
    assert status == 400


def test_confirm_endpoint_execution_allowed_invariant():
    entry = _make_queue_entry()
    body = json.dumps(
        {
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
            "confirmed": True,
        }
    ).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 200
    assert response.get("execution_allowed") is False
    assert response.get("can_execute_now") is False


# ── Task 7: End-to-end flow ───────────────────────────────────────────────────


def test_full_flow_plan_request_to_confirmation():
    """Full segment: enqueue → GET pending → confirm → GET pending shows updated status.

    execution_allowed must be False at every step.
    """
    # 1. MSO produces a prepared action (simulating 05.1 flow)
    entry = _make_queue_entry("create architecture doc for auth module")
    entry_id = entry.queue_entry_id
    action_id = entry.prepared_action_id

    # 2. GET pending — visible in Mission Control
    items = list_pending_confirmable_action_dicts()
    assert len(items) == 1
    assert items[0]["human_confirmation_status"] == "pending"
    assert items[0]["execution_allowed"] is False

    # 3. Operator confirms via endpoint
    body = json.dumps(
        {
            "entry_id": entry_id,
            "action_id": action_id,
            "confirmed": True,
            "operator_note": "architecture doc plan looks correct",
        }
    ).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 200
    assert response["ok"] is True
    assert response["execution_allowed"] is False
    assert response["can_execute_now"] is False

    # 4. GET pending — status updated after merge
    items = list_pending_confirmable_action_dicts()
    merged = [merge_confirmation_into_dict(i) for i in items]
    assert merged[0]["human_confirmation_status"] == "human_confirmed"
    assert merged[0]["execution_allowed"] is False
    assert merged[0]["can_execute_now"] is False

    # 5. Confirmation record exists in store
    record = get_human_confirmation(entry_id)
    assert record is not None
    assert record.confirmed is True
    assert record.execution_allowed is False
