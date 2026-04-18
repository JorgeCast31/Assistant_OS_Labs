"""Static policy registry and fail-closed enforcement for MACHINE_OPERATOR.

The registry is authoritative for the sovereign lane:
- N0 = read-only observation, no side effects
- N1 = bounded navigation, still no side effects
- N2 = deny-by-default placeholder for future expansion

The adapter translates; the MSO decides; OpenClaw executes; nobody crosses lanes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from .contracts import (
    MachineOperatorCapabilityPolicy,
    validate_machine_operator_request,
)


MACHINE_OPERATOR_DOMAIN = "MACHINE_OPERATOR"

CAPABILITY_BROWSER_NAVIGATE = "browser.navigate"
CAPABILITY_BROWSER_SNAPSHOT = "browser.snapshot"
CAPABILITY_BROWSER_SCREENSHOT = "browser.screenshot"
CAPABILITY_BROWSER_READ_VISIBLE_TEXT = "browser.read_visible_text"

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
    if is_dataclass(payload):
        return asdict(payload)
    if isinstance(payload, dict):
        return payload
    raise TypeError("MachineOperatorIntentRequest must be a dict or dataclass instance")


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
    capability_name = request["capability_name"]
    policy = get_machine_operator_policy(capability_name)

    if not is_machine_operator_capability_known(capability_name):
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="unknown_capability",
            message=f"Unknown MACHINE_OPERATOR capability: {capability_name}",
            policy=policy,
        )

    if not policy.allowed_by_default:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="capability_disabled",
            message=f"MACHINE_OPERATOR capability is not enabled by default: {capability_name}",
            policy=policy,
        )

    if request["capability_tier"] != policy.capability_tier:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="invalid_tier",
            message=(
                f"MACHINE_OPERATOR capability tier mismatch for {capability_name}: "
                f"expected {policy.capability_tier}, got {request['capability_tier']}"
            ),
            policy=policy,
        )

    policy_context = request["policy_context"]
    if policy_context["approval_mode"] != policy.approval_mode:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="approval_mode_mismatch",
            message=(
                f"MACHINE_OPERATOR capability approval_mode mismatch for {capability_name}: "
                f"expected {policy.approval_mode}, got {policy_context['approval_mode']}"
            ),
            policy=policy,
        )

    if policy.approval_mode == "required":
        approval_token = request.get("approval_token")
        if not isinstance(approval_token, str) or not approval_token.strip():
            return MachineOperatorEnforcementDecision(
                allowed=False,
                reason_code="missing_approval",
                message=f"MACHINE_OPERATOR capability requires approval: {capability_name}",
                policy=policy,
            )

    if policy.requires_allowlist and not policy_context.get("allowlist_refs"):
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="missing_allowlist_context",
            message=f"MACHINE_OPERATOR capability requires allowlist context: {capability_name}",
            policy=policy,
        )

    if policy.requires_secrets and not policy_context.get("secret_refs"):
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="missing_secret_context",
            message=f"MACHINE_OPERATOR capability requires secret context: {capability_name}",
            policy=policy,
        )

    requested_side_effects = request.get("requested_side_effects", [])
    if requested_side_effects and not policy.allows_side_effects:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="side_effects_not_allowed",
            message=f"MACHINE_OPERATOR capability does not permit side effects: {capability_name}",
            policy=policy,
        )

    if not policy.allows_side_effects and request["budget"]["max_side_effects"] != 0:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="side_effect_budget_not_allowed",
            message=(
                f"MACHINE_OPERATOR capability does not permit side-effect budget: "
                f"{capability_name}"
            ),
            policy=policy,
        )

    budget = request["budget"]
    if budget["max_steps"] > policy.max_steps:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="budget_exceeded",
            message=(
                f"MACHINE_OPERATOR capability budget max_steps exceeds policy for {capability_name}: "
                f"{budget['max_steps']} > {policy.max_steps}"
            ),
            policy=policy,
        )

    if budget["max_duration_ms"] > policy.max_duration_ms:
        return MachineOperatorEnforcementDecision(
            allowed=False,
            reason_code="budget_exceeded",
            message=(
                f"MACHINE_OPERATOR capability budget max_duration_ms exceeds policy for {capability_name}: "
                f"{budget['max_duration_ms']} > {policy.max_duration_ms}"
            ),
            policy=policy,
        )

    return MachineOperatorEnforcementDecision(
        allowed=True,
        reason_code="allowed",
        message=f"MACHINE_OPERATOR capability allowed: {capability_name}",
        policy=policy,
    )
