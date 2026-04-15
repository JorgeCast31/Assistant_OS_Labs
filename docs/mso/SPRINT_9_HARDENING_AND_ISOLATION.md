# Sprint 9: Hardening and Isolation

## Objective

Sprint 9 hardens the Sprint 8 architecture without changing the canonical control model:

- the orchestrator remains the only execution entrypoint
- the kernel remains the only authority for validation and capability issuance
- the MSO remains sovereign governance, not execution
- the Worker remains bounded cognitive execution only

The goal of this sprint is narrower behavior, stronger failure boundaries, and better operator visibility.

## What Changed

### 1. Worker Isolation Hardening

`BASIC_COGNITIVE_EXECUTION` now runs through a subprocess boundary:

- orchestrator still dispatches the task
- kernel-issued capability is still mandatory
- the worker receives only structured contracts
- subprocess timeout is enforced
- worker process crash produces a bounded failure report plus escalation
- no persistent mutation path exists inside the worker boundary

The in-process worker module remains the bounded implementation core, but the orchestrator now reaches it through `assistant_os.executors.cognitive_worker_runner`.

### 2. Translator Discipline

`assistant_os.mso.translator` is now a strict translation layer, not a hidden planner.

Allowed mappings are explicit:

- `delegation_recommendation == "none"` -> passthrough canonical request
- `delegation_recommendation == "delegate_basic_cognitive_execution"` -> structured `ACTION_BASIC_COGNITIVE_EXECUTION`

The translator now rejects:

- unsupported delegation recommendations
- empty original input
- empty interpreted goal
- missing delegation task for delegated intent
- mismatched delegation task origin
- ambiguous "none + delegation task" combinations

Rejected translations produce a typed `TranslatorRejection`, are persisted, and do not dispatch the orchestrator.

### 3. Persistence Lifecycle Governance

The MSO store now wraps persisted records in metadata envelopes:

- kind
- record_id
- trace_id
- stored_at
- source_timestamp
- retention_until

The store now supports:

- persisted sovereign cycles
- persisted translator rejections
- counts by artifact type
- query by trace
- cleanup of expired records
- lifecycle status reporting for diagnostics

This keeps storage bounded without introducing a full database project.

### 4. Stronger Sovereign Bookkeeping

The runtime now records explicit sovereign cycles.

Each cycle tracks:

- `cycle_id`
- `intent_id`
- runtime decision type
- translator status
- canonical request linkage
- delegation linkage
- plan/trace linkage
- persistence refs

Current decision types:

- `respond`
- `delegate`
- `execute_through_kernel`
- `persist_only`

Successful cycles are attached back into the unified trace chain.

### 5. Diagnostics Hardening

`assistant_os.mso.diagnostics` now exposes:

- recent sovereign cycles
- recent translator rejections
- worker failures/timeouts
- store counts and cleanup status
- current operational mode
- recent anomalies
- hardened domains

This remains an internal/admin surface only.

## Safety Notes

- No natural-language execution path was added.
- The translator still cannot grant authority.
- The Worker still cannot mutate persistent state.
- The kernel still owns capability issuance and execution validation.
- The subprocess runner is a hardening step, not a new orchestrator.

## Current Limits

- worker isolation is process-based, not container-based
- retention is filesystem-backed and intentionally simple
- diagnostics are read-only and internal
- translator rejections stop before kernel dispatch by design

## Next Hardening Candidates

- stronger out-of-process worker isolation
- retention policy tuning and pruning automation
- richer operator diagnostics over persisted cycles
- stricter validation of expected output schemas by task class
