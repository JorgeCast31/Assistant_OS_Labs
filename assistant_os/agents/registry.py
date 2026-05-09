"""
agents/registry.py — Agent registry for AssistantOS.

WHAT IS AN AGENT HERE
---------------------
An agent is a named, versioned execution unit with an explicit contract.
It owns a single capability boundary: one entrypoint, one input type,
one output type, one domain.

WHAT AN AGENT IS NOT
--------------------
- Not an autonomous loop.
- Not a planner or decision-maker.
- Not a replacement for domain pipelines.
- Not an LLM wrapper.

Agents formalize WHERE execution crosses a boundary (pipeline → runner)
and make that crossing inspectable, testable, and replaceable without
touching domain logic.

REGISTRY ROLE
-------------
AGENT_REGISTRY is the single source of truth for what agents exist.
Nothing outside this module instantiates agents directly.
get_agent() is the only public accessor — it validates before returning.

AgentDefinition fields
----------------------
name             : str        — unique identifier, matches registry key
domain           : str        — domain this agent serves ("CODE", "WORK", "FIN")
version          : str        — semver string
description      : str        — human-readable capability summary
input_contract   : str        — type name of expected input
output_contract  : str        — type name of expected output
requires_review  : bool       — whether execution output requires human review
capability_scope : list[str]  — declared capabilities this agent exercises
entrypoint       : callable   — the function to call; must accept (request) -> result

Validation
----------
get_agent() calls _validate_agent_definition() before returning.
Missing required fields raise ValueError immediately — no silent failures.

Required fields (operational minimum):
    name, entrypoint, input_contract, output_contract
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List
from uuid import uuid4

from ..police.enforcement import check
from ..police.gate_models import PoliceGateRequest, PoliceOutcome


# ---------------------------------------------------------------------------
# AgentDefinition type alias — plain dict, zero runtime overhead.
# The structure is enforced by _validate_agent_definition at access time.
# ---------------------------------------------------------------------------

AgentDefinition = Dict[str, Any]

# Fields that MUST be present for an agent to be valid.
_REQUIRED_FIELDS: tuple[str, ...] = (
    "name",
    "entrypoint",
    "input_contract",
    "output_contract",
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_agent_definition(agent: AgentDefinition, registry_key: str) -> None:
    """Raise ValueError if *agent* is missing any required field.

    Called by get_agent() before every return so callers always receive
    a structurally valid definition or an explicit error — never a partial dict.

    Args:
        agent        : The AgentDefinition dict to validate.
        registry_key : The key used to look it up (for the error message).

    Raises:
        ValueError — with a descriptive message listing missing fields.
    """
    missing = [f for f in _REQUIRED_FIELDS if f not in agent or agent[f] is None]
    if missing:
        raise ValueError(
            f"Agent {registry_key!r} is registered but has missing required fields: "
            f"{missing}. "
            f"Every agent must declare: {list(_REQUIRED_FIELDS)}."
        )
    if not callable(agent["entrypoint"]):
        raise ValueError(
            f"Agent {registry_key!r}: 'entrypoint' must be callable, "
            f"got {type(agent['entrypoint']).__name__!r}."
        )


# ---------------------------------------------------------------------------
# Agent implementations
# ---------------------------------------------------------------------------


def _code_executor_entrypoint(request: Any) -> Any:
    """Execute a RunnerExecutionRequest via the audited runner.

    Contract
    --------
    Input : RunnerExecutionRequest
    Output: RunnerExecutionResult

    Thin named boundary — delegates to RunnerBackedExecutor without altering
    execution logic.  Import is deferred to avoid circular imports at load time.
    """
    from ..executors.runner_backed_executor import RunnerBackedExecutor
    return RunnerBackedExecutor().execute(request)


def _host_launcher_entrypoint(request: Any) -> Any:
    """Launch a host application via the controlled HOST executor.

    Contract
    --------
    Input : HostActionRequest
    Output: HostActionResult

    S-POLICE-CORE-03: Before delegating to execute_host_action, validate that
    the request has proper authorization context via the Police Gate.

    Direct-call requests (registry → entrypoint) lack MSO governance context
    (token_ref, governance_ref, policy_decision_ref, binding_ref) and are
    therefore fail-closed by the Police Gate.

    Delegates to execute_host_action only if Police permits.
    All invariant enforcement (confirmed, ACTIVE, allowlist, audit) lives
    in host_agent.execute_host_action — this is a thin named boundary only.
    Import is deferred to avoid circular imports at load time.
    """
    from .host_agent import HostActionResult, execute_host_action

    # S-POLICE-CORE-03: Police Gate check before execution
    # Direct-call requests have no authorization context; Police Gate will DENY.
    police_request = PoliceGateRequest(
        execution_id=request.execution_id,
        operation_key="op.host_execute",
        token_ref=None,  # Not available in direct-call path
        binding_ref=None,  # Not available in direct-call path
        authorized_plan_ref=None,  # Not available in direct-call path
        capability_name=f"host.{request.action}",
        governance_ref=None,  # Not available in direct-call path
        policy_decision_ref=None,  # Not available in direct-call path
        trace_id=str(uuid4()),
    )

    police_decision = check(police_request)

    # Fail-closed: if Police does not PERMIT, return error result without executing
    if police_decision.outcome != PoliceOutcome.PERMITTED:
        return HostActionResult(
            ok=False,
            action=request.action,
            execution_id=request.execution_id,
            error=f"Police Gate rejected execution: {police_decision.reason.value} — {police_decision.detail}",
            error_code=None,  # Generic rejection; specific error_code is host_agent responsibility
        )

    return execute_host_action(request)


def _machine_operator_entrypoint(request: Any) -> Any:
    """Execute a bounded browser capability via the MACHINE_OPERATOR pipeline.

    Contract
    --------
    Input : machine_operator_request dict (capability_name, arguments, policy_context, budget, …)
    Output: DomainResult

    S-POLICE-CORE-03: Before delegating to the MACHINE_OPERATOR pipeline, validate
    that the request has proper authorization context via the Police Gate.

    Direct-call requests (registry → entrypoint) lack MSO governance context
    (token_ref, governance_ref, policy_decision_ref, binding_ref) and are
    therefore fail-closed by the Police Gate.

    Wraps the raw request into the canonical plan envelope and delegates
    to the MACHINE_OPERATOR domain pipeline without altering any control logic.
    Only delegates if Police permits.
    Import is deferred to avoid circular imports at load time.
    """
    from ..contracts import (
        ACTION_MACHINE_OPERATOR_EXECUTE,
        RESULT_TYPE_MACHINE_OPERATOR_ACTION,
        make_domain_result,
    )
    from ..pipelines.machine_operator_pipeline import execute as _mo_execute

    # S-POLICE-CORE-03: Police Gate check before execution
    # Direct-call requests have no authorization context; Police Gate will DENY.
    capability_name = request.get("capability_name", "machine_operator.unknown")
    police_request = PoliceGateRequest(
        execution_id=request.get("execution_id", str(uuid4())),
        operation_key="op.machine_operator_execute",
        token_ref=None,  # Not available in direct-call path
        binding_ref=None,  # Not available in direct-call path
        authorized_plan_ref=None,  # Not available in direct-call path
        capability_name=capability_name,
        governance_ref=None,  # Not available in direct-call path
        policy_decision_ref=None,  # Not available in direct-call path
        trace_id=str(uuid4()),
    )

    police_decision = check(police_request)

    # Fail-closed: if Police does not PERMIT, return error DomainResult without executing
    if police_decision.outcome != PoliceOutcome.PERMITTED:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_MACHINE_OPERATOR_ACTION,
            domain="MACHINE_OPERATOR",
            message=f"Police Gate rejected execution: {police_decision.reason.value}",
            error={
                "type": "police_gate_denied",
                "message": police_decision.detail,
            },
        )

    plan = {
        "action": ACTION_MACHINE_OPERATOR_EXECUTE,
        "domain": "MACHINE_OPERATOR",
        "domain_payload": {"machine_operator_request": request},
    }
    return _mo_execute(plan, context_id="agent_registry")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

AGENT_REGISTRY: Dict[str, AgentDefinition] = {
    "code_executor": {
        # Identity
        "name":        "code_executor",
        "domain":      "CODE",
        "version":     "1.0.0",
        "description": "Executes CODE proposals through the audited runner pipeline.",
        # Contract — what this agent consumes and produces
        "input_contract":  "RunnerExecutionRequest",
        "output_contract": "RunnerExecutionResult",
        # Review policy — runner can return needs_review; human decision required
        "requires_review": True,
        # Capability scope — aligned with AuthorizedPlan defaults for the CODE domain
        "capability_scope": ["code_execute"],
        # Entrypoint — the only callable surface
        "entrypoint": _code_executor_entrypoint,
    },
    "host_launcher": {
        # Identity
        "name":        "host_launcher",
        "domain":      "HOST",
        "version":     "1.0.0",
        "description": (
            "Launches allowed host applications (notepad, calc) under strict "
            "control: confirmed gate, ACTIVE status gate, allowlist resolution, "
            "intent/outcome audit, and in-flight registration for kill_switch."
        ),
        # Contract — what this agent consumes and produces
        "input_contract":  "HostActionRequest",
        "output_contract": "HostActionResult",
        # Review policy — host launches are operator-controlled; no async review queue
        "requires_review": False,
        # Capability scope — host_launch_app declares the OS-level capability
        "capability_scope": ["host_launch_app"],
        # Entrypoint — the only callable surface
        "entrypoint": _host_launcher_entrypoint,
    },
    "machine_operator": {
        # Identity
        "name":        "machine_operator",
        "domain":      "MACHINE_OPERATOR",
        "version":     "1.0.0",
        "description": (
            "Executes bounded browser capabilities (snapshot, screenshot, "
            "read_visible_text, navigate) under strict policy control: "
            "contract validation, capability-tier enforcement, policy gate, "
            "and adapter-level execution with full audit trail."
        ),
        # Contract — what this agent consumes and produces
        "input_contract":  "MachineOperatorRequest",
        "output_contract": "DomainResult",
        # Review policy — read-only capabilities are auto-approved; navigate requires explicit approval
        "requires_review": False,
        # Capability scope — all allowed browser capabilities declared
        "capability_scope": [
            "browser.snapshot",
            "browser.screenshot",
            "browser.read_visible_text",
            "browser.navigate",
        ],
        # Entrypoint — the only callable surface
        "entrypoint": _machine_operator_entrypoint,
    },
}


# ---------------------------------------------------------------------------
# Public accessor
# ---------------------------------------------------------------------------


def get_agent(name: str) -> AgentDefinition:
    """Return the validated AgentDefinition for *name*.

    Validates required fields before returning.  Callers always receive
    a structurally complete definition or an explicit exception.

    Raises
    ------
    KeyError  — agent not registered.
    ValueError — agent registered but structurally incomplete.
    """
    try:
        agent = AGENT_REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"Agent {name!r} not found. "
            f"Registered agents: {list(AGENT_REGISTRY)}"
        ) from None

    _validate_agent_definition(agent, name)
    return agent


def list_agents() -> list[AgentDefinition]:
    """Return all validated agents in stable registry order."""
    return [get_agent(name) for name in sorted(AGENT_REGISTRY)]
