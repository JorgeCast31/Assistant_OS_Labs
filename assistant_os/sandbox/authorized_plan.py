"""
AuthorizedPlan — execution authorization binding for sandbox operations.

Every container execution in AssistantOS may be bound to an AuthorizedPlan.
The plan carries all authorization metadata required to establish:
  - Execution identity  (execution_id)
  - Plan provenance     (plan_id, authorized_plan_hash)
  - Policy binding      (policy_id, capability_scope)
  - Runtime constraints (runtime_profile)

Validation
----------
AuthorizedPlan.validate() raises ValueError for any missing or invalid field.
RunnerAPI calls validate() before any Docker work is started.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Supported runtime profiles — must mirror ALLOWED_RUNTIMES in runner_api.py.
ALLOWED_RUNTIME_PROFILES: frozenset[str] = frozenset({"python3.11"})

# Known policy identifiers.  "default" is the baseline; extend as needed.
KNOWN_POLICY_IDS: frozenset[str] = frozenset({"default", "strict", "readonly"})


@dataclass
class AuthorizedPlan:
    """
    Execution authorization binding.

    Fields
    ------
    execution_id         : Unique ID for this specific execution request.
    plan_id              : ID of the proposal/plan that authorized the execution.
    authorized_plan_hash : Deterministic hash of the plan content at auth time.
    policy_id            : Policy identifier governing allowed capabilities.
    capability_scope     : List of capability strings granted to this execution.
    runtime_profile      : Runtime identifier (must be in ALLOWED_RUNTIME_PROFILES).
    """

    execution_id: str
    plan_id: str
    authorized_plan_hash: str
    policy_id: str
    capability_scope: list[str] = field(default_factory=list)
    runtime_profile: str = "python3.11"

    def validate(self) -> None:
        """
        Validate all required fields.

        Raises
        ------
        ValueError — with a descriptive message for the first failing check.
        """
        if not self.execution_id or not self.execution_id.strip():
            raise ValueError("AuthorizedPlan.execution_id must be non-empty")
        if not self.plan_id or not self.plan_id.strip():
            raise ValueError("AuthorizedPlan.plan_id must be non-empty")
        if not self.authorized_plan_hash or not self.authorized_plan_hash.strip():
            raise ValueError("AuthorizedPlan.authorized_plan_hash must be non-empty")
        if not self.policy_id or not self.policy_id.strip():
            raise ValueError("AuthorizedPlan.policy_id must be non-empty")
        if self.policy_id not in KNOWN_POLICY_IDS:
            raise ValueError(
                f"Unknown policy_id {self.policy_id!r}. "
                f"Known policies: {sorted(KNOWN_POLICY_IDS)}"
            )
        if self.runtime_profile not in ALLOWED_RUNTIME_PROFILES:
            raise ValueError(
                f"Unsupported runtime_profile {self.runtime_profile!r}. "
                f"Allowed: {sorted(ALLOWED_RUNTIME_PROFILES)}"
            )
