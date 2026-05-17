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
# Read-model helpers — safe for embedding in surface/pending responses
# ---------------------------------------------------------------------------

_READINESS_SUB_FIELDS = (
    "readiness_status",
    "current_chain_stage",
    "missing_requirements",
    "blocking_reasons",
    "next_safe_step",
    "execution_allowed",
    "can_execute_now",
    "used_execution",
)


def get_police_readiness_for_item(entry_id: str, action_id: str) -> dict:
    """Return a compact police-readiness sub-dict for embedding in read-model items.

    Calls evaluate_police_readiness_for_prepared_action() and returns only the
    fields needed for surface embedding. Fail-soft: returns an empty dict on any
    error so callers are never broken by a diagnostic failure.

    Always returns execution_allowed=False, can_execute_now=False, used_execution=False.
    """
    if not entry_id or not action_id:
        return {}
    try:
        report = evaluate_police_readiness_for_prepared_action(entry_id, action_id)
        rpt = report.to_dict()
        return {k: rpt[k] for k in _READINESS_SUB_FIELDS if k in rpt}
    except Exception:  # noqa: BLE001 — fail-soft, diagnostic must never break callers
        return {}


def build_readiness_summary(items: list[dict]) -> dict:
    """Aggregate police-readiness status counts across a list of prepared-action item dicts.

    Each dict must contain 'queue_entry_id' and 'prepared_action_id' keys.
    Items missing those keys are skipped.

    Returns a summary dict with status counts and a list of next safe operator
    actions derived from the most urgent missing steps.

    Read-only. Fail-soft: any per-item evaluation error is counted as 'unknown'.
    execution_allowed, can_execute_now, used_execution are always False.
    """
    counts: dict[str, int] = {}
    next_steps: list[str] = []

    for item in items:
        entry_id = item.get("queue_entry_id", "")
        action_id = item.get("prepared_action_id", "")
        if not entry_id or not action_id:
            counts["unknown"] = counts.get("unknown", 0) + 1
            continue
        try:
            report = evaluate_police_readiness_for_prepared_action(entry_id, action_id)
            status = report.readiness_status
            counts[status] = counts.get(status, 0) + 1
            if report.next_safe_step and report.next_safe_step not in next_steps:
                next_steps.append(report.next_safe_step)
        except Exception:  # noqa: BLE001 — fail-soft
            counts["unknown"] = counts.get("unknown", 0) + 1

    return {
        "total": len(items),
        "awaiting_human_confirmation": counts.get("awaiting_human_confirmation", 0),
        "awaiting_policy_review": counts.get("awaiting_policy_review", 0),
        "awaiting_authority_binding": counts.get("awaiting_authority_binding", 0),
        "authority_chain_draft_complete": counts.get("authority_chain_draft_complete", 0),
        "blocked_by_governance": counts.get("blocked_by_governance", 0),
        "policy_denied": counts.get("policy_denied", 0),
        "missing_prepared_action": counts.get("missing_prepared_action", 0),
        "unknown": counts.get("unknown", 0),
        "next_safe_operator_actions": next_steps[:5],
        "execution_allowed": False,
        "can_execute_now": False,
        "used_execution": False,
    }


# ---------------------------------------------------------------------------
# Operation trace v0 — visual/read-model trace per prepared action
# ---------------------------------------------------------------------------

