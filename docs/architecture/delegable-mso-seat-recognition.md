# Delegable MSO Seat Recognition

**Milestone:** MSO Delegable + GPT on Seat  
**Status:** Architecture Specification (PHASE 1)  
**Date:** 2026-05-08  
**Author:** Architecture Review (Code-First Analysis)  
**Source of Truth:** Repository code in `assistant_os/mso/`, `assistant_os/police/`, `assistant_os/capabilities/`, `assistant_os/sandbox/`

---

## 1. CORE CONCEPTS

### 1.1 MSO Seat (Master Operator Seat)

An **MSO Seat** is a named, bounded authority position within the Assistant_OS_Labs execution system.

A seat is:
- **Identifiable**: Has seat_id, seat_type, holder identity
- **Scoped**: Carries explicit list of allowed operations (plan, audit, classify, recommend, prepare_execution_request)
- **Revocable**: Can be revoked at any time, with explicit audit record
- **Auditable**: Every action using seat authority must be traced to seat_id and audit_ref
- **Temporal**: Has issued_at, expires_at (optional), revoked_at (optional) timestamps
- **Restrictive**: Carries explicit list of forbidden_actions

A seat does NOT:
- Convey direct execution authority
- Bypass PolicyDecision or Police Gate
- Permit modification of system internals
- Create a second sovereign authority

### 1.2 Canonical MSO vs. Delegated MSO Seat

#### Canonical MSO (System Default Authority)
- **Identity**: The system itself (represented as "kernel" or system principal)
- **Authority**: Absolute, unrestricted
- **Scope**: All operations
- **Revocation**: Not applicable (cannot revoke system)
- **Expiration**: Never expires
- **Enforcement**: Hardcoded within runtime

