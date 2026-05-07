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

## Pending Alpha Layers

### 1. Candidate Audit Persistence

- Durable storage for candidate audit records
- Contract-level candidate audit record is closed in `S-CANDIDATE-AUDIT-01`
- Depends on: Police persistence layer

### 2. Police Persistence

- Persist Police verdicts with enough context for audit replay
- Must not mutate Policy retroactively
- Unblocks: Candidate audit, Police showroom

### 3. Police Query / Showroom

- Read-only query interface over Police verdict history
- Operator-facing: "show me why this was denied"
- Depends on: Police persistence

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
