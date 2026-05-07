# EXECUTION_CHANNELS_MAP — Execution Candidate Pipeline

> Navigational reference only. Source of truth: `tests/` + active contracts.

## Closed Contracts

| Contract | File | Status |
|---|---|---|
| MissionExecutionCandidate | [mission-execution-candidate-contract.md](../mission/mission-execution-candidate-contract.md) | ✅ Closed |

## Execution Pipeline (navigational)

```
MissionExecutionCandidate
      │  (proposed action, bounded scope, no execution yet)
      ▼
Police evaluation
      │
   ALLOW ──────────────────────────────► Agent Permission Bridge
      │                                          │
   DENY                                          ▼
      │                                   Agent executes
      ▼
   Hard stop (no fallback)
```

## Candidate Constraints

- A candidate is a proposal, not a commitment
- Candidates are stateless descriptions — they carry no side effects
- Execution only begins after Police ALLOW + token issuance
- Candidate scope must be minimal (fail-closed selection)

## Pending Extensions

| Layer | Status |
|---|---|
| Candidate audit trail | 🔲 Pending |
| CODE/Runner co-enforcement | 🔲 Pending |
| Token-bound gate (full) | 🔲 Pending |
