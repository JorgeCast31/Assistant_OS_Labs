"""
Prepare Contract — Plan → PrepareRequest → PreparedAction (review-only).

This module implements the formal prepare contract from Sprint #229 design.

This module is intentionally NOT:
  - executing anything
  - calling Runner
  - emitting tokens (CapabilityToken, etc.)
  - creating AuthorityArtifact from UI
  - calling Machine Operator
  - using policy_decision_ref with auto-ref pattern
  - setting execution_allowed = True

This IS:
  - a prepare-layer function that validates Plan state + ACK
  - evaluates policy/governance/capability before enqueue
  - creates PrepareRequest (audit artifact) in SQLite
  - creates PreparedAction (ConfirmablePreparedAction) review-only
  - enqueues PreparedAction into the confirm queue
  - always returns execution_allowed=False, used_execution=False, runner_reachable_from_ui=False

Invariants (enforced throughout, not negotiable)
------------------------------------------------
  execution_allowed         = False  (always)
  used_execution            = False  (always)
  runner_reachable_from_ui  = False  (always)

D-21: PrepareRequest persisted to SQLite (audit artifact, survives restart).
D-22: Duplicate PrepareRequest for same plan_id → DuplicatePrepareRequest (409).

Sprint: #230 — Prepare Contract Implementation, no execution.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from ..contracts import EXECUTION_MODE_CONFIRM, EXECUTION_MODE_BLOCKED, EXECUTION_MODE_AUTO
from ..contracts import (
    ACTION_WORK_QUERY, ACTION_WORK_CREATE, ACTION_WORK_UPDATE, ACTION_WORK_UPDATE_BULK,
    ACTION_WORK_DELETE, ACTION_WORK_CREATE_TEST, ACTION_WORK_DELETE_TEST, ACTION_WORK_TEST_RESET,
    ACTION_FIN_EXPENSE, ACTION_FIN_BATCH, ACTION_FIN_PLAN, ACTION_FIN_COMMIT, ACTION_FIN_CONFIRM,
    ACTION_FIN_CHAPERON,
    ACTION_CODE_EXPLAIN, ACTION_CODE_REVIEW, ACTION_CODE_FIX, ACTION_CODE_CREATE,
    ACTION_HOST_LIST_DIRECTORY, ACTION_HOST_READ_TEXT_FILE, ACTION_HOST_WRITE_TEXT_FILE,
    ACTION_HOST_APPEND_TEXT_FILE, ACTION_HOST_OPEN_URL, ACTION_HOST_OPEN_APP,
    ACTION_HOST_OPEN_FILE, ACTION_HOST_OPEN_DIRECTORY, ACTION_HOST_CREATE_DIRECTORY,
    ACTION_HOST_CLOSE_PID,
    ACTION_BASIC_COGNITIVE_EXECUTION,
)
from .capability_registry import check_capability
from .confirmable_prepared_action import ConfirmablePreparedAction
from .draft_store import get_plan
from .execution_proposal import REQUIRED_AUTHORITY_CHAIN
from .governance_engine import evaluate_governance
from .plan_ack import (
    PlanMSOAck, PlanAckNotFound, get_ack_for_plan, get_prepare_store_path,
    _PREPARE_STORE_ENV,  # noqa: F401 — re-exported for test isolation
)
from .plan_model import (
    PlanNotFound, OperatorSeatMismatch, PlanRecord,
)
from .prepared_action_queue import enqueue_confirmable_prepared_action
from .system_state import build_system_state_snapshot


# ---------------------------------------------------------------------------
# Capability scope mapping table
#
# Maps free-form target_action strings → (capability_action, capability_domain).
# Conservative: only unambiguous mappings. Unmapped = fail closed.
# ---------------------------------------------------------------------------

_TARGET_ACTION_MAP: dict[str, tuple[str, str]] = {
    # Canonical ACTION_* values (uppercase)
    ACTION_WORK_QUERY:          (ACTION_WORK_QUERY, "WORK"),
    ACTION_WORK_CREATE:         (ACTION_WORK_CREATE, "WORK"),
    ACTION_WORK_UPDATE:         (ACTION_WORK_UPDATE, "WORK"),
    ACTION_WORK_UPDATE_BULK:    (ACTION_WORK_UPDATE_BULK, "WORK"),
    ACTION_WORK_DELETE:         (ACTION_WORK_DELETE, "WORK"),
    ACTION_WORK_CREATE_TEST:    (ACTION_WORK_CREATE_TEST, "WORK"),
    ACTION_WORK_DELETE_TEST:    (ACTION_WORK_DELETE_TEST, "WORK"),
    ACTION_WORK_TEST_RESET:     (ACTION_WORK_TEST_RESET, "WORK"),
    ACTION_FIN_EXPENSE:         (ACTION_FIN_EXPENSE, "FIN"),
    ACTION_FIN_BATCH:           (ACTION_FIN_BATCH, "FIN"),
    ACTION_FIN_PLAN:            (ACTION_FIN_PLAN, "FIN"),
    ACTION_FIN_COMMIT:          (ACTION_FIN_COMMIT, "FIN"),
    ACTION_FIN_CONFIRM:         (ACTION_FIN_CONFIRM, "FIN"),
    ACTION_FIN_CHAPERON:        (ACTION_FIN_CHAPERON, "FIN"),
    ACTION_CODE_EXPLAIN:        (ACTION_CODE_EXPLAIN, "CODE"),
    ACTION_CODE_REVIEW:         (ACTION_CODE_REVIEW, "CODE"),
    ACTION_CODE_FIX:            (ACTION_CODE_FIX, "CODE"),
    ACTION_CODE_CREATE:         (ACTION_CODE_CREATE, "CODE"),
    ACTION_HOST_LIST_DIRECTORY: (ACTION_HOST_LIST_DIRECTORY, "HOST"),
    ACTION_HOST_READ_TEXT_FILE: (ACTION_HOST_READ_TEXT_FILE, "HOST"),
    ACTION_HOST_WRITE_TEXT_FILE: (ACTION_HOST_WRITE_TEXT_FILE, "HOST"),
    ACTION_HOST_APPEND_TEXT_FILE: (ACTION_HOST_APPEND_TEXT_FILE, "HOST"),
    ACTION_HOST_OPEN_URL:       (ACTION_HOST_OPEN_URL, "HOST"),
    ACTION_HOST_OPEN_APP:       (ACTION_HOST_OPEN_APP, "HOST"),
    ACTION_HOST_OPEN_FILE:      (ACTION_HOST_OPEN_FILE, "HOST"),
    ACTION_HOST_OPEN_DIRECTORY: (ACTION_HOST_OPEN_DIRECTORY, "HOST"),
    ACTION_HOST_CREATE_DIRECTORY: (ACTION_HOST_CREATE_DIRECTORY, "HOST"),
    ACTION_HOST_CLOSE_PID:      (ACTION_HOST_CLOSE_PID, "HOST"),
    ACTION_BASIC_COGNITIVE_EXECUTION: (ACTION_BASIC_COGNITIVE_EXECUTION, "COGNITIVE"),
    # Lowercase snake_case aliases
    "work_query":            (ACTION_WORK_QUERY, "WORK"),
    "work_create":           (ACTION_WORK_CREATE, "WORK"),
    "work_update":           (ACTION_WORK_UPDATE, "WORK"),
    "work_update_bulk":      (ACTION_WORK_UPDATE_BULK, "WORK"),
    "work_delete":           (ACTION_WORK_DELETE, "WORK"),
    "work_create_test":      (ACTION_WORK_CREATE_TEST, "WORK"),
    "work_delete_test":      (ACTION_WORK_DELETE_TEST, "WORK"),
    "work_test_reset":       (ACTION_WORK_TEST_RESET, "WORK"),
    "fin_expense":           (ACTION_FIN_EXPENSE, "FIN"),
    "fin_batch":             (ACTION_FIN_BATCH, "FIN"),
    "fin_plan":              (ACTION_FIN_PLAN, "FIN"),
    "fin_commit":            (ACTION_FIN_COMMIT, "FIN"),
    "fin_confirm":           (ACTION_FIN_CONFIRM, "FIN"),
    "fin_chaperon":          (ACTION_FIN_CHAPERON, "FIN"),
    "code_explain":          (ACTION_CODE_EXPLAIN, "CODE"),
    "code_review":           (ACTION_CODE_REVIEW, "CODE"),
    "code_fix":              (ACTION_CODE_FIX, "CODE"),
    "code_create":           (ACTION_CODE_CREATE, "CODE"),
    "host_list_directory":   (ACTION_HOST_LIST_DIRECTORY, "HOST"),
    "host_read_text_file":   (ACTION_HOST_READ_TEXT_FILE, "HOST"),
    "host_write_text_file":  (ACTION_HOST_WRITE_TEXT_FILE, "HOST"),
    "host_append_text_file": (ACTION_HOST_APPEND_TEXT_FILE, "HOST"),
    "host_open_url":         (ACTION_HOST_OPEN_URL, "HOST"),
    "host_open_app":         (ACTION_HOST_OPEN_APP, "HOST"),
    "host_open_file":        (ACTION_HOST_OPEN_FILE, "HOST"),
    "host_open_directory":   (ACTION_HOST_OPEN_DIRECTORY, "HOST"),
    "host_create_directory": (ACTION_HOST_CREATE_DIRECTORY, "HOST"),
    "host_close_pid":        (ACTION_HOST_CLOSE_PID, "HOST"),
    "basic_cognitive_execution": (ACTION_BASIC_COGNITIVE_EXECUTION, "COGNITIVE"),
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class UnmappableTargetAction(ValueError):
    """A target_action string could not be mapped to a known capability."""


class DuplicatePrepareRequest(ValueError):
    """A PrepareRequest for this plan_id already exists. One per plan in ALPHA 1 (D-22)."""


class PrepareContractError(RuntimeError):
    """Unexpected error during prepare contract evaluation."""


# ---------------------------------------------------------------------------
# PrepareRequest model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrepareRequest:
    """Audit record of a prepare operation. Persisted to SQLite.

    Not an authorization. Not an execution artifact.
    Carries correlation_id = plan_id (D-17).
    """

    prepare_request_id: str
    plan_id: str
    operator_seat: str
    requested_by: str
    requested_at: str
    source: str                           # always "prepare_contract"
    intent_summary: str
    target_actions: tuple[str, ...]
    risk_level: Optional[str]
    capability_scope_candidate: tuple[str, ...]
    correlation_id: str                   # = plan_id (D-17)
    prepare_status: str                   # prepared | rejected | requires_review
    policy_outcome: Optional[str]
    governance_outcome: Optional[str]
    fail_closed_reason: Optional[str]
    notes: Optional[str]

    # Safety invariants — NEVER change these defaults
    execution_allowed: bool = False
    used_execution: bool = False
    runner_reachable_from_ui: bool = False

    def __post_init__(self) -> None:
        if self.execution_allowed is not False:
            raise ValueError("PrepareRequest.execution_allowed must always be False.")
        if self.used_execution is not False:
            raise ValueError("PrepareRequest.used_execution must always be False.")
        if self.runner_reachable_from_ui is not False:
            raise ValueError("PrepareRequest.runner_reachable_from_ui must always be False.")

    def to_dict(self) -> dict:
        return {
            "prepare_request_id": self.prepare_request_id,
            "plan_id": self.plan_id,
            "operator_seat": self.operator_seat,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "source": self.source,
            "intent_summary": self.intent_summary,
            "target_actions": list(self.target_actions),
            "risk_level": self.risk_level,
            "capability_scope_candidate": list(self.capability_scope_candidate),
            "correlation_id": self.correlation_id,
            "prepare_status": self.prepare_status,
            "policy_outcome": self.policy_outcome,
            "governance_outcome": self.governance_outcome,
            "fail_closed_reason": self.fail_closed_reason,
            "notes": self.notes,
            "execution_allowed": self.execution_allowed,
            "used_execution": self.used_execution,
            "runner_reachable_from_ui": self.runner_reachable_from_ui,
        }


# ---------------------------------------------------------------------------
# PrepareContractResponse
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrepareContractResponse:
    """Response from prepare_plan(). Always carries safety invariants."""

    ok: bool
    source: str                        # always "prepare_contract"
    plan_id: str
    prepare_request_id: Optional[str]
    prepared_action_id: Optional[str]
    correlation_id: Optional[str]
    prepare_status: str                # prepared | rejected | requires_review
    fail_closed_reason: Optional[str]

    # Safety invariants — NEVER change these defaults
    execution_allowed: bool = False
    used_execution: bool = False
    runner_reachable_from_ui: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "source": self.source,
            "plan_id": self.plan_id,
            "prepare_request_id": self.prepare_request_id,
            "prepared_action_id": self.prepared_action_id,
            "correlation_id": self.correlation_id,
            "prepare_status": self.prepare_status,
            "fail_closed_reason": self.fail_closed_reason,
            "execution_allowed": self.execution_allowed,
            "used_execution": self.used_execution,
            "runner_reachable_from_ui": self.runner_reachable_from_ui,
        }


# ---------------------------------------------------------------------------
# SQLite store for PrepareRequests
# ---------------------------------------------------------------------------

_lock = threading.RLock()


def _get_prepare_conn() -> sqlite3.Connection:
    db_path = get_prepare_store_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_prepare_schema(conn)
    return conn


def _init_prepare_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS prepare_requests (
            prepare_request_id      TEXT PRIMARY KEY,
            plan_id                 TEXT NOT NULL UNIQUE,
            operator_seat           TEXT NOT NULL,
            requested_by            TEXT NOT NULL,
            requested_at            TEXT NOT NULL,
            source                  TEXT NOT NULL DEFAULT 'prepare_contract',
            intent_summary          TEXT NOT NULL,
            target_actions_json     TEXT NOT NULL DEFAULT '[]',
            risk_level              TEXT,
            capability_scope_json   TEXT NOT NULL DEFAULT '[]',
            correlation_id          TEXT NOT NULL,
            prepare_status          TEXT NOT NULL,
            policy_outcome          TEXT,
            governance_outcome      TEXT,
            fail_closed_reason      TEXT,
            notes                   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_prepare_requests_plan_id
            ON prepare_requests (plan_id);
    """)
    conn.commit()


