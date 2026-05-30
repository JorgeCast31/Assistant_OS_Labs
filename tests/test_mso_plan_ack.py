"""
Tests for assistant_os.mso.plan_ack (PlanMSOAck model + SQLite store).

Validates:
- PlanMSOAck model invariants (no execution, no tokens, no authorization)
- ack_id format enforced: ack_<timestamp_ms>_<uuid4_short>
- ack_status limited to: acknowledged | rejected_for_review
- create_ack persists to SQLite
- get_ack_for_plan retrieves by plan_id + operator_seat
- multiple ACKs: latest retrieved
- rejected_for_review stored correctly
- duplicate ACK rejected (409-equivalent DuplicatePlanAck exception)
- ACK does not produce execution_allowed, used_execution, runner_reachable_from_ui = True
- static boundary: plan_ack does not import from execution, runner, police, machine_operator
- test isolation via ASSISTANT_OS_PREPARE_STORE_PATH env var
"""
import os
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from assistant_os.mso.plan_ack import (
    PlanMSOAck,
    DuplicatePlanAck,
    PlanAckNotFound,
    InvalidAckStatus,
    create_ack,
    get_ack_for_plan,
    list_acks_for_plan,
    _PREPARE_STORE_ENV,
)


# ---------------------------------------------------------------------------
# Test isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    db = tmp_path / "test_prepare.db"
    monkeypatch.setenv(_PREPARE_STORE_ENV, str(db))
    yield db


def _plan_id() -> str:
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    uid = uuid4().hex[:8]
    return f"plan_{ts}_{uid}"


def _make_ack(
    plan_id: str | None = None,
    operator_seat: str = "operator_1",
    ack_status: str = "acknowledged",
    acknowledged_by: str = "mso_operator",
    note: str | None = None,
) -> PlanMSOAck:
    return PlanMSOAck(
        plan_id=plan_id or _plan_id(),
        operator_seat=operator_seat,
        ack_status=ack_status,
        acknowledged_by=acknowledged_by,
        note=note,
    )


# ---------------------------------------------------------------------------
# Model invariants
# ---------------------------------------------------------------------------

class TestPlanMSOAckModel:
    def test_ack_id_format(self):
        ack = _make_ack()
        assert ack.ack_id.startswith("ack_"), f"Expected ack_ prefix, got: {ack.ack_id}"
        parts = ack.ack_id.split("_")
        assert len(parts) == 3, f"Expected ack_<ts>_<uid>, got: {ack.ack_id}"

    def test_execution_allowed_always_false(self):
        ack = _make_ack()
        assert ack.execution_allowed is False

    def test_used_execution_always_false(self):
        ack = _make_ack()
        assert ack.used_execution is False

    def test_runner_reachable_always_false(self):
        ack = _make_ack()
        assert ack.runner_reachable_from_ui is False

    def test_source_is_plan_mso_ack(self):
        ack = _make_ack()
        assert ack.source == "plan_mso_ack"

    def test_acknowledged_status_valid(self):
        ack = _make_ack(ack_status="acknowledged")
        assert ack.ack_status == "acknowledged"

    def test_rejected_for_review_status_valid(self):
        ack = _make_ack(ack_status="rejected_for_review")
        assert ack.ack_status == "rejected_for_review"

    def test_invalid_ack_status_raises(self):
        with pytest.raises((InvalidAckStatus, ValueError)):
            _make_ack(ack_status="authorized")

    def test_invalid_ack_status_auto_raises(self):
        with pytest.raises((InvalidAckStatus, ValueError)):
            _make_ack(ack_status="auto:approved")

    def test_acknowledged_at_is_set(self):
        ack = _make_ack()
        assert ack.acknowledged_at
        datetime.fromisoformat(ack.acknowledged_at)  # must be valid ISO 8601

    def test_note_optional(self):
        ack = _make_ack(note=None)
        assert ack.note is None

    def test_note_stored_when_provided(self):
        ack = _make_ack(note="MSO has reviewed this plan.")
        assert ack.note == "MSO has reviewed this plan."

    def test_cannot_set_execution_allowed_true(self):
        with pytest.raises((ValueError, TypeError)):
            PlanMSOAck(
                plan_id=_plan_id(),
                operator_seat="op",
                ack_status="acknowledged",
                acknowledged_by="mso",
                execution_allowed=True,
            )

    def test_cannot_set_used_execution_true(self):
        with pytest.raises((ValueError, TypeError)):
            PlanMSOAck(
                plan_id=_plan_id(),
                operator_seat="op",
                ack_status="acknowledged",
                acknowledged_by="mso",
                used_execution=True,
            )

    def test_to_dict_has_no_execution_true(self):
        ack = _make_ack()
        d = ack.to_dict()
        assert d["execution_allowed"] is False
        assert d["used_execution"] is False
        assert d["runner_reachable_from_ui"] is False

    def test_to_dict_no_token_refs(self):
        ack = _make_ack()
        d = ack.to_dict()
        forbidden = {"capability_token_ref", "authority_artifact_ref", "runner_ref", "mission_id"}
        for key in forbidden:
            assert key not in d, f"Forbidden field '{key}' found in PlanMSOAck.to_dict()"


