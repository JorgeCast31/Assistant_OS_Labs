"""
PlanPrepareStatus — read-only correlated read-model.

Aggregates Plan + PlanMSOAck + PrepareRequest + PreparedAction queue status
into a single, honest, non-executing read-model for observability.

This module is intentionally NOT:
  - executing anything
  - calling Runner
  - emitting tokens
  - creating AuthorityArtifact
  - changing Plan state
  - changing ACK or PrepareRequest

This IS:
  - a read-only aggregator: Plan → ACK → PrepareRequest → queue
  - answering "where is this plan in the prepare lifecycle?"
  - always returning execution_allowed=False, used_execution=False

Status values:
  no_plan                    — plan_id not found
  operator_seat_mismatch     — wrong seat
  draft                      — Plan.state = draft
  planning                   — Plan.state = planning
  mso_review_ack_pending     — mso_review, no ACK yet
  mso_review_ack_rejected    — mso_review, ACK rejected_for_review
  acked_prepare_not_requested — acknowledged ACK, no PrepareRequest
  prepared_awaiting_confirmation — PrepareRequest prepared, PreparedAction queued
  prepare_rejected           — PrepareRequest rejected
  requires_review            — PrepareRequest requires_review
  unknown                    — unexpected state

Sprint: #231 — Plan Prepare Status and Authority Trace Correlation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .draft_store import get_plan
from .plan_ack import get_ack_for_plan, PlanAckNotFound
from .plan_model import PlanNotFound, OperatorSeatMismatch
from .prepare_contract import get_prepare_request_for_plan
from .prepared_action_queue import list_pending_confirmable_actions


# ---------------------------------------------------------------------------
# PlanPrepareStatus dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanPrepareStatus:
    """Read-only correlated status snapshot for a Plan's prepare lifecycle.

    Never authorizes. Never executes. Never emits tokens.
    """

    ok: bool
    source: str                         # always "prepare_status"
    plan_id: str
    operator_seat: str
    correlation_id: Optional[str]       # = plan_id when plan found
    status: str                         # see module docstring
    plan_state: Optional[str]
    ack_status: Optional[str]
    prepare_request_id: Optional[str]
    prepare_request_status: Optional[str]
    prepared_action_id: Optional[str]
    confirm_queue_status: Optional[str]
    authority_stage: str
    missing_requirements: list[str]
    error: Optional[str]

    # Safety invariants — NEVER change these defaults
    execution_allowed: bool = False
    used_execution: bool = False
    runner_reachable_from_ui: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "source": self.source,
            "plan_id": self.plan_id,
            "operator_seat": self.operator_seat,
            "correlation_id": self.correlation_id,
            "status": self.status,
            "plan_state": self.plan_state,
            "ack_status": self.ack_status,
            "prepare_request_id": self.prepare_request_id,
            "prepare_request_status": self.prepare_request_status,
            "prepared_action_id": self.prepared_action_id,
            "confirm_queue_status": self.confirm_queue_status,
            "authority_stage": self.authority_stage,
            "missing_requirements": list(self.missing_requirements),
            "error": self.error,
            "execution_allowed": self.execution_allowed,
            "used_execution": self.used_execution,
            "runner_reachable_from_ui": self.runner_reachable_from_ui,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unknown(plan_id: str, seat: str, error: str) -> PlanPrepareStatus:
    return PlanPrepareStatus(
        ok=False,
        source="prepare_status",
        plan_id=plan_id,
        operator_seat=seat,
        correlation_id=plan_id,
        status="unknown",
        plan_state=None,
        ack_status=None,
        prepare_request_id=None,
        prepare_request_status=None,
        prepared_action_id=None,
        confirm_queue_status=None,
        authority_stage="unknown",
        missing_requirements=[],
        error=error,
    )


def _find_queue_entry_for_prepare_request(prepare_request_id: str):
    """Return queue entry whose preparation_id matches, or None."""
    for entry in list_pending_confirmable_actions():
        if entry.preparation_id == prepare_request_id:
            return entry
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_plan_prepare_status(plan_id: str, operator_seat: str) -> PlanPrepareStatus:
    """Build the correlated prepare status for a plan.

    Never raises. Always returns a PlanPrepareStatus.
    execution_allowed, used_execution, runner_reachable_from_ui are invariantly False.
    """
    # 1. Load Plan
    try:
        plan = get_plan(plan_id, operator_seat)
    except PlanNotFound:
        return PlanPrepareStatus(
            ok=False,
            source="prepare_status",
            plan_id=plan_id,
            operator_seat=operator_seat,
            correlation_id=None,
            status="no_plan",
            plan_state=None,
            ack_status=None,
            prepare_request_id=None,
            prepare_request_status=None,
            prepared_action_id=None,
            confirm_queue_status=None,
            authority_stage="unknown",
            missing_requirements=[f"Plan '{plan_id}' not found."],
            error=f"no_plan: plan_id='{plan_id}' not found.",
        )
    except OperatorSeatMismatch:
        return PlanPrepareStatus(
            ok=False,
            source="prepare_status",
            plan_id=plan_id,
            operator_seat=operator_seat,
            correlation_id=plan_id,
            status="operator_seat_mismatch",
            plan_state=None,
            ack_status=None,
            prepare_request_id=None,
            prepare_request_status=None,
            prepared_action_id=None,
            confirm_queue_status=None,
            authority_stage="unknown",
            missing_requirements=[],
            error=f"operator_seat_mismatch: plan '{plan_id}' does not belong to seat '{operator_seat}'.",
        )
    except Exception as exc:  # noqa: BLE001
        return _unknown(plan_id, operator_seat, str(exc))

    # 2. Handle pre-mso_review states immediately
    if plan.state == "draft":
        return PlanPrepareStatus(
            ok=True,
            source="prepare_status",
            plan_id=plan_id,
            operator_seat=operator_seat,
            correlation_id=plan_id,
            status="draft",
            plan_state="draft",
            ack_status=None,
            prepare_request_id=None,
            prepare_request_status=None,
            prepared_action_id=None,
            confirm_queue_status=None,
            authority_stage="intent",
            missing_requirements=[
                "Transition plan to 'planning' then 'mso_review' before prepare.",
            ],
            error=None,
        )

    if plan.state == "planning":
        return PlanPrepareStatus(
            ok=True,
            source="prepare_status",
            plan_id=plan_id,
            operator_seat=operator_seat,
            correlation_id=plan_id,
            status="planning",
            plan_state="planning",
            ack_status=None,
            prepare_request_id=None,
            prepare_request_status=None,
            prepared_action_id=None,
            confirm_queue_status=None,
            authority_stage="intent",
            missing_requirements=[
                "Transition plan to 'mso_review' before prepare.",
            ],
            error=None,
        )

    # plan.state == "mso_review" from here

    # 3. Check ACK
    try:
        ack = get_ack_for_plan(plan_id, operator_seat)
    except PlanAckNotFound:
        return PlanPrepareStatus(
            ok=True,
            source="prepare_status",
            plan_id=plan_id,
            operator_seat=operator_seat,
            correlation_id=plan_id,
            status="mso_review_ack_pending",
            plan_state="mso_review",
            ack_status=None,
            prepare_request_id=None,
            prepare_request_status=None,
            prepared_action_id=None,
            confirm_queue_status=None,
            authority_stage="mso_read",
            missing_requirements=[
                "POST /mso/plans/{plan_id}/ack with ack_status=acknowledged before prepare.",
            ],
            error=None,
        )
    except Exception as exc:  # noqa: BLE001
        return _unknown(plan_id, operator_seat, f"ack lookup error: {exc}")

    if ack.ack_status == "rejected_for_review":
        return PlanPrepareStatus(
            ok=True,
            source="prepare_status",
            plan_id=plan_id,
            operator_seat=operator_seat,
            correlation_id=plan_id,
            status="mso_review_ack_rejected",
            plan_state="mso_review",
            ack_status="rejected_for_review",
            prepare_request_id=None,
            prepare_request_status=None,
            prepared_action_id=None,
            confirm_queue_status=None,
            authority_stage="mso_read",
            missing_requirements=[
                "ACK is rejected_for_review. Create a new Plan to proceed.",
            ],
            error=None,
        )

    # ack_status == "acknowledged"

    # 4. Check PrepareRequest
    try:
        prep_req = get_prepare_request_for_plan(plan_id)
    except Exception as exc:  # noqa: BLE001
        return _unknown(plan_id, operator_seat, f"prepare request lookup error: {exc}")

    if prep_req is None:
        return PlanPrepareStatus(
            ok=True,
            source="prepare_status",
            plan_id=plan_id,
            operator_seat=operator_seat,
            correlation_id=plan_id,
            status="acked_prepare_not_requested",
            plan_state="mso_review",
            ack_status="acknowledged",
            prepare_request_id=None,
            prepare_request_status=None,
            prepared_action_id=None,
            confirm_queue_status=None,
            authority_stage="mso_read",
            missing_requirements=[
                "POST /mso/plans/{plan_id}/prepare with confirmation_acknowledged=true.",
            ],
            error=None,
        )

    # PrepareRequest exists — check its status
    prep_status = prep_req.prepare_status

    if prep_status == "rejected":
        return PlanPrepareStatus(
            ok=True,
            source="prepare_status",
            plan_id=plan_id,
            operator_seat=operator_seat,
            correlation_id=plan_id,
            status="prepare_rejected",
            plan_state="mso_review",
            ack_status="acknowledged",
            prepare_request_id=prep_req.prepare_request_id,
            prepare_request_status="rejected",
            prepared_action_id=None,
            confirm_queue_status=None,
            authority_stage="mso_read",
            missing_requirements=[
                f"Prepare was rejected: {prep_req.fail_closed_reason or 'see prepare request'}.",
                "Create a new Plan to retry prepare.",
            ],
            error=None,
        )

    if prep_status == "requires_review":
        return PlanPrepareStatus(
            ok=True,
            source="prepare_status",
            plan_id=plan_id,
            operator_seat=operator_seat,
            correlation_id=plan_id,
            status="requires_review",
            plan_state="mso_review",
            ack_status="acknowledged",
            prepare_request_id=prep_req.prepare_request_id,
            prepare_request_status="requires_review",
            prepared_action_id=None,
            confirm_queue_status=None,
            authority_stage="mso_read",
            missing_requirements=[
                "Governance requires additional operator decision before prepare can proceed.",
            ],
            error=None,
        )

    # prep_status == "prepared" — find queue entry
    queue_entry = _find_queue_entry_for_prepare_request(prep_req.prepare_request_id)

    prepared_action_id = queue_entry.prepared_action_id if queue_entry else None
    confirm_queue_status = queue_entry.status if queue_entry else None

    return PlanPrepareStatus(
        ok=True,
        source="prepare_status",
        plan_id=plan_id,
        operator_seat=operator_seat,
        correlation_id=plan_id,
        status="prepared_awaiting_confirmation",
        plan_state="mso_review",
        ack_status="acknowledged",
        prepare_request_id=prep_req.prepare_request_id,
        prepare_request_status="prepared",
        prepared_action_id=prepared_action_id,
        confirm_queue_status=confirm_queue_status,
        authority_stage="confirm_pending",
        missing_requirements=[
            "Human confirmation required: POST /mso/prepared-actions/confirm.",
        ],
        error=None,
    )
