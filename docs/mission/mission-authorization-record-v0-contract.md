# Mission / Authorization Record v0 — Contract

Status: v0 (contract + validation only). PR #262. Closes groundwork for TASK-0001 **F1**
(authorization must be an auditable in-repo record, not a human-cable chat message).

## Purpose

Represent a sovereign mission / authorization as an **auditable, verifiable** object
with objective, scope, limits, required human confirmations, authority level, status,
expiry and linked evidence. A future governed path may *read* such a record; this
contract itself **executes nothing and grants no execution authority**.

> Record exists ≠ can execute. Approved ≠ executed. `can_execute` is hard-wired `False` in v0.

## Module

`assistant_os/mso/mission_record.py` — stdlib only; no imports of police, runner,
executors, policy, network, or UI.

## Fields

`mission_id, created_at, created_by, objective, reason, scope, allowed_operations,
forbidden_operations, required_human_confirmations, authority_level, status, expires_at,
linked_evidence, risk_flags, capability_requirements, execution_policy, audit_notes`.

## Closed enums

- **status**: `DRAFT, PROPOSED, HUMAN_APPROVED, REJECTED, EXPIRED, REVOKED, COMPLETED`
- **authority_level**: `NONE, READ_ONLY, LOW, MEDIUM, HIGH, SOVEREIGN`
- **execution_policy**: `NO_EXECUTION` (default), `REQUIRES_HUMAN_CONFIRMATION`, `GOVERNED_ONLY`
  — none grant execution in v0; they only *describe* intent for a later governed step.

## Semantics (helpers)

- `validate()` → fail-closed, raises `MissionRecordError` on any problem; `is_valid()` → bool.
- `is_expired()` → true once `expires_at` ≤ now.
- `is_approved()` → valid AND `HUMAN_APPROVED` AND a recorded human confirmation AND not expired.
- `is_active()` → equals `is_approved()` (expired is never active).
- `is_operation_allowed(op)` → **forbidden wins**; allowed only if in `allowed_operations` and not forbidden.
- `can_execute` → **always `False`** (contract, not a grant).
- `to_dict()/from_dict()` → JSON-stable, enum values serialized; `to_dict()` always emits `can_execute=false`.

## Safety invariants

1. Invalid record fails closed. 2. Expired ⇒ not active. 3. No human confirmation ⇒ not approved.
4. Approved ⇒ still no auto-execution. 5. No secrets (secret-like content invalidates).
6. Empty critical field ⇒ invalid. 7. allowed ∩ forbidden ⇒ invalid. 8. Forbidden overrides allowed.
9. Closed enums. 10. `NO_EXECUTION` expressible; `can_execute` stays false.

## Out of scope (explicitly)

No endpoint, no UI, no Runner, no queue/scheduler, no backend deploy, no execution,
no authority grant. Those are separate, later, governed steps.
