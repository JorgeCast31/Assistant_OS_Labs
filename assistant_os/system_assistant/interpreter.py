"""System Assistant — interpretation layer.

Transforms a read-only SystemSnapshot into a non-authoritative
SystemInterpretation.

INVARIANTS — never violated by this module:
  - Does NOT call observe_system() or any observer automatically.
  - Does NOT call any domain pipeline, agent, or Kernel.
  - Does NOT produce execution_mode, GovernanceVerdict, or PolicyDecision.
  - Does NOT contain execution triggers, commands, or pipeline targets.
  - Does NOT modify any state.
  - Does NOT use LLM.
  - narrative=True in all outputs (marks non-authoritative origin).
  - execution_status=None in all outputs.

This module is pure: same input always produces same output.
"""

from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Public contract
# ---------------------------------------------------------------------------

class SystemInterpretation(TypedDict):
    """Non-authoritative interpretation of a SystemSnapshot.

    All fields are present (total=True by default).
    """

    status: str           # "healthy" | "partial" | "unavailable" | "unknown"
    summary: str          # single human-readable summary sentence
    observations: list[str]  # individual observation strings (counts only, no raw dicts)
    warnings: list[str]   # warnings verbatim from the snapshot
    narrative: bool       # always True — marks non-authoritative origin
    source: str           # always "system_assistant"
    execution_status: None  # always None — this layer never executes


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _derive_status(snapshot: dict[str, Any]) -> str:
    """Map snapshot status + warnings to interpretation status."""
    snap_status = snapshot.get("status", "")
    warnings = snapshot.get("warnings") or []

    if snap_status == "unavailable":
        return "unavailable"
    if snap_status == "partial" or warnings:
        return "partial"
    if snap_status == "ok":
        return "healthy"
    return "unknown"


def _describe_mode(mode: str | None) -> str:
    """Return a safe mode description that never assumes NORMAL."""
    if mode is None:
        return "operational mode: no override set (unknown)"
    return f"operational mode: {mode}"


def _describe_effective_mode(snapshot: dict[str, Any]) -> str:
    """Build mode text for summary using best available mode signal.

    Priority: manual override > governance effective mode > unknown.
    This does not infer MSO activity or health.
    """
    override = snapshot.get("operational_mode")
    if override is not None:
        return f"manual operational override {override}"

    gov = snapshot.get("governance_status_summary")
    if isinstance(gov, dict):
        gov_mode = gov.get("operational_mode")
        gov_source = gov.get("operational_mode_source") or "derived"
        if gov_mode is not None:
            return f"effective governance mode {gov_mode} (source {gov_source})"

    return "mode unknown (no override set)"


