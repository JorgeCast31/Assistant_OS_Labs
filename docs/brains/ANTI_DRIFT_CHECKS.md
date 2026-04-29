# ANTI_DRIFT_CHECKS

These are forbidden patterns that indicate semantic drift in the system's architecture. Each pattern must be detected and blocked during code review and documentation audit. Any instance found must be reported as a critical finding, not corrected silently.

---

## D-01 — System Assistant triggers execution

**Pattern:** System Assistant calls any pipeline, invokes any agent, calls `handle_request()`, writes to any store, or produces a side effect.

**Why forbidden:** System Assistant is an observer only. Execution authority does not exist at the observer layer.

**Invariant violated:** I-01, I-07, I-08

**Minimal correction:** Remove all execution calls from System Assistant. Route the triggering intent through the Chat surface → Kernel pipeline instead.

---

## D-02 — Kernel emits execution_mode

**Pattern:** `orchestrator.py` or any file in `core/` sets, overrides, or emits `execution_mode` (auto / confirm / clarify / blocked) outside of `core/policy.py`.

**Why forbidden:** `execution_mode` is the product of `PolicyDecision`, which derives authority from MSO. The Kernel routes; it does not determine execution legality.

**Invariant violated:** I-04, I-05

**Minimal correction:** Remove `execution_mode` assignment from Kernel code. Ensure the value flows exclusively from `core/policy.py::decide()`.

---

## D-03 — Police creates approval

**Pattern:** Police calls `governance_engine.authorize()`, issues a capability token, creates a grant, or overrides a BLOCKED verdict to allow execution.

**Why forbidden:** Police enforces rules produced by MSO. It has no authority to create or modify authorization decisions.

**Invariant violated:** I-03, I-11

**Minimal correction:** Remove any approval or grant creation logic from Police components. Route grant creation through MSO Authority Core and Control Plane only.

---

## D-04 — MSO Narrative Interface modifies Authority Core decisions

**Pattern:** `advisory_engine.py`, `translator.py`, or any MSO Narrative component writes to `sovereign_state_store`, modifies a `GovernanceVerdict`, or routes around a BLOCK decision.

**Why forbidden:** The Narrative Interface is non-authoritative. Any modification to Authority Core decisions from outside the Authority Core creates parallel authority.

**Invariant violated:** I-02, I-11

**Minimal correction:** Remove all state writes from Narrative Interface components. If advisory output should influence a decision, it must be passed as input to `governance_engine.py`, which makes the final determination.

---

## D-05 — Agent decides policy

**Pattern:** An agent in `agents/` or `executors/` checks whether it is permitted to execute, produces a `PolicyDecision`, decides whether to retry, or routes results to components other than its pipeline.

**Why forbidden:** Agents are thin execution boundaries. Policy decisions are made by MSO and enforced by Police before the agent is invoked.

**Invariant violated:** I-09, I-11

**Minimal correction:** Remove all policy logic from agent code. By the time an agent is invoked, `AuthorizedPlan` has already been validated by Police.

---

## D-06 — Surface bypasses Kernel

**Pattern:** A surface component (`ui/`, `chat_core.py`, `webhook_server.py`) invokes a domain pipeline, calls an agent, or calls MSO directly without routing through `core/orchestrator.py::handle_request()`.

**Why forbidden:** The Kernel is the single orchestration entry point. Direct pipeline invocation from a surface bypasses intent classification, planning, and policy enforcement.

**Invariant violated:** I-04, I-12

**Minimal correction:** Remove all direct pipeline or agent calls from surface code. All execution must enter through `handle_request(CanonicalRequest)`.

---

## D-07 — Semi-agent becomes agent without registry contract

**Pattern:** A component in `executors/` or `mso/` begins invoking domain pipelines, persisting results, or making governance decisions without a corresponding `AgentRegistration` entry in `agents/registry.py`.

**Why forbidden:** Agents are governed by explicit contracts. An unregistered executor that behaves like an agent creates an ungoverned execution boundary outside the capability scope system.

**Invariant violated:** I-09, I-12

**Minimal correction:** Either (a) register the component as an agent with a complete `AgentRegistration` and wire it into the capability token flow, or (b) remove the execution behavior and return the component to bounded semi-agent constraints.

---

## D-08 — LLM output treated as authority

**Pattern:** Output from `advisory_engine.py`, `local_llm_adapter.py`, `cognitive_worker.py`, or any LLM call is assigned to a `GovernanceVerdict`, `PolicyDecision`, or capability grant field without transformation through an authoritative component.

**Why forbidden:** LLMs produce probabilistic outputs. Authority in this system is deterministic. Assigning LLM output directly to a governance field introduces non-deterministic authority.

**Invariant violated:** I-10, I-11

**Minimal correction:** All LLM output must be tagged as `narrative: true` or equivalent. Before any LLM-derived value influences a governance decision, it must be processed by `governance_engine.py` as input — not assigned directly as the decision output.

---

## D-09 — Parallel authority component created

**Pattern:** A new module is introduced that produces `GovernanceVerdict`, makes execution decisions, or issues capability tokens outside the `mso/` package.

**Why forbidden:** MSO Authority Core is the single authority. A second authority component creates split governance, which undermines fail-closed enforcement and traceability.

**Invariant violated:** I-01, I-11

**Minimal correction:** Remove the parallel authority logic. If new governance rules are required, they must be added to `mso/governance_engine.py` or `mso/restrictions.py` under the existing MSO authority structure.

---

## D-10 — execution_status set without execution

**Pattern:** A component returns `execution_status: SUCCESS` when no pipeline executed, or when execution was blocked, simulated, or mocked.

**Why forbidden:** `execution_status` must reflect actual system behavior. A synthetic success status makes the audit trail unreliable and violates veracidad operativa.

**Invariant violated:** I-15

**Minimal correction:** Set `execution_status` only from the component that performed or failed the action. Observers and narrative components must NEVER set this field.

---

## D-11 — ExecutionRegistry treated as passive derived status

**Pattern:** A component reads from `execution_registry.py` as if it is a read-only view or derived-status cache. A UI contract is designed assuming `ExecutionRegistry` cannot be absent or stale. A component writes `execution_status` to a UI surface without accounting for in-memory-only persistence.

**Why forbidden:** `ExecutionRegistry` is a mutable, in-memory lifecycle state manager. It directly mutates `ExecutionRun.status` on every transition (`mark_running`, `mark_completed`, `mark_failed`, `mark_aborted`, `update_status`). It does not survive process restart. Treating it as a passive view produces incorrect UI state after restart and bypasses the `audit_store.py` fallback contract.

**Invariant violated:** I-15 (execution_status must reflect actual system behavior)

**Minimal correction:** Classify `ExecutionRegistry` as a Lifecycle State Component (see `SEMI_AGENTS.md §7`). UI contracts for `execution_status` must define explicit fallback behavior: if `ExecutionRegistry.get(execution_id)` returns `None`, query `audit_store.py` for the persisted execution record before returning a status to the UI.

---

## Audit Use

These checks must be applied:
- During every code review that touches `assistant_os/`
- When documentation in `docs/brains/` is modified
- When new components are introduced into any layer
- When an LLM-generated output is added to a governance or execution flow

Each violation found must be reported with: component name, file path, line reference, drift pattern ID, and invariant violated.
