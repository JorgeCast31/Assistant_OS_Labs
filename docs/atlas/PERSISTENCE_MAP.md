# PERSISTENCE_MAP — Persistence Boundaries & State Ownership

> Navigational reference only. Source of truth: `tests/` + active contracts.

## State Ownership Boundaries

| State type | Owner | Location pattern | Canonical? |
|---|---|---|---|
| MSO sovereign state | MSO | `assistant_os/memory/mso_store/` | Yes — gitignored |
| Runtime memory | Assistant OS | `assistant_os/memory/` | Runtime only |
| Policy rules | Policy layer | Immutable at runtime | Yes |
| Mission definitions | Mission Core | In-memory / contract-defined | Per-session |
| Execution candidates | Mission seam | Ephemeral — pre-evaluation | No |
| Police verdicts | Police layer | Ephemeral — per-evaluation | No |
| Police audit events | Audit persistence | `assistant_os/memory/police_audit.jsonl` | Observation only |
| Candidate audit records | Audit persistence | `assistant_os/memory/candidate_audit.jsonl` | Observation only |
| Mission events | Mission persistence | Deferred | No |
| Agent permission tokens | Permission Bridge | Ephemeral — per-execution | No |
| Atlas maps | docs/atlas/ | Git-tracked | Navigational only |
| Obsidian workspace | .obsidian/ | Local disk only, gitignored | **Never canonical** |

## Persistence Invariants

- Runtime state is never committed to git (see `.gitignore`)
- MSO store is gitignored — it is not shared via version control
- Atlas maps are committed, but they describe, they do not control
- No persistence layer may mutate Policy
- `S-PERSISTENCE-01-ALPHA` audit stores are append-only observation stores
- Audit persistence does not create execution authority

## Pending

| Layer | Status |
|---|---|
| AuditSink | ✅ Alpha — emit-only boundary |
| Police audit event persistence | ✅ Alpha — append-only JSONL wrapper over JsonlAuditStore |
| Candidate audit record persistence | ✅ Alpha — append-only JSONL wrapper over JsonlAuditStore |
| Mission event persistence | 🔲 Deferred — later mission persistence sprint |
| DurableMissionStore | 🔲 Pending — no mutable mission persistence yet |
| SQLite persistence | 🔲 Pending — not introduced in alpha |