#### Delegated MSO Seat (Temporary Bounded Authority)
- **Identity**: An external model or human (GPT, Claude, human_operator@domain)
- **Authority**: Explicit and limited (only what's in `scope`)
- **Scope**: Explicitly enumerated list of allowed operations
- **Revocation**: Can be revoked at any time with audit trail
- **Expiration**: Can have explicit TTL (expires_at)
- **Enforcement**: Registry-checked + Policy/Police evaluated at runtime

**Key Difference**: Canonical MSO is architectural authority (implicit). Delegated MSO Seat is operational authority (explicit, bounded, temporary).

---

## 2. AUTHORITY HIERARCHY

### 2.1 Six Authority Archetypes

```
Hierarchy (top = strongest authority):

    ┌─ Canonical MSO (System)
    │  └─ Unrestricted, non-revocable, non-delegable
    │
    ├─ Human Operator (Direct)
    │  └─ Can authorize, approve, revoke seats
    │  └─ Can execute with full scope if authenticated
    │
    ├─ Delegated MSO Seat (GPT / Claude / External Model)
    │  └─ Bounded by seat contract
    │  └─ Can plan, audit, recommend, prepare
    │  └─ CANNOT execute directly
    │  └─ Can be revoked by Human Operator or Canonical MSO
    │
    ├─ Advisory Model (Conversational GPT)
    │  └─ Provides suggestions only (no seat)
    │  └─ No authority, no scope
    │  └─ Result is informational only
    │
    └─ Executor (Sandbox Runtime)
       └─ Executes only AuthorizedPlan
       └─ Bound by CapabilityToken and CapabilityScope
       └─ Cannot act independently
```

### 2.2 MACHINE_OPERATOR (Future Arm)

**MACHINE_OPERATOR** is a potential future capability that would allow a system agent to perform infrastructure-level operations (create, modify, destroy resources).

**Status**: Not integrated yet.  
**Blocker**: S-POLICE-CORE-03 (Police Gate token-bound implementation).  
**Subordination**: If integrated, MACHINE_OPERATOR must be:
1. Bound to an explicit seat (cannot operate without seat context)
2. Gated by Police enforcement
3. Audited at every invocation
4. Subject to kill-switch / revocation

A delegated MSO seat (even one with broad scope) **CANNOT** directly invoke MACHINE_OPERATOR. Any MACHINE_OPERATOR action must:
1. Go through PolicyDecision evaluation
2. Pass Police Gate check
3. Be authorized by CapabilityToken
4. Produce an AuthorizedPlan
5. Execute through Runner

---

## 3. DELEGATED MSO SEAT DEFINITIONS

### 3.1 What is a "Delegated MSO Seat"?

A delegated MSO seat is a **named permission grant** that allows an external agent (GPT, Claude, another model, or a human) to occupy a temporary authority position with explicit boundaries.

**Formal Definition:**
```
DelegatedMSOSeat = (
    seat_id: unique identifier,
    seat_type: classification (gpt, claude, human, external_model),
    holder: the agent/person occupying the seat,
    issued_by: who granted the seat,
    scope: list of allowed operations,
    forbidden_actions: explicit prohibitions,
    requires_policy: bool (must pass PolicyDecision),
    requires_police: bool (must pass Police Gate),
    requires_human_approval: bool (requires confirmation for certain actions),
    status: (active | expired | revoked | suspended | pending_approval),
    issued_at: datetime,
    expires_at: optional datetime,
    revoked_at: optional datetime,
    audit_ref: reference to creation/revocation audit event
)
```

### 3.2 What is "GPT on Seat"?

**"GPT on seat"** means:

1. **GPT is recognized** by the system as occupying a delegated MSO seat
2. **GPT has explicit scope**: Can only perform operations in the seat's scope list
3. **GPT must be authorized**: Every action goes through PolicyDecision and Police Gate
4. **GPT cannot execute**: Even if GPT "plans" an action, execution requires AuthorizedPlan + CapabilityToken
5. **GPT can be revoked**: The seat can be revoked immediately, denying all future access
6. **GPT is auditable**: All actions are attributed to the seat_id and holder identity

**Metaphor**: GPT sits in a chair (the seat). The chair has armrests (scope boundaries). GPT can see across the table (audit, plan, recommend). GPT cannot stand up and walk to the machine (execute directly). If we need to remove GPT from the chair, we revoke the seat.

### 3.3 How is a Delegated MSO Seat Recognized?

#### Recognition Mechanism

1. **At Request Time**: 
   - Request metadata includes `seat_id` and `seat_holder`
   - System queries MSOSeatRegistry for seat record
   
2. **Validation**:
   - Seat exists in registry
   - Seat status == "active"
   - Seat has not expired (expires_at is null or > now)
   - Seat has not been revoked (revoked_at is null)

3. **Scope Binding**:
   - Requested action is in seat.scope list
   - Requested action is NOT in seat.forbidden_actions list

4. **Authority Check**:
   - If requires_policy == True: action passes PolicyDecision
   - If requires_police == True: action passes Police Gate
   - If requires_human_approval == True: confirmation required for this action

5. **Token Issuance**:
   - If all checks pass, CapabilityToken issued
   - Token carries seat context in OperationBinding.principal_id or new seat_id field

6. **Audit Recording**:
   - Action attributed to seat_id, seat_holder, timestamp
   - Audit event references seat.audit_ref

#### Recognition Flow (Pseudocode)

```python
def recognize_seat_action(request):
    seat_id = request.metadata.seat_id
    seat = MSOSeatRegistry.get_seat(seat_id)
    
    # Step 1: Does seat exist and is it active?
    if not seat or seat.status != "active":
        return DENY("Seat not active")
    
    # Step 2: Has seat expired?
    if seat.expires_at and seat.expires_at < now():
        return DENY("Seat expired")
    
    # Step 3: Has seat been revoked?
    if seat.revoked_at is not None:
        return DENY("Seat revoked")
    
    # Step 4: Is requested action in scope?
    if request.action not in seat.scope:
        return DENY("Action not in seat scope")
    
    # Step 5: Is action explicitly forbidden?
    if request.action in seat.forbidden_actions:
        return DENY("Action explicitly forbidden")
    
    # Step 6: Does action require policy approval?
    if seat.requires_policy:
        policy_decision = PolicyDecision.evaluate(request)
        if not policy_decision.permitted:
            return DENY(f"Policy denied: {policy_decision.reason}")
    
    # Step 7: Does action require police gate?
    if seat.requires_police:
        police_decision = Police.check(request)  # S-POLICE-CORE-03
        if not police_decision.permitted:
            return DENY(f"Police gate denied: {police_decision.reason}")
    
    # Step 8: Does action require human approval?
    if seat.requires_human_approval:
        return DEFER("Requires human confirmation")
    
    # Step 9: Issue capability token
    token = CapabilityToken.issue(
        operation_binding=OperationBinding(
            principal_id=seat_id,
            subject_state="active",
            action_type=request.action,
            capability=request.capability,
            operation_key=request.operation_key,
            seat_id=seat_id  # NEW field
        )
    )
    
    return ALLOW(token=token, seat_context=seat)
```

---

## 4. PERMISSIONS AND PROHIBITIONS

### 4.1 What a Delegated MSO Seat CAN Do

**By Design (Scope Operations):**
- `plan`: Propose plans, analyses, recommendations (does not execute)
- `audit`: Review logs, trace authority paths, check compliance
- `classify`: Categorize issues, tasks, requests
- `recommend`: Suggest actions, optimizations, next steps
- `prepare_execution_request`: Prepare an AuthorizedPlan for human approval or automatic execution

**Operational Constraints:**
- Can read system state (subject to policy restrictions)
- Can propose changes (via plan or recommendation)
- Can ask for authorization (via prepare_execution_request)
- Can be revoked immediately
- Can have its actions audited retroactively
- Can expire automatically based on TTL

### 4.2 What a Delegated MSO Seat CANNOT Do

**Hard Prohibitions (By Design):**
- ❌ Execute code directly (no direct invocation of runners or pipelines)
- ❌ Bypass PolicyDecision (every action subject to policy check)
- ❌ Bypass Police Gate (if requires_police, must pass gate)
- ❌ Invoke MACHINE_OPERATOR directly (must go through full authority chain)
- ❌ Modify PolicyDecision rules (policy is system authority)
- ❌ Modify Police Gate rules (police is system authority)
- ❌ Create or revoke other seats without authorization
- ❌ Modify its own scope or forbidden_actions
- ❌ Prevent its own revocation
- ❌ Extend its own expiration
- ❌ Disable or modify audit trails
- ❌ Assume system identity (kernel, canonical MSO)
- ❌ Treat itself as sovereign (it is subordinate to contracts)

**Architectural Constraints:**
- Cannot act without explicit seat context
- Cannot bypass CapabilityToken requirement
- Cannot bypass AuthorizedPlan binding
- Cannot bypass CapabilityScope enforcement
- Cannot operate after revocation or expiration
- Cannot modify sandbox internals

---

## 5. MINIMUM CONTRACT FIELDS

### 5.1 DelegatedMSOSeat Dataclass

```python
@dataclass
class DelegatedMSOSeat:
    """Formal seat contract."""
    
    # Identity
    seat_id: str                                    # UUID or unique identifier
    seat_type: MSOSeatType                          # Enum: gpt, claude, human, external_model
    holder: str                                     # "gpt-4", "claude-opus", "user@example.com", etc.
    
    # Issuance
    issued_by: str                                  # "kernel", "human_operator", system principal
    issued_at: datetime                             # ISO 8601 timestamp
    
    # Scope and Restrictions
    scope: list[MSOSeatScope]                       # Allowed operations: [plan, audit, classify, recommend, prepare_execution_request]
    forbidden_actions: list[str]                    # Explicit prohibitions beyond scope
    
    # Authority Requirements
    requires_policy: bool = True                    # Must pass PolicyDecision.evaluate()
    requires_police: bool = True                    # Must pass Police.check() (deferred to S-POLICE-CORE-03)
    requires_human_approval: bool = False           # Requires human confirmation for certain actions
    
    # Lifecycle
    status: MSOSeatStatus                           # active | expired | revoked | suspended | pending_approval
    expires_at: Optional[datetime] = None           # TTL; null means never expires
    revoked_at: Optional[datetime] = None           # When revoked (if revoked); null means not revoked
    
    # Audit
    audit_ref: str                                  # Reference to audit log entry for seat creation
    revocation_audit_ref: Optional[str] = None      # Reference to audit log entry for revocation (if revoked)
    revocation_reason: Optional[str] = None         # Why the seat was revoked
```

### 5.2 Enums

```python
class MSOSeatType(str, Enum):
    """Classification of seat holder."""
    GPT_CONVERSATIONAL = "gpt_conversational"       # GPT-4, GPT-4-turbo (advisory/conversational)
    CLAUDE_ANALYTICAL = "claude_analytical"         # Claude Opus, Sonnet (analytical/developer)
    HUMAN_OPERATOR = "human_operator"               # Human user (direct authority)
    EXTERNAL_MODEL = "external_model"               # Other model/system
    SERVICE_ACCOUNT = "service_account"             # System service

class MSOSeatScope(str, Enum):
    """Allowed operations for a seat."""
    PLAN = "plan"                                   # Propose plans, analyses
    AUDIT = "audit"                                 # Review logs, trace authority
    CLASSIFY = "classify"                           # Categorize issues
    RECOMMEND = "recommend"                         # Suggest actions
    PREPARE_EXECUTION_REQUEST = "prepare_execution_request"  # Prepare AuthorizedPlan

class MSOSeatStatus(str, Enum):
    """Lifecycle state of a seat."""
    ACTIVE = "active"                               # Seat is valid and usable
    EXPIRED = "expired"                             # TTL exceeded
    REVOKED = "revoked"                             # Explicitly revoked
    SUSPENDED = "suspended"                         # Temporarily suspended
    PENDING_APPROVAL = "pending_approval"           # Awaiting authorization
```

### 5.3 Validation Rules

```python
def validate_delegated_mso_seat(seat: DelegatedMSOSeat) -> None:
    """Validate seat contract."""
    
    # Identity checks
    if not seat.seat_id or not seat.seat_id.strip():
        raise ValueError("seat_id is required")
    
    if not seat.holder or not seat.holder.strip():
        raise ValueError("holder is required")
    
    if not seat.issued_by or not seat.issued_by.strip():
        raise ValueError("issued_by is required")
    
    # Scope checks
    if not seat.scope:
        raise ValueError("scope must be non-empty")
    
    for op in seat.scope:
        if not isinstance(op, MSOSeatScope):
            raise ValueError(f"Invalid scope operation: {op}")
    
    # Timestamp checks
    if not seat.issued_at:
        raise ValueError("issued_at is required")
    
    if seat.issued_at.tzinfo is None:
        raise ValueError("issued_at must be timezone-aware")
    
    if seat.expires_at and seat.expires_at.tzinfo is None:
        raise ValueError("expires_at must be timezone-aware if set")
    
    if seat.expires_at and seat.expires_at <= seat.issued_at:
        raise ValueError("expires_at must be after issued_at")
    
    # Status consistency
    if seat.status == MSOSeatStatus.REVOKED:
        if not seat.revoked_at:
            raise ValueError("revoked seat must have revoked_at")
    
    if seat.revoked_at and seat.status != MSOSeatStatus.REVOKED:
        raise ValueError("revoked_at set but status is not REVOKED")
    
    # Audit ref
    if not seat.audit_ref or not seat.audit_ref.strip():
        raise ValueError("audit_ref is required")
```

---

## 6. AUDIT AND REVOCATION

### 6.1 How Seats are Audited

Every delegated MSO seat action creates an audit trail:

1. **Creation Audit**:
   - Event: "SEAT_ISSUED"
   - seat_id, seat_type, holder, issued_by, scope, issued_at
   - audit_ref generated and stored in seat.audit_ref

2. **Action Audit**:
   - Event: "SEAT_ACTION"
   - seat_id, holder, action_type, outcome (ALLOW/DENY), timestamp
   - trace_id linking to execution context
   - policy_decision_id (if policy was consulted)
   - police_decision_id (if police was consulted)

3. **Revocation Audit**:
   - Event: "SEAT_REVOKED"
   - seat_id, holder, revoked_by, revoked_at, reason
   - revocation_audit_ref generated and stored in seat.revocation_audit_ref

4. **Expiration Audit**:
   - Event: "SEAT_EXPIRED"
   - seat_id, holder, expires_at
   - Generated automatically when seat.expires_at < now()

5. **Audit Storage**:
   - All audit events written to audit_store (existing Audit infrastructure)
   - Immutable once written
   - Queryable by seat_id, holder, timestamp range, event_type
   - Linked to execution traces via trace_id

### 6.2 Revocation Mechanism

#### Immediate Revocation

```python
def revoke_seat(
    seat_id: str,
    revoked_by: str,
    reason: str,
    audit_ref: str
) -> None:
    """Revoke a seat immediately."""
    
    seat = MSOSeatRegistry.get_seat(seat_id)
    if not seat:
        raise ValueError(f"Seat {seat_id} not found")
    
    # Mark as revoked
    seat.status = MSOSeatStatus.REVOKED
    seat.revoked_at = now()
    seat.revocation_audit_ref = audit_ref
    seat.revocation_reason = reason
    
    # Record in registry (process-local)
    MSOSeatRegistry.update_seat(seat)
    
    # Audit trail
    audit_store.record_event(
        event_type="SEAT_REVOKED",
        seat_id=seat_id,
        holder=seat.holder,
        revoked_by=revoked_by,
        reason=reason,
        audit_ref=audit_ref
    )
```

#### Effect of Revocation

Once a seat is revoked:
- ✗ No new actions using this seat can be authorized
- ✗ `recognize_seat_action()` returns DENY immediately
- ✗ No new CapabilityToken issued for this seat
- ✗ No new AuthorizedPlan created for this seat
- ✓ Historical actions remain in audit trail
- ✓ Revocation is immediately visible to all components

#### Authority for Revocation

Who can revoke a seat?
1. **Canonical MSO** (system authority - highest privilege)
2. **Human Operator** (authenticated user with operator role)
3. **Self-revocation** (a delegated seat can revoke itself if scope permits)

**Rule**: Revocation cannot be prevented or deferred by the seat itself.

### 6.3 Automatic Expiration

If a seat has `expires_at` set:

```python
def is_seat_expired(seat: DelegatedMSOSeat) -> bool:
    """Check if seat has expired."""
    if not seat.expires_at:
        return False
    return seat.expires_at < now()

def recognize_seat_action(request):
    seat = MSOSeatRegistry.get_seat(request.seat_id)
    
    if is_seat_expired(seat):
        seat.status = MSOSeatStatus.EXPIRED
        MSOSeatRegistry.update_seat(seat)
        
        audit_store.record_event(
            event_type="SEAT_EXPIRED",
            seat_id=seat.seat_id,
            expires_at=seat.expires_at
        )
        
        return DENY("Seat expired")
    
    return ALLOW(...)
```

---

## 7. INTEGRATION WITH CORE SYSTEMS

### 7.1 PolicyDecision Integration

**Current State** (from `assistant_os/policy/policy_models.py`):
- PolicyDecision contains: request_id, outcome (APPROVED/DENIED/NEEDS_CONSENT/QUARANTINED), reason, permitted field

**Proposed Integration**:
```python
# In policy_models.py (future extension)
@dataclass
class PolicyDecision:
    # ... existing fields ...
    
    # NEW: Seat context (for future integration)
    evaluated_seat_id: Optional[str] = None         # Which seat was evaluated
    seat_scope_checked: bool = False                # Was seat scope validated
    seat_required_policy: bool = False              # Did seat require policy check
```

**Flow**:
1. Request arrives with seat_id
2. `recognize_seat_action()` checks seat is active
3. If seat.requires_policy == True, request forwarded to PolicyDecision.evaluate()
4. PolicyDecision returns APPROVED/DENIED
5. If DENIED, action blocked
6. If APPROVED, continue to Police Gate (if requires_police)

### 7.2 CapabilityToken Integration

**Current State** (from `assistant_os/capabilities/token_models.py`):
- OperationBinding contains: principal_id, subject_state, action_type, capability, operation_key
- CapabilityToken is issued after PolicyDecision.APPROVED

**Proposed Integration**:
```python
# In token_models.py (future extension)
@dataclass(frozen=True)
class OperationBinding:
    principal_id: str                               # "user_id" or "seat_id"
    subject_state: str
    action_type: str
    capability: Optional[str]
    operation_key: str
    
    # NEW: Seat context
    seat_id: Optional[str] = None                   # If action performed via seat
    seat_scope: Optional[list[str]] = None          # Copy of seat scope at token time
```

**Flow**:
1. Seat action passes recognition and policy check
2. CapabilityToken issued with OperationBinding.seat_id = seat_id
3. Token carries seat context across execution boundary
4. Runner/Executor can verify token is bound to seat
5. Audit can correlate token to original seat

### 7.3 CapabilityScope Integration

**Current State**: CapabilityScope manages what operations are allowed based on capability names.

**Proposed Integration**:
- Seat scope (plan, audit, classify, recommend, prepare_execution_request) is orthogonal to capability scope
- Seat scope is a **permission filter** applied before capability check
- If action is not in seat.scope, it is denied before CapabilityScope is evaluated
- Seat scope is more restrictive than capability scope

### 7.4 Police Enforcer / Gate Integration

**Current State** (from `assistant_os/police/enforcement.py`):
```python
def check(request: PoliceGateRequest) -> PoliceDecision:
    raise NotImplementedError(
        "Token-bound Police gate is not implemented until S-POLICE-CORE-03"
    )
```

**Proposed Integration** (deferred):
```python
# In police/enforcement.py (S-POLICE-CORE-03)
def check(request: PoliceGateRequest) -> PoliceDecision:
    # Check if request came from a delegated seat
    if request.seat_id:
        seat = MSOSeatRegistry.get_seat(request.seat_id)
        if not seat or seat.status != "active":
            return PoliceDecision(
                outcome=PoliceOutcome.DENIED,
                reason=PoliceReason.SEAT_INVALID
            )
    
    # Proceed with token-bound gate logic (S-POLICE-CORE-03)
    # ... implementation deferred ...
```

**PoliceGateRequest Extension**:
```python
# In police/gate_models.py (future)
@dataclass(frozen=True, kw_only=True)
class PoliceGateRequest:
    # ... existing fields ...
    
    # NEW: Seat context
    seat_id: Optional[str] = None
    seat_holder: Optional[str] = None
    seat_scope: Optional[list[str]] = None
```

### 7.5 AuthorizedPlan Integration

**Current State** (from `assistant_os/sandbox/authorized_plan.py`):
- AuthorizedPlan contains: execution_id, plan_id, authorized_plan_hash, policy_id, capability_scope, runtime_profile, authority_artifact

**Proposed Integration**:
```python
# In authorized_plan.py (future)
@dataclass
class AuthorizedPlan:
    # ... existing fields ...
    
    # NEW: Optional seat binding
    issued_by_seat: Optional[str] = None            # Which seat prepared this plan
    seat_scope_at_prep: Optional[list[str]] = None  # Seat scope at authorization time
```

**Flow**:
1. Seat requests `prepare_execution_request`
2. Seat generates AuthorizedPlan with issued_by_seat = seat_id
3. Runner validates that AuthorizedPlan.issued_by_seat matches request context
4. Execution proceeds with seat context preserved

### 7.6 Audit Infrastructure Integration

**Current State**: audit_store exists for recording events.

**Integration**:
- Seat creation → audit_store.record_event("SEAT_ISSUED", ...)
- Seat action → audit_store.record_event("SEAT_ACTION", seat_id, outcome, ...)
- Seat revocation → audit_store.record_event("SEAT_REVOKED", ...)
- Seat expiration → audit_store.record_event("SEAT_EXPIRED", ...)
- All events are queryable by seat_id, audit_ref, timestamp

---

## 8. RISKS AND MITIGATIONS

### 8.1 Authority Drift

**Risk**: A delegated seat gradually acquires more authority than originally intended, through:
- Scope creeping upward
- Checks being bypassed incrementally
- Interpretation drift (what "plan" means expands)

**Mitigation**:
- Scope is immutable after issuance (enum, checked at init)
- Scope enforced at every action (no exceptions)
- Audit trail captures every scope boundary crossing
- Regular audit reviews detect drift
- Revocation can happen immediately if drift detected

### 8.2 Fake Delegation

**Risk**: An attacker fabricates a false seat (claims to have seat authority but doesn't).

**Mitigation**:
- Seats only exist if registered in MSOSeatRegistry
- Registry is process-local and authoritative
- Seat_id + audit_ref form a cryptographic-like pairing
- Fabricated seat_id will fail lookup → DENY
- Audit trail shows every lookup failure
- Human Operator is the only source of seat authority initially

### 8.3 Stale Seat

**Risk**: A seat expires or is revoked, but cached references to it remain active.

**Mitigation**:
- Every action queries MSOSeatRegistry for fresh seat state
- Expired seats automatically marked in registry
- Revoked seats immediately visible
- No caching of seat state across request boundaries
- Audit captures every use-after-revocation attempt

### 8.4 Unrevoked Seat

**Risk**: A seat should have been revoked but wasn't, allowing continued unauthorized use.

**Mitigation**:
- Revocation is atomic (status + revoked_at + audit_ref all set together)
- Revocation is irreversible (cannot unrevoke)
- Revocation is auditable (audit_ref logged)
- Regular audit checks identify unrevoked seats beyond TTL
- Human Operator has kill-switch power (though kill-switch itself not yet implemented)

### 8.5 Model Treated as Sovereign

**Risk**: A delegated seat (GPT, Claude) is treated as if it were canonical MSO (system authority).

**Mitigation**:
- Architecture explicitly distinguishes canonical MSO from delegated seat
- Delegated seat CANNOT modify Policy, Police, MSO runtime
- Delegated seat CANNOT revoke or modify other seats (without authorization)
- Every delegated seat action is subordinate to Policy/Police contracts
- Tests enforce that delegated seat cannot operate as sovereign

### 8.6 Execution Bypass

**Risk**: A delegated seat somehow causes code execution without going through proper authorization:
- Direct invocation of runners
- Bypassing AuthorizedPlan requirement
- Bypassing CapabilityToken requirement

**Mitigation**:
- Delegated seat scope does NOT include "execute" or "direct_execution"
- Only AuthorizedPlan + CapabilityToken allows execution
- Runners validate that execution_id matches seat context
- Audit logs every execution attempt and its seat binding
- Tests verify that delegated seat cannot invoke runners

### 8.7 MACHINE_OPERATOR Bypass

**Risk**: A delegated seat (especially with broad scope) could invoke MACHINE_OPERATOR without going through Police Gate.

**Mitigation**:
- MACHINE_OPERATOR not integrated until S-POLICE-CORE-03 completes
- Delegated seat scope does NOT include "invoke_machine_operator"
- If/when MACHINE_OPERATOR is integrated, it must:
  1. Check that request has seat context
  2. Require Police Gate check (when implemented)
  3. Require explicit human approval
  4. Audit every invocation to seat_id

---

## 9. WHAT IS NOT IMPLEMENTED YET

This specification defines the **contract and recognition mechanism** for delegated MSO seats. The following are explicitly NOT implemented in PHASE 1-2:

### 9.1 Deferred to S-POLICE-CORE-03
- [ ] Police Gate token-bound enforcement (`police/enforcement.py` is stub)
- [ ] Revocation via Police Gate (when Police Gate is implemented)
- [ ] Police decision caching for delegated seats

### 9.2 Not Implemented (Out of Scope)
- [ ] MACHINE_OPERATOR integration (blocked until Police Gate closes)
- [ ] UI/CLI for seat management (future phase)
- [ ] Seat delegation chains (seat delegating to another seat)
- [ ] Conditional scope (scope that changes based on time/context)
- [ ] Rate limiting per seat
- [ ] Cost accounting per seat
- [ ] Federated/distributed seat registry (stays process-local)
- [ ] Persistence of seat registry (stays in-memory)
- [ ] Cryptographic signing of seat contracts (process-local only)

### 9.3 Unchanged (Not Modified)
- Core/orchestrator.py (request entry point) - not modified
- webhook_server.py (webhook ingestion) - not modified
- Pipelines (execution channels) - not modified
- Runner invocation (execution dispatch) - not modified
- PolicyDecision (existing policy engine) - not modified yet (extended in future)
- AuthorizedPlan (existing authorization) - not modified yet (extended in future)

---

## 10. CLOSURE CRITERIA FOR MILESTONE

The milestone "MSO Delegable + GPT on Seat Recognition" is considered **COMPLETE** when:

### 10.1 Specification Complete
- [x] Formal definition of DelegatedMSOSeat documented
- [x] Distinction between canonical MSO and delegated seat clear
- [x] Authority hierarchy defined
- [x] Scope and forbidden actions documented
- [x] Recognition mechanism specified (pseudocode provided)
- [x] Audit and revocation mechanisms documented
- [x] Minimum contract fields specified
- [x] Enums and validation rules provided
- [x] Integration points with Policy, Police, Capabilities, AuthorizedPlan identified
- [x] Risks enumerated and mitigations documented
- [x] Out-of-scope items explicitly listed
- [x] Closure criteria defined

### 10.2 Contract Implemented
- [ ] DelegatedMSOSeat dataclass created in `assistant_os/mso/delegated_seat.py`
- [ ] Validation logic implemented
- [ ] Enums defined (MSOSeatType, MSOSeatScope, MSOSeatStatus)
- [ ] No integration with execution path yet (isolated contract)

### 10.3 Registry Implemented
- [ ] MSOSeatRegistry created in `assistant_os/mso/delegated_seat_registry.py`
- [ ] Process-local storage (in-memory, no persistence)
- [ ] Core methods: register, lookup, revoke, is_active, get_scope
- [ ] No integration with production flow yet (isolated registry)

### 10.4 Tests Implemented
- [ ] tests/test_delegated_mso_seat.py created
- [ ] Test: Delegated seat active allows plan/audit/recommend
- [ ] Test: Delegated seat does NOT allow direct_execution
- [ ] Test: Delegated seat cannot invoke MACHINE_OPERATOR directly
- [ ] Test: Revoked seat denies all actions
- [ ] Test: Expired seat denies all actions
- [ ] Test: Registry does not execute, only evaluates
- [ ] Test: Requires_policy/requires_police flags honored in contract
- [ ] Test: Forbidden_actions enforced
- [ ] All tests passing

### 10.5 Authority Path Audit
- [ ] PHASE 5 task: Execute Authority Path Audit
- [ ] Confirm MSO is obligatory in main path
- [ ] Confirm PolicyDecision is consulted
- [ ] Confirm Police entry point is available
- [ ] Confirm CapabilityToken path is correct
- [ ] Identify any authority bypass risks
- [ ] Document findings in AUTHORITY_PATH_AUDIT.md

### 10.6 Integration Plan Documented
- [ ] PoliceGateRequest extension documented (for S-POLICE-CORE-03)
- [ ] PolicyDecision extension documented (for future)
- [ ] AuthorizedPlan extension documented (for future)
- [ ] OperationBinding extension documented (for future)
- [ ] Integration sequence documented

### 10.7 NO-GO Rule for OpenClaw
- [ ] Explicit decision: MACHINE_OPERATOR integration deferred until S-POLICE-CORE-03
- [ ] Rule documented: "Do not integrate MACHINE_OPERATOR until Police Gate token-bound is complete"
- [ ] This rule enforced in code review / CI checks

### 10.8 Ready for Sprint 19 Planning
- [ ] Decision made: Next sprint is S-POLICE-CORE-03, policy consolidation, or MSO path hardening
- [ ] Milestone handoff clear
- [ ] No ambiguities remaining about delegable seat design

---

## 11. RELATIONSHIP TO CURRENT AUTHORITY HOLDERS

### 11.1 Canonical MSO (System Kernel)

**Current Role**: System-level authority, implicit and non-revocable.  
**Scope**: Unrestricted.  
**Revocable**: No.  
**Expirable**: No.  
**Audit**: Implicit (actions attributed to system).

### 11.2 GPT (Conversational Model)

**Current Role**: Advisory-only, no authority.  
**Proposed Role with Delegable Seat**: Can occupy "gpt_conversational" seat with explicit scope (plan, audit, classify, recommend).  
**If Seated**: Must pass Policy/Police checks, cannot execute directly, can be revoked.  
**If Not Seated**: Remains advisory-only (informational role only).

**Example Seat (GPT on Seat)**:
```python
DelegatedMSOSeat(
    seat_id="gpt-seat-001",
    seat_type=MSOSeatType.GPT_CONVERSATIONAL,
    holder="gpt-4-turbo",
    issued_by="kernel",
    scope=[
        MSOSeatScope.PLAN,
        MSOSeatScope.AUDIT,
        MSOSeatScope.RECOMMEND,
        MSOSeatScope.CLASSIFY
    ],
    forbidden_actions=["direct_execution", "invoke_machine_operator", "modify_policy"],
    requires_policy=True,
    requires_police=True,
    requires_human_approval=False,
    status=MSOSeatStatus.ACTIVE,
    issued_at=now(),
    expires_at=now() + timedelta(hours=24),  # 24-hour TTL
    audit_ref="audit-evt-gpt-seat-001"
)
```

### 11.3 Claude (Analytical/Developer Model)

**Current Role**: Code-focused advisory, no authority.  
**Proposed Role with Delegable Seat**: Can occupy "claude_analytical" seat with explicit scope (plan, audit, classify, recommend, prepare_execution_request).  
**If Seated**: Must pass Policy/Police checks, can prepare execution plans, can be revoked.  
**If Not Seated**: Remains advisory-only.

**Example Seat (Claude on Seat)**:
```python
DelegatedMSOSeat(
    seat_id="claude-seat-dev-001",
    seat_type=MSOSeatType.CLAUDE_ANALYTICAL,
    holder="claude-opus",
    issued_by="kernel",
    scope=[
        MSOSeatScope.PLAN,
        MSOSeatScope.AUDIT,
        MSOSeatScope.RECOMMEND,
        MSOSeatScope.CLASSIFY,
        MSOSeatScope.PREPARE_EXECUTION_REQUEST
    ],
    forbidden_actions=["direct_execution", "invoke_machine_operator", "modify_police"],
    requires_policy=True,
    requires_police=True,  # Because it can prepare execution requests
    requires_human_approval=True,  # Execution requests require confirmation
    status=MSOSeatStatus.ACTIVE,
    issued_at=now(),
    expires_at=now() + timedelta(days=7),  # 7-day TTL
    audit_ref="audit-evt-claude-seat-dev-001"
)
```

### 11.4 Human Operator

**Current Role**: Direct authority, explicit actions.  
**Role with Delegable Seat Framework**: Can authorize/revoke seats, can occupy human_operator seat, can directly execute or approve execution.  
**Explicit Seat** (optional): May or may not need a formal seat (depends on implementation).  
**Authority Level**: Highest (can revoke any seat, modify policy, invoke MACHINE_OPERATOR when available).

---

## 12. DECISION: DEFERRAL TO S-POLICE-CORE-03

This specification documents the **structure** of delegable MSO seats but defers the **enforcement mechanism** for token-bound Police Gate to **S-POLICE-CORE-03**.

### Why Deferred?

Currently, `police/enforcement.py` raises `NotImplementedError`:

```python
def check(request: PoliceGateRequest) -> PoliceDecision:
    raise NotImplementedError(
        "Token-bound Police gate is not implemented until S-POLICE-CORE-03"
    )
```

Until S-POLICE-CORE-03 is complete:
- Police Gate cannot enforce seat-aware decisions
- MACHINE_OPERATOR cannot be safely integrated
- Full delegation enforcement is incomplete

### Interim Behavior

Until S-POLICE-CORE-03:
1. Delegated seats are recognized and validated at the registry level
2. PolicyDecision.evaluate() still runs (policy engine is implemented)
3. Police.check() is skipped or returns DEFERRED
4. Actions may proceed based on policy alone
5. Police enforcement is marked as "pending completion"

### Post-S-POLICE-CORE-03

Once S-POLICE-CORE-03 completes:
1. Police.check() will implement token-bound enforcement
2. Seat context will be passed to Police Gate
3. Police will deny out-of-scope seat actions
4. MACHINE_OPERATOR can be integrated with full gatekeeping
5. Enforcement becomes complete and binding

---

## 13. IMPLEMENTATION ROADMAP

### PHASE 1: Architecture Specification ✅ (This Document)
**Output**: `docs/architecture/delegable-mso-seat-recognition.md`  
**Contains**: Formal definitions, contracts, integration points, risks, closure criteria.

### PHASE 2: Delegated Seat Contract (Ready)
**Output**: `assistant_os/mso/delegated_seat.py`  
**Contains**: DelegatedMSOSeat dataclass, enums, validation logic.  
**Constraints**: Isolated, no side effects, no execution.

### PHASE 3: Seat Registry (Ready if PHASE 2 clean)
**Output**: `assistant_os/mso/delegated_seat_registry.py`  
**Contains**: MSOSeatRegistry, register/lookup/revoke operations.  
**Constraints**: Process-local, in-memory, no persistence.

### PHASE 4: Tests (Ready if PHASE 3 clean)
**Output**: `tests/test_delegated_mso_seat.py`  
**Contains**: Lifecycle, scope, revocation, integration tests.  
**Coverage**: All clauses from contract, all enum states, edge cases.

### PHASE 5: Authority Path Audit (Separate effort)
**Output**: `AUTHORITY_PATH_AUDIT.md`  
**Contains**: Verification that PolicyDecision, Police, CapabilityToken, AuthorizedPlan are in the true execution path.  
**Discovery**: Identify any authority bypass risks.

### PHASE 6: Integration (Post-S-POLICE-CORE-03)
**Output**: Extensions to PolicyDecision, PoliceGateRequest, OperationBinding, AuthorizedPlan.  
**Constraints**: Only after S-POLICE-CORE-03 gate is complete.

---

## REFERENCES

### Code Locations (Source of Truth)

- `assistant_os/mso/` — MSO module, delegation primitives
- `assistant_os/police/models.py` — Police models (PoliceCheckRequest, PoliceEvaluation)
- `assistant_os/police/gate_models.py` — Police gate (PoliceGateRequest, PoliceDecision)
- `assistant_os/police/enforcement.py` — Police gate stub (S-POLICE-CORE-03 deferred)
- `assistant_os/policy/policy_models.py` — Policy models (PolicyDecision, PolicyOutcome)
- `assistant_os/capabilities/token_models.py` — Capability tokens (OperationBinding, CapabilityToken)
- `assistant_os/sandbox/authorized_plan.py` — AuthorizedPlan contract
- `assistant_os/sandbox/audit.py` — Audit infrastructure
- `tests/test_mso_*.py` — Existing MSO tests (reference pattern)
- `tests/test_police_*.py` — Existing Police tests (reference pattern)

### Documentation

- `docs/mso/SPRINT_*.md` — Historical sprint documentation
- `docs/brains/MSO.md` — MSO architecture overview
- `docs/brains/POLICE.md` — Police architecture overview
- `docs/atlas/AUTHORITY_MAP.md` — Authority hierarchy visualization
- `docs/mission/mission-core-contract.md` — Mission execution contract
- `docs/police/police-core-contract.md` — Police core contract

---

## APPROVAL AND SIGN-OFF

**Specification Version**: 1.0  
**Freeze Date**: 2026-05-08  
**Status**: ✅ Ready for PHASE 2  
**Next Milestone**: DelegatedMSOSeat Contract Implementation

**Phrase Rectrix (From Plan)**:
> "GPT can sit in the MSO seat, but the seat is bounded, auditable, revocable, and subordinate to real system contracts."

---

**Document End**