def _build_trace_steps_from_report(report: MSOPoliceReadinessReport) -> list[dict]:
    """Derive 6-step operation trace from a readiness report. Read-only, no side effects."""
    steps: list[dict] = []

    # Step 1: prepared_action
    if report.prepared_action_present:
        steps.append({
            "step": "prepared_action",
            "status": "complete",
            "label": "Prepared Action",
            "description": f"{report.domain}: {report.requested_action}",
            "completed": True,
        })
    else:
        steps.append({
            "step": "prepared_action",
            "status": "missing",
            "label": "Prepared Action",
            "description": "No prepared action found in queue.",
            "completed": False,
        })

    # Step 2: human_confirmation
    if report.human_confirmation_satisfied:
        steps.append({
            "step": "human_confirmation",
            "status": "complete",
            "label": "Human Confirmation",
            "description": "Operator confirmed.",
            "completed": True,
        })
    elif report.human_confirmation_status == "human_rejected":
        steps.append({
            "step": "human_confirmation",
            "status": "rejected",
            "label": "Human Confirmation",
            "description": "Operator rejected this action.",
            "completed": False,
        })
    elif report.human_confirmation_status == "pending":
        steps.append({
            "step": "human_confirmation",
            "status": "pending",
            "label": "Human Confirmation",
            "description": "Awaiting operator confirmation.",
            "completed": False,
        })
    else:
        steps.append({
            "step": "human_confirmation",
            "status": "missing",
            "label": "Human Confirmation",
            "description": "No confirmation record.",
            "completed": False,
        })

    # Step 3: policy_review
    if report.policy_review_present and report.policy_outcome in ("approved", "approved_confirm_only"):
        steps.append({
            "step": "policy_review",
            "status": "complete",
            "label": "Policy Review",
            "description": f"Capability policy approved (outcome={report.policy_outcome}).",
            "completed": True,
        })
    elif report.policy_outcome == "denied":
        steps.append({
            "step": "policy_review",
            "status": "denied",
            "label": "Policy Review",
            "description": "Policy denied by capability registry.",
            "completed": False,
        })
    elif report.human_confirmation_satisfied:
        steps.append({
            "step": "policy_review",
            "status": "pending",
            "label": "Policy Review",
            "description": "Awaiting capability policy evaluation.",
            "completed": False,
        })
    else:
        steps.append({
            "step": "policy_review",
            "status": "missing",
            "label": "Policy Review",
            "description": "Not yet reached.",
            "completed": False,
        })

    # Step 4: authority_binding
    if report.authority_binding_draft_present:
        steps.append({
            "step": "authority_binding",
            "status": "complete",
            "label": "Authority Binding Draft",
            "description": "MSOAuthorityBindingDraft created.",
            "completed": True,
        })
    elif report.policy_review_present and report.policy_outcome not in ("denied", ""):
        steps.append({
            "step": "authority_binding",
            "status": "pending",
            "label": "Authority Binding Draft",
            "description": "Awaiting authority binding draft creation.",
            "completed": False,
        })
    else:
        steps.append({
            "step": "authority_binding",
            "status": "missing",
            "label": "Authority Binding Draft",
            "description": "Not yet reached.",
            "completed": False,
        })

    # Step 5: police_readiness
    if report.readiness_status == "authority_chain_draft_complete":
        steps.append({
            "step": "police_readiness",
            "status": "draft_complete",
            "label": "Police Readiness",
            "description": "MSO draft chain complete. Downstream artifacts not yet implemented.",
            "completed": False,
        })
    elif report.readiness_status in ("blocked_by_governance", "policy_denied"):
        steps.append({
            "step": "police_readiness",
            "status": "blocked",
            "label": "Police Readiness",
            "description": "; ".join(report.blocking_reasons) if report.blocking_reasons else "Blocked.",
            "completed": False,
        })
    else:
        steps.append({
            "step": "police_readiness",
            "status": "not_ready",
            "label": "Police Readiness",
            "description": "Authority chain prerequisites not yet met.",
            "completed": False,
        })

    # Step 6: execution — always blocked by design
    steps.append({
        "step": "execution",
        "status": "blocked_by_design",
        "label": "Execution",
        "description": (
            "Execution is closed by design. "
            "CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate → Runner "
            "not yet implemented."
        ),
        "completed": False,
    })

    return steps


def build_operation_trace_v0(entry_id: str, action_id: str) -> dict:
    """Build an operation trace v0 dict for a prepared action.

    Derives a 6-step visual trace from the police readiness report.
    Fail-soft: returns a minimal trace with empty steps on any error.
    Always returns execution_allowed=False, can_execute_now=False, used_execution=False.
    """
    if not entry_id or not action_id:
        return {
            "trace_version": "v0",
            "entry_id": entry_id,
            "action_id": action_id,
            "steps": [],
            "missing_requirements": [],
            "blocking_reasons": [],
            "next_safe_step": "",
            "execution_allowed": False,
            "can_execute_now": False,
            "used_execution": False,
        }
    try:
        report = evaluate_police_readiness_for_prepared_action(entry_id, action_id)
        steps = _build_trace_steps_from_report(report)
        return {
            "trace_version": "v0",
            "entry_id": entry_id,
            "action_id": action_id,
            "steps": steps,
            "missing_requirements": list(report.missing_requirements),
            "blocking_reasons": list(report.blocking_reasons),
            "next_safe_step": report.next_safe_step,
            "execution_allowed": False,
            "can_execute_now": False,
            "used_execution": False,
        }
    except Exception:  # noqa: BLE001 — fail-soft, trace must never break callers
        return {
            "trace_version": "v0",
            "entry_id": entry_id,
            "action_id": action_id,
            "steps": [],
            "missing_requirements": [],
            "blocking_reasons": ["Trace evaluation failed."],
            "next_safe_step": "",
            "execution_allowed": False,
            "can_execute_now": False,
            "used_execution": False,
        }


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
