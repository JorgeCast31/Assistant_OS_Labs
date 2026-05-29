# Sprint #226 — Draft Persistence DESIGN ONLY

> Date: 2026-05-28
> Status: DESIGN — No implementation. No code changes.
> Prerequisite: Sprint #225 design approved. D-01 through D-07 resolved by Jorge.
> Principle: MSO is the only source of executable authority.
> Truth before power. Order before speed. MSO before execution.

---

## Preamble

This document designs the Draft Store — the persistence layer for Plans in
`draft` and `planning` state. It incorporates all decisions resolved by Jorge
in D-01 through D-07.

The Draft Store is not an execution surface. It does not affect the authority
chain. It does not connect to MSO, Police, Runner, or any token-issuing module.
It is operator-layer infrastructure: a durable scratchpad for operator intent
before MSO sees anything.

Approval of this document gates Sprint #227 (Draft Store Implementation).

---

## 1. Decisiones de Jorge incorporadas

| Decision | Resolution |
|---|---|
| D-01 plan_id format | `plan_<timestamp_ms>_<uuid4_short>` — approved |
| D-02 cancelled state | Not approved. States: `draft`, `planning`, `mso_review` only. Draft abandoned silently. Planning abandoned with audit log entry. mso_review is terminal — new Plan required for changes. |
| D-03 Draft Store location | SQLite local, co-located with existing `MEMORY_DIR` infrastructure |
| D-04 escalation confirmation UX | Explicit operator confirmation required. UI must warn that Plan will be frozen. |
| D-05 schema versioning | `schema_version: "1"` mandatory. Fail-closed on unknown version. No formal migration system pre-ALFA. |
| D-06 target_actions | Free-form list of strings. Not bound to capability registry in ALFA. |
| D-07 UI badge | Design now. Implement only when Draft Persistence exists. Shows only `draft`, `planning`, `mso_review`. Never: `running`, `executing`, `completed`, `approved`, `authorized`. |

---

## 2. Por qué SQLite y no JSON-per-file

The existing `mso_store` uses a file-per-record JSON pattern
(`assistant_os/storage/mso_store.py`). That pattern is appropriate for
append-only event records (cycles, escalations, tokens) where each record is
written once and read occasionally.

Plans are different:

- A draft is **mutated repeatedly** before escalation (title, intent, notes, state).
- Concurrent writes from UI interactions require **row-level locking**, which
  file-per-record JSON cannot provide without complex file locking.
- Plans need **atomic state transitions** (e.g., `draft → planning` must not
  produce a half-written record).
- Future queries ("show all plans in `planning` state") are **unacceptably slow**
  against a directory of JSON files without indexing.

SQLite provides all of these with zero network dependency, zero service
dependency, and a single file on disk — consistent with the project's
local-first posture.

The Draft Store SQLite file lives at:

```
MEMORY_DIR / "draft_store" / "plans.db"
```

Rationale: `MEMORY_DIR` (`assistant_os/memory/`) is already the canonical
location for all persistent local state. The `draft_store/` subdirectory keeps
the Draft Store isolated from `mso_store/` (which holds authority-chain records)
without ambiguity.

**The Draft Store file must never be placed in `mso_store/`.** That directory
holds authority artifacts. Plans are pre-authority.

---

## 3. Schema de la tabla `plans`

```sql
CREATE TABLE IF NOT EXISTS plans (
    plan_id          TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    intent_summary   TEXT NOT NULL,
    domain           TEXT NOT NULL,
    state            TEXT NOT NULL CHECK (state IN ('draft', 'planning', 'mso_review')),
    risk_level       TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'critical') OR risk_level IS NULL),
    target_actions   TEXT NOT NULL DEFAULT '[]',   -- JSON array of strings
    notes            TEXT,
    operator_seat    TEXT NOT NULL,
    schema_version   TEXT NOT NULL DEFAULT '1',
    created_at       TEXT NOT NULL,                -- ISO 8601 UTC
    updated_at       TEXT NOT NULL                 -- ISO 8601 UTC
);
```

**Index:**

```sql
CREATE INDEX IF NOT EXISTS idx_plans_state ON plans (state);
CREATE INDEX IF NOT EXISTS idx_plans_operator_seat ON plans (operator_seat);
CREATE INDEX IF NOT EXISTS idx_plans_created_at ON plans (created_at);
```

