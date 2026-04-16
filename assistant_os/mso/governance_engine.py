"""Dynamic MSO governance decision engine."""

from __future__ import annotations

from ..contracts import EXECUTION_MODE_BLOCKED, EXECUTION_MODE_CONFIRM, should_auto_execute
from .capability_registry import check_capability
from .contracts import (
    AnomalySignal,
    DomainOperationalState,
    GovernanceConstraint,
    GovernanceDecision,
    GovernanceIntervention,
    GovernanceReason,
    RiskEvaluation,
    SystemStateSnapshot,
)


def _domain_state_for(snapshot: SystemStateSnapshot | None, domain: str) -> DomainOperationalState | None:
    if snapshot is None:
        return None
    return next((item for item in snapshot.domain_operational_states if item.domain == domain), None)


def evaluate_governance(
    *,
    action: str,
    domain: str,
    base_execution_mode: str,
    risk: RiskEvaluation,
    created_at: str,
    system_state: SystemStateSnapshot | None = None,
) -> GovernanceDecision:
    """Return the MSO governance decision over the deterministic policy."""
    capability = check_capability(action, domain)
    reasons = list(risk.reasons)
    constraints: list[GovernanceConstraint] = []
    interventions: list[GovernanceIntervention] = []
    dynamic_factors: list[str] = []
    anomaly_signals: list[AnomalySignal] = [
        signal for signal in (system_state.recent_anomaly_signals if system_state else []) if signal.domain in {"", domain}
    ]
    domain_state = _domain_state_for(system_state, domain)
    operational_mode = system_state.operational_mode if system_state else risk.operational_mode
    operational_mode_source = system_state.operational_mode_source if system_state else ""

    if operational_mode != "NORMAL":
        dynamic_factors.append(f"operational_mode:{operational_mode}")
        reasons.append(
            GovernanceReason(
                code="operational_mode",
                detail=f"System operational mode is {operational_mode}.",
            )
        )

    if capability.source != "static":
        dynamic_factors.append(f"capability_source:{capability.source}")

    if capability.is_revoked:
        reasons.append(GovernanceReason(code="capability_revoked", detail=capability.deny_reason or "Capability revoked."))
        interventions.append(GovernanceIntervention(kind="revoke_capability", value=action, reason=capability.deny_reason))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="BLOCK",
            target_domain=domain,
            target_action=action,
            effective_execution_mode=EXECUTION_MODE_BLOCKED,
            risk_level=risk.level,
            justification="Capability revoked by dynamic governance.",
            reasons=reasons,
            constraints=constraints,
            interventions=interventions,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            operational_mode=operational_mode,
            created_at=created_at,
            capability_source=capability.source,
            anomaly_signals=anomaly_signals,
            dynamic_factors=dynamic_factors,
        )

    if not capability.allowed:
        reasons.append(GovernanceReason(code="capability_denied", detail=capability.deny_reason or "Capability denied."))
        interventions.append(GovernanceIntervention(kind="deny_capability", value=action, reason=capability.deny_reason))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="BLOCK",
            target_domain=domain,
            target_action=action,
            effective_execution_mode=EXECUTION_MODE_BLOCKED,
            risk_level=risk.level,
            justification="Capability registry denied this action.",
            reasons=reasons,
            constraints=constraints,
            interventions=interventions,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            operational_mode=operational_mode,
            created_at=created_at,
            capability_source=capability.source,
            anomaly_signals=anomaly_signals,
            dynamic_factors=dynamic_factors,
        )

    if capability.mode == "plan_only":
        constraints.append(GovernanceConstraint(kind="degrade", value="plan_only"))
        interventions.append(GovernanceIntervention(kind="degrade_scope", value="plan_only", reason="Capability limited to plan visibility."))
        reasons.append(GovernanceReason(code="plan_only_capability", detail="Capability allows plan visibility only; execution is degraded."))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="DEGRADE",
            target_domain=domain,
            target_action=action,
            effective_execution_mode=EXECUTION_MODE_BLOCKED,
            risk_level=risk.level,
            justification="Capability registry reduced execution to plan-only.",
            reasons=reasons,
            constraints=constraints,
            interventions=interventions,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            operational_mode=operational_mode,
            created_at=created_at,
            capability_source=capability.source,
            anomaly_signals=anomaly_signals,
            dynamic_factors=dynamic_factors,
        )

    is_post_confirmation_auto = base_execution_mode == "auto" and should_auto_execute({
        "action": action,
        "risk_level": risk.base_risk or risk.level,
        "requires_confirmation": False,
    })
    derived_mode_auto_exception = is_post_confirmation_auto and operational_mode_source == "derived"

    if risk.level == "high" and not is_post_confirmation_auto:
        reasons.append(GovernanceReason(code="high_risk", detail="High risk requests are blocked by governance."))
        interventions.append(GovernanceIntervention(kind="block_high_risk", value=action, reason="High risk"))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="BLOCK",
            target_domain=domain,
            target_action=action,
            effective_execution_mode=EXECUTION_MODE_BLOCKED,
            risk_level=risk.level,
            justification="High risk blocked by MSO governance.",
            reasons=reasons,
            constraints=constraints,
            interventions=interventions,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            operational_mode=operational_mode,
            created_at=created_at,
            capability_source=capability.source,
            anomaly_signals=anomaly_signals,
            dynamic_factors=dynamic_factors,
        )

    if operational_mode == "DEGRADED" and base_execution_mode == "auto" and not derived_mode_auto_exception:
        constraints.append(GovernanceConstraint(kind="degrade", value="degraded_mode_confirmation"))
        interventions.append(GovernanceIntervention(kind="confirmation_escalation", value=domain, reason="System is in DEGRADED mode."))
        reasons.append(GovernanceReason(code="degraded_mode", detail="DEGRADED mode converts auto execution into confirmation."))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="DEGRADE",
            target_domain=domain,
            target_action=action,
            effective_execution_mode=EXECUTION_MODE_CONFIRM,
            risk_level=risk.level,
            justification="System degraded mode hardened auto execution to confirmation.",
            reasons=reasons,
            constraints=constraints,
            interventions=interventions,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            operational_mode=operational_mode,
            created_at=created_at,
            capability_source=capability.source,
            anomaly_signals=anomaly_signals,
            dynamic_factors=dynamic_factors,
        )

    if domain_state and domain_state.hardened and base_execution_mode == "auto" and not derived_mode_auto_exception:
        constraints.append(GovernanceConstraint(kind="degrade", value="soft_quarantine_confirmation"))
        interventions.append(GovernanceIntervention(kind="soft_quarantine", value=domain, reason=domain_state.notes))
        reasons.append(GovernanceReason(code="soft_quarantine", detail=f"Domain {domain} is under soft quarantine."))
        dynamic_factors.append(f"domain_hardened:{domain}")
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="DEGRADE",
            target_domain=domain,
            target_action=action,
            effective_execution_mode=EXECUTION_MODE_CONFIRM,
            risk_level=risk.level,
            justification="Domain hardening reduced auto execution to confirmation.",
            reasons=reasons,
            constraints=constraints,
            interventions=interventions,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            operational_mode=operational_mode,
            created_at=created_at,
            capability_source=capability.source,
            anomaly_signals=anomaly_signals,
            dynamic_factors=dynamic_factors,
        )

    if (
        operational_mode == "RESTRICTED"
        and base_execution_mode == "auto"
        and risk.level in {"medium", "low"}
        and not derived_mode_auto_exception
    ):
        reasons.append(GovernanceReason(code="restricted_mode_confirmation", detail="RESTRICTED mode requires confirmation for auto execution."))
        interventions.append(GovernanceIntervention(kind="confirmation_escalation", value=domain, reason="Restricted mode"))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="REQUIRE_CONFIRMATION",
            target_domain=domain,
            target_action=action,
            effective_execution_mode=EXECUTION_MODE_CONFIRM,
            risk_level=risk.level,
            justification="Restricted mode upgraded auto execution to confirmation.",
            reasons=reasons,
            constraints=constraints,
            interventions=interventions,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            operational_mode=operational_mode,
            created_at=created_at,
            capability_source=capability.source,
            anomaly_signals=anomaly_signals,
            dynamic_factors=dynamic_factors,
        )

    if risk.anomaly_detected and base_execution_mode == "auto" and not derived_mode_auto_exception:
        constraints.append(GovernanceConstraint(kind="degrade", value="confirm_due_to_recent_failures"))
        interventions.append(GovernanceIntervention(kind="domain_hardening", value=domain, reason="Recent failures reduced automatic execution scope."))
        reasons.append(GovernanceReason(code="anomaly_degrade", detail="Recent failures reduced automatic execution scope."))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="DEGRADE",
            target_domain=domain,
            target_action=action,
            effective_execution_mode=EXECUTION_MODE_CONFIRM,
            risk_level=risk.level,
            justification="Execution degraded to confirmation because of recent domain failures.",
            reasons=reasons,
            constraints=constraints,
            interventions=interventions,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            operational_mode=operational_mode,
            created_at=created_at,
            capability_source=capability.source,
            anomaly_signals=anomaly_signals,
            dynamic_factors=dynamic_factors,
        )

    if capability.requires_confirmation and base_execution_mode == "auto":
        # Post-confirmation canonical actions (e.g. WORK_CREATE/WORK_DELETE,
        # FIN_COMMIT/FIN_BATCH) intentionally re-enter as auto after prior
        # user approval. Preserve execution for those explicit whitelist cases.
        if is_post_confirmation_auto:
            return GovernanceDecision(
                governance_ref=f"governance:{created_at}:{action}",
                action="ALLOW",
                target_domain=domain,
                target_action=action,
                effective_execution_mode=base_execution_mode,
                risk_level=risk.level,
                justification="Post-confirmation whitelist preserves automatic execution.",
                reasons=reasons,
                constraints=constraints,
                interventions=interventions,
                capability_mode=capability.mode,
                base_execution_mode=base_execution_mode,
                operational_mode=operational_mode,
                created_at=created_at,
                capability_source=capability.source,
                anomaly_signals=anomaly_signals,
                dynamic_factors=dynamic_factors,
            )

        reasons.append(GovernanceReason(code="capability_confirm_only", detail="Capability policy requires user confirmation."))
        interventions.append(GovernanceIntervention(kind="confirmation_escalation", value=action, reason="confirm_only capability"))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="REQUIRE_CONFIRMATION",
            target_domain=domain,
            target_action=action,
            effective_execution_mode=EXECUTION_MODE_CONFIRM,
            risk_level=risk.level,
            justification="Capability registry requires confirmation.",
            reasons=reasons,
            constraints=constraints,
            interventions=interventions,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            operational_mode=operational_mode,
            created_at=created_at,
            capability_source=capability.source,
            anomaly_signals=anomaly_signals,
            dynamic_factors=dynamic_factors,
        )

    if (
        risk.level == "medium"
        and base_execution_mode == "auto"
        and not (capability.mode == "allow" and is_post_confirmation_auto and system_state is not None)
    ):
        reasons.append(GovernanceReason(code="medium_risk_confirmation", detail="Medium risk cannot continue as silent auto execution."))
        interventions.append(GovernanceIntervention(kind="confirmation_escalation", value=action, reason="medium risk"))
        return GovernanceDecision(
            governance_ref=f"governance:{created_at}:{action}",
            action="REQUIRE_CONFIRMATION",
            target_domain=domain,
            target_action=action,
            effective_execution_mode=EXECUTION_MODE_CONFIRM,
            risk_level=risk.level,
            justification="Medium risk upgraded to confirmation by MSO governance.",
            reasons=reasons,
            constraints=constraints,
            interventions=interventions,
            capability_mode=capability.mode,
            base_execution_mode=base_execution_mode,
            operational_mode=operational_mode,
            created_at=created_at,
            capability_source=capability.source,
            anomaly_signals=anomaly_signals,
            dynamic_factors=dynamic_factors,
        )

    return GovernanceDecision(
        governance_ref=f"governance:{created_at}:{action}",
        action="ALLOW",
        target_domain=domain,
        target_action=action,
        effective_execution_mode=base_execution_mode,
        risk_level=risk.level,
        justification="Governance allows deterministic policy to proceed.",
        reasons=reasons,
        constraints=constraints,
        interventions=interventions,
        capability_mode=capability.mode,
        base_execution_mode=base_execution_mode,
        operational_mode=operational_mode,
        created_at=created_at,
        capability_source=capability.source,
        anomaly_signals=anomaly_signals,
        dynamic_factors=dynamic_factors,
    )
