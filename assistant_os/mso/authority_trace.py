"""MSO Authority Trace Read Model — S-AUTHORITY-TRACE-RECONCILIATION-01.

Provides a unified, observational read-model of the sovereign execution chain.
The trace surfaces what the MSO knows about each stage of authority processing
without calling any enforcement components.

Core invariant:
    This module is observational only. It MUST NOT:
    - issue tokens
    - call Police
    - call Runner
    - alter execution mode
    - approve or execute anything

Trace stages:
    mso_kernel → intent_contract → policy → governance → capability_token
    → police_gate → authority_artifact → runner → outcome

Police decision_ref is not currently persisted to a stable store. The trace
reports this honestly as 'not_persisted_yet' rather than fabricating a ref.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Static chain definition
# ---------------------------------------------------------------------------

AUTHORITY_CHAIN: list[str] = [
    "mso_kernel",
    "intent_contract",
    "policy",
    "governance",
    "capability_token",
    "police_gate",
    "authority_artifact",
    "runner",
    "outcome",
]

TRACE_VERSION = "1"


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_authority_trace_snapshot(
    result_or_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an observational authority trace snapshot.

    Parameters
    ----------
    result_or_context:
        Optional DomainResult or surface_behavior response dict. When supplied,
        stage details are derived from it where available. When absent (or None),
        static system-known values are used and per-request fields are reported
        as not available.

    Returns
    -------
    dict
        Trace snapshot. Never raises. Fail-soft on bad input.
    """
    ctx: dict[str, Any] = {}
    if result_or_context is not None and isinstance(result_or_context, dict):
        ctx = result_or_context

    # -- Extract common execution flags from context -------------------------
    used_execution = bool(ctx.get("used_execution", False))
    execution_allowed = bool(ctx.get("execution_allowed", False))
    can_execute_now = bool(ctx.get("can_execute_now", False))
    result_type = ctx.get("result_type") or None
    ok = ctx.get("ok")
    execution_status = ctx.get("execution_status") or None
    domain = ctx.get("domain") or None

    # -- Derive authority source/class from context data ---------------------
    data = ctx.get("data") or {}
    authority_source: str | None = data.get("authority_source") or None
    authority_class: str | None = data.get("authority_class") or None

    # If not in data, check context-level (entity_status embeds code_api info)
    if not authority_source and domain == "CODE":
        authority_source = "code_api"
        authority_class = "external_local"

    if not authority_source:
        # Default: MSO sovereign chain
        authority_source = "mso"
        authority_class = "sovereign"

    # -- Stage: request -------------------------------------------------------
    request_stage: dict[str, Any] = {
        "available": bool(ctx),
        "surface": ctx.get("surface") or ctx.get("audit", {}).get("surface") if isinstance(ctx.get("audit"), dict) else ctx.get("surface") or None,
        "intent_mode": (ctx.get("intent_metadata") or {}).get("intent_mode") or None,
        "cognition_level": (ctx.get("intent_metadata") or {}).get("cognition_level") or None,
        "execution_intent": (ctx.get("intent_metadata") or {}).get("execution_intent", False),
    }

    # -- Stage: mso -----------------------------------------------------------
    mso_stage: dict[str, Any] = {
        "kernel_boundary": True,
        "orchestrator_owned": True,
    }

    # -- Stage: policy --------------------------------------------------------
    policy_execution_mode = ctx.get("execution_mode") or execution_status or None
    policy_stage: dict[str, Any] = {
        "available": bool(policy_execution_mode),
        "execution_mode": policy_execution_mode,
        "policy_decision_ref": ctx.get("policy_decision_ref") or None,
    }

    # -- Stage: governance ----------------------------------------------------
    governance_ref = ctx.get("governance_ref") or None
    governance_stage: dict[str, Any] = {
        "available": governance_ref is not None,
        "effective_execution_mode": policy_execution_mode,
        "governance_ref": governance_ref,
        "blocked": not ok if ok is not None else False,
    }

    # -- Stage: capability ----------------------------------------------------
    capability_name = ctx.get("capability_name") or None
    token_ref = ctx.get("token_ref") or None
    capability_stage: dict[str, Any] = {
        "available": capability_name is not None,
        "capability_name": capability_name,
        "token_ref_present": token_ref is not None,
    }

    # -- Stage: police --------------------------------------------------------
    # Police is wired into the authority chain (gate_integrated=True).
    # Individual decision_ref is NOT persisted to a stable store — reported honestly.
    police_stage: dict[str, Any] = {
        "available": True,
        "gate_integrated": True,
        "permitted": None,
        "reason": None,
        "decision_ref": None,
        "decision_visibility": "not_persisted_yet",
    }

    # -- Stage: artifact ------------------------------------------------------
    artifact_stage: dict[str, Any] = {
        "available": True,
        "artifact_version": "2",
        "authority_source": authority_source,
        "authority_class": authority_class,
    }

    # -- Stage: runner --------------------------------------------------------
    runner_stage: dict[str, Any] = {
        "available": True,
        "fail_closed": True,
        "executed": used_execution,
        "blocked": not used_execution and execution_status in ("blocked", "denied"),
    }

    # -- Stage: outcome -------------------------------------------------------
    outcome_stage: dict[str, Any] = {
        "available": bool(ctx),
        "result_type": result_type,
        "ok": ok,
    }

    # -- Next safe action -----------------------------------------------------
    if used_execution:
        next_safe_action = "Inspect runner result and validate outcome"
    elif can_execute_now:
        next_safe_action = "Confirm prepared action to proceed through Police → Runner"
    else:
        next_safe_action = "Use planning mode to prepare confirmable actions; use assistant_chat for governed execution"

    return {
        "trace_version": TRACE_VERSION,
        "available": True,
        "chain": list(AUTHORITY_CHAIN),
        "last_known_stage": _infer_last_stage(ctx),
        "used_execution": used_execution,
        "execution_allowed": execution_allowed,
        "can_execute_now": can_execute_now,
        "request": request_stage,
        "mso": mso_stage,
        "policy": policy_stage,
        "governance": governance_stage,
        "capability": capability_stage,
        "police": police_stage,
        "artifact": artifact_stage,
        "runner": runner_stage,
        "outcome": outcome_stage,
        "next_safe_action": next_safe_action,
    }


def _infer_last_stage(ctx: dict[str, Any]) -> str:
    """Infer the last known stage from context, without fabrication."""
    if not ctx:
        return "mso_kernel"
    exec_status = ctx.get("execution_status") or ""
    if exec_status == "real" and ctx.get("used_execution"):
        return "outcome"
    if exec_status in ("not_executed", "stub", "unavailable"):
        return "intent_contract"
    if ctx.get("intent_metadata"):
        return "intent_contract"
    return "mso_kernel"


# ---------------------------------------------------------------------------
# Entity status descriptor
# ---------------------------------------------------------------------------


def build_authority_trace_descriptor() -> dict[str, Any]:
    """Return the static authority trace support descriptor for entity_status."""
    return {
        "supported": True,
        "trace_version": TRACE_VERSION,
        "chain": list(AUTHORITY_CHAIN),
        "police_decision_ref_embedded": False,
        "runner_fail_closed_visible": True,
    }
