"""Read-only sovereign state access contract for runtime enforcement.

This module defines the narrow interface that runtime surfaces use to consult
already-existing sovereign state. It does not introduce a new store and it does
not implement persistence or decision logic.

The intended backing data remains the existing MSO state surfaces, primarily:
- storage.mso_store record families
- MSO restriction and governance read models
- system_state snapshot derivation

Backends should consume this contract as a read-only boundary before executing
real machine actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


SovereignDecisionState = Literal["allowed", "blocked"]
SovereignReasonCode = Literal[
    "allowed",
    "kill_switch_active",
    "restriction_active",
    "approval_missing",
    "approval_expired",
    "governance_missing",
    "governance_unresolved",
    "state_unavailable",
]
KillSwitchState = Literal["active", "inactive", "unknown"]


@dataclass(frozen=True, slots=True)
class SovereignExecutionQuery:
    """Minimal sovereign inputs needed to evaluate backend execution."""

    approval_id: str
    capability_name: str
    capability_scope: str
    expires_at: str
    policy_decision_ref: str
    governance_ref: str
    trace_id: str = ""
    plan_id: str = ""
    intent_id: str = ""
    correlation_id: str = ""
    target_domain: str = "MACHINE_OPERATOR"
    target_action: str = ""


@dataclass(frozen=True, slots=True)
class SovereignDecisionReason:
    """Structured reason attached to a sovereign access decision."""

    code: SovereignReasonCode
    message: str
    source: str = ""
    governance_ref: str = ""
    restriction_ids: tuple[str, ...] = ()
    signal_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SovereignExecutionDecision:
    """Outcome returned by the runtime sovereign gate."""

    state: SovereignDecisionState
    allowed: bool
    reason: SovereignDecisionReason
    kill_switch_state: KillSwitchState
    operational_mode: str = ""
    checked_at: str = ""
    governance_ref: str = ""
    policy_decision_ref: str = ""
    approval_id: str = ""


@dataclass(frozen=True, slots=True)
class SovereignKillSwitchSnapshot:
    """Current kill-switch posture as exposed to runtime callers."""

    state: KillSwitchState
    active: bool
    reason: SovereignDecisionReason
    checked_at: str = ""


@dataclass(frozen=True, slots=True)
class SovereignGovernanceSnapshot:
    """Compact read model needed by backend ingress decisions."""

    governance_ref: str
    policy_decision_ref: str = ""
    approval_id: str = ""
    trace_id: str = ""
    operational_mode: str = ""
    kill_switch_state: KillSwitchState = "unknown"
    active_restriction_ids: tuple[str, ...] = ()
    active_signal_ids: tuple[str, ...] = ()
    active_reasons: tuple[SovereignDecisionReason, ...] = ()
    backing_record_kinds: tuple[str, ...] = field(
        default_factory=lambda: (
            "restrictions",
            "control_plane_signals",
            "cycles",
            "capabilities",
        )
    )


class SovereignStateStore(Protocol):
    """Read-only sovereign state boundary for runtime execution surfaces.

    Responsibilities:
    - answer whether a backend execution may proceed right now
    - expose kill-switch posture in one place
    - return the governing reason for a block or allowance decision
    - provide a compact governance snapshot suitable for audit/log enrichment

    Non-responsibilities:
    - persistence writes
    - mutation of restrictions, signals, approvals, or governance decisions
    - backend transport or runtime execution
    """

    def is_execution_allowed(
        self,
        query: SovereignExecutionQuery,
    ) -> SovereignExecutionDecision:
        """Return the sovereign allow/block decision for one backend request."""

    def get_kill_switch_state(
        self,
        *,
        target_domain: str,
        target_action: str = "",
        trace_id: str = "",
    ) -> SovereignKillSwitchSnapshot:
        """Return the current kill-switch posture for the requested execution surface."""

    def get_reason(
        self,
        *,
        governance_ref: str = "",
        policy_decision_ref: str = "",
        approval_id: str = "",
        trace_id: str = "",
    ) -> SovereignDecisionReason:
        """Resolve the most specific sovereign reason available for the given references."""

    def get_governance_snapshot(
        self,
        *,
        governance_ref: str,
        policy_decision_ref: str = "",
        trace_id: str = "",
        approval_id: str = "",
    ) -> SovereignGovernanceSnapshot:
        """Return the compact sovereign snapshot needed by backend ingress code."""
