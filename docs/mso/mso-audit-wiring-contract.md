# MSO Audit Wiring Contract

## Purpose

`S-MSO-ORCHESTRATION-02` adds MSO-owned audit wiring for candidate orchestration results. It connects `PoliceAuditEvent` and `CandidateAuditRecord` outputs to their typed audit stores so candidate orchestration can be observed durably.

## Router Location

`OrchestrationAuditRouter` lives in `assistant_os/mso/audit_wiring.py`, not in `assistant_os/audit/`.

The router knows both the Police audit event shape and the mission candidate audit record shape. Keeping this composition in MSO preserves the audit package as a small persistence boundary instead of turning it into cross-domain orchestration logic.

## Behavior

The router is an emit-only sink:

- `PoliceAuditEvent` is recorded by `PoliceAuditEventStore`
- `CandidateAuditRecord` is recorded by `CandidateAuditRecordStore`
- unknown record types are ignored in this sprint

`make_default_orchestration_sink(...)` builds the router from the existing audit path helpers. Tests must inject `tmp_path`; production defaults continue to point at runtime memory.

`persist_orchestration_result(...)` records only audit objects already present on `MSOCandidateOrchestrationResult`:

- `CANDIDATE_CREATED` records Police audit first, then candidate audit when present
- `DENIED` records Police audit when present
- `REQUIRES_CONFIRMATION` records Police audit when present
- `AGENT_NOT_FOUND` records nothing

## Authority Boundary

This wiring is observational persistence. It does not decide whether work may proceed, does not read stores for authority, and does not fabricate missing audit records.

It does not persist `MissionExecutionCandidate`. It does not add a candidate object store, `DurableMissionStore`, mission event store, SQLite layer, API, UI, query surface, token gate, or Police decision implementation.

## Runtime Boundary

This sprint does not run work. It does not contact runtime request handling, runner layers, CODE, external operator services, or agent callables. Candidate orchestration still stops at `MissionExecutionCandidateStatus.PENDING_GATE`.
