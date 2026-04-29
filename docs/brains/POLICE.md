# POLICE

## 1. Definition

Police is the validation and enforcement layer. It enforces rules produced by MSO against incoming execution requests. Police validates capability tokens, checks grant conditions, and gates pipeline invocation. Police does not create authority, does not decide what is permitted, and does not modify system state beyond tracking token consumption.

---

## 2. Responsibilities

- Validate capability tokens prior to pipeline execution (`capabilities/token_verifier.py`)
- Verify grant conditions are met before execution proceeds (`grants/grant_store.py`)
- Apply `PolicyDecision` produced by the policy engine to gate execution
- Consume capability tokens exactly once per authorized execution (`runners/authority_consumption.py`)
- Gate execution if token is invalid, expired, or already consumed
- Enforce temporal restrictions issued by MSO (`mso/restrictions.py`)
- Bind execution to `AuthorizedPlan` before sandbox invocation (`sandbox/authorized_plan.py`)
- Record enforcement events in the audit log

---

## 3. Non-Responsibilities

- Must NOT create capability grants or tokens
- Must NOT produce `GovernanceVerdict` — that is MSO's responsibility
- Must NOT modify operator state or sovereign state
- Must NOT decide what actions are permitted — that decision comes from MSO
- Must NOT allow execution to proceed on an ambiguous or unresolvable validation
- Must NOT cache or reuse a consumed token

---

## 4. Inputs

| Input | Type | Source |
|-------|------|--------|
| Capability token | signed token | MSO via `token_issuer.py` |
| `PolicyDecision` | TypedDict | `core/policy.py` |
| `ExecutionPlan` | TypedDict | Kernel |
| Grant record | dict | `grants/grant_store.py` |
| Temporal restriction state | dict | `mso/restrictions.py` |

---

## 5. Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `AuthorizedPlan` | TypedDict | Sandbox / Pipeline |
| Token consumption record | dict | `runners/authority_consumption.py` |
| Enforcement audit entry | dict | `sandbox/audit_store.py` |
| Validation error | exception / result | Returned to Kernel; blocks execution |

---

## 6. Boundaries

| Component | Interaction | Direction |
|-----------|-------------|-----------|
| MSO | Receives capability tokens and grant records from MSO | Input |
| Kernel | Receives PolicyDecision and ExecutionPlan from Kernel | Input |
| Sandbox | Produces AuthorizedPlan for sandbox invocation | Output |
| Audit Store | Writes enforcement events | Output |
| Agents | Gates pipeline invocation; does NOT invoke agents directly | Gate only |

---

## 7. Invariants

- Police must NEVER allow execution to proceed without a valid, unconsumed capability token
- Police must NEVER produce an authorization decision — only enforce one already produced by MSO
- A consumed token must NEVER be accepted a second time
- A failed validation must result in execution being fully blocked — no partial execution
- Enforcement must be deterministic: same token + same plan always produces the same enforcement result
- Temporal restrictions must be enforced without exception — no grace periods

---

## 8. Failure Modes

| Failure | System Impact | Recovery |
|---------|--------------|----------|
| Token verification fails (invalid signature) | Execution blocked | AuthorizedPlan not produced; error returned |
| Token already consumed | Execution blocked | Duplicate consumption rejected; error logged |
| Grant record not found | Execution blocked | Fail-closed; no execution |
| Temporal restriction active | Execution blocked | Restriction enforced; no execution |
| `authorized_plan` binding fails | Execution blocked | Sandbox not invoked |

---

## 9. Examples (Allowed)

```
Token: { capability: "code_execute", issued_by: "MSO", consumed: false, expires_at: T+300s }
PolicyDecision: { execution_mode: "auto" }
Police:
  1. token_verifier.verify() → valid
  2. authority_consumption.consume() → token marked consumed
  3. authorized_plan.bind(plan, token) → AuthorizedPlan
  4. Sandbox proceeds with AuthorizedPlan
→ Correct: enforcement without authority creation
```

```
Token: { capability: "code_execute", consumed: true }
Police:
  → token_verifier.verify() → REJECTED (already consumed)
  → Execution blocked
  → Audit entry written
→ Correct: fail-closed on consumed token
```

---

## 10. Examples (Forbidden)

```
FORBIDDEN: Police calls governance_engine.authorize() to create a new grant when token is missing
→ Violation: authority creation
```

```
FORBIDDEN: Police accepts an expired token with a grace period logic
→ Violation: relaxing fail-closed constraint
```

```
FORBIDDEN: Police allows execution to proceed with PolicyDecision { execution_mode: "blocked" }
→ Violation: bypassing enforcement
```

```
FORBIDDEN: Police creates a second token when the first was consumed
→ Violation: authority creation
```