**Notes:**

- `target_actions` is stored as a JSON array string. Deserialized on read. Never
  parsed for execution logic.
- `state` has a CHECK constraint. The database rejects any value not in the
  permitted set. This enforces the state invariant at the persistence layer, not
  just the application layer.
- `schema_version` defaults to `'1'`. Any read of a record with an unknown
  schema_version must fail closed (raise, not silently coerce).
- No `cancelled` column. No `executing`, `approved`, `running` columns. Their
  absence is intentional and must be preserved.

---

## 4. Audit log table `plan_audit`

Plans in `planning` state that are abandoned require an audit log entry
(per D-02 resolution). This table also records all state transitions for
traceability.

```sql
CREATE TABLE IF NOT EXISTS plan_audit (
    audit_id     TEXT PRIMARY KEY,      -- audit_<timestamp_ms>_<uuid4_short>
    plan_id      TEXT NOT NULL,
    event        TEXT NOT NULL,         -- see permitted events below
    from_state   TEXT,
    to_state     TEXT,
    operator_seat TEXT NOT NULL,
    occurred_at  TEXT NOT NULL,         -- ISO 8601 UTC
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_plan_audit_plan_id ON plan_audit (plan_id);
```

**Permitted audit events:**

| Event | When | Required? |
|---|---|---|
| `created` | Plan first written to store | Yes |
| `state_transition` | Any `state` change | Yes |
| `updated` | Non-state mutation (title, notes, etc.) | Yes |
| `abandoned_from_planning` | Plan in `planning` discarded by operator | Yes — per D-02 |
| `escalated_to_mso_review` | `planning → mso_review` transition | Yes |

No `abandoned_from_draft` event — per D-02, draft abandonment has no audit
record.

---

## 5. API de acceso al Draft Store (contratos Python)

The Draft Store exposes a narrow, explicit contract. All methods are synchronous.
No async. No background tasks. No callbacks.

```python
# assistant_os/mso/draft_store.py  (file to be created in Sprint #227)

def create_plan(plan: PlanRecord) -> None:
    """Write a new Plan to the store. Raises if plan_id already exists."""

def get_plan(plan_id: str) -> PlanRecord:
    """Return a Plan by ID. Raises PlanNotFound if absent."""

def update_plan(plan_id: str, updates: PlanUpdate) -> PlanRecord:
    """Apply non-state mutations. Returns updated record. Validates schema_version."""

def transition_state(
    plan_id: str,
    from_state: PlanState,
    to_state: PlanState,
    operator_seat: str,
    notes: str | None = None,
) -> PlanRecord:
    """Atomic state transition. Raises if current state != from_state.
    Writes audit log entry. Raises on invalid transition."""

def abandon_plan(plan_id: str, operator_seat: str) -> None:
    """Discard a plan. If state == 'planning', writes audit log entry.
    If state == 'draft', silent discard. Raises if state == 'mso_review'."""

def list_plans(
    operator_seat: str | None = None,
    state: PlanState | None = None,
) -> list[PlanRecord]:
    """Return plans matching optional filters. Never raises on empty result."""

def get_audit_log(plan_id: str) -> list[PlanAuditEntry]:
    """Return all audit entries for a plan in chronological order."""
```

**What these methods must NOT do:**

- Call MSO, Police, Runner, or any authority-chain module.
- Emit tokens.
- Trigger orchestration.
- Accept Plans in non-permitted states.
- Accept unknown schema_version without raising.
- Silently coerce invalid state values.

---

## 6. Dataclasses de dominio

