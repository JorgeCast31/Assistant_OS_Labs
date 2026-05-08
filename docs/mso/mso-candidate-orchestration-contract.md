# MSO Candidate Orchestration Contract

## Purpose

This contract defines the first MSO-owned candidate orchestration seam. It receives a bounded candidate request with an existing `mission_id`, derives an agent permission profile, asks Police for a `PoliceEvaluation`, and stops after creating a `MissionExecutionCandidate` only when Police returns `ALLOW`.

## Authority Boundary

MSO remains the orchestrator, not an executor. This seam does not run domain work, call runtime request handling, contact API/UI surfaces, or enter any agent callable boundary.

## Stop State

The candidate stops at `MissionExecutionCandidateStatus.PENDING_GATE`. The MSO result outcome is `CANDIDATE_CREATED`.

`ALLOW` creates:

- `MissionExecutionCandidate`
- `CandidateAuditRecord`

`DENY` and `REQUIRES_CONFIRMATION` create no candidate and no candidate audit.

`AGENT_NOT_FOUND` is a structured fail-closed outcome for unknown or misconfigured agents. It emits no audit and does not fabricate a Police record.

## Result Object

The MSO result returns frozen live domain objects, not scalar refs only:

- `PoliceEvaluation`
- `PoliceAuditEvent`
- `MissionExecutionCandidate`
- `CandidateAuditRecord`

Persistence must not be used to reconstruct objects that were just created in the same call.

## AuditSink

`AuditSink` is mandatory and emit-only. The seam emits a `PoliceAuditEvent` first and emits a `CandidateAuditRecord` second only for `ALLOW`.

Persistence is observation, not authority. The seam never reads audit storage to decide what to do.

## Future Layers

PoliceDecision and token-gate verification are future layers. Runner, CODE, and Machine Operator work are also future layers.

## Runtime Isolation

`run_mso_cycle(...)` remains untouched. This seam is separate from the current runtime cycle and is not wired into existing execution paths.
