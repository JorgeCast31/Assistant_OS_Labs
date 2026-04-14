# Sprint 4: MSO System Presence Foundation

Sprint 4 introduces the first real internal MSO presence layer.

The goal is not autonomy. The goal is governed visibility.

## What exists now

### 1. Task Registry

Module:

- `assistant_os/mso/task_registry.py`

Tracks internal task records with these lifecycle states:

- `active`
- `pending`
- `completed`
- `failed`
- `blocked`

Each task record links, when available, to:

- `context_id`
- `trace_id`
- `plan_id`
- `domain`
- `last_known_action`
- `execution_mode`
- advisory trace ref
- deterministic decision trace ref

### 2. Trace Aggregation

Module:

- `assistant_os/mso/trace_aggregator.py`

Builds a coherent chain over existing architecture:

- request text
- advisory trace
- deterministic decision trace
- execution metadata
- final `DomainResult`

This layer does not redesign tracing. It consolidates it.

### 3. System State Snapshot

Module:

- `assistant_os/mso/system_state.py`

Builds an internal snapshot with:

- active tasks
- pending tasks
- blocked tasks
- recent task transitions
- recent deterministic decisions
- running execution ids
- domain status summary
- minimal agent/component summary
- recent trace chain refs

### 4. Minimal Governance Surface

Module:

- `assistant_os/mso/governance_surface.py`

Provides internal read functions for questions like:

- what is active now?
- what is pending?
- what just failed?
- what is the current high-level system state?
- what trace chain belongs to this task/plan?

## Integration point

The integration remains conservative:

- `assistant_os/core/orchestrator.py` is still the canonical executor
- MSO modules observe and register lifecycle events
- no domain pipeline surrendered control
- no advisory output became authoritative

Publishing now happens from the orchestrator at the safe boundary where it already knows:

- request
- plan
- policy execution mode
- advisory trace
- final `DomainResult`

## Publication model

For each orchestrated request:

1. A deterministic decision trace is created.
2. A task record is registered.
3. A trace chain is opened.
4. If execution occurs, the final result is attached and the task transitions to:
   - `completed`, or
   - `failed`
5. If execution does not occur, the task remains:
   - `pending`, or
   - `blocked`

## Important limits

- This is in-memory state for now.
- There is no autonomous loop.
- There is no final user-facing MSO conversational surface yet.
- Agent status is intentionally conservative and derived from observable workload, not fake heartbeats.

## Suggested Sprint 5 direction

- persist task/trace state to a durable store
- expose a diagnostics endpoint or internal admin surface
- connect runner/code execution metadata more deeply into the same trace chain
- add explicit retention/cleanup policy for state history