```python
# In assistant_os/mso/plan_model.py  (file to be created in Sprint #227)

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional

PlanState = Literal["draft", "planning", "mso_review"]
PlanRiskLevel = Literal["low", "medium", "high", "critical"]

@dataclass(frozen=True)
class PlanRecord:
    plan_id:         str
    title:           str
    intent_summary:  str
    domain:          str
    state:           PlanState
    operator_seat:   str
    schema_version:  str                         # must be "1"; fail-closed otherwise
    created_at:      str                         # ISO 8601 UTC
    updated_at:      str                         # ISO 8601 UTC
    risk_level:      Optional[PlanRiskLevel] = None
    target_actions:  tuple[str, ...] = ()        # free-form strings
    notes:           Optional[str] = None

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise ValueError(
                f"Unknown schema_version '{self.schema_version}'. "
                "Fail-closed: cannot read Plans with unknown schema."
            )
        valid_states = {"draft", "planning", "mso_review"}
        if self.state not in valid_states:
            raise ValueError(f"Invalid Plan state: '{self.state}'")
        if not self.plan_id.startswith("plan_"):
            raise ValueError(f"Invalid plan_id format: '{self.plan_id}'")


@dataclass(frozen=True)
class PlanUpdate:
    """Fields that may be mutated on a non-frozen Plan."""
    title:           Optional[str] = None
    intent_summary:  Optional[str] = None
    domain:          Optional[str] = None
    risk_level:      Optional[PlanRiskLevel] = None
    target_actions:  Optional[tuple[str, ...]] = None
    notes:           Optional[str] = None
    # Prohibited: state, plan_id, operator_seat, schema_version, created_at


@dataclass(frozen=True)
class PlanAuditEntry:
    audit_id:      str
    plan_id:       str
    event:         str
    from_state:    Optional[str]
    to_state:      Optional[str]
    operator_seat: str
    occurred_at:   str
    notes:         Optional[str] = None
```

**Prohibited fields — never add to PlanRecord:**

`execution_allowed`, `policy_decision_ref`, `capability_token_ref`,
`operation_binding_ref`, `authorized_plan_ref`, `police_decision_ref`,
`runner_ref`, `mission_id`, `used_execution`, `cognitive_only`,
`pending_authority_steps`, `auto` (any variant), `cancelled`, `executing`,
`running`, `completed`, `approved`, `authorized`.

---

## 7. Transiciones de estado — tabla de validación

```
from_state    to_state       allowed?   audit event
-----------   -----------    ---------  -----------------------
draft         planning       YES        state_transition
draft         mso_review     NO         —
planning      draft          YES        state_transition
planning      mso_review     YES        state_transition + escalated_to_mso_review
mso_review    draft          NO         —
mso_review    planning       NO         —
mso_review    mso_review     NO         —
(any)         (same state)   NO         — (idempotent re-write is not a transition)
```

`transition_state()` must raise `InvalidTransition` for any row marked NO.

---

## 8. Inicialización y ubicación del archivo

```python
# Canonical path
DRAFT_STORE_PATH: Path = MEMORY_DIR / "draft_store" / "plans.db"

# Environment override for tests
_DRAFT_STORE_ENV = "ASSISTANT_OS_DRAFT_STORE_PATH"

def get_draft_store_path() -> Path:
    env_val = os.environ.get(_DRAFT_STORE_ENV, "").strip()
    if env_val:
        return Path(env_val)
    return DRAFT_STORE_PATH
```

On first connection, the store creates the `plans` and `plan_audit` tables if
they do not exist. This is idempotent. No migration runner required for ALFA
(per D-05).

**On unknown schema_version encountered during read:** raise `UnknownSchemaVersion`.
Do not silently coerce. Do not default to version "1". Fail closed.

---

## 9. Diseño del badge de estado en UI (D-07)

Badge para Mission Control y futuras superficies del operador.

### Estados visibles

| State | Badge label | Badge color (token) | Notes |
|---|---|---|---|
| `draft` | Draft | `text-tx-muted` / border neutral | Uncommitted, may be incomplete |
| `planning` | Planning | `text-warn` / border warn | Committed intent, pre-escalation |
| `mso_review` | MSO Review | `text-accent` / border accent | Frozen — awaiting sovereign review |

### Estados explícitamente prohibidos en el badge

`running`, `executing`, `completed`, `approved`, `authorized`, `cancelled`.
If any of these appears in Plan state at runtime, the UI must render an error
badge (`Unknown State — contact operator`) and emit a console warning. It must
never silently display an execution-implying label.

### Componente propuesto

```
PlanStateBadge.tsx
  props: { state: "draft" | "planning" | "mso_review" }
  renders: pill badge with label + color from table above
  never renders: execution states
  on unknown state: renders error pill, logs warning
```

