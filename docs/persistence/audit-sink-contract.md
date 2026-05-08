# Audit Sink Contract

## Purpose

`S-PERSISTENCE-01-ALPHA` establishes the first operational persistence foundation for audit records. It persists audit facts for observation and replay without turning persistence into an authority boundary.

## Boundary

`AuditSink` is an emit-only protocol:

```python
class AuditSink(Protocol):
    def emit(self, record: object) -> None: ...
```

It has no read requirement and no authority methods. A sink records facts; it does not decide whether work may proceed.

## Stores

The alpha stores are append-only observation stores:

- `PoliceAuditEventStore` persists `PoliceAuditEvent`
- `CandidateAuditRecordStore` persists `CandidateAuditRecord`

`MissionEventStore` is deferred. Durable mission/event persistence belongs to a later sprint.

Each store accepts an explicit path so tests and future callers can inject file locations. Default path helpers point at `assistant_os/memory/`:

- `police_audit.jsonl`
- `candidate_audit.jsonl`

## Existing JSONL Layer

The stores wrap `assistant_os.audit.jsonl_store.JsonlAuditStore`. The previous `assistant_os.sandbox.audit_store.AuditStore` import path is now a compatibility shim that re-exports the relocated implementation.

Domain-level audit persistence must not import from `assistant_os.sandbox.*`.

## Non-Goals

This sprint does not add mutable mission persistence, SQLite, runtime wiring, MSO wiring, API routes, UI surfaces, PoliceDecision persistence, token verification, gate handling, runner integration, CODE integration, Machine Operator integration, or MissionEvent persistence.

## Authority Isolation

Persisted audit records are evidence, not permission. They can be inspected by tests and future read-only surfaces, but no store is a source of authority. Future authority checks must be performed by the dedicated Police gate and its contracts.

## Atlas

`docs/atlas` remains navigational memory. It is not operational persistence and must not be written by runtime code.
