# AUTHORITY_MAP — Authority Chain

> Navigational reference only. Source of truth: `tests/` + active contracts.

## Single Authority: MSO

The system has exactly one source of authority: **MSO (Machine Sovereign Operator)**.

No parallel authority exists. No alternative decision paths are permitted.

## Authority Chain

```
MSO
 └── Policy        (defines rules — immutable at runtime)
      └── Police   (evaluates and decides — contracts below)
           └── Agents (act under Police verdict)
                └── Pipeline / Execution
```

## Contracts by Layer

| Layer | Contract file |
|---|---|
| Police evaluation + decision | [police-core-contract.md](../police/police-core-contract.md) |
| Police token gate | [police-token-gate-contract.md](../police/police-token-gate-contract.md) |
| Agent permission bridge | [agent-permission-contract.md](../agents/agent-permission-contract.md) |
| Mission core | [mission-core-contract.md](../mission/mission-core-contract.md) |
| Mission query seam | [mission-query-seam-contract.md](../mission/mission-query-seam-contract.md) |
| Mission execution candidate | [mission-execution-candidate-contract.md](../mission/mission-execution-candidate-contract.md) |

## Forbidden Patterns

- Parallel authority (two systems both deciding)
- Bypassing Police with a direct agent call
- Soft-failing past a blocked verdict
- Mutating Policy at runtime
