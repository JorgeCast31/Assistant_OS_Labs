# AGENTS

## 1. Definition

An agent is a named, versioned execution unit with an explicit input contract, output contract, and declared capability scope. Agents execute domain actions within a pipeline. Agents do not make decisions, do not hold authority, and do not determine what is permitted. An agent is a thin, governed boundary crossing from pipeline to execution backend.

---

## 2. Constraints

- Every agent must be registered in `agents/registry.py` with a complete `AgentRegistration` record
- Every agent must declare its capability scope — execution is blocked if the required capability is not granted
- Agents must NEVER decide whether execution is permitted — that decision is made by MSO and enforced by Police
- Agents must NEVER call other agents directly
- Agents must NEVER modify system state (no writes to sovereign store, no policy changes)
- Agents must NEVER retry execution on their own — retries must be authorized by MSO
- Agent output must be returned to the pipeline; agents must not route results themselves

---

## 3. Agent Registration Structure

```python
AgentRegistration = {
    "name": str,                   # unique agent identifier
    "domain": str,                 # CODE | HOST | MACHINE_OPERATOR | WORK | FIN
    "version": str,                # semantic version (e.g., "1.0.0")
    "description": str,            # plain-language description of what the agent does
    "input_contract": str,         # TypedDict type name for input
    "output_contract": str,        # TypedDict type name for output
    "requires_review": bool,       # whether human review is required before execution
    "capability_scope": list[str], # required capability tokens
    "entrypoint": callable,        # execution function
}
```

---

## 4. Defined Agents

| Name | Domain | Input Contract | Output Contract | Capability Scope | Requires Review |
|------|--------|----------------|-----------------|-----------------|-----------------|
| `code_executor` | CODE | `RunnerExecutionRequest` | `RunnerExecutionResult` | `["code_execute"]` | Conditional |
| `host_launcher` | HOST | `HostActionRequest` | `HostActionResult` | `["host_launch_app"]` | False |
| `machine_operator` | MACHINE_OPERATOR | `machine_operator_request` | `DomainResult` | `["machine_operator_*"]` | Conditional |

---

## 5. Relation to Execution Boundary

```
Pipeline receives AuthorizedPlan (from Police)
  → Pipeline looks up agent in registry
  → Pipeline verifies capability token matches agent's capability_scope
  → Pipeline invokes agent entrypoint
  → Agent executes and returns output
  → Pipeline returns DomainResult to Kernel
```

Agents are invoked by pipelines only. Agents are never invoked by: MSO, Kernel, System Assistant, surfaces, or other agents.

---

## 6. Invariants

- No agent may be invoked without a valid `AuthorizedPlan`
- No agent may execute if its required capability token is missing, expired, or consumed
- Agent invocation control flow must be deterministic and auditable; external execution outcomes must be reported honestly
- `requires_review: true` agents must not execute until an explicit review signal is received
- Every agent invocation must produce an audit entry in `sandbox/audit_store.py`