def _row_to_prepare_request(row: sqlite3.Row) -> PrepareRequest:
    return PrepareRequest(
        prepare_request_id=row["prepare_request_id"],
        plan_id=row["plan_id"],
        operator_seat=row["operator_seat"],
        requested_by=row["requested_by"],
        requested_at=row["requested_at"],
        source=row["source"],
        intent_summary=row["intent_summary"],
        target_actions=tuple(json.loads(row["target_actions_json"] or "[]")),
        risk_level=row["risk_level"],
        capability_scope_candidate=tuple(json.loads(row["capability_scope_json"] or "[]")),
        correlation_id=row["correlation_id"],
        prepare_status=row["prepare_status"],
        policy_outcome=row["policy_outcome"],
        governance_outcome=row["governance_outcome"],
        fail_closed_reason=row["fail_closed_reason"],
        notes=row["notes"],
    )


def _persist_prepare_request(req: PrepareRequest) -> None:
    with _lock:
        conn = _get_prepare_conn()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO prepare_requests
                        (prepare_request_id, plan_id, operator_seat, requested_by,
                         requested_at, source, intent_summary, target_actions_json,
                         risk_level, capability_scope_json, correlation_id,
                         prepare_status, policy_outcome, governance_outcome,
                         fail_closed_reason, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        req.prepare_request_id,
                        req.plan_id,
                        req.operator_seat,
                        req.requested_by,
                        req.requested_at,
                        req.source,
                        req.intent_summary,
                        json.dumps(list(req.target_actions)),
                        req.risk_level,
                        json.dumps(list(req.capability_scope_candidate)),
                        req.correlation_id,
                        req.prepare_status,
                        req.policy_outcome,
                        req.governance_outcome,
                        req.fail_closed_reason,
                        req.notes,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper() or "unique" in str(exc):
                raise DuplicatePrepareRequest(
                    f"A PrepareRequest for plan_id='{req.plan_id}' already exists. "
                    "One prepare per plan in ALPHA 1 (D-22). "
                    "Create a new Plan to retry prepare."
                ) from exc
            raise


def get_prepare_request(prepare_request_id: str) -> PrepareRequest:
    """Retrieve a PrepareRequest by ID. Raises KeyError if not found."""
    with _lock:
        conn = _get_prepare_conn()
        row = conn.execute(
            "SELECT * FROM prepare_requests WHERE prepare_request_id = ?",
            (prepare_request_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"PrepareRequest not found: {prepare_request_id}")
    return _row_to_prepare_request(row)


def get_prepare_request_for_plan(plan_id: str) -> Optional[PrepareRequest]:
    """Return existing PrepareRequest for a plan, or None."""
    with _lock:
        conn = _get_prepare_conn()
        row = conn.execute(
            "SELECT * FROM prepare_requests WHERE plan_id = ?", (plan_id,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_prepare_request(row)


# ---------------------------------------------------------------------------
# Capability scope mapper
# ---------------------------------------------------------------------------

def map_target_actions_to_capability_scope(
    target_actions: list[str],
) -> list[tuple[str, str]]:
    """Map free-form target_action strings to (capability_action, domain) pairs.

    Conservative: any unmappable string → raises UnmappableTargetAction.
    Empty list → raises UnmappableTargetAction.

    Returns list of (action, domain) pairs in the same order as input.
    """
    if not target_actions:
        raise UnmappableTargetAction(
            "empty_target_actions: cannot map empty action list to capability scope. "
            "At least one target_action is required."
        )
    result = []
    for raw in target_actions:
        normalized = raw.strip()
        mapping = _TARGET_ACTION_MAP.get(normalized)
        if mapping is None:
            raise UnmappableTargetAction(
                f"unmappable_target_action: '{normalized}' is not in the prepare-layer "
                "capability mapping table. "
                "Fail-closed: cannot determine capability scope for unknown action. "
                "Add explicit mapping or use a known action name."
            )
        result.append(mapping)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_prepare_request_id() -> str:
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    uid = uuid4().hex[:8]
    return f"prep_req_{ts_ms}_{uid}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _should_evaluate_governance(risk_level: Optional[str], capability_scope: list[tuple[str, str]]) -> bool:
    """Return True if governance evaluation is warranted."""
    if risk_level in ("high", "critical"):
        return True
    # Any confirm_only capability warrants governance check
    for action, domain in capability_scope:
        cap = check_capability(action, domain)
        if cap.mode == "confirm_only":
            return True
    return False


def _reject_response(plan_id: str, prepare_request_id: Optional[str], reason: str) -> PrepareContractResponse:
    return PrepareContractResponse(
        ok=False,
        source="prepare_contract",
        plan_id=plan_id,
        prepare_request_id=prepare_request_id,
        prepared_action_id=None,
        correlation_id=plan_id,
        prepare_status="rejected",
        fail_closed_reason=reason,
        execution_allowed=False,
        used_execution=False,
        runner_reachable_from_ui=False,
    )


# ---------------------------------------------------------------------------
# Core contract function
# ---------------------------------------------------------------------------

def prepare_plan(
    *,
    plan_id: str,
    operator_seat: str,
    requested_by: str,
    confirmation_acknowledged: bool,
    notes: Optional[str] = None,
) -> PrepareContractResponse:
    """Prepare a Plan for the confirm queue.

    Steps:
    1. Validate confirmation_acknowledged
    2. Load Plan from Draft Store
    3. Validate operator_seat match
    4. Require Plan.state == mso_review
    5. Require valid PlanMSOAck (ack_status=acknowledged)
    6. Reject duplicate PrepareRequest
    7. Map target_actions → capability scope
    8. Evaluate PolicyDecision (check_capability) for each capability
    9. Evaluate GovernanceDecision if warranted
    10. Persist PrepareRequest
    11. Produce ConfirmablePreparedAction
    12. Enqueue into confirm queue
    13. Return PrepareContractResponse

    Returns PrepareContractResponse with ok=False on any failure.
    Never raises. All failures are fail-closed via response.

    Invariants: execution_allowed=False, used_execution=False,
    runner_reachable_from_ui=False — always.
    """
    # Step 1: confirmation required
    if not confirmation_acknowledged:
        return _reject_response(
            plan_id, None,
            "confirmation_required: operator must explicitly acknowledge before prepare. "
            "Set confirmation_acknowledged=True."
        )

    # Step 2: load Plan
    try:
        plan = get_plan(plan_id, operator_seat)
    except PlanNotFound:
        return _reject_response(
            plan_id, None,
            f"plan_not_found: no plan with plan_id='{plan_id}' exists in the draft store."
        )
    except OperatorSeatMismatch:
        return _reject_response(
            plan_id, None,
            f"operator_seat_mismatch: plan '{plan_id}' does not belong to seat '{operator_seat}'."
        )

    # Step 3: validate operator seat (already handled above via get_plan OperatorSeatMismatch)

    # Step 4: require mso_review state
    if plan.state != "mso_review":
        return _reject_response(
            plan_id, None,
            f"plan_not_in_mso_review: current_state={plan.state!r}. "
            "Prepare requires Plan.state == 'mso_review'. "
            "Transition the plan to mso_review before calling prepare."
        )

    # Step 5: require valid ACK
    try:
        ack = get_ack_for_plan(plan_id, operator_seat)
    except PlanAckNotFound:
        return _reject_response(
            plan_id, None,
            f"mso_ack_not_found: plan_id='{plan_id}' has no PlanMSOAck. "
            "POST /mso/plans/{plan_id}/ack (ack_status=acknowledged) before calling prepare."
        )

    if ack.ack_status == "rejected_for_review":
        return _reject_response(
            plan_id, None,
            f"mso_ack_rejected: PlanMSOAck for plan_id='{plan_id}' has ack_status=rejected_for_review. "
            "MSO has flagged this plan for additional review. "
            "Create a new Plan to retry."
        )

    # Step 6: reject duplicate PrepareRequest
    existing = get_prepare_request_for_plan(plan_id)
    if existing is not None:
        return _reject_response(
            plan_id, existing.prepare_request_id,
            f"duplicate_prepare_request: plan_id='{plan_id}' already has a PrepareRequest "
            f"(prepare_request_id='{existing.prepare_request_id}', "
            f"status='{existing.prepare_status}'). "
            "One prepare per plan in ALPHA 1 (D-22). Create a new Plan to retry."
        )

    # Step 7: map target_actions → capability scope
    try:
        capability_scope = map_target_actions_to_capability_scope(list(plan.target_actions))
    except UnmappableTargetAction as exc:
        return _reject_response(plan_id, None, str(exc))

    # Step 8: evaluate PolicyDecision
    denied_capabilities = []
    for action, domain in capability_scope:
        cap = check_capability(action, domain)
        if not cap.allowed:
            denied_capabilities.append((action, domain, cap.deny_reason or cap.notes or "denied by registry"))

    if denied_capabilities:
        reasons = "; ".join(
            f"capability '{a}' in domain '{d}' is denied — {r}"
            for a, d, r in denied_capabilities
        )
        policy_outcome = "denied"
        prepare_request_id = _generate_prepare_request_id()
        req = PrepareRequest(
            prepare_request_id=prepare_request_id,
            plan_id=plan_id,
            operator_seat=operator_seat,
            requested_by=requested_by,
            requested_at=_now_iso(),
            source="prepare_contract",
            intent_summary=plan.intent_summary,
            target_actions=plan.target_actions,
            risk_level=plan.risk_level,
            capability_scope_candidate=tuple(a for a, _ in capability_scope),
            correlation_id=plan_id,
            prepare_status="rejected",
            policy_outcome="denied",
            governance_outcome=None,
            fail_closed_reason=f"policy_denied: {reasons}",
            notes=notes,
        )
        try:
            _persist_prepare_request(req)
        except DuplicatePrepareRequest as exc:
            return _reject_response(plan_id, None, str(exc))
        return _reject_response(plan_id, prepare_request_id, f"policy_denied: {reasons}")

    policy_outcome = "approved"

    # Step 9: evaluate GovernanceDecision if warranted
    governance_outcome: str
    governance_reason: Optional[str] = None

    if _should_evaluate_governance(plan.risk_level, capability_scope):
        now = _now_iso()
        system_state = build_system_state_snapshot()

        from .contracts import RiskEvaluation, GovernanceReason, RiskLevel
        risk = RiskEvaluation(
            level=plan.risk_level or "medium",
            reasons=[],
            base_risk=plan.risk_level or "medium",
            operational_mode=system_state.operational_mode if system_state else "NORMAL",
        )

        # Evaluate governance for the most constrained capability in scope
        # (the one requiring the most governance scrutiny)
        primary_action, primary_domain = capability_scope[0]
        from ..contracts import EXECUTION_MODE_CONFIRM
        gov_decision = evaluate_governance(
            action=primary_action,
            domain=primary_domain,
            base_execution_mode=EXECUTION_MODE_CONFIRM,
            risk=risk,
            created_at=now,
            system_state=system_state,
        )

        if gov_decision.action == "BLOCK":
            justification = gov_decision.justification or "Governance blocked prepare."
            prepare_request_id = _generate_prepare_request_id()
            req = PrepareRequest(
                prepare_request_id=prepare_request_id,
                plan_id=plan_id,
                operator_seat=operator_seat,
                requested_by=requested_by,
                requested_at=_now_iso(),
                source="prepare_contract",
                intent_summary=plan.intent_summary,
                target_actions=plan.target_actions,
                risk_level=plan.risk_level,
                capability_scope_candidate=tuple(a for a, _ in capability_scope),
                correlation_id=plan_id,
                prepare_status="rejected",
                policy_outcome=policy_outcome,
                governance_outcome="denied",
                fail_closed_reason=f"governance_blocked: {justification}",
                notes=notes,
            )
            try:
                _persist_prepare_request(req)
            except DuplicatePrepareRequest as exc:
                return _reject_response(plan_id, None, str(exc))
            return _reject_response(plan_id, prepare_request_id, f"governance_blocked: {justification}")

        governance_outcome = "approved"
    else:
        governance_outcome = "not_required"
        governance_reason = "No governed operations in capability scope at this risk level."

    # Step 10: persist PrepareRequest (success path)
    prepare_request_id = _generate_prepare_request_id()
    req = PrepareRequest(
        prepare_request_id=prepare_request_id,
        plan_id=plan_id,
        operator_seat=operator_seat,
        requested_by=requested_by,
        requested_at=_now_iso(),
        source="prepare_contract",
        intent_summary=plan.intent_summary,
        target_actions=plan.target_actions,
        risk_level=plan.risk_level,
        capability_scope_candidate=tuple(a for a, _ in capability_scope),
        correlation_id=plan_id,
        prepare_status="prepared",
        policy_outcome=policy_outcome,
        governance_outcome=governance_outcome,
        fail_closed_reason=None,
        notes=notes,
    )
    try:
        _persist_prepare_request(req)
    except DuplicatePrepareRequest as exc:
        return _reject_response(plan_id, None, str(exc))

    # Step 11: produce ConfirmablePreparedAction (review-only)
    primary_action, primary_domain = capability_scope[0]
    prepared_action = ConfirmablePreparedAction(
        preparation_id=prepare_request_id,   # PrepareRequest serves as preparation ref
        proposal_id="",                       # No MSOExecutionProposal in Plan path
        user_intent=plan.intent_summary,
        domain=primary_domain,
        requested_action=primary_action,
        capability_name=primary_action,
        capability_scope=tuple(a for a, _ in capability_scope),
        plan_steps=plan.target_actions,       # informational only
        risk_level=plan.risk_level or "unknown",
        pending_authority_steps=REQUIRED_AUTHORITY_CHAIN,
        delegated_seat_ref=operator_seat,
        provider_name=None,
        model_name=None,
        action_type="plan_prepare",
        status="waiting_for_human_confirmation",
        execution_allowed=False,
        used_execution=False,
        cognitive_only=True,
        confirmed=False,
        notes=(
            f"Prepared from Plan plan_id='{plan_id}' via prepare contract. "
            f"correlation_id='{plan_id}'. "
            f"prepare_request_id='{prepare_request_id}'. "
            "Waiting for explicit human confirmation before any execution authority can proceed. "
            "This artifact does not execute, does not issue tokens, "
            "and does not authorize any action."
        ),
    )

    # Step 12: enqueue into confirm queue
    queue_entry = enqueue_confirmable_prepared_action(prepared_action)

    # Step 13: return success response
    return PrepareContractResponse(
        ok=True,
        source="prepare_contract",
        plan_id=plan_id,
        prepare_request_id=prepare_request_id,
        prepared_action_id=prepared_action.action_id,
        correlation_id=plan_id,
        prepare_status="prepared",
        fail_closed_reason=None,
        execution_allowed=False,
        used_execution=False,
        runner_reachable_from_ui=False,
    )
