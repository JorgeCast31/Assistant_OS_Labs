# INVARIANTS

These invariants must NEVER be violated by any component in the system. Any change to production code or documentation that would break an invariant must be blocked and reported as a critical finding.

---

## I-01 — MSO is the only producer of execution decisions

MSO Authority Core is the single source of `GovernanceVerdict`. No other component may produce, modify, or substitute an execution decision. This includes: Kernel, Police, System Assistant, Agents, Surfaces, Semi-agents, and LLMs.

**Source:** `assistant_os/mso/governance_engine.py`

---

## I-02 — MSO Narrative Interface cannot emit, modify, or replace Authority Core decisions

The MSO Narrative Interface (advisory engine, translator, inspection bundle) is non-authoritative. It must NEVER produce a `GovernanceVerdict`, modify an existing verdict, or substitute a new authorization path. Its outputs are informational only.

**Source:** `assistant_os/mso/advisory_engine.py`, `assistant_os/mso/translator.py`

---

## I-03 — Police enforces but does not create authority

Police validates capability tokens and enforces `PolicyDecision`. Police must NEVER generate capability grants, issue tokens, or produce governance verdicts. All authority it enforces must originate from MSO.

**Source:** `assistant_os/capabilities/token_verifier.py`, `assistant_os/sandbox/authorized_plan.py`

---

## I-04 — Kernel produces RouteDecision only

The Kernel's authoritative output is `RouteDecision` (and subsequently `ExecutionPlan` and `DomainResult`). The Kernel must NEVER produce an `execution_mode` value. Execution mode is the responsibility of the policy layer, which receives its authority from MSO.

**Source:** `assistant_os/core/orchestrator.py`, `assistant_os/core/routing.py`

---

## I-05 — Kernel never emits execution_mode

`execution_mode` (auto / confirm / clarify / blocked) is produced exclusively by `core/policy.py` under authority delegated from MSO. The Kernel routes requests and produces `DomainResult`. It must NEVER set or override `execution_mode`.

**Source:** `assistant_os/core/policy.py`

---

## I-06 — RouteDecision semantic fields are non-authoritative signals

`RouteDecision` fields (`semantic_summary`, `risk_hint`, `suggested_next_step`, `operator_goal`) are enrichment signals only. They must NEVER be used as the basis for an authorization decision. Risk classification from RouteDecision must be confirmed by `mso/risk_engine.py` before influencing governance.

**Source:** `assistant_os/core/routing.py`, `assistant_os/mso/risk_engine.py`

---

## I-07 — System Assistant has read-only access to system state

System Assistant must NEVER write to any store, trigger any pipeline, or invoke any component that has side effects. Its access is strictly read-only against operability endpoints.

**Source:** `assistant_os/operability.py`, `assistant_os/surface_behavior.py`

---

## I-08 — System Assistant never executes or modifies state

System Assistant must NEVER produce an execution event. Any action attributed to System Assistant that results in a state change or pipeline invocation is a critical invariant violation.

**Source:** `assistant_os/surface_behavior.py`

---

## I-09 — Agents execute only through governed pipelines

An agent must NEVER be invoked outside of its domain pipeline. The pipeline is responsible for verifying `AuthorizedPlan` and capability token before invoking the agent entrypoint. Direct agent invocation from Kernel, MSO, surfaces, or other agents is forbidden.

**Source:** `assistant_os/agents/registry.py`, `assistant_os/sandbox/authorized_plan.py`

---

## I-10 — LLM-assisted outputs must be marked narrative when applicable

Any output produced with LLM assistance must be explicitly marked as non-authoritative (`narrative: true` or equivalent) before being passed to a governance or policy component. An LLM output must NEVER be treated as a `GovernanceVerdict`, `PolicyDecision`, or capability grant without transformation through an authoritative component.

**Source:** `assistant_os/mso/advisory_engine.py`, `assistant_os/mso/prompts.py`

---

## I-11 — No component outside MSO Authority Core may decide execution

The set of components permitted to produce execution decisions is exactly one: MSO Authority Core (`mso/governance_engine.py`). Any pattern where a second component produces, proxies, or routes around a governance decision is a critical violation.

**Source:** `assistant_os/mso/governance_engine.py`

---

## I-12 — Fail-closed

Any ambiguous, unresolvable, or missing authorization state must result in execution being BLOCKED. No component may default to permissive behavior under uncertainty.

**Source:** `assistant_os/core/policy.py`, `assistant_os/capabilities/capability_gate.py`

---

## I-13 — Capability tokens are consumed exactly once

A capability token must be consumed at the point of execution and must NEVER be reused, cached, or transferred. Duplicate consumption must be rejected with an enforcement error.

**Source:** `assistant_os/runners/authority_consumption.py`, `assistant_os/capabilities/token_verifier.py`

---

## I-14 — SovereignCycleRecord is persisted before execution begins

MSO must persist the `SovereignCycleRecord` before the CanonicalRequest is passed to the Kernel. No execution may proceed without a cycle record. This ensures all execution is traceable and reversible to an audit record.

**Source:** `assistant_os/mso/runtime.py`

---

## I-15 — execution_status must reflect actual system behavior

No component may return `execution_status: SUCCESS` when execution did not occur. `execution_status` must be set by the component that performed or failed the action, not by any observer or narrative component.

**Source:** `assistant_os/contracts.py`, `assistant_os/mso/contracts.py`