**Implementation gate:** This component is designed here but must not be
implemented until Draft Persistence (Sprint #227) exists. No stub, no
placeholder. When implemented, it must have a test contract asserting it cannot
render forbidden states.

---

## 10. Relación con stores existentes

| Store | Path | Relation to Draft Store |
|---|---|---|
| `mso_store` | `MEMORY_DIR/mso_store/` | Authority-chain records. Plans must never be written here. |
| `draft_store` | `MEMORY_DIR/draft_store/plans.db` | Plan records only. Must never hold authority artifacts. |

These two stores must remain strictly separated at the filesystem level. Any
code that imports both `mso_store` and `draft_store` in the same module is a
design smell requiring review.

---

## 11. Invariantes soberanas de la capa de persistencia

```
INV-PERSIST-01   The Draft Store does not import from execution_proposal,
                 authority_preparation, confirmable_prepared_action,
                 prepared_action_queue, or police modules.
INV-PERSIST-02   The Draft Store does not call MSO, Police, Runner, or any
                 token-issuing module.
INV-PERSIST-03   Plans in state mso_review cannot be mutated by update_plan().
INV-PERSIST-04   Plans in state mso_review cannot be abandoned.
INV-PERSIST-05   transition_state() must be atomic: state change and audit log
                 entry succeed together or neither commits.
INV-PERSIST-06   Any read of a record with schema_version != "1" raises
                 UnknownSchemaVersion. No silent coercion.
INV-PERSIST-07   The Draft Store SQLite file must never reside in mso_store/.
INV-PERSIST-08   plan_id must pass prefix check (starts with "plan_") before
                 any write operation.
INV-PERSIST-09   target_actions is stored as a JSON array of strings. It is
                 never parsed for capability matching, permission checking, or
                 any authority-chain logic.
INV-PERSIST-10   The Draft Store is test-isolated via ASSISTANT_OS_DRAFT_STORE_PATH
                 environment variable. Production path is never used in tests.
```

---

## 12. Decisiones pendientes para Jorge — bloqueo para #227

| ID | Question | Default if unresolved |
|---|---|---|
| **D-08** | Should `update_plan()` be blocked when `state == 'planning'`, or allowed with an audit log entry? | NO DEFAULT — must be resolved |
| **D-09** | Should the Draft Store expose a `list_plans()` without operator_seat filter (admin view), or always require operator_seat? | NO DEFAULT — must be resolved |
| **D-10** | Should the Draft Store have a retention policy (e.g., auto-delete drafts older than N days), or are Plans kept indefinitely until abandoned? | NO DEFAULT — must be resolved |
| **D-11** | Should `mso_review` Plans be visible in Mission Control's read-model before MSO acts on them, or only after MSO acknowledges? | NO DEFAULT — must be resolved |

---

## 13. Criterios de aceptación para pasar a #227

Sprint #227 (Draft Store Implementation) may begin if and only if:

| Criterion | Status |
|---|---|
| Sprint #225 design merged to main | Pending merge |
| This document reviewed and approved by Jorge | Pending |
| D-08 (update_plan in planning state) resolved | Pending |
| D-09 (list_plans admin view) resolved | Pending |
| D-10 (retention policy) resolved | Pending |
| D-11 (mso_review visibility before MSO acks) resolved | Pending |
| No code was written in this sprint | Confirmed |
| No /plans endpoint created | Confirmed |
| No /prepare endpoint created | Confirmed |
| MSO, Police, Runner, tokens unchanged | Confirmed |
| Mission Control remains read-model | Confirmed |

---

## Cierre: Recomendación GO / NO-GO para #227

### Recomendación: **CONDITIONAL GO**

Sprint #227 (Draft Store Implementation) is approved to proceed under the
condition that D-08 through D-11 are resolved by Jorge before the sprint begins.

**Rationale:**

- The design is internally consistent with #225.
- No authority-chain boundary is crossed.
- SQLite choice is coherent with the project's local-first posture and justified
  over file-per-JSON for Plans specifically.
- D-08 (mutability of `planning` state) directly determines which operations
  `update_plan()` must implement. Implementing without this decision forces
  a retro-fix.
- D-10 (retention) determines whether a cleanup job is in scope for #227. If
  deferred, it must be documented as explicit debt.

**If Jorge does not resolve D-08 through D-11: NO-GO.**

No implementation sprint (#227+) may begin until both #225 and #226 designs are
approved.

---

> Truth before power.
> Order before speed.
> MSO before execution.
