# Sprint 7: Cognitive Worker Foundation

Sprint 7 creates the first explicit structural separation between:

- sovereign cognition
- deterministic control
- bounded cognitive execution

This sprint does not redesign the kernel.
It does not introduce a general agent framework.
It introduces one narrow execution tier:

- `BASIC_COGNITIVE_EXECUTION`

## Layered mapping

### Layer 1 — Sovereign Governance

- MSO
- continuity
- persistence decisions
- delegation recommendations
- user-facing sovereign representation

### Layer 2 — Deterministic Control

- kernel
- policy
- capability issuance
- governance intercept
- orchestrator

### Layer 3 — Cognitive Execution

- local cognitive worker
- structured contracts only
- bounded operations only
- explicit kernel-issued capability required

### Layer 4 — Domain Execution

- CODE
- HOST
- WORK
- FIN
- other domain pipelines

## Core contracts

Sprint 7 introduces explicit contracts in `assistant_os/mso/contracts.py`:

- `SovereignIntent`
- `DelegationTask`
- `ExecutionCapability`
- `ExecutionReport`
- `EscalationRequest`

These contracts are not free-form.
They are structured, typed, and trace-linked.

### Contract boundaries

`SovereignIntent`

- interpretive input only
- references a real request
- cannot grant permissions
- cannot act as execution authority

`DelegationTask`

- bounded worker task only
- task type must be `BASIC_COGNITIVE_EXECUTION`
- scope required
- allowed operations required
- expected output schema required

`ExecutionCapability`

- kernel-issued only
- explicit
- task-bound
- scoped
- required before worker execution

`ExecutionReport`

- worker output only
- records operations actually performed
- contains artifacts and findings
- cannot claim domain mutations

`EscalationRequest`

- worker can request more authority
- worker cannot self-approve
- always trace-linked

## Worker boundary

Module:

- `assistant_os/executors/cognitive_worker.py`

The worker is:

- local
- bounded
- subordinate
- task-bound
- non-sovereign
- non-state-mutating

Allowed operations:

- `read_system_state`
- `summarize_context`
- `classify_issue`
- `consistency_check`
- `simulate`

Forbidden by construction:

- domain execution
- persistent state mutation
- policy override
- governance override
- sovereign memory persistence
- implicit permission inheritance

## Insertion point

The canonical insertion point remains:

- `assistant_os/core/orchestrator.py`

The orchestrator now recognizes `ACTION_BASIC_COGNITIVE_EXECUTION` and:

1. validates governance as usual
2. validates sovereign/delegation contracts
3. issues an explicit execution capability
4. dispatches to the worker
5. receives `ExecutionReport`
6. records `EscalationRequest` when needed
7. returns a canonical `DomainResult`

The worker is not independently routable.
The orchestrator remains the only structural execution entrypoint.

## Trace continuity

`assistant_os/mso/trace_aggregator.py` now links:

- sovereign intent
- delegation task
- execution capability
- execution report
- escalation request

This preserves end-to-end reconstructability:

MSO intent -> kernel-issued task/capability -> worker report -> sovereign evaluation

## Current limits

- worker execution is local and in-process for Sprint 7
- no persistent worker memory exists
- no background scheduling exists
- no general tool-use framework exists
- no direct natural-language worker execution path exists
- no domain mutation path exists through the worker

## Sprint 8 candidates

- durable audit persistence for worker contracts
- explicit sovereign-to-kernel delegation translation helpers
- richer capability issuance policy for worker scopes
- isolated worker runtime boundary beyond module-level separation
- admin visibility for worker reports and escalations
