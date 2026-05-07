# POLICE_MAP — Police Evaluation & Decision Layers

> Navigational reference only. Source of truth: `tests/` + active contracts.

## Closed Contracts

| Contract | File | Status |
|---|---|---|
| PoliceEvaluation v0 | [police-core-contract.md](../police/police-core-contract.md) | ✅ Closed |
| PoliceDecision | [police-core-contract.md](../police/police-core-contract.md) | ✅ Closed |
| PoliceTokenGate | [police-token-gate-contract.md](../police/police-token-gate-contract.md) | ✅ Closed |

## Evaluation Flow (navigational)

```
Incoming request
      │
      ▼
PoliceEvaluation  ──── reads Policy rules (immutable)
      │
      ▼
PoliceDecision    ──── permitted / denied / deferred (token-bound gate vocabulary)
      │
      ▼
TokenGate         ──── verifies token binding before execution
      │
      ▼
Agent / Pipeline
```

## Pending Extensions

| Layer | Status |
|---|---|
| Candidate audit persistence | 🔲 Pending |
| Police persistence | 🔲 Pending |
| Police query / showroom | 🔲 Pending |
| Token-bound gate (full) | 🔲 Pending |
| CODE/Runner co-enforcement | 🔲 Pending |

## Police Invariants

- PoliceEvaluation vocabulary: ALLOW / DENY / REQUIRES_CONFIRMATION.
- PoliceDecision vocabulary: permitted / denied / deferred.
- PoliceEvaluation.ALLOW is not execution authorization.
- PoliceDecision.permitted is the future token-bound gate result.
- PoliceEvaluation and PoliceDecision vocabularies must never be collapsed.
- Denial is hard-stop. No fallback execution.
- Token gate fires after decision, never before.
- Police does not modify Policy.
