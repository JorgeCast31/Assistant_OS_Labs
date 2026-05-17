"""MSO Police Readiness Diagnostic — read-only, MSO-internal.

Evaluates whether a prepared action has reached the Police/authority boundary,
and if not, exactly what is missing. This is NOT a Police call, NOT execution,
NOT authority. It is a readiness report built only from MSO-owned stores.

Authority chain awareness
-------------------------
PreparedAction → HumanConfirmation → PolicyDecisionDraft → AuthorityBindingDraft
→ [CapabilityToken] → [OperationBinding] → [AuthorizedPlan] → [PoliceGate] → [Runner]

This module reads from chain stages 1–4 only. Stages 5+ (CapabilityToken and
beyond) are not yet implemented, so all downstream presence flags are always False.

Forbidden imports
-----------------
This module MUST NOT import from:
  - assistant_os.police.*
  - assistant_os.capabilities.*
  - assistant_os.sandbox.*

It MUST NOT call:
  - token_issuer.issue_token()
  - PoliceGate.check()
  - RunnerAPI.execute()
  - Any audit sink write
  - Any productive authority primitive

Invariants (enforced by __post_init__)
--------------------------------------
  execution_allowed      = False  (always)
  can_execute_now        = False  (always)
  used_execution         = False  (always)
  police_check_performed = False  (always — diagnostic only)
  runner_check_performed = False  (always — diagnostic only)
  capability_token_present      = False  (not yet implemented)
  operation_binding_present     = False  (not yet implemented)
  authorized_plan_present       = False  (not yet implemented)
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from .prepared_action_queue import get_confirmable_action_queue_entry
from .human_confirmation import get_human_confirmation
from .policy_review import get_mso_policy_review
from .authority_binding import get_mso_authority_binding
from .system_state import get_operational_mode_override


def _new_id() -> str:
    return f"prr-{uuid4()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# MSOPoliceReadinessReport
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class MSOPoliceReadinessReport:
    """Read-only diagnostic snapshot of authority chain readiness for a prepared action.

    Tells the operator exactly how far the MSO authority chain has progressed
    and what artifacts are still missing before the Police boundary could be
    approached (not that it will be — execution remains closed).

    Invariants: execution_allowed, can_execute_now, used_execution,
    police_check_performed, runner_check_performed are always False.
    Downstream artifact presence flags (capability_token_present,
    operation_binding_present, authorized_plan_present) are always False
    because those artifacts are not yet implemented.
    """

    # Identity
    report_id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)

    # Target
    entry_id: str = ""
    action_id: str = ""

    # Copied from prepared action (if present)
    domain: str = "UNKNOWN"
    requested_action: str = ""

    # Chain stage reached
    current_chain_stage: str = ""

    # Stage presence flags
    prepared_action_present: bool = False
    human_confirmation_status: str = "none"  # "none" | "pending" | "human_confirmed" | "human_rejected"
    human_confirmation_satisfied: bool = False
    policy_review_present: bool = False
    policy_outcome: str = ""  # "" | "approved" | "approved_confirm_only" | "denied"
    authority_binding_draft_present: bool = False

    # Future stages — always False (not yet implemented)
    capability_token_present: bool = False
    operation_binding_present: bool = False
    authorized_plan_present: bool = False

    # Police/Runner — always False (diagnostic does not cross the Police boundary)
    police_check_performed: bool = False
    runner_check_performed: bool = False

    # Readiness verdict
    readiness_status: str = ""
    missing_requirements: tuple[str, ...] = field(default_factory=tuple)
    blocking_reasons: tuple[str, ...] = field(default_factory=tuple)
    next_safe_step: str = ""

    # Safety invariants — NEVER change these defaults
    execution_allowed: bool = False
    can_execute_now: bool = False
    used_execution: bool = False

    # Artifact type
    artifact_type: str = "mso_police_readiness_report"

    def __post_init__(self) -> None:
        if self.execution_allowed is not False:
            raise ValueError(
                "MSOPoliceReadinessReport.execution_allowed must always be False. "
                "A readiness diagnostic does not authorize execution."
            )
        if self.can_execute_now is not False:
            raise ValueError(
                "MSOPoliceReadinessReport.can_execute_now must always be False. "
                "A readiness diagnostic does not open any execution path."
            )
        if self.used_execution is not False:
            raise ValueError(
                "MSOPoliceReadinessReport.used_execution must always be False. "
                "No execution was performed to produce this diagnostic."
            )
        if self.police_check_performed is not False:
            raise ValueError(
                "MSOPoliceReadinessReport.police_check_performed must always be False. "
                "This diagnostic does not cross the Police boundary."
            )
        if self.runner_check_performed is not False:
            raise ValueError(
                "MSOPoliceReadinessReport.runner_check_performed must always be False. "
                "This diagnostic does not invoke the runner."
            )
        if self.capability_token_present is not False:
            raise ValueError(
                "MSOPoliceReadinessReport.capability_token_present must be False. "
                "CapabilityToken issuance is not implemented in this sprint."
            )
        if self.operation_binding_present is not False:
            raise ValueError(
                "MSOPoliceReadinessReport.operation_binding_present must be False. "
                "OperationBinding is not implemented in this sprint."
            )
        if self.authorized_plan_present is not False:
            raise ValueError(
                "MSOPoliceReadinessReport.authorized_plan_present must be False. "
                "AuthorizedPlan is not implemented in this sprint."
            )

    def to_dict(self) -> dict:
        """Serialize for surface/API transport. Never includes secrets."""
        return {
            "artifact_type": self.artifact_type,
            "report_id": self.report_id,
            "created_at": self.created_at.isoformat(),
            "entry_id": self.entry_id,
            "action_id": self.action_id,
            "domain": self.domain,
            "requested_action": self.requested_action,
            "current_chain_stage": self.current_chain_stage,
            "prepared_action_present": self.prepared_action_present,
            "human_confirmation_status": self.human_confirmation_status,
            "human_confirmation_satisfied": self.human_confirmation_satisfied,
            "policy_review_present": self.policy_review_present,
            "policy_outcome": self.policy_outcome,
            "authority_binding_draft_present": self.authority_binding_draft_present,
            "capability_token_present": self.capability_token_present,
            "operation_binding_present": self.operation_binding_present,
            "authorized_plan_present": self.authorized_plan_present,
            "police_check_performed": self.police_check_performed,
            "runner_check_performed": self.runner_check_performed,
            "readiness_status": self.readiness_status,
            "missing_requirements": list(self.missing_requirements),
            "blocking_reasons": list(self.blocking_reasons),
            "next_safe_step": self.next_safe_step,
            "execution_allowed": self.execution_allowed,
            "can_execute_now": self.can_execute_now,
            "used_execution": self.used_execution,
        }


# ---------------------------------------------------------------------------
# In-memory report store
# ---------------------------------------------------------------------------

_reports: list[MSOPoliceReadinessReport] = []
_lock = threading.Lock()


def _store_report(report: MSOPoliceReadinessReport) -> None:
    with _lock:
        _reports.append(report)


def list_recent_police_readiness_reports(limit: int = 50) -> list[MSOPoliceReadinessReport]:
    """Return the most recent readiness reports, newest-first. Read-only."""
    with _lock:
        snapshot = list(_reports)
    snapshot.sort(key=lambda r: r.created_at, reverse=True)
    return snapshot[:limit]


def clear_police_readiness_reports_for_tests() -> None:
    """Empty the report store. FOR TESTS ONLY."""
    with _lock:
        _reports.clear()


# ---------------------------------------------------------------------------
# Core diagnostic function
# ---------------------------------------------------------------------------

def evaluate_police_readiness_for_prepared_action(
    entry_id: str,
    action_id: str,
) -> MSOPoliceReadinessReport:
    """Read-only diagnostic: assess how far the authority chain has progressed.

    Reads from MSO-owned stores only. Does not write to any authority store,
    does not call Police, does not issue tokens, does not invoke runner.

    Each call produces a new snapshot report (idempotent over authority state:
    repeated calls return the same conclusion as long as the underlying stores
    have not changed).

    Parameters
    ----------
    entry_id : str
        Queue entry ID to evaluate.
    action_id : str
        Prepared action ID expected for this entry.

    Returns
    -------
    MSOPoliceReadinessReport
        Frozen read-only diagnostic snapshot.
        execution_allowed, can_execute_now, used_execution are always False.
    """
    # --- 1. Governance check (FROZEN blocks everything) ---
    mode_override, mode_reason = get_operational_mode_override()
    if mode_override == "FROZEN":
        report = MSOPoliceReadinessReport(
            entry_id=entry_id,
            action_id=action_id,
            current_chain_stage="governance_check",
            prepared_action_present=False,
            readiness_status="blocked_by_governance",
            blocking_reasons=(
                f"System is FROZEN: {mode_reason or 'governance override active'}. "
                "No authority chain progress is possible while the system is frozen.",
            ),
            missing_requirements=(),
            next_safe_step=(
                "Wait for the system FROZEN state to be lifted by the operator "
                "before evaluating police readiness."
            ),
            execution_allowed=False,
            can_execute_now=False,
            used_execution=False,
        )
        _store_report(report)
        return report

    # --- 2. Lookup prepared action ---
    entry = get_confirmable_action_queue_entry(entry_id)
    if entry is None:
        report = MSOPoliceReadinessReport(
            entry_id=entry_id,
            action_id=action_id,
            current_chain_stage="prepared_action",
            prepared_action_present=False,
            readiness_status="missing_prepared_action",
            missing_requirements=("prepared_action",),
            blocking_reasons=(
                f"No prepared action found in queue for entry_id={entry_id!r}.",
            ),
            next_safe_step=(
                "Enqueue a ConfirmablePreparedAction via the MSO authority preparation "
                "chain before evaluating police readiness."
            ),
            execution_allowed=False,
            can_execute_now=False,
            used_execution=False,
        )
        _store_report(report)
        return report

    domain = entry.domain
    requested_action = entry.requested_action

    # --- 3. Human confirmation ---
    confirmation = get_human_confirmation(entry_id)
    if confirmation is None:
        report = MSOPoliceReadinessReport(
            entry_id=entry_id,
            action_id=action_id,
            domain=domain,
            requested_action=requested_action,
            current_chain_stage="human_confirmation",
            prepared_action_present=True,
            human_confirmation_status="pending",
            human_confirmation_satisfied=False,
            readiness_status="awaiting_human_confirmation",
            missing_requirements=("human_confirmation",),
            blocking_reasons=(
                "No human confirmation record found for this prepared action.",
            ),
            next_safe_step=(
                "POST /mso/prepared-actions/confirm with confirmed=true to record "
                "human operator confirmation."
            ),
            execution_allowed=False,
            can_execute_now=False,
            used_execution=False,
        )
        _store_report(report)
        return report

    hc_status = "human_confirmed" if confirmation.confirmed else "human_rejected"

    if not confirmation.confirmed:
        report = MSOPoliceReadinessReport(
            entry_id=entry_id,
            action_id=action_id,
            domain=domain,
            requested_action=requested_action,
            current_chain_stage="human_confirmation",
            prepared_action_present=True,
            human_confirmation_status=hc_status,
            human_confirmation_satisfied=False,
            readiness_status="awaiting_human_confirmation",
            missing_requirements=("human_confirmation",),
            blocking_reasons=(
                "Operator rejected this prepared action. "
                "Authority chain cannot advance from a rejected action.",
            ),
            next_safe_step=(
                "The action was rejected by the operator. "
                "A new prepared action must be created and confirmed to proceed."
            ),
            execution_allowed=False,
            can_execute_now=False,
            used_execution=False,
        )
        _store_report(report)
        return report

    # --- 4. Policy review ---
    policy_review = get_mso_policy_review(entry_id)
    if policy_review is None:
        report = MSOPoliceReadinessReport(
            entry_id=entry_id,
            action_id=action_id,
            domain=domain,
            requested_action=requested_action,
            current_chain_stage="policy_review",
            prepared_action_present=True,
            human_confirmation_status=hc_status,
            human_confirmation_satisfied=True,
            policy_review_present=False,
            readiness_status="awaiting_policy_review",
            missing_requirements=("policy_review",),
            blocking_reasons=(
                "Human confirmation is recorded but no policy review has been evaluated.",
            ),
            next_safe_step=(
                "POST /mso/prepared-actions/policy-review with entry_id and action_id "
                "to evaluate capability policy."
            ),
            execution_allowed=False,
            can_execute_now=False,
            used_execution=False,
        )
        _store_report(report)
        return report

    policy_outcome = policy_review.policy_outcome

    if policy_outcome == "denied":
        report = MSOPoliceReadinessReport(
            entry_id=entry_id,
            action_id=action_id,
            domain=domain,
            requested_action=requested_action,
            current_chain_stage="policy_review",
            prepared_action_present=True,
            human_confirmation_status=hc_status,
            human_confirmation_satisfied=True,
            policy_review_present=True,
            policy_outcome=policy_outcome,
            readiness_status="policy_denied",
            missing_requirements=(),
            blocking_reasons=(
                f"Policy review outcome is 'denied' "
                f"(capability_mode={policy_review.capability_mode!r}). "
                "Authority chain cannot advance past a denied policy review.",
            ),
            next_safe_step=(
                "Policy was denied by the capability registry. "
                "Review the capability configuration or request a different action."
            ),
            execution_allowed=False,
            can_execute_now=False,
            used_execution=False,
        )
        _store_report(report)
        return report

    # --- 5. Authority binding ---
    authority_binding = get_mso_authority_binding(entry_id)
    if authority_binding is None:
        report = MSOPoliceReadinessReport(
            entry_id=entry_id,
            action_id=action_id,
            domain=domain,
            requested_action=requested_action,
            current_chain_stage="authority_binding",
            prepared_action_present=True,
            human_confirmation_status=hc_status,
            human_confirmation_satisfied=True,
            policy_review_present=True,
            policy_outcome=policy_outcome,
            authority_binding_draft_present=False,
            readiness_status="awaiting_authority_binding",
            missing_requirements=("authority_binding_draft",),
            blocking_reasons=(
                f"Policy review is approved (outcome={policy_outcome!r}) "
                "but no authority binding draft has been created.",
            ),
            next_safe_step=(
                "POST /mso/prepared-actions/authority-binding with entry_id and action_id "
                "to create an MSOAuthorityBindingDraft."
            ),
            execution_allowed=False,
            can_execute_now=False,
            used_execution=False,
        )
        _store_report(report)
        return report

    # --- 6. Authority chain draft complete — downstream artifacts still missing ---
    _downstream_missing = (
        "CapabilityToken",
        "OperationBinding",
        "AuthorizedPlan",
        "PoliceGate",
        "Runner",
    )
    report = MSOPoliceReadinessReport(
        entry_id=entry_id,
        action_id=action_id,
        domain=domain,
        requested_action=requested_action,
        current_chain_stage="authority_binding_draft",
        prepared_action_present=True,
        human_confirmation_status=hc_status,
        human_confirmation_satisfied=True,
        policy_review_present=True,
        policy_outcome=policy_outcome,
        authority_binding_draft_present=True,
        readiness_status="authority_chain_draft_complete",
        missing_requirements=_downstream_missing,
        blocking_reasons=(
            "MSO draft chain has reached AuthorityBindingDraft. "
            "Productive downstream artifacts are not yet implemented: "
            "CapabilityToken, OperationBinding, AuthorizedPlan, PoliceGate, Runner. "
            "Execution remains closed.",
        ),
        next_safe_step=(
            "Authority chain draft is complete. "
            "Downstream productive artifacts (CapabilityToken → OperationBinding → "
            "AuthorizedPlan → PoliceGate → Runner) must be implemented before "
            "any execution can occur. This is a future sprint."
        ),
        execution_allowed=False,
        can_execute_now=False,
        used_execution=False,
    )
    _store_report(report)
    return report
