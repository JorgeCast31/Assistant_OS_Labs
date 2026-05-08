# ROADMAP_ALPHA — Pending Alpha Layers

> Navigational reference only. Source of truth: `tests/` + active contracts.
> This file describes intent, not commitment. Status changes when contracts are signed and tests pass.

## Completed (Alpha-stable baseline)

| Layer | Contract |
|---|---|
| Mission Core | [mission-core-contract.md](../mission/mission-core-contract.md) |
| Mission Query Seam | [mission-query-seam-contract.md](../mission/mission-query-seam-contract.md) |
| MissionExecutionCandidate | [mission-execution-candidate-contract.md](../mission/mission-execution-candidate-contract.md) |
| Candidate Audit Trail | [candidate-audit-contract.md](../mission/candidate-audit-contract.md) |
| PoliceEvaluation v0 | [police-core-contract.md](../police/police-core-contract.md) |
| PoliceDecision | [police-core-contract.md](../police/police-core-contract.md) |
| Agent Permission Bridge | [agent-permission-contract.md](../agents/agent-permission-contract.md) |
| S-PERSISTENCE-01-ALPHA | [audit-sink-contract.md](../persistence/audit-sink-contract.md) |
| S-MSO-ORCHESTRATION-01 | [mso-candidate-orchestration-contract.md](../mso/mso-candidate-orchestration-contract.md) |

## Pending Alpha Layers

### 1. Durable Mission Persistence

- No `DurableMissionStore` exists yet
- Must not treat audit records as mutable mission state
- Depends on: a future mission persistence contract

### 2. SQLite Persistence

- No SQLite layer exists yet
- JSONL audit persistence is the only alpha persistence added by `S-PERSISTENCE-01-ALPHA`
- Depends on: explicit storage contract

### 3. Police Query / Showroom

- Read-only query interface over Police and candidate audit history
- Operator-facing: "show me why this was denied"
- Depends on: audit persistence and future query contracts

### 3a. MSO Candidate Gate Follow-Up

- Candidate-only MSO orchestration stops at `PENDING_GATE`
- No runtime, API, UI, token gate, CODE, runner, or Machine Operator wiring exists here
- Depends on: future Police gate and Police query contracts

### 4. UI Surface

- Operator-facing UI layer consuming the Mission and Police APIs
- No direct Policy access from UI
- Depends on: Mission query seam, Police query

### 5. Token-Bound Gate (full)

- Complete token lifecycle: issuance → binding → expiry → revocation
- Currently partial — issuance exists, revocation pending
- Depends on: Police persistence

### 6. CODE/Runner Co-Enforcement

- Runner validates Police token independently before executing code
- Prevents token replay and scope escalation at execution time
- Depends on: Token-bound gate

### 7. Machine Operator Governance

- MCO (Machine Operator) role definition and authority boundaries
- Distinguishes operator actions from MSO sovereign actions
- Depends on: Authority chain stability

### 8. MCO/MSO Orchestration

- Protocol for MCO-initiated missions under MSO authority
- Prevents MCO from acting outside delegated scope
- Depends on: Machine Operator governance

## Alpha Persistence Status

`S-PERSISTENCE-01-ALPHA` adds:

- `AuditSink`
- `PoliceAuditEventStore`
- `CandidateAuditRecordStore`
- `MissionEventStore`

It does not add:

- `DurableMissionStore`
- `MissionEventStore`
- SQLite
- runtime, MSO, API, UI, token gate, CODE, runner, or Machine Operator wiring

## Sequencing Notes

```
Police persistence
      │
      ├──► Police query / showroom
      └──► Candidate audit
                │
                └──► Token-bound gate (full)
                            │
                            └──► CODE/Runner co-enforcement

Machine Operator governance
      │
      └──► MCO/MSO orchestration

UI surface  ──── parallel track, depends on query seam + police query
```
