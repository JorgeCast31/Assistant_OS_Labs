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
PoliceDecision    ──── ALLOW / DENY (binary, no ambiguity)
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
| Police persistence | 🔲 Pending |
| Police query / showroom | 🔲 Pending |
| Token-bound gate (full) | 🔲 Pending |
| CODE/Runner co-enforcement | 🔲 Pending |

## Police Invariants

- Decision is binary: ALLOW or DENY. Never ambiguous.
- Denial is hard-stop. No fallback execution.
- Token gate fires after decision, never before.
- Police does not modify Policy.
