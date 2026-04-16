"""Deterministic anomaly signals for dynamic MSO governance."""

from __future__ import annotations

from collections import Counter, defaultdict

from ..contracts import now_iso
from .contracts import (
    AnomalySignal,
    DomainOperationalState,
    DomainStatusSummary,
    GovernanceDecision,
    OperationalMode,
)


def _signal(
    *,
    code: str,
    severity: str,
    detail: str,
    domain: str = "",
    target_action: str = "",
    recommended_mode: OperationalMode = "NORMAL",
    recommended_intervention: str = "",
) -> AnomalySignal:
    return AnomalySignal(
        signal_id=f"anomaly:{code}:{domain or 'global'}:{target_action or 'none'}:{now_iso()}",
        code=code,
        severity=severity,
        detail=detail,
        created_at=now_iso(),
        domain=domain,
        target_action=target_action,
        recommended_mode=recommended_mode,
        recommended_intervention=recommended_intervention,
    )


def analyze_anomalies(
    *,
    domain_status_summary: list[DomainStatusSummary],
    recent_governance_decisions: list[GovernanceDecision],
    recent_worker_security_events: list[dict] | None = None,
) -> list[AnomalySignal]:
    """Derive explicit anomaly signals from observable system state."""
    signals: list[AnomalySignal] = []

    by_domain_governance: dict[str, Counter] = defaultdict(Counter)
    sensitive_attempts: dict[str, int] = defaultdict(int)
    for decision in recent_governance_decisions:
        by_domain_governance[decision.target_domain][decision.action] += 1
        if decision.target_action.endswith("_DELETE") or decision.target_action.endswith("_RESET") or decision.target_action in {"CODE_FIX", "CODE_CREATE", "FIN_COMMIT", "WORK_UPDATE", "WORK_UPDATE_BULK"}:
            sensitive_attempts[decision.target_domain] += 1

    for summary in domain_status_summary:
        if summary.failed >= 4:
            signals.append(
                _signal(
                    code="domain_failures_critical",
                    severity="high",
                    detail=f"Domain {summary.domain} has {summary.failed} recent failed tasks.",
                    domain=summary.domain,
                    recommended_mode="DEGRADED",
                    recommended_intervention="soft_quarantine",
                )
            )
        elif summary.failed >= 2:
            signals.append(
                _signal(
                    code="domain_failures_elevated",
                    severity="medium",
                    detail=f"Domain {summary.domain} has {summary.failed} recent failed tasks.",
                    domain=summary.domain,
                    recommended_mode="RESTRICTED",
                    recommended_intervention="confirmation_escalation",
                )
            )

        if summary.blocked >= 3:
            signals.append(
                _signal(
                    code="blocked_attempt_spike",
                    severity="medium",
                    detail=f"Domain {summary.domain} has {summary.blocked} blocked task(s).",
                    domain=summary.domain,
                    recommended_mode="RESTRICTED",
                    recommended_intervention="domain_hardening",
                )
            )

    for domain, counter in by_domain_governance.items():
        if counter["DEGRADE"] >= 3:
            signals.append(
                _signal(
                    code="repeated_degrade",
                    severity="medium",
                    detail=f"Domain {domain} has {counter['DEGRADE']} recent degraded governance decisions.",
                    domain=domain,
                    recommended_mode="RESTRICTED",
                    recommended_intervention="confirmation_escalation",
                )
            )
        if counter["BLOCK"] >= 3:
            signals.append(
                _signal(
                    code="repeated_blocks",
                    severity="medium",
                    detail=f"Domain {domain} has {counter['BLOCK']} recent blocked governance decisions.",
                    domain=domain,
                    recommended_mode="RESTRICTED",
                    recommended_intervention="domain_hardening",
                )
            )

    for domain, count in sensitive_attempts.items():
        if count >= 3:
            signals.append(
                _signal(
                    code="sensitive_attempt_spike",
                    severity="high" if count >= 5 else "medium",
                    detail=f"Domain {domain} saw {count} recent sensitive action attempts.",
                    domain=domain,
                    recommended_mode="DEGRADED" if count >= 5 else "RESTRICTED",
                    recommended_intervention="soft_quarantine" if count >= 5 else "confirmation_escalation",
                )
            )

    worker_security_events = recent_worker_security_events or []
    timeout_events = sum(1 for item in worker_security_events if item.get("payload", {}).get("event_type") == "worker_timeout")
    crash_events = sum(1 for item in worker_security_events if item.get("payload", {}).get("event_type") == "worker_crash")
    denied_events = sum(
        1
        for item in worker_security_events
        if item.get("payload", {}).get("event_type") in {"network_denied", "invalid_input_ref", "scope_violation", "resource_limit_exceeded"}
    )
    if timeout_events >= 2:
        signals.append(
            _signal(
                code="worker_timeout_spike",
                severity="medium",
                detail=f"Worker has {timeout_events} recent timeout event(s).",
                domain="COGNITIVE",
                recommended_mode="RESTRICTED",
                recommended_intervention="confirmation_escalation",
            )
        )
    if crash_events >= 1:
        signals.append(
            _signal(
                code="worker_crash_detected",
                severity="high",
                detail=f"Worker has {crash_events} recent crash/kill event(s).",
                domain="COGNITIVE",
                recommended_mode="DEGRADED",
                recommended_intervention="soft_quarantine",
            )
        )
    if denied_events >= 2:
        signals.append(
            _signal(
                code="worker_security_denial_spike",
                severity="medium",
                detail=f"Worker has {denied_events} recent denied security event(s).",
                domain="COGNITIVE",
                recommended_mode="RESTRICTED",
                recommended_intervention="domain_hardening",
            )
        )

    return signals


def derive_operational_mode(
    signals: list[AnomalySignal],
    *,
    override_mode: OperationalMode | None = None,
    override_reason: str = "",
) -> tuple[OperationalMode, str, str]:
    """Resolve system operational mode from explicit override or anomalies."""
    if override_mode is not None:
        return override_mode, override_reason or "manual_override", "manual"
    if any(signal.severity == "high" for signal in signals):
        return "DEGRADED", "derived_from_high_anomaly", "derived"
    if any(signal.severity == "medium" for signal in signals):
        return "RESTRICTED", "derived_from_medium_anomaly", "derived"
    return "NORMAL", "normal_operation", "derived"


def build_domain_operational_states(
    domain_status_summary: list[DomainStatusSummary],
    signals: list[AnomalySignal],
    *,
    operational_mode: OperationalMode,
) -> list[DomainOperationalState]:
    """Build derived domain-level hardening posture from anomaly signals."""
    per_domain: dict[str, list[AnomalySignal]] = defaultdict(list)
    for signal in signals:
        if signal.domain:
            per_domain[signal.domain].append(signal)

    states: list[DomainOperationalState] = []
    for summary in domain_status_summary:
        domain_signals = per_domain.get(summary.domain, [])
        hardened = any(signal.recommended_intervention in {"soft_quarantine", "domain_hardening"} for signal in domain_signals)
        mode = operational_mode
        if any(signal.recommended_mode == "DEGRADED" for signal in domain_signals):
            mode = "DEGRADED"
        elif any(signal.recommended_mode == "RESTRICTED" for signal in domain_signals) and mode == "NORMAL":
            mode = "RESTRICTED"
        notes = "; ".join(signal.code for signal in domain_signals[:3])
        states.append(
            DomainOperationalState(
                domain=summary.domain,
                mode=mode,
                hardened=hardened,
                active_anomaly_count=len(domain_signals),
                notes=notes,
            )
        )
    return states
