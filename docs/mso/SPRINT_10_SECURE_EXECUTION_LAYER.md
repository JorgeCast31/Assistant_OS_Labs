# Sprint 10: Secure Execution Layer

## Objective

Sprint 10 hardens the Local Cognitive Worker as a restricted execution surface.

This sprint does not expand the Worker role. It narrows and traces it more aggressively.

Canonical invariants remain:

- orchestrator is still the only execution entrypoint
- kernel still issues capability and validates execution
- MSO still does not execute domain actions
- the Worker still performs bounded cognitive execution only

## Controls Added

### 1. Resource Limits

The Worker now enforces explicit execution limits:

- `timeout_ms`
- `max_operations`
- `max_input_refs`
- `max_artifact_count`
- `max_artifact_bytes`
- single-flight subprocess execution

When these limits are exceeded, execution fails closed and emits traceable security events.

### 2. Filesystem / Readable Scope Policy

Worker readable scope is now stricter:

- only structured input refs are accepted
- refs must match the bounded `kind:value` pattern
- traversal-like refs are rejected
- slash/backslash/path-style refs are rejected
- URL-like refs are rejected
- dangerous refs are not normalized into validity

This keeps the Worker on abstract references rather than filesystem reach.

### 3. Network Posture

The Worker now runs under deny-by-default task posture for network use:

- no URL refs
- no scope-based network request fields
- no socket or host request path in task scope

Residual risk:

- Sprint 10 does not implement OS-level network isolation on Windows
- instead, it implements explicit deterministic prohibition and traceable rejection

This is the strongest reliable control added in this sprint without overbuilding infrastructure.

### 4. Lifecycle Control

The subprocess runner now tracks:

- worker start
- completion
- timeout
- crash
- forced kill

The runner also maintains active-process bookkeeping and exposes current runner status for diagnostics.

Single-flight execution reduces concurrent subprocess sprawl and simplifies lifecycle cleanup.

### 5. Security Event Model

Structured worker security events are now first-class artifacts.

Current event types include:

- `worker_started`
- `worker_completed`
- `worker_timeout`
- `worker_crash`
- `worker_forced_kill`
- `invalid_input_ref`
- `scope_violation`
- `network_denied`
- `resource_limit_exceeded`

These events are:

- persisted
- attached to trace chains
- visible in diagnostics
- partially fed into anomaly posture derivation

## Diagnostics / Governance Impact

Diagnostics now exposes:

- recent worker security events
- worker lifecycle events
- runner active-process status
- persisted store counts including worker security events

Anomaly derivation now reacts to:

- repeated worker timeouts
- worker crash / forced-kill events
- repeated denied worker security events

This allows governance posture to observe worker instability or unsafe request patterns without granting the Worker new authority.

## Residual Risk

Sprint 10 improves restriction materially, but does not yet provide:

- OS-level network sandboxing
- job-object memory/CPU enforcement on Windows
- user-account isolation for the worker subprocess
- containerized or VM-based isolation

Those remain future hardening work.

## Suggested Next Hardening

- Windows Job Object limits for subprocess containment
- stronger OS-level network restriction
- dedicated worker user/token isolation
- periodic cleanup of worker runtime temp artifacts
- stricter per-operation artifact schemas
