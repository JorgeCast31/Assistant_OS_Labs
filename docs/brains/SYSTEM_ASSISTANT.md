> [!WARNING]
> **Historical / Conceptual Specification**
> This document is historical/conceptual reference material. It is not the current source of truth for runtime behavior.
> Current source of truth: code in `assistant_os/` and `ui/`, plus `README.md`, `docs/RUNTIME_TOPOLOGY.md`, and `docs/CHAT.md`.

<!-- agent:do-not-treat-as-source-of-truth -->

---

# SYSTEM_ASSISTANT

## 1. Definition

The System Assistant is a read-only observer component that interprets system state and explains it to users and operators. It does not execute, authorize, or modify any system behavior. It is a presentation layer, not an authority layer.

---

## 2. Responsibilities

- Read current system state from operability endpoints (`/mso/state`, `/agents/registry`, `/system/capabilities`)
- Interpret `execution_status` values and translate them into human-readable explanations
- Respond to surface-level informational queries (greetings, capability questions, system status)
- Surface structured observations about what is happening in the system
- Route surface-matched queries via `surface_behavior.py` pattern intercepts before reaching the orchestrator

---

## 3. Non-Responsibilities

- Must NOT trigger execution of any pipeline, agent, or domain action
- Must NOT authorize capability grants or tokens
- Must NOT modify any system state (no writes to sovereign state store, no intent creation)
- Must NOT produce execution decisions
- Must NOT interpret intent in a way that leads to action
- Must NOT bypass the orchestrator, policy, or police layers

---

## 4. Inputs

| Input | Type | Source |
|-------|------|--------|
| User query string | str | Chat surface |
| System state snapshot | dict | `operability.py` endpoints |
| `execution_status` value | str | `DomainResult` |
| Surface context | str | `surface_behavior.py` |

---

## 5. Outputs

| Output | Type | Destination |
|--------|------|-------------|
| Human-readable state explanation | str | Chat surface response |
| System observation text | str | System chat view |
| Surface intercept response | str | Returned before orchestrator |

---

## 6. Boundaries

| Component | Interaction | Direction |
|-----------|-------------|-----------|
| Kernel (Orchestrator) | Receives DomainResult to explain | Read only |
| MSO | Reads sovereign cycle state | Read only |
| Surfaces | Responds to user-facing queries | Output only |
| Policy / Police | Must NOT interact with | None |
| Agents | Must NOT invoke | None |

---

## 7. Invariants

- The System Assistant must NEVER produce a side effect
- The System Assistant must NEVER trigger pipeline execution
- The System Assistant must NEVER hold or convey authority
- `execution_status` explanations must reflect actual system state, not inferred or synthetic state
- Pattern intercepts in `surface_behavior.py` must only short-circuit informational queries, never action requests

---

## 8. Failure Modes

| Failure | System Impact | Recovery |
|---------|--------------|----------|
| Cannot read system state | Returns degraded explanation (e.g., "state unavailable") | No execution impact; system continues |
| Pattern intercept false-positive match | Query is answered superficially without orchestrator | Surface behavior patterns must be conservative |
| LLM response generation failure | Returns static fallback message | No authority or execution impact |

---

## 9. Examples (Allowed)

```
User: "What is the system doing right now?"
System Assistant: reads /mso/state → responds with current mode (NORMAL/RESTRICTED) and active cycles
→ No execution occurs
→ No state is modified
```

```
User: "Can you help me?"
System Assistant: matches surface_behavior greeting pattern → responds with capability list
→ Orchestrator is not invoked
→ No pipeline is triggered
```

```
execution_status: "BLOCKED — policy_decision: BLOCKED reason: unresolved_capability"
System Assistant: "The action was blocked because a required capability was not granted. No execution occurred."
→ Explanation only
→ No retry or override
```

---

## 10. Examples (Forbidden)

```
FORBIDDEN: System Assistant triggers CODE pipeline execution after explaining a code error
→ Violation: execution
```

```
FORBIDDEN: System Assistant calls governance_engine.authorize() based on user confirmation
→ Violation: authorization
```

```
FORBIDDEN: System Assistant writes to sovereign_state_store to "update" observed status
→ Violation: state modification
```

```
FORBIDDEN: System Assistant returns execution_status: "SUCCESS" when the pipeline did not execute
→ Violation: veracidad operativa
```
