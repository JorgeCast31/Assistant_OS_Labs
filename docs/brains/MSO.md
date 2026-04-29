# MSO (Machine Sovereign Operator)

## 1. Definition

MSO is the single authority of the system. It is the only component that produces execution decisions — all authorization, capability grants, and governance verdicts originate exclusively from MSO. MSO operates as two strictly separated layers: an **Authority Core** that makes binding decisions, and a **Narrative Interface** that is non-authoritative and used only for explanation and inspection.

---

## 2. Responsibilities

**Authority Core:**
- Build `SovereignIntent` from raw operator input
- Authorize or block execution via `governance_engine.py`
- Manage capability state via `sovereign_state_store.py`
- Issue capability tokens via `capabilities/token_issuer.py`
- Maintain system operational mode: NORMAL / RESTRICTED / DEGRADED / FROZEN
- Detect anomalies via `anomaly_engine.py`
- Score and classify risk via `risk_engine.py`
- Apply temporal restrictions via `restrictions.py`
- Produce and persist `SovereignCycleRecord` for every cycle
- Produce and persist `DelegationTask` for each delegated execution
- Aggregate execution traces via `trace_aggregator.py`
- Enforce operator identity and role boundaries via `operator_auth.py`

**Narrative Interface (non-authoritative):**
- Consult local LLM advisory engine (`advisory_engine.py`) for semantic enrichment only
- Translate `SovereignIntent` to `CanonicalRequest` via `translator.py`
- Produce inspection bundle for operator surface

---

## 3. Non-Responsibilities

- Must NOT execute domain actions directly (no pipeline invocation from Authority Core)
- Must NOT invoke agents directly
- Must NOT produce narrative or explanation text that carries authority
- Must NOT delegate authority to any LLM (including advisory engine)
- Must NOT allow the Narrative Interface to produce authorization decisions
- Must NOT reuse a `SovereignCycleRecord` for a different intent
- Must NOT grant capability tokens without explicit operator authorization flow

---

## 4. Inputs

| Input | Type | Source |
|-------|------|--------|
| Raw operator intent | str | Operator surface / chat |
| Operator identity token | str | `operator_auth.py` |
| System state snapshot | `SystemState` | `system_state.py` |
| Capability grant request | dict | Control plane |
| Advisory LLM response | dict | `advisory_engine.py` (non-authoritative) |

---

## 5. Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `SovereignIntent` | TypedDict | Internal; passed to translator |
| `CanonicalRequest` | TypedDict | Kernel (via translator) |
| `GovernanceVerdict` | TypedDict | `{ decision: ALLOW / REQUIRE_CONFIRMATION / BLOCK / DEGRADE }` |
| Capability token | signed token | `capabilities/token_verifier.py` |
| `SovereignCycleRecord` | TypedDict | Persistent store |
| `DelegationTask` | TypedDict | Cognitive worker scope |
| Inspection bundle | dict | Operator surface |

---

## 6. Sovereign Cycle

```
1. build_sovereign_intent(raw_input) → SovereignIntent
2. governance_engine.evaluate(intent) → GovernanceVerdict
3. Persist SovereignCycleRecord (before any execution begins)
4. If BLOCK → return blocked DomainResult
5. If REQUIRE_CONFIRMATION → pause cycle, await operator signal
6. If ALLOW → translator.translate(intent) → CanonicalRequest
7. kernel.handle_request(canonical_request) → DomainResult
8. Persist: DelegationTask, trace (execution result appended to existing CycleRecord)
9. Return inspection bundle
```

---

## 7. Authority Separation

| Layer | Authority | Writes State | Produces Decisions |
|-------|-----------|-------------|-------------------|
| Authority Core | Yes | Yes | Yes |
| Narrative Interface | No | No | No |
| Advisory Engine (LLM) | No | No | No — advisory only |
| Kernel | No | No | No |

---

## 8. Boundaries

| Component | Interaction | Direction |
|-----------|-------------|-----------|
| Kernel | Passes CanonicalRequest; receives DomainResult | Output → Input |
| Police (Policy Engine) | Receives governance verdicts for enforcement | MSO → Police |
| Operator Surface | Receives inspection bundle | Output |
| Advisory Engine | Consults for semantic enrichment only | Non-authoritative read |
| Agents | Must NOT invoke directly | None |
| System Assistant | Must NOT grant authority to | None |

---

## 9. Invariants

- MSO is the ONLY source of authorization decisions in the system
- No other component may produce or modify a `GovernanceVerdict`
- No LLM may produce or modify a governance decision
- The Advisory Engine result must NEVER bypass or override the Authority Core
- `SovereignCycleRecord` must be persisted before execution begins
- A BLOCK verdict must stop the cycle completely — no partial execution
- Capability tokens must be consumed exactly once per authorized execution
- System operational mode (NORMAL / RESTRICTED / DEGRADED / FROZEN) must be respected by all downstream components

---

## 10. Failure Modes

| Failure | System Impact | Recovery |
|---------|--------------|----------|
| Advisory engine unavailable | Cycle continues without LLM enrichment | No execution impact; record notes advisory failure |
| `sovereign_state_store` write failure | Cycle is aborted before execution | DomainResult: FAILED; no execution occurs |
| Translator validation error | CanonicalRequest rejected | Cycle stops; error persisted in CycleRecord |
| Governance engine produces ambiguous verdict | Defaults to BLOCK | Fail-closed; no execution |
| Operator identity verification failure | Cycle blocked | No execution; identity error logged |

---

## 11. Examples (Allowed)

```
Operator submits: "Execute code fix for auth module"
MSO Authority Core:
  1. build_sovereign_intent → SovereignIntent { domain: CODE, action: CODE_EXECUTE, risk: MEDIUM }
  2. governance_engine.evaluate → GovernanceVerdict { decision: ALLOW }
  3. Persist SovereignCycleRecord (before execution begins)
  4. translator.translate → CanonicalRequest { action: CODE_EXECUTE, payload: { ... } }
  5. kernel.handle_request → DomainResult { execution_status: SUCCESS }
  6. Append DelegationTask, trace, result to existing CycleRecord
→ Correct: authority flows from MSO, record exists before execution, execution through Kernel
```

```
GovernanceVerdict { decision: BLOCK, reason: "restricted_mode_active" }
MSO:
  → Does NOT translate intent
  → Does NOT call kernel
  → Persists blocked CycleRecord
  → Returns DomainResult { execution_status: BLOCKED }
→ Correct: fail-closed
```

---

## 12. Examples (Forbidden)

```
FORBIDDEN: advisory_engine LLM response directly sets GovernanceVerdict { decision: ALLOW }
→ Violation: LLM holds authority
```

```
FORBIDDEN: MSO Narrative Interface modifies SovereignCycleRecord after the Authority Core wrote it
→ Violation: Narrative Interface writes state
```

```
FORBIDDEN: MSO invokes code_pipeline.execute() directly without going through Kernel
→ Violation: MSO executes domain action
```

```
FORBIDDEN: A second MSO-like component is created to handle "lightweight" intents
→ Violation: parallel authority
```
