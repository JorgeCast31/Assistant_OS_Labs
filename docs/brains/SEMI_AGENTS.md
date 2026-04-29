# SEMI_AGENTS

## 1. Definition

A semi-agent is an internal behavioral component that operates within the system's orchestration or governance layers. Semi-agents have bounded behavior but do not have canonical domain pipelines, do not hold authority, and do not execute external actions. They process inputs, apply bounded logic, and return outputs to the component that invoked them.

Semi-agents are NOT:
- System Assistant (observer component — see `SYSTEM_ASSISTANT.md`)
- Kernel (orchestration layer — see `KERNEL.md`)
- MSO (authority layer — see `MSO.md`)
- Police (enforcement layer — see `POLICE.md`)
- Agents (execution units — see `AGENTS.md`)
- Surfaces (interaction boundaries — see `SURFACES.md`)
- GovernanceEngine (MSO Authority Core internal component — see §5)

Semi-agents are "semi" because they:
- Apply bounded classification, routing, registry, or tracking logic
- Cannot make governance or policy decisions
- Cannot execute domain pipelines
- Cannot invoke agents
- Cannot persist state directly — results are returned to the invoking component

---

## 2. Constraints

- Semi-agents must NEVER produce authorization decisions
- Semi-agents must NEVER invoke domain pipelines or agents
- Semi-agents must NEVER persist state — they return outputs only
- Semi-agents must NEVER exceed the bounded logic of their declared role
- Semi-agents must NEVER be promoted to agent status without a full `AgentRegistration` in `agents/registry.py`
- LLM calls within a semi-agent are informational only — their output must NOT be treated as authoritative

---

## 3. Defined Semi-Agents

### Classifier

**File:** `assistant_os/core/semantic.py`
**Role:** Deterministic intent classification
**Input:** `CanonicalRequest` fields
**Output:** `intent_type`, `domain`, `risk_hint`
**Cannot:** Authorize execution, modify requests, produce PolicyDecision

---

### Router

**File:** `assistant_os/core/routing.py`
**Role:** Domain registry dispatch — maps intent_type to a domain key
**Input:** `RouteDecision`
**Output:** Symbolic route / domain key / pipeline identifier
**Cannot:** Invoke pipelines directly, decide execution legality, modify RouteDecision, return executable callables

---

### CapabilityRegistry

**File:** `assistant_os/mso/capability_registry.py`
**Role:** Maintains declared capabilities and delegation scopes
**Input:** Capability queries
**Output:** Capability definitions, scope boundaries
**Cannot:** Grant capabilities, issue tokens, produce governance verdicts

---

## 4. Invariants

- Semi-agents must NEVER produce `GovernanceVerdict`, `PolicyDecision`, or capability tokens
- Semi-agents must NEVER invoke domain pipelines or agents
- Semi-agents must NEVER persist results — all persistence is handled by the invoking authority component
- A semi-agent must NEVER be called "an agent" or registered as one without a full `AgentRegistration` contract
- LLM-assisted semi-agent outputs must be marked as non-authoritative before being passed upstream

---

## 5. MSO Authority Core Internal Components

The following components operate exclusively inside the MSO Authority Core cycle. They are not semi-agents. They are internal bounded functions of MSO Authority Core and must never be invoked, accessed, or observed from outside the MSO package.

### GovernanceEngine

**File:** `assistant_os/mso/governance_engine.py`
**Role:** Produces `GovernanceVerdict` based on MSO Authority Core inputs
**Input:** `SovereignIntent`, system state, capability state
**Output:** `GovernanceVerdict { decision: ALLOW | REQUIRE_CONFIRMATION | BLOCK | DEGRADE }`
**Owner:** MSO Authority Core
**Cannot:** Modify sovereign state directly, issue capability tokens, act outside MSO cycle, be called from outside `mso/`

---

## 6. Audit Components

The following components persist state by design. They are not semi-agents. Semi-agents must never persist state; these components exist specifically to persist records. They are passive sinks — they accept writes and return nothing that influences execution.

### AuditLog

**File:** `assistant_os/sandbox/audit_store.py`
**Role:** Append-only sink for all execution and enforcement events
**Input:** Execution events, enforcement records
**Output:** Immutable audit entries written to jsonl store
**Cannot:** Delete records, modify existing entries, gate execution, influence any component's behavior
**Note:** AuditLog persists state by definition. It is not a semi-agent. No component may skip writing to AuditLog to avoid leaving a record.

---

## 7. Lifecycle State Components

The following components own and mutate lifecycle state directly. They are not semi-agents. Semi-agents must never persist or mutate state; these components exist specifically to manage mutable execution lifecycle state.

### ExecutionRegistry

**File:** `assistant_os/sandbox/execution_registry.py`
**Role:** Mutable, thread-safe in-memory lifecycle state manager for execution runs.

**Owns:**
- `register(run)` — inserts a new ExecutionRun into the registry
- `mark_running()` — transitions PENDING → RUNNING; writes container_id, started_at
- `mark_completed()` — transitions RUNNING → COMPLETED; writes ended_at
- `mark_failed()` — transitions RUNNING or PENDING → FAILED; writes termination_reason, ended_at
- `mark_aborted()` — transitions any non-terminal state → ABORTED; idempotent
- `update_status()` — general-purpose mutation used by RunnerAPI finally block

**State model:** `PENDING → RUNNING → COMPLETED / FAILED / ABORTED`

**Persistence:** In-memory only. Does not survive process restart. Persistent record of execution events is in `audit_store.py`, not here.

**Constraints:**
- Must enforce valid state transitions; must reject transitions out of terminal states with `InvalidTransition`
- Must NOT authorize execution
- Must NOT produce policy decisions
- Must NOT substitute for `audit_store.py` as the persistent audit record
- UI consumers must handle missing records after process restart — fall back to `audit_store.py` for historical state
