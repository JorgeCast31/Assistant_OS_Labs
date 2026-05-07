# AGENTS_MAP — Agent Permission Bridge

> Navigational reference only. Source of truth: `tests/` + active contracts.

## Closed Contracts

| Contract | File | Status |
|---|---|---|
| Agent Permission Bridge | [agent-permission-contract.md](../agents/agent-permission-contract.md) | ✅ Closed |

## Agent Permission Flow (navigational)

```
Police verdict: ALLOW
      │
      ▼
Agent Permission Bridge  ──── translates verdict into agent-scoped permission
      │
      ▼
Agent receives bounded permission token
      │
      ▼
Agent executes within permitted scope only
```

## Bridge Invariants

- Agents receive permission tokens, never raw Policy objects
- Permission scope is bounded to the evaluated candidate
- A new candidate requires a new Police evaluation — tokens do not carry over
- Agents cannot escalate their own permissions

## Pending

| Layer | Status |
|---|---|
| Machine Operator governance | 🔲 Pending |
| MCO/MSO orchestration | 🔲 Pending |
