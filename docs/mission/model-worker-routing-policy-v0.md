# Model / Worker Routing Policy v0

Status: v0 (recommendation policy only). PR #266. Evaluates a `DelegationWorkPacket`
(#264) against `list[WorkerProfile]` (#265) to produce a `RoutingRecommendation`.

> policy ≠ router · recommendation ≠ authorization · available worker ≠ executable ·
> local model ≠ automatic secret access · cost preference ≠ permission.

## Module
`assistant_os/mso/routing_policy.py` — stdlib only. No execution, no model calls, no
external APIs, no Runner, no queue, no endpoint, no token minting, no authority,
no automatic handoff. `can_execute` is always `False`.

## API
- `recommend_worker(packet, workers) -> RoutingRecommendation`
- `eligible_workers(packet, workers) -> list[WorkerProfile]`
- `explain_worker_mismatch(packet, worker) -> list[str]`

`RoutingStatus`: RECOMMENDED, NO_ELIGIBLE_WORKER, BLOCKED_BY_RISK, BLOCKED_BY_PRIVACY,
BLOCKED_BY_COST, BLOCKED_BY_STATUS, NEEDS_HUMAN_REVIEW, INVALID_INPUT.

## Heuristics (v0)
- Worker must be `is_assignable()` (AVAILABLE) — DRAFT/DISABLED/BLOCKED/DEPRECATED excluded.
- `forbidden_task_types` wins over `preferred_task_types`.
- packet `cost_tier` must be in worker `supported_cost_tiers`.
- packet `risk_level` rank must be ≤ worker `max_risk_level` rank; `BLOCKED` risk blocks globally.
- Privacy: `forbidden_inputs` containing `cloud`/`external` requires a LOCAL_MODEL worker;
  `allowed_inputs` containing `secrets` requires a worker that can handle secret context
  (`can_access_secrets` and not `SECRET_PROHIBITED`).
- `LOCAL_PREFERRED`/local requirement favors `LOCAL_MODEL` among eligible workers.
- `PREMIUM_REQUIRED` cost or `EXTERNAL_WRITE_REQUIRES_CONFIRMATION` risk ⇒ `NEEDS_HUMAN_REVIEW`.
- No eligible worker ⇒ `NO_ELIGIBLE_WORKER` (never an unsafe fallback).

## Safety invariants
1. Invalid/impossible ⇒ fail closed (`INVALID_INPUT` / blocked). 2. `can_execute` always false.
3. Recommendation ≠ authorization. 4. `recommended_worker_id` ⇏ automatic handoff. 5. Non-assignable
workers never recommended. 6. Secret-incompatible worker blocked when packet needs secret context.
7. forbidden beats preferred. 8. cost must be supported. 9. PREMIUM ⇒ human review. 10. risk BLOCKED blocks.
11. external-write-confirmation ⇒ human review. 12. local preference favors local. 13. capabilities are
descriptive. 14. no unsafe fallback. 15. no secrets in output. 16. stable JSON. 17. deterministic.
18. no token/capability minting.

## Future connection
A later governed step (NOT here) could take a `RECOMMENDED`/`NEEDS_HUMAN_REVIEW` recommendation into a
human-reviewed dry-run/handoff — still with no execution and no authority grant in this policy.

## Out of scope (explicitly)
No Runner, execution, queue/scheduler, UI execute, endpoint, backend deploy, external API,
model calls, operational routing, capability token, authority.
