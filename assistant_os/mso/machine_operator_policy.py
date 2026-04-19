"""Static policy registry and fail-closed enforcement for MACHINE_OPERATOR.

The registry is authoritative for the sovereign lane:
- N0 = read-only observation, no side effects
- N1 = bounded navigation, still no side effects
- N2 = deny-by-default placeholder for future expansion

The adapter translates; the MSO decides; OpenClaw executes; nobody crosses lanes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import (
    CAPABILITY_BROWSER_NAVIGATE,
    CAPABILITY_BROWSER_READ_VISIBLE_TEXT,
    CAPABILITY_BROWSER_SCREENSHOT,
    CAPABILITY_BROWSER_SNAPSHOT,
    MachineOperatorCapabilityPolicy,
    normalize_machine_operator_request,
    validate_machine_operator_request,
)


MACHINE_OPERATOR_DOMAIN = "MACHINE_OPERATOR"

_CAPABILITY_POLICIES: dict[str, MachineOperatorCapabilityPolicy] = {
    CAPABILITY_BROWSER_NAVIGATE: MachineOperatorCapabilityPolicy(
        capability_name=CAPABILITY_BROWSER_NAVIGATE,
        capability_tier="interactive",
        policy_level="N1",
        approval_mode="required",
        requires_allowlist=True,
        allows_side_effects=False,
        requires_secrets=False,
        max_steps=3,
        max_duration_ms=15000,
        allowed_by_default=True,
    ),
    CAPABILITY_BROWSER_SNAPSHOT: MachineOperatorCapabilityPolicy(
        capability_name=CAPABILITY_BROWSER_SNAPSHOT,
        capability_tier="read_only",
        policy_level="N0",
        approval_mode="none",
        requires_allowlist=True,
        allows_side_effects=False,
        requires_secrets=False,
        max_steps=2,
        max_duration_ms=8000,
        allowed_by_default=True,
    ),
    CAPABILITY_BROWSER_SCREENSHOT: MachineOperatorCapabilityPolicy(
        capability_name=CAPABILITY_BROWSER_SCREENSHOT,
        capability_tier="read_only",
        policy_level="N0",
        approval_mode="none",
        requires_allowlist=True,
        allows_side_effects=False,
        requires_secrets=False,
        max_steps=2,
        max_duration_ms=8000,
        allowed_by_default=True,
    ),
    CAPABILITY_BROWSER_READ_VISIBLE_TEXT: MachineOperatorCapabilityPolicy(
        capability_name=CAPABILITY_BROWSER_READ_VISIBLE_TEXT,
        capability_tier="read_only",
        policy_level="N0",
        approval_mode="none",
        requires_allowlist=True,
        allows_side_effects=False,
        requires_secrets=False,
        max_steps=2,
        max_duration_ms=8000,
        allowed_by_default=True,
    ),
}

_DENY_BY_DEFAULT_POLICY = MachineOperatorCapabilityPolicy(
    capability_name="",
    capability_tier="mutating",
    policy_level="N2",
    approval_mode="required",
    requires_allowlist=True,
    allows_side_effects=False,
    requires_secrets=False,
    max_steps=0,
    max_duration_ms=0,
    allowed_by_default=False,
)


@dataclass(slots=True)
class MachineOperatorEnforcementDecision:
    """Deterministic policy decision for a MACHINE_OPERATOR request."""

    allowed: bool
    reason_code: str
    message: str
    policy: MachineOperatorCapabilityPolicy


def _request_to_dict(payload: Any) -> dict[str, Any]:
    request, error = normalize_machine_operator_request(payload)
    if request is None:
        raise TypeError(error)
    return request


def _workflow_policy_capability_name(steps: list[dict[str, Any]]) -> str:
    capability_names = [str(step["capability_name"]) for step in steps]
    if len(capability_names) == 1:
        return capability_names[0]
    return "workflow:" + "->".join(capability_names)


def _workflow_policy_tier(steps: list[dict[str, Any]]) -> str:
    tiers = {str(step["capability_tier"]) for step in steps}
    if not tiers:
        raise ValueError("MACHINE_OPERATOR workflow aggregation requires at least one step.")
    unsupported_tiers = tiers - {"read_only", "interactive", "mutating"}
    if unsupported_tiers:
        raise ValueError(
            "MACHINE_OPERATOR workflow aggregation encountered unsupported capability tiers: "
            + ", ".join(sorted(unsupported_tiers))
        )
    if "mutating" in tiers:
        return "mutating"
    if "interactive" in tiers:
        return "interactive"
    return "read_only"


def _workflow_policy_level(policies: list[MachineOperatorCapabilityPolicy]) -> str:
    levels = {policy.policy_level for policy in policies}
    if not levels:
        raise ValueError("MACHINE_OPERATOR workflow aggregation requires at least one policy.")
    unsupported_levels = levels - {"N0", "N1"}
    if unsupported_levels:
        raise ValueError(
            "MACHINE_OPERATOR workflow aggregation encountered unsupported policy levels: "
            + ", ".join(sorted(unsupported_levels))
        )
    return "N1" if "N1" in levels else "N0"


def _workflow_policy_approval_mode(policies: list[MachineOperatorCapabilityPolicy]) -> str:
    approval_modes = {policy.approval_mode for policy in policies}
    if not approval_modes:
        raise ValueError("MACHINE_OPERATOR workflow aggregation requires at least one policy.")
    unsupported_modes = approval_modes - {"none", "required"}
    if unsupported_modes:
        raise ValueError(
            "MACHINE_OPERATOR workflow aggregation encountered unsupported approval modes: "
            + ", ".join(sorted(unsupported_modes))
        )
    if "required" in approval_modes:
        return "required"
    return "none"


def _build_workflow_policy(
    *,
    steps: list[dict[str, Any]],
    policies: list[MachineOperatorCapabilityPolicy],
) -> MachineOperatorCapabilityPolicy:
    if not steps or not policies or len(steps) != len(policies):
        raise ValueError(
            "MACHINE_OPERATOR workflow aggregation requires a one-to-one mapping between steps and policies."
        )
    return MachineOperatorCapabilityPolicy(
        capability_name=_workflow_policy_capability_name(steps),
        capability_tier=_workflow_policy_tier(steps),
        policy_level=_workflow_policy_level(policies),
        approval_mode=_workflow_policy_approval_mode(policies),
        requires_allowlist=any(policy.requires_allowlist for policy in policies),
        allows_side_effects=all(policy.allows_side_effects for policy in policies),
        requires_secrets=any(policy.requires_secrets for policy in policies),
        max_steps=sum(policy.max_steps for policy in policies),
        max_duration_ms=sum(policy.max_duration_ms for policy in policies),
        allowed_by_default=all(policy.allowed_by_default for policy in policies),
    )


def _step_subject(steps: list[dict[str, Any]], step_index: int) -> str:
    capability_name = str(steps[step_index]["capability_name"])
    if len(steps) == 1:
        return capability_name
    return f"step {step_index} ({capability_name})"


def list_machine_operator_capabilities() -> list[MachineOperatorCapabilityPolicy]:
    """Return the explicit MACHINE_OPERATOR capability registry."""
    return list(_CAPABILITY_POLICIES.values())


def get_machine_operator_policy(capability_name: str) -> MachineOperatorCapabilityPolicy:
    """Return the explicit policy entry or a fail-closed deny fallback."""
    policy = _CAPABILITY_POLICIES.get(capability_name)
    if policy is not None:
        return policy
    return MachineOperatorCapabilityPolicy(
        capability_name=capability_name,
        capability_tier=_DENY_BY_DEFAULT_POLICY.capability_tier,
        policy_level=_DENY_BY_DEFAULT_POLICY.policy_level,
        approval_mode=_DENY_BY_DEFAULT_POLICY.approval_mode,
        requires_allowlist=_DENY_BY_DEFAULT_POLICY.requires_allowlist,
        allows_side_effects=_DENY_BY_DEFAULT_POLICY.allows_side_effects,
        requires_secrets=_DENY_BY_DEFAULT_POLICY.requires_secrets,
        max_steps=_DENY_BY_DEFAULT_POLICY.max_steps,
        max_duration_ms=_DENY_BY_DEFAULT_POLICY.max_duration_ms,
        allowed_by_default=_DENY_BY_DEFAULT_POLICY.allowed_by_default,
    )


def is_machine_operator_capability_known(capability_name: str) -> bool:
    """Return True only for explicitly registered capabilities."""
    return capability_name in _CAPABILITY_POLICIES


def enforce_machine_operator_request(payload: Any) -> MachineOperatorEnforcementDecision:
    """Validate a MACHINE_OPERATOR request against the static fail-closed policy matrix."""

    ok, error = validate_machine_operator_request(payload)
    if not ok:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="invalid_request",
            message=error,
            policy=_DENY_BY_DEFAULT_POLICY,
        )

    request = _request_to_dict(payload)
    workflow_steps = request["workflow_steps"]
    policies: list[MachineOperatorCapabilityPolicy] = []
    for step_index, workflow_step in enumerate(workflow_steps):
        capability_name = workflow_step["capability_name"]
        policy = get_machine_operator_policy(capability_name)
        subject = _step_subject(workflow_steps, step_index)

        if not is_machine_operator_capability_known(capability_name):
            return MachineOperatorEnforcementDecision(
                allowed=False,
                reason_code="unknown_capability",
                message=f"Unknown MACHINE_OPERATOR capability at {subject}",
                policy=policy,
            )

        if not policy.allowed_by_default:
            return MachineOperatorEnforcementDecision(
                allowed=False,
                reason_code="capability_disabled",
                message=f"MACHINE_OPERATOR capability is not enabled by default at {subject}",
                policy=policy,
            )

        if workflow_step["capability_tier"] != policy.capability_tier:
            return MachineOperatorEnforcementDecision(
                allowed=False,
                reason_code="invalid_tier",
                message=(
                    f"MACHINE_OPERATOR capability tier mismatch at {subject}: "
                    f"expected {policy.capability_tier}, got {workflow_step['capability_tier']}"
                ),
                policy=policy,
            )
        policies.append(policy)

    try:
        workflow_policy = _build_workflow_policy(steps=workflow_steps, policies=policies)
    except ValueError as exc:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="invalid_request",
            message=str(exc),
            policy=_DENY_BY_DEFAULT_POLICY,
        )
    policy_context = request["policy_context"]
    if policy_context["approval_mode"] != workflow_policy.approval_mode:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="approval_mode_mismatch",
            message=(
                "MACHINE_OPERATOR workflow approval_mode mismatch: "
                f"expected {workflow_policy.approval_mode}, got {policy_context['approval_mode']}"
            ),
            policy=workflow_policy,
        )

    if workflow_policy.approval_mode == "required":
        approval_token = request.get("approval_token")
        if not isinstance(approval_token, str) or not approval_token.strip():
            return MachineOperatorEnforcementDecision(
                allowed=False,
                reason_code="missing_approval",
                message="MACHINE_OPERATOR workflow requires approval.",
                policy=workflow_policy,
            )

    if workflow_policy.requires_allowlist and not policy_context.get("allowlist_refs"):
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="missing_allowlist_context",
            message="MACHINE_OPERATOR workflow requires allowlist context.",
            policy=workflow_policy,
        )

    if workflow_policy.requires_secrets and not policy_context.get("secret_refs"):
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="missing_secret_context",
            message="MACHINE_OPERATOR workflow requires secret context.",
            policy=workflow_policy,
        )

    requested_side_effects = request.get("requested_side_effects", [])
    if requested_side_effects and not workflow_policy.allows_side_effects:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="side_effects_not_allowed",
            message="MACHINE_OPERATOR workflow does not permit side effects.",
            policy=workflow_policy,
        )

    if not workflow_policy.allows_side_effects and request["budget"]["max_side_effects"] != 0:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="side_effect_budget_not_allowed",
            message="MACHINE_OPERATOR workflow does not permit side-effect budget.",
            policy=workflow_policy,
        )

    budget = request["budget"]
    if budget["max_steps"] > workflow_policy.max_steps:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="budget_exceeded",
            message=(
                "MACHINE_OPERATOR workflow budget max_steps exceeds aggregate policy: "
                f"{budget['max_steps']} > {workflow_policy.max_steps}"
            ),
            policy=workflow_policy,
        )

    if budget["max_duration_ms"] > workflow_policy.max_duration_ms:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="budget_exceeded",
            message=(
                "MACHINE_OPERATOR workflow budget max_duration_ms exceeds aggregate policy: "
                f"{budget['max_duration_ms']} > {workflow_policy.max_duration_ms}"
            ),
            policy=workflow_policy,
        )

    if len(workflow_steps) == 1:
        return MachineOperatorEnforcementDecision(
            allowed=True,
            reason_code="allowed",
            message=f"MACHINE_OPERATOR capability allowed: {workflow_steps[0]['capability_name']}",
            policy=workflow_policy,
        )

    return MachineOperatorEnforcementDecision(
        allowed=True,
        reason_code="allowed",
        message=(
            "MACHINE_OPERATOR workflow allowed: "
            + " -> ".join(step["capability_name"] for step in workflow_steps)
        ),
        policy=workflow_policy,
    )
