# Handoff Envelope v0

Status: v0 (contract + validation only). PR #267. Packages a task that COULD later be
handed to a recommended worker, linking Mission Record (#262), Delegation Work Packet
(#264), Routing Recommendation (#266) and expected WorkerProfile (#265).

> handoff envelope ≠ dispatch · dispatch ≠ execution · human_approval_ref ≠ authority ·
> evidence_refs ≠ execution proof · refs, not secrets or raw contents.

## Module
`assistant_os/mso/handoff_envelope.py` — stdlib only. No dispatch, no execution, no model
calls, no external API, no Runner, no queue, no endpoint, no token minting, no authority.
`can_dispatch` and `can_execute` are hard-wired `False` (read-only properties; from_dict ignores them).

## Contract: `HandoffEnvelope`
Fields: `handoff_id, mission_id, packet_id, routing_decision_id, target_worker_id,
target_worker_type, created_at, created_by, handoff_status, objective, input_refs,
forbidden_input_refs, allowed_operations, forbidden_operations, constraints,
expected_outputs, verification_plan, acceptance_criteria, evidence_refs,
requires_human_review, human_approval_ref, expires_at, audit_notes` (+ derived `can_dispatch`,
`can_execute` = always false).

`HandoffStatus`: DRAFT, PROPOSED, READY_FOR_REVIEW, APPROVED_FOR_HANDOFF, REJECTED, RETURNED,
EXPIRED, REVOKED, COMPLETED.

## Helpers
`validate()` (fail-closed), `is_expired()`, `is_active()` (APPROVED_FOR_HANDOFF + not expired —
still not dispatchable), `is_operation_allowed()`/`is_input_allowed()` (forbidden wins),
`is_dispatchable()` (always false), `to_dict()/from_dict()`.

## Safety invariants
1. Invalid ⇒ fail closed. 2. `can_dispatch` always false. 3. `can_execute` always false. 4. Envelope ≠
capability token. 5. Grants no authority. 6. `APPROVED_FOR_HANDOFF` ⇏ dispatch. 7. `human_approval_ref`
records review but authorizes nothing. 8. Missing mission/packet/routing/target ⇒ invalid. 9. Missing
objective ⇒ invalid. 10. forbidden ops win. 11. forbidden input refs win. 12. Expired ⇒ not active.
13. `requires_human_review` default true. 14. No secrets (secret values invalidate). 15. Refs, not raw
contents (oversized field invalidates). 16. `evidence_refs` are references, not execution proof.
17. Stable JSON. 18. Deterministic. 19. No token minting. 20. No dispatch side effects.

## Future connection
A later governed **dry-run orchestration** (NOT here) could take an `APPROVED_FOR_HANDOFF` envelope,
under Police/human review, into a simulated (non-executing) run — still with no dispatch and no authority
grant in this contract.

## Out of scope (explicitly)
No Runner, dispatch, execution, queue/scheduler, UI execute, endpoint, backend deploy,
external API, model calls, capability token, authority.
