# Delegation / Work Packet v0

Status: v0 (contract + validation only). PR #264. Builds on the Mission contract
(PR #262). A **Delegation / Work Packet** is an auditable description of a unit of
work that MAY later be delegated — to Claude Code, Codex, GPT-MSO, a local model,
a tool, or a human — under a mission, with limits and a verification plan.

> packet exists ≠ can execute · APPROVED_FOR_HANDOFF ≠ executable · preference ≠ authorization.

## Module
`assistant_os/mso/delegation_packet.py` — stdlib only; no execution, no model call,
no external API, no auto-routing, no token minting.

## Fields
`packet_id, mission_id, created_at, created_by, task_title, objective, task_type,
target_worker, model_preference, cost_tier, risk_level, allowed_inputs,
forbidden_inputs, allowed_operations, forbidden_operations, expected_outputs,
verification_plan, acceptance_criteria, human_review_required, status, expires_at,
linked_evidence, audit_notes`.

## Closed enums
- **status**: DRAFT, PROPOSED, APPROVED_FOR_HANDOFF, IN_PROGRESS, RETURNED, REJECTED, EXPIRED, COMPLETED, REVOKED
- **target_worker**: CLAUDE_CODE, CODEX, GPT_MSO, LOCAL_MODEL, HUMAN, TOOL_ONLY, UNASSIGNED
- **task_type**: REPO_INSPECTION, CODE_PATCH, TESTING, DOCUMENTATION, SUMMARIZATION, CLASSIFICATION, PLANNING, REVIEW, EXTRACTION
- **cost_tier**: LOCAL_PREFERRED, LOW, STANDARD, HIGH, PREMIUM_REQUIRED
- **risk_level**: READ_ONLY, DOCS_ONLY, PATCH_ALLOWED, EXTERNAL_WRITE_PROHIBITED, EXTERNAL_WRITE_REQUIRES_CONFIRMATION, BLOCKED

## Semantics
- `validate()` fail-closed (raises `DelegationPacketError`); `is_valid()` → bool.
- `is_expired()`, `is_active()` (APPROVED_FOR_HANDOFF and not expired — still not executable).
- `is_operation_allowed(op)` / `is_input_allowed(x)` → forbidden wins.
- `can_execute` → always `False`; `is_auto_executable()` → always `False`.
- `to_dict()/from_dict()` stable; `to_dict()` always emits `can_execute=false`.

## Safety invariants
1. Invalid ⇒ fail closed. 2. Executes nothing. 3. Grants nothing. 4. No `mission_id` ⇒ invalid.
5. No objective ⇒ invalid. 6. No secrets (secret-like content invalidates). 7. Forbidden wins.
8. `human_review_required` defaults true. 9. `target_worker` never implies auto-execution.
10. `model_preference` is preference, not authorization. 11. `PREMIUM_REQUIRED` requires
justification in `audit_notes`. 12. Expired ⇒ not active. 13. `APPROVED_FOR_HANDOFF` ⇒ not executable.
14. Stable JSON. 15. Deterministic. No token/capability minting.

## Out of scope (explicitly)
No Runner, no execution, no queue/scheduler, no UI execute, no endpoint, no backend
deploy, no real model calls, no external API, no auto-routing, no capability token.
