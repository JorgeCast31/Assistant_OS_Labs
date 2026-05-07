# MISSION_MAP — Mission Lifecycle & Seam Architecture

> Navigational reference only. Source of truth: `tests/` + active contracts.

## Closed Contracts

| Contract | File | Status |
|---|---|---|
| Mission Core | [mission-core-contract.md](../mission/mission-core-contract.md) | ✅ Closed |
| Mission Query Seam | [mission-query-seam-contract.md](../mission/mission-query-seam-contract.md) | ✅ Closed |
| MissionExecutionCandidate | [mission-execution-candidate-contract.md](../mission/mission-execution-candidate-contract.md) | ✅ Closed |

## Mission Lifecycle (navigational)

```
Operator input
      │
      ▼
Mission Core     ──── defines intent, scope, constraints
      │
      ▼
Query Seam       ──── translates mission into queryable form
      │
      ▼
ExecutionCandidate ── selects candidate action for Police evaluation
      │
      ▼
Police           ──── ALLOW / DENY
      │
      ▼
Pipeline / Agent execution
```

## Seam Architecture

The Query Seam is the explicit boundary between mission definition and execution selection. It prevents mission intent from leaking directly into execution logic.

- Mission Core does not know about candidates
- Candidates do not know about Policy rules
- Police knows neither — it only sees the candidate and Policy

## Pending

| Layer | Status |
|---|---|
| Candidate audit trail | 🔲 Pending |
| MCO/MSO orchestration layer | 🔲 Pending |
