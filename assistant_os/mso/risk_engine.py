"""Rule-driven MSO risk engine."""

from __future__ import annotations

from ..contracts import (
    ACTION_BASIC_COGNITIVE_EXECUTION,
    ACTION_CODE_EXPLAIN,
    ACTION_CODE_REVIEW,
    ACTION_FIN_CHAPERON,
    ACTION_FIN_PLAN,
    ACTION_WORK_QUERY,
    EXECUTION_MODE_AUTO,
)
from .contracts import GovernanceReason, RiskEvaluation, SystemStateSnapshot

_READ_ONLY_ACTIONS = {
    ACTION_BASIC_COGNITIVE_EXECUTION,
    ACTION_WORK_QUERY,
    ACTION_CODE_EXPLAIN,
    ACTION_CODE_REVIEW,
    ACTION_FIN_PLAN,
    ACTION_FIN_CHAPERON,
}


def _bump_risk(level: str) -> str:
    return {"low": "medium", "medium": "high"}.get(level, "high")


def evaluate_risk(
    *,
    domain: str,
    action: str,
    risk_level: str,
    execution_mode: str,
    advisory_trace: dict | None = None,
    system_state: SystemStateSnapshot | None = None,
) -> RiskEvaluation:
    """Evaluate risk using explicit deterministic rules."""
    reasons: list[GovernanceReason] = []
    current_level = risk_level or "medium"
    snapshot = system_state
    domain_summary = next((item for item in snapshot.domain_status_summary if item.domain == domain), None) if snapshot else None
    domain_operational_state = next((item for item in snapshot.domain_operational_states if item.domain == domain), None) if snapshot else None
    recent_failure_count = domain_summary.failed if domain_summary else 0
    anomaly_signals = [item for item in (snapshot.recent_anomaly_signals if snapshot else []) if item.domain in {"", domain}]

    reasons.append(GovernanceReason(code="base_risk", detail=f"Planner risk level is {current_level}."))

    anomaly_detected = False
    if recent_failure_count >= 2:
        anomaly_detected = True
        if execution_mode == EXECUTION_MODE_AUTO and action not in _READ_ONLY_ACTIONS:
            bumped = _bump_risk(current_level)
            reasons.append(
                GovernanceReason(
                    code="recent_failures",
                    detail=f"Detected {recent_failure_count} failed task(s) in domain {domain}; risk raised from {current_level} to {bumped}.",
                )
            )
            current_level = bumped
        else:
            reasons.append(
                GovernanceReason(
                    code="recent_failures_observed",
                    detail=f"Detected {recent_failure_count} failed task(s) in domain {domain}; anomaly recorded without changing base risk.",
                )
            )

    if action.endswith("_DELETE") or action.endswith("_RESET"):
        reasons.append(GovernanceReason(code="destructive_action", detail="Destructive action detected."))
        current_level = "high"

    if action.startswith("CODE_") and action in {"CODE_FIX", "CODE_CREATE"} and current_level == "low":
        reasons.append(GovernanceReason(code="code_mutation", detail="Mutating CODE action cannot remain low risk."))
        current_level = "medium"

    if advisory_trace and advisory_trace.get("error"):
        reasons.append(GovernanceReason(code="advisory_error", detail="Advisory layer was unavailable or incomplete; governance remained deterministic."))

    if snapshot and snapshot.operational_mode != "NORMAL":
        reasons.append(GovernanceReason(code="operational_mode", detail=f"Operational mode is {snapshot.operational_mode}."))
        if snapshot.operational_mode == "DEGRADED" and action not in _READ_ONLY_ACTIONS:
            current_level = _bump_risk(current_level)
        elif snapshot.operational_mode == "RESTRICTED" and current_level == "low" and action not in _READ_ONLY_ACTIONS:
            current_level = "medium"

    if domain_operational_state and domain_operational_state.hardened:
        anomaly_detected = True
        reasons.append(
            GovernanceReason(
                code="domain_hardened",
                detail=f"Domain {domain} is hardened by MSO due to recent anomalies.",
            )
        )

    if execution_mode == "auto" and current_level == "medium":
        reasons.append(GovernanceReason(code="auto_mode_medium_risk", detail="Auto execution combined with medium risk requires governance review."))

    return RiskEvaluation(
        level=current_level,
        reasons=reasons,
        base_risk=risk_level or "medium",
        recent_failure_count=recent_failure_count,
        anomaly_detected=anomaly_detected,
        operational_mode=(snapshot.operational_mode if snapshot else "NORMAL"),
        anomaly_signals=anomaly_signals,
    )
