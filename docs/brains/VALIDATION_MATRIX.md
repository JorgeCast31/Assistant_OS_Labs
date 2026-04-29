# VALIDATION_MATRIX

Each row defines the exact allowed and forbidden behavior for one system component.

---

## Matrix

| Component | Role | Allowed Actions | Forbidden Actions | Authority Level | Execution Permission | LLM Permission | Failure Behavior |
|-----------|------|-----------------|-------------------|-----------------|---------------------|----------------|-----------------|
| **System Assistant** | Observer | Read system state; explain execution_status; respond to informational queries | Execute pipelines; modify state; authorize; invoke agents; produce execution_status | None | None | Read-only, non-authoritative | Return degraded explanation; no execution impact |
| **Kernel** | Orchestrator | Classify intent; build ExecutionPlan; apply PolicyDecision; route to pipeline; return DomainResult | Authorize; invoke agents directly; produce execution_mode; modify sovereign state | None | None | None | Return DomainResult with error status; fail-closed on blocked policy |
| **MSO Authority Core** | Single authority | Build SovereignIntent; produce GovernanceVerdict; issue capability tokens; manage system state; persist SovereignCycleRecord | Execute domain pipelines; invoke agents; produce narrative; delegate authority to LLM | Sole authority | None (delegates to Kernel) | None | Abort cycle; persist failed record; return blocked DomainResult |
| **MSO Narrative Interface** | Non-authoritative interface | Translate SovereignIntent to CanonicalRequest; produce inspection bundle; consult advisory engine | Produce GovernanceVerdict; modify Authority Core decisions; issue capability tokens; persist sovereign state | None | None | Advisory read-only | Log advisory failure; cycle continues without LLM enrichment |
| **Police** | Enforcement | Validate capability tokens; verify grant conditions; enforce PolicyDecision; consume tokens; bind AuthorizedPlan; write enforcement audit entries | Produce GovernanceVerdict; create capability grants; issue tokens; authorize actions | None | Gate only | None | Block execution; return enforcement error; write audit entry |
| **Agents** | Execution units | Execute declared domain action within pipeline; return DomainResult to pipeline | Decide execution legality; invoke other agents; modify system state; retry without MSO authorization | None | Yes — only through governed pipeline with valid AuthorizedPlan | Bounded to declared capability scope | Return error result to pipeline; write audit entry; no self-retry |
| **Surfaces** | Interaction boundaries | Accept user input; submit intents through Kernel; display results; relay confirmation signals | Invoke agents or pipelines directly; bypass Kernel; create authority; modify policy | None | None | None | Surface-layer error response; no execution impact |
| **Semi-agents** | Internal behavioral components | Apply bounded classification, routing, registry, or risk logic; return output to invoking component | Produce governance decisions; invoke pipelines; invoke agents; persist state; mutate lifecycle state; be promoted to agent without AgentRegistration | None | None | Informational only — output must be marked non-authoritative | Return bounded error output; invoking component handles failure |
| **Lifecycle State Components** | Mutable in-memory lifecycle managers | Own and mutate execution run state; enforce valid state transitions; reject invalid transitions | Authorize execution; produce policy decisions; substitute for audit_store.py; survive process restart | None | None | None | Transitions to terminal state; UI consumers fall back to audit_store.py for historical state |

---

## Authority Levels

| Level | Definition | Components |
|-------|------------|------------|
| **Sole authority** | Only component that may produce execution decisions | MSO Authority Core |
| **Gate only** | Enforces decisions; does not create them | Police |
| **None** | No authority; reads or routes only | Kernel, System Assistant, Surfaces, Agents, Semi-agents, MSO Narrative Interface |

---

## Execution Permission

| Permission | Definition | Components |
|------------|------------|------------|
| **Yes — governed pipeline only** | May execute when pipeline has valid AuthorizedPlan | Agents |
| **None** | Must not execute | All other components |

---

## LLM Permission

| Permission | Definition | Components |
|------------|------------|------------|
| **Advisory read-only** | May consult LLM; output is non-authoritative | MSO Narrative Interface |
| **Informational only — must mark non-authoritative** | May use LLM output if marked narrative | Semi-agents (where applicable) |
| **None** | Must not use LLM output as input to decisions | MSO Authority Core, Police, Kernel, System Assistant, Agents, Surfaces |

---

## Notes

- "None" in Execution Permission means the component must NEVER trigger, initiate, or proxy execution of a domain pipeline or agent.
- "None" in Authority Level means the component must NEVER produce, modify, or substitute a `GovernanceVerdict` or `PolicyDecision`.
- LLM Permission of "None" for MSO Authority Core is absolute: governance decisions must NEVER be LLM-derived.
- Lifecycle State Components mutate in-memory state and are explicitly not semi-agents. Semi-agents must never mutate state. These two categories must not be merged.
