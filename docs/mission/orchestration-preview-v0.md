# Orchestration Preview / Dry-Run v0

Status: v0 (preview/dry-run only). PR #268. Chains `DelegationWorkPacket` (#264) +
`list[WorkerProfile]` (#265) + `RoutingRecommendation` (#266) + `HandoffEnvelope` (#267)
into a reviewable preview.

> preview ≠ dispatch · dry-run ≠ execution · recommendation ≠ authorization ·
> handoff envelope ≠ real handoff · evidence_refs ≠ proof of execution.

## Module
`assistant_os/mso/orchestration_preview.py` — stdlib only + the four sibling contracts.
No dispatch, execution, model calls, external APIs, Runner, queue, endpoint, token minting,
authority, automatic handoff, input mutation, or side effects. `can_dispatch`/`can_execute`
are hard-`False` read-only properties.

## API
- `build_orchestration_preview(packet, workers, *, created_by="mso") -> OrchestrationPreview`
- `preview_handoff(packet, workers, *, created_by="mso") -> (RoutingRecommendation, HandoffEnvelope|None, OrchestrationPreview)`
- `validate_preview(preview)` (fail-closed)

`PreviewStatus`: DRAFT, READY_FOR_REVIEW, NEEDS_HUMAN_REVIEW, NO_ELIGIBLE_WORKER, BLOCKED,
INVALID_INPUT, EXPIRED.

## Behavior
Runs routing (#266). Maps routing status → preview status: RECOMMENDED→READY_FOR_REVIEW,
NEEDS_HUMAN_REVIEW→NEEDS_HUMAN_REVIEW, NO_ELIGIBLE_WORKER→NO_ELIGIBLE_WORKER, BLOCKED_BY_*→BLOCKED,
INVALID_INPUT→INVALID_INPUT. When a worker is recommended, builds a DRAFT `HandoffEnvelope`
(`can_dispatch`/`can_execute` false); if it can't be built, fails closed to BLOCKED. `steps` lists the
chain; `evidence_refs` are pending references. Inputs are never mutated.

## Safety invariants
1. Invalid ⇒ fail closed. 2/3. `can_dispatch`/`can_execute` always false. 4. Not a Runner. 5. Not dispatch.
6. Grants no authority. 7. No model/API calls. 8. No input mutation. 9. No eligible worker ⇒ no valid handoff.
10. Routing human-review ⇒ `NEEDS_HUMAN_REVIEW`. 11. No eligible ⇒ `NO_ELIGIBLE_WORKER`. 12. Invalid input ⇒
`INVALID_INPUT`. 13. Risk block ⇒ `BLOCKED`. 14. Built envelope keeps dispatch/execute false. 15. evidence_refs
are references. 16. Refs, not raw contents. 17. No secrets in steps/reasons/warnings/blockers/audit_notes.
18. Stable JSON. 19. Deterministic. 20. No token minting. 21. No side effects.

## Future connection
Prepares a future **dry-run UI / mission inbox**: a human reviews the preview (and its envelope) before any
future governed dispatch — which remains outside this contract and still requires human review.

## Out of scope (explicitly)
No Runner, dispatch, execution, queue/scheduler, UI execute, endpoint, backend deploy, external API,
model calls, capability token, authority, automatic handoff.
