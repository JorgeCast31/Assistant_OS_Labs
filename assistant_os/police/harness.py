"""Dry Police gate harness; not a production runtime path."""

from .gate_models import PoliceDecision, PoliceOutcome


def apply_police_gate(decision: PoliceDecision) -> dict[str, object]:
    if decision.outcome is PoliceOutcome.PERMITTED and decision.permitted is True:
        return {
            "ok": True,
            "status": "would_continue",
            "police_decision_ref": decision.decision_id,
        }

    if decision.outcome is PoliceOutcome.DENIED:
        return {
            "ok": False,
            "status": "blocked",
            "reason": decision.reason.value,
            "why_blocked": decision.detail,
            "police_decision_ref": decision.decision_id,
        }

    if decision.outcome is PoliceOutcome.DEFERRED:
        return {
            "ok": False,
            "status": "requires_confirmation",
            "reason": decision.reason.value,
            "required_confirmation_reason": decision.detail,
            "police_decision_ref": decision.decision_id,
        }

    raise ValueError(f"Unsupported Police outcome: {decision.outcome}")
