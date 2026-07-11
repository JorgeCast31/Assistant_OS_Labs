# Worker / Subagent Registry v0

Status: v0 (contract + validation only). PR #265. Describes workers/subagents/models/
tools that MAY later receive a `DelegationWorkPacket` (PR #264).

> This is a **registry, not a router**. worker profile ≠ authorization ·
> capability description ≠ permission · local model ≠ secret access · AVAILABLE ≠ executable.

## Module
`assistant_os/mso/worker_registry.py` — stdlib only. No routing, no execution, no model
calls, no external API, no token minting, no authority grants. Reuses `RiskLevel`,
`CostTier`, `TaskType` from `delegation_packet` (PR #264).

## Contract: `WorkerProfile`
Fields: `worker_id, display_name, worker_type, provider, model_family, model_name,
capabilities, preferred_task_types, forbidden_task_types, max_risk_level,
supported_cost_tiers, default_cost_tier, context_window_class, privacy_class,
tool_access, requires_human_supervision, can_execute, can_write_external,
can_access_secrets, status, audit_notes`.

Closed enums: `WorkerType`, `WorkerStatus`, `PrivacyClass`, `ContextWindowClass`
(+ `RiskLevel`/`CostTier`/`TaskType` from delegation_packet).

## Safe defaults
`can_execute=false`, `can_access_secrets=false`, `can_write_external=false`,
`requires_human_supervision=true`, `privacy_class=SECRET_PROHIBITED`, `status=DRAFT`.

## Semantics
- `validate()` fail-closed (`WorkerProfileError`); `is_valid()` → bool.
- `is_assignable()` → true only when valid AND `status==AVAILABLE`. Assignable is NOT
  execution authority.
- `to_dict()/from_dict()` deterministic and stable.

## Safety invariants
1. Invalid ⇒ fail closed. 2. `can_execute` default false. 3. `can_access_secrets` default false.
4. `can_write_external` default false. 5. Local worker ⇏ secret access. 6. AVAILABLE ⇏ executable.
7. preferred ∩ forbidden task types ⇒ invalid. 8. `default_cost_tier` must be in `supported_cost_tiers`.
9. Closed enums. 10. `capabilities` are descriptive, not permissions. 11. DISABLED/BLOCKED/DEPRECATED/DRAFT
not assignable. 12. `PREMIUM_REQUIRED` requires justification in `audit_notes`. 13. No secrets.
14. Stable JSON. 15. Deterministic. No token/capability minting.

## Future connection with DelegationWorkPacket
A later, governed routing step (NOT in this PR) could match a `DelegationWorkPacket`'s
`task_type`/`risk_level`/`cost_tier` against `WorkerProfile` fields to *suggest* candidate
workers for human review — still with no execution and no authority grant.

## Out of scope (explicitly)
No Runner, no execution, no queue/scheduler, no UI execute, no endpoint, no backend deploy,
no external API, no model calls, no routing, no capability token.
