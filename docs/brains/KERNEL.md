> [!WARNING]
> **Historical / Conceptual Specification**
> This document is historical/conceptual reference material. It is not the current source of truth for runtime behavior.
> Current source of truth: code in `assistant_os/` and `ui/`, plus `README.md`, `docs/RUNTIME_TOPOLOGY.md`, and `docs/CHAT.md`.

<!-- agent:do-not-treat-as-source-of-truth -->

---

# KERNEL

## 1. Definition

The Kernel is the deterministic orchestration layer that receives a `CanonicalRequest`, classifies intent, builds an `ExecutionPlan`, applies policy, routes to the correct domain pipeline, and returns a `DomainResult`. The Kernel routes and enriches requests. It does not decide authority, execute actions, or authorize capability grants.

---

## 2. Responsibilities

- Accept `CanonicalRequest` as the single entry point (`core/orchestrator.py::handle_request`)
- Classify intent deterministically via `semantic.py` (same input always produces same classification)
- Build `ExecutionPlan` via `planning.py` (pure function, no side effects)
- Receive and respect `PolicyDecision` from `core/policy.py` (execution_mode: auto / confirm / clarify / blocked)
- Route to the correct domain pipeline via `routing.py`
- Produce `RouteDecision` as an intermediate enrichment artifact
- Aggregate pipeline output into `DomainResult`
- Return `DomainResult` to the caller

---

## 3. Non-Responsibilities

- Must NOT authorize capability grants or tokens
- Must NOT produce sovereign intents
- Must NOT modify operator state or MSO state
- Must NOT decide what actions are permitted (that is Policy's responsibility)
- Must NOT execute code, run subprocesses, or invoke agents directly
- Must NOT hold conversational context between requests
- Must NOT surface results to users directly (that is the surface layer's responsibility)

---

## 4. Inputs

| Input | Type | Source |
|-------|------|--------|
| `CanonicalRequest` | TypedDict | MSO Translator / Direct caller |
| Request context | `RequestContext` | `core/context.py` |

---

## 5. Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `RouteDecision` | TypedDict | Internal enrichment (not persisted) |
| `ExecutionPlan` | TypedDict | Passed to policy layer and pipeline |
| `DomainResult` | TypedDict | Returned to caller |

---

## 5a. Consumed External Decisions

| Decision | Type | Origin |
|----------|------|--------|
| `PolicyDecision` | TypedDict | Produced by `core/policy.py`; consumed by Kernel to gate pipeline invocation |

---

## 6. RouteDecision Structure

```python
RouteDecision = {
    "intent_type": str,         # classified intent category (e.g., CODE_EXECUTE, FIN_QUERY)
    "domain": str,              # target domain (CODE, FIN, WORK, HOST, MACHINE_OPERATOR)
    "operator_goal": str,       # normalized goal statement derived from request
    "semantic_summary": str,    # concise description of classified intent
    "risk_hint": str,           # LOW / MEDIUM / HIGH / CRITICAL
    "suggested_next_step": str, # non-authoritative operator guidance text
}
```

---

## 7. Boundaries

| Component | Interaction | Direction |
|-----------|-------------|-----------|
| MSO | Receives CanonicalRequest from MSO Translator | Input |
| Policy / Police | Delegates authorization decision to policy layer | Calls policy; accepts decision |
| Domain Pipelines | Dispatches ExecutionPlan to matched pipeline | Output |
| System Assistant | Produces DomainResult that System Assistant may explain | Output |
| Agents | Must NOT invoke agents directly; pipelines invoke agents | None |

---

## 8. Invariants

- Intent classification must be deterministic: same `CanonicalRequest` must always produce the same `RouteDecision`
- `make_plan()` must be a pure function with no side effects
- The Kernel must NEVER invoke an agent or pipeline if `PolicyDecision.execution_mode == "blocked"`
- The Kernel must NEVER execute if `CanonicalRequest` fails validation
- `DomainResult.execution_status` must accurately reflect what occurred — never synthetic or assumed
- Confirmation flows must pause execution and return to the caller; the Kernel must NOT auto-proceed

---

## 9. Failure Modes

| Failure | System Impact | Recovery |
|---------|--------------|----------|
| Intent classification returns unknown type | PolicyDecision defaults to BLOCKED | No execution; DomainResult contains error |
| Pipeline raises unhandled exception | DomainResult captures error, execution_status: FAILED | Caller receives explicit failure |
| PolicyDecision is BLOCKED | Kernel stops at routing; pipeline not invoked | DomainResult returned with blocked status |
| CanonicalRequest missing required fields | Validation error at entry point | Request rejected before orchestration begins |

---

## 10. Examples (Allowed)

```
Input: CanonicalRequest { action: "CODE_EXECUTE", payload: { ... } }
Kernel:
  1. semantic.classify() → intent_type: "CODE_EXECUTE", domain: "CODE"
  2. planning.make_plan() → ExecutionPlan { risk_level: "MEDIUM", requires_confirmation: false }
  3. policy.decide() → PolicyDecision { execution_mode: "auto" }
  4. routing.dispatch() → code_pipeline.execute(plan)
  5. Returns DomainResult { execution_status: "SUCCESS", ... }
→ Correct: full orchestration without authority creation
```

```
Input: CanonicalRequest { action: "FIN_QUERY", payload: { ... } }
PolicyDecision { execution_mode: "blocked", reason: "unresolved_capability" }
Kernel:
  → Does NOT invoke fin_pipeline
  → Returns DomainResult { execution_status: "BLOCKED", reason: "unresolved_capability" }
→ Correct: fail-closed on blocked policy
```

---

## 11. Examples (Forbidden)

```
FORBIDDEN: Kernel calls governance_engine.authorize() to override a BLOCKED PolicyDecision
→ Violation: authority creation outside MSO
```

```
FORBIDDEN: Kernel invokes code_agent.execute() directly, bypassing code_pipeline
→ Violation: agent invocation outside pipeline
```

```
FORBIDDEN: Kernel caches prior PolicyDecision and reuses it for a new request
→ Violation: non-deterministic execution path
```

```
FORBIDDEN: Kernel returns DomainResult { execution_status: "SUCCESS" } when pipeline was not invoked
→ Violation: veracidad operativa
```
