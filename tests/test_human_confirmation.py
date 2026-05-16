"""Tests for HumanConfirmationRecord — S-HUMAN-CONFIRM-01.

HumanConfirmationRecord records that a human operator has reviewed a
ConfirmablePreparedAction and signalled confirm or reject.

It does NOT grant execution authority, issue tokens, satisfy any step in the
authority chain (PolicyDecision → CapabilityToken → OperationBinding →
AuthorizedPlan → PoliceGate), or change execution_allowed.
"""
import pytest

from assistant_os.mso.human_confirmation import (
    HumanConfirmationRecord,
    clear_human_confirmation_store_for_tests,
    get_human_confirmation,
    merge_confirmation_into_dict,
    record_human_confirmation,
)


@pytest.fixture(autouse=True)
def clear_store():
    clear_human_confirmation_store_for_tests()
    yield
    clear_human_confirmation_store_for_tests()


# ── HumanConfirmationRecord invariants ──────────────────────────────────────


def test_confirmed_true_sets_status():
    r = HumanConfirmationRecord(entry_id="e1", action_id="a1", confirmed=True)
    assert r.execution_allowed is False
    d = r.to_dict()
    assert d["human_confirmation_status"] == "human_confirmed"
    assert d["execution_allowed"] is False
    assert d["can_execute_now"] is False
    assert "recorded_at" in d and "T" in d["recorded_at"]


def test_confirmed_false_sets_status():
    r = HumanConfirmationRecord(entry_id="e1", action_id="a1", confirmed=False)
    assert r.to_dict()["human_confirmation_status"] == "human_rejected"


def test_execution_allowed_enforced():
    with pytest.raises(ValueError, match="execution_allowed must be False"):
        HumanConfirmationRecord(
            entry_id="e1", action_id="a1", confirmed=True, execution_allowed=True
        )


def test_empty_entry_id_raises():
    with pytest.raises(ValueError, match="entry_id"):
        HumanConfirmationRecord(entry_id="", action_id="a1", confirmed=True)


def test_empty_action_id_raises():
    with pytest.raises(ValueError, match="action_id"):
        HumanConfirmationRecord(entry_id="e1", action_id="", confirmed=True)


# ── Store operations ─────────────────────────────────────────────────────────


def test_record_and_retrieve():
    record_human_confirmation(entry_id="e1", action_id="a1", confirmed=True, operator_note="lgtm")
    result = get_human_confirmation("e1")
    assert result is not None
    assert result.confirmed is True
    assert result.operator_note == "lgtm"
    assert result.execution_allowed is False


def test_get_none_for_unknown():
    assert get_human_confirmation("nonexistent") is None


def test_double_record_overwrites():
    record_human_confirmation(entry_id="e1", action_id="a1", confirmed=True)
    record_human_confirmation(entry_id="e1", action_id="a1", confirmed=False)
    assert get_human_confirmation("e1").confirmed is False


# ── merge_confirmation_into_dict ─────────────────────────────────────────────


def test_merge_injects_status_when_record_exists():
    record_human_confirmation(entry_id="e1", action_id="a1", confirmed=True, operator_note="ok")
    merged = merge_confirmation_into_dict(
        {"queue_entry_id": "e1", "human_confirmation_status": "pending"}
    )
    assert merged["human_confirmation_status"] == "human_confirmed"
    assert "confirmation_recorded_at" in merged
    assert merged["operator_note"] == "ok"


def test_merge_is_noop_when_no_record():
    d = {"queue_entry_id": "e99", "human_confirmation_status": "pending"}
    merged = merge_confirmation_into_dict(d)
    assert merged["human_confirmation_status"] == "pending"
    assert "confirmation_recorded_at" not in merged


def test_merge_does_not_set_execution_allowed():
    record_human_confirmation(entry_id="e1", action_id="a1", confirmed=True)
    merged = merge_confirmation_into_dict({"queue_entry_id": "e1", "execution_allowed": False})
    assert merged.get("execution_allowed") is False


def test_merge_handles_missing_queue_entry_id_gracefully():
    record_human_confirmation(entry_id="e1", action_id="a1", confirmed=True)
    d = {"human_confirmation_status": "pending"}
    merged = merge_confirmation_into_dict(d)
    assert merged["human_confirmation_status"] == "pending"
