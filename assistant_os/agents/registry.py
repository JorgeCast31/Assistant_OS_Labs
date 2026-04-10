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
