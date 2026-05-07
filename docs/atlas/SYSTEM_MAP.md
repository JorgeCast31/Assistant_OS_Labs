# SYSTEM_MAP — Layer Closure Status

> Navigational reference only. Source of truth: `tests/` + active contracts.

## Closed Layers (Alpha-stable)

| Layer | Contract | Status |
|---|---|---|
| Mission Core | [mission-core-contract.md](../mission/mission-core-contract.md) | ✅ Closed |
| Mission Query Seam | [mission-query-seam-contract.md](../mission/mission-query-seam-contract.md) | ✅ Closed |
| MissionExecutionCandidate | [mission-execution-candidate-contract.md](../mission/mission-execution-candidate-contract.md) | ✅ Closed |
| PoliceEvaluation v0 | [police-core-contract.md](../police/police-core-contract.md) | ✅ Closed |
| PoliceDecision contract | [police-core-contract.md](../police/police-core-contract.md) | ✅ Closed |
| Agent Permission Bridge | [agent-permission-contract.md](../agents/agent-permission-contract.md) | ✅ Closed |

## Pending Alpha Layers

See [ROADMAP_ALPHA.md](ROADMAP_ALPHA.md) for detail.

| Layer | Status |
|---|---|
| Candidate audit | 🔲 Pending |
| Police persistence | 🔲 Pending |
| Police query / showroom | 🔲 Pending |
| UI surface | 🔲 Pending |
| Token-bound gate | 🔲 Pending |
| CODE/Runner co-enforcement | 🔲 Pending |
| Machine Operator governance | 🔲 Pending |
| MCO/MSO orchestration | 🔲 Pending |

## System Invariants

- Fail-closed: uncertain execution is blocked, never assumed
- Single authority source: MSO
- No bypass of Policy → Police → Pipeline chain
- No mocks in production paths