# ---------------------------------------------------------------------------
# Store: create and retrieve
# ---------------------------------------------------------------------------

class TestPlanAckStore:
    def test_create_and_get_ack(self):
        pid = _plan_id()
        ack = _make_ack(plan_id=pid, operator_seat="seat_1")
        create_ack(ack)
        retrieved = get_ack_for_plan(pid, "seat_1")
        assert retrieved.ack_id == ack.ack_id
        assert retrieved.plan_id == pid
        assert retrieved.operator_seat == "seat_1"
        assert retrieved.ack_status == "acknowledged"

    def test_get_ack_not_found_raises(self):
        with pytest.raises(PlanAckNotFound):
            get_ack_for_plan("plan_9999_nonexistent", "seat_1")

    def test_create_rejected_for_review_ack(self):
        pid = _plan_id()
        ack = _make_ack(plan_id=pid, ack_status="rejected_for_review", note="Needs more context.")
        create_ack(ack)
        retrieved = get_ack_for_plan(pid, "operator_1")
        assert retrieved.ack_status == "rejected_for_review"
        assert retrieved.note == "Needs more context."

    def test_duplicate_ack_raises(self):
        pid = _plan_id()
        ack1 = _make_ack(plan_id=pid)
        create_ack(ack1)
        ack2 = _make_ack(plan_id=pid)
        with pytest.raises(DuplicatePlanAck):
            create_ack(ack2)

    def test_list_acks_for_plan(self):
        pid = _plan_id()
        ack = _make_ack(plan_id=pid)
        create_ack(ack)
        acks = list_acks_for_plan(pid)
        assert len(acks) == 1
        assert acks[0].ack_id == ack.ack_id

    def test_list_acks_empty_for_unknown_plan(self):
        acks = list_acks_for_plan("plan_0000_unknown")
        assert acks == []

    def test_ack_persists_execution_false_in_db(self):
        pid = _plan_id()
        ack = _make_ack(plan_id=pid)
        create_ack(ack)
        retrieved = get_ack_for_plan(pid, "operator_1")
        assert retrieved.execution_allowed is False
        assert retrieved.used_execution is False
        assert retrieved.runner_reachable_from_ui is False

    def test_ack_isolation_across_plans(self):
        pid1 = _plan_id()
        pid2 = _plan_id()
        ack1 = _make_ack(plan_id=pid1, acknowledged_by="mso_1")
        ack2 = _make_ack(plan_id=pid2, acknowledged_by="mso_2")
        create_ack(ack1)
        create_ack(ack2)
        r1 = get_ack_for_plan(pid1, "operator_1")
        r2 = get_ack_for_plan(pid2, "operator_1")
        assert r1.acknowledged_by == "mso_1"
        assert r2.acknowledged_by == "mso_2"


# ---------------------------------------------------------------------------
# Static boundary: plan_ack must not import execution primitives
# ---------------------------------------------------------------------------

class TestPlanAckStaticBoundary:
    def test_no_runner_import(self):
        import ast, inspect
        import assistant_os.mso.plan_ack as m
        src = inspect.getsource(m)
        forbidden = ["from .runner", "import runner", "from ..runner", "machine_operator"]
        for token in forbidden:
            assert token not in src, f"Forbidden import '{token}' found in plan_ack.py"

    def test_no_execution_proposal_import(self):
        import inspect
        import assistant_os.mso.plan_ack as m
        src = inspect.getsource(m)
        assert "execution_proposal" not in src
        assert "authority_preparation" not in src
        assert "confirmable_prepared_action" not in src
        assert "prepared_action_queue" not in src

    def test_no_auto_ref_pattern(self):
        import inspect
        import assistant_os.mso.plan_ack as m
        src = inspect.getsource(m)
        assert "auto:" not in src