def _build_observations(snapshot: dict[str, Any]) -> list[str]:
    """Build a list of observation strings from snapshot fields.

    Reports only counts — never echoes raw agent or capability dicts.
    Never mentions execution_mode, GovernanceVerdict, or PolicyDecision.
    Never claims MSO ACTIVE, MSO HEALTHY, system safe/unsafe.
    """
    observations: list[str] = []

    # Operational mode
    mode = snapshot.get("operational_mode")
    observations.append(_describe_mode(mode))

    # Agents — count only
    agents = snapshot.get("agents") or []
    observations.append(f"registered agents: {len(agents)}")

    # Capabilities — count only
    capabilities = snapshot.get("capabilities") or []
    observations.append(f"registered capabilities: {len(capabilities)}")

    # Tasks — counts by status
    tasks_summary = snapshot.get("tasks_summary") or {}
    if tasks_summary:
        parts = ", ".join(f"{s}={n}" for s, n in sorted(tasks_summary.items()))
        observations.append(f"tasks summary: {parts}")
    else:
        observations.append("tasks summary: no tasks recorded")

    # Governance status summary — passive observability, not authority
    gov_summary = snapshot.get("governance_status_summary")
    if gov_summary is not None:
        gov_mode = gov_summary.get("operational_mode", "unknown")
        gov_mode_source = gov_summary.get("operational_mode_source", "unknown")
        hardened = gov_summary.get("hardened_domain_count", 0)
        revocations = gov_summary.get("active_revocation_count", 0)
        anomalies = gov_summary.get("recent_anomaly_count", 0)
        observations.append(
            f"Governance status: mode {gov_mode} (source {gov_mode_source}), "
            f"{hardened} hardened domains, {revocations} active revocations, "
            f"{anomalies} recent anomalies. "
            "This is runtime status, not MSO activity or health."
        )

    # Recent governance decisions — presence/count only, not authority
    recent_gov = snapshot.get("recent_governance")
    if recent_gov is not None:
        if len(recent_gov) == 0:
            observations.append(
                "Recent governance: no decisions recorded since backend start. "
                "This does not imply MSO inactivity."
            )
        else:
            latest = recent_gov[0]
            action = latest.get("action", "unknown")
            domain = latest.get("target_domain", "unknown")
            target_action = latest.get("target_action", "unknown")
            exec_mode = latest.get("effective_execution_mode", "unknown")
            reason = latest.get("reason") or ""
            reason_part = f" Reason: {reason}" if reason else ""
            observations.append(
                f"Recent governance: {len(recent_gov)} decision(s) shown; "
                f"latest {action} on {domain}/{target_action}, "
                f"execution mode {exec_mode}.{reason_part}"
            )

    # CODE readiness summary — passive observability, counts only, not authority.
    # Wording must never imply: ready to execute, safe to apply, authorized,
    # MSO ACTIVE, MSO HEALTHY, system healthy because online.
    code = snapshot.get("code_readiness_summary")
    if code is not None:
        api_word = "reachable" if code.get("code_api_reachable") else "unavailable"
        apply_mode = code.get("apply_execution_mode", "unknown")
        allowed = code.get("code_capability_allowed_count", 0)
        confirm = code.get("code_capability_confirm_only_count", 0)
        blocked = code.get("code_capability_blocked_count", 0)
        runner_part = ""
        if code.get("runner_backend_probed"):
            available = code.get("runner_backend_available")
            if available is True:
                runner_part = ", runner backend available"
            elif available is False:
                runner_part = ", runner backend unavailable"
            else:
                runner_part = ", runner backend unknown"
        observations.append(
            f"CODE readiness: API {api_word}, apply mode {apply_mode}, "
            f"{allowed} allow / {confirm} confirm_only / {blocked} blocked "
            f"capabilities{runner_part}. "
            "This is readiness, not execution authority."
        )
    else:
        observations.append(
            "CODE readiness: unavailable. This does not imply CODE authority."
        )

    return observations


def _build_summary(status: str, snapshot: dict[str, Any]) -> str:
    """Build a single-sentence human-readable summary."""
    mode_text = _describe_effective_mode(snapshot)

    if status == "healthy":
        return f"System observation complete — {mode_text}, all sources available."
    if status == "partial":
        warning_count = len(snapshot.get("warnings") or [])
        return (
            f"System observation partial — {mode_text}, "
            f"{warning_count} source(s) unavailable."
        )
    if status == "unavailable":
        return "System observation unavailable — all sources failed."
    return "System observation status unknown."


# ---------------------------------------------------------------------------
# Public interpreter function
# ---------------------------------------------------------------------------

def interpret_system_snapshot(snapshot: dict[str, Any]) -> SystemInterpretation:
    """Transform a read-only SystemSnapshot dict into a SystemInterpretation.

    This function is pure: identical inputs produce identical outputs.
    It does not call observe_system(), pipelines, agents, or Kernel.
    It does not modify any state.

    Args:
        snapshot: A SystemSnapshot dict as returned by observe_system().

    Returns:
        A SystemInterpretation dict. Never raises.
    """
    status = _derive_status(snapshot)
    observations = _build_observations(snapshot)
    summary = _build_summary(status, snapshot)
    warnings = list(snapshot.get("warnings") or [])

    return SystemInterpretation(
        status=status,
        summary=summary,
        observations=observations,
        warnings=warnings,
        narrative=True,
        source="system_assistant",
        execution_status=None,
    )
