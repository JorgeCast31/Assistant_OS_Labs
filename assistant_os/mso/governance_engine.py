"""Active MSO governance decision engine."""

from __future__ import annotations

from ..contracts import EXECUTION_MODE_BLOCKED, EXECUTION_MODE_CONFIRM
from .capability_registry import check_capability
from .contracts import GovernanceConstraint, GovernanceDecision, GovernanceReason, RiskEvaluation


def evaluate_governance(
    *,
    action: str,
    domain: str,
    base_execution_mode: str,
    risk: RiskEvaluation,
    created_at: str,
) -> GovernanceDecision:
    """Return the MSO governance decision over the deterministic policy."""
    capability = check_capability(action, domain)
    reasons = list(risk.reasons)
    constraints: list[GovernanceConstraint] = []

    if not capability.allowed:
        reasons.append(GovernanceReason(code="capability_denied", detail=capability.deny_reason or "Capability denied."))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="BLOCK",
            effective_execution_mode=EXECUTION_MODE_BLOCKED,
            risk_level=risk.level,
            justification="Capability registry denied this action.",
            reasons=reasons,
            constraints=constraints,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            created_at=created_at,
        )

    if capability.mode == "plan_only":
        constraints.append(GovernanceConstraint(kind="degrade", value="plan_only"))
        reasons.append(GovernanceReason(code="plan_only_capability", detail="Capability allows plan visibility only; execution is degraded."))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="DEGRADE",
            effective_execution_mode=EXECUTION_MODE_BLOCKED,
            risk_level=risk.level,
            justification="Capability registry reduced execution to plan-only.",
            reasons=reasons,
            constraints=constraints,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            created_at=created_at,
        )

    if risk.level == "high":
        reasons.append(GovernanceReason(code="high_risk", detail="High risk requests are blocked in Sprint 5 governance."))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="BLOCK",
            effective_execution_mode=EXECUTION_MODE_BLOCKED,
            risk_level=risk.level,
            justification="High risk blocked by MSO governance.",
            reasons=reasons,
            constraints=constraints,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            created_at=created_at,
        )

    if risk.anomaly_detected and base_execution_mode == "auto":
        constraints.append(GovernanceConstraint(kind="degrade", value="confirm_due_to_recent_failures"))
        reasons.append(GovernanceReason(code="anomaly_degrade", detail="Recent failures reduced automatic execution scope."))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="DEGRADE",
            effective_execution_mode=EXECUTION_MODE_CONFIRM,
            risk_level=risk.level,
            justification="Execution degraded to confirmation because of recent domain failures.",
            reasons=reasons,
            constraints=constraints,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            created_at=created_at,
        )

    if capability.requires_confirmation and base_execution_mode == "auto":
        reasons.append(GovernanceReason(code="capability_confirm_only", detail="Capability policy requires user confirmation."))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="REQUIRE_CONFIRMATION",
            effective_execution_mode=EXECUTION_MODE_CONFIRM,
            risk_level=risk.level,
            justification="Capability registry requires confirmation.",
            reasons=reasons,
            constraints=constraints,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            created_at=created_at,
        )

    if risk.level == "medium" and base_execution_mode == "auto":
        reasons.append(GovernanceReason(code="medium_risk_confirmation", detail="Medium risk cannot continue as silent auto execution."))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="REQUIRE_CONFIRMATION",
            effective_execution_mode=EXECUTION_MODE_CONFIRM,
            risk_level=risk.level,
            justification="Medium risk upgraded to confirmation by MSO governance.",
            reasons=reasons,
            constraints=constraints,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            created_at=created_at,
        )

    return GovernanceDecision(
        governance_ref=f"governance:{created_at}:{action}",
        action="ALLOW",
        effective_execution_mode=base_execution_mode,
        risk_level=risk.level,
        justification="Governance allows deterministic policy to proceed.",
        reasons=reasons,
        constraints=constraints,
        capability_mode=capability.mode,
        base_execution_mode=base_execution_mode,
        created_at=created_at,
    )
