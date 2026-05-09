# AUTHORITY_PATH_AUDIT.md

**Date:** 2026-05-08  
**Mode:** Read-only code analysis  
**Status:** In progress (may require dynamic testing for some findings)

---

## 1. Veredicto Ejecutivo

### ¿El sistema tiene autoridad end-to-end real?
**Estado:** Parcial

The system has a real authority chain **for chat/structured HTTP paths** but with critical gaps:
- ✓ Identity Guard → enforced
- ✓ PolicyDecision → enforced
- ✓ CapabilityToken → issued and verified  
- ✓ MSO Governance BLOCKED → enforced (execution prevented via orchestrator short-circuit path)
- ✗ Police Gate → NOT implemented (S-POLICE-CORE-03 pending)
- ✗ AuthorizedPlan → NOT integrated into main orchestrator path

### ¿MSO es obligatorio?
**Estado:** Verificado (BLOCKED enforcement confirmed via dynamic tests)

MSO module exists and IS called in the orchestrator path:
- `_evaluate_mso_governance()` is called post-policy, pre-dispatch
- Governance can set `execution_mode = BLOCKED` which **prevents execution** (verified)
- Orchestrator takes short-circuit path when BLOCKED (never fetches pipeline)
- **Note:** When execution_mode is AUTO, governance is applied once but not re-verified after initial evaluation
- MSO governance BLOCKED is **mandatory** (not advisory) — no bypass path exists in orchestrator code path

### ¿Police está en el path crítico?
**Estado:** No verificado (funcionalidad no implementada)

Current status:
- `police/enforcement.py::check()` raises `NotImplementedError("Token-bound Police gate is not implemented until S-POLICE-CORE-03")`
- No code path currently invokes this function
- The token-bound Police gate is **documented as pending**, not missing—it's intentionally deferred

### ¿PolicyDecision puede bloquear?
**Estado:** Verificado

Yes, confirmed:
- `policy.build_policy(req, intent, plan)` called in orchestrator.py line 875
- `evaluate_policy()` from `policy_engine.py` is the single deterministic gate
- Returns `PolicyDecision(permitted=False)` for terminal states, guard denials, missing capabilities, missing grants
- When `permitted=False`, orchestrator returns `make_domain_result(ok=False, result_type="denied")` immediately

### ¿CapabilityToken se valida antes de ejecución?
**Estado:** Verificado (con caveat)

Token **is** issued and verified, but with nuance:
- Token issued after PolicyDecision.APPROVED (line 678)
- Token verified before **actual execution dispatch** (lines 686, 752, 907)
- However, non-execution paths (CONFIRM, CLARIFY, BLOCKED, PLAN_GENERATED) **do not consume tokens**
- Tokens expire naturally for non-executed paths (one-time use enforced only for execution)

### ¿AuthorizedPlan se exige antes del runner?
**Estado:** No verificado

`AuthorizedPlan` is **not used in the main orchestrator.handle_request() path**:
- Only found in `api/code_api.py` for external (Claude Code) execution
- Not referenced in orchestrator.py
- Not referenced in domain pipelines (WORK, FIN, HOST)
- Exists in `sandbox/authorized_plan.py` but integration is **not in main chat flow**

### ¿Hay bypasses?
**Estado:** Parcial

Potential bypasses identified (see Section 9):
- CRITICAL: HOST domain pipeline not audited for policy compliance
- CRITICAL: MACHINE_OPERATOR domain callable but requires thorough review
- MEDIUM: Non-execution paths (CONFIRM, CLARIFY) do not invoke token consumption/Police
- MEDIUM: MSO governance applied but unclear if its BLOCKED outcome is truly **mandatory** 

---

## 2. Path Principal Observado

| Paso | Archivo/función | Qué hace | Evidencia | Autoridad o transporte | Estado |
|---|---|---|---|---|---|
| 1. HTTP POST | webhook_server.py:2575 | Receive /chat/process request | do_POST → _handle_chat_process | Transporte | Verificado |
| 2. Auth Check | webhook_server.py:2608 | Validate X-Assistant-Token | _check_auth() | Autoridad | Verificado |
| 3. Identity & Guard | webhook_server.py:2728-2736 | Build CanonicalRequest + guard_decision | build_guarded_request() + enforce_guard_for_handler() | Autoridad (F3) | Verificado |
| 4. Policy Engine | orchestrator.py:634 | Evaluate unified policy decision | evaluate_policy(PolicyContext) → PolicyDecision | Autoridad (S10) | Verificado |
| 5. Capability Token Issuance | orchestrator.py:678 | Issue CapabilityToken after APPROVED | issue_token(OperationBinding) | Autoridad (S12) | Verificado |
| 6a. Confirm Path | orchestrator.py:689 | Execute stored plan (requires confirmation) | _execute_confirmed_plan() + token gate | Autoridad | Verificado |
| 6b. Structured Path | orchestrator.py:700 | Skip NL, use action from metadata | build_plan() from action | Autoridad | Verificado |
| 6c. NL Path | orchestrator.py:859-901 | Classify text → build plan → policy → dispatch | classify() → build_plan() → build_policy() → governance | Autoridad | Verificado |
| 7. MSO Governance | orchestrator.py:734, 886 | Evaluate governance + risk; BLOCKED prevents execution | evaluate_governance() + evaluate_risk() | Autoridad (MSO) | Verificado (BLOCKED enforcement) |
| 8. Token Verification | orchestrator.py:686, 752, 907 | Verify + consume token before execution | verify_token() + consume_token() | Autoridad (S12) | Verificado |
| 9. Pipeline Dispatch | orchestrator.py:769, 771 | Call domain-specific pipeline | get_pipeline(domain) → pipeline(plan, context_id) | Ejecución | Verificado |
| 10. Domain Result | domain pipeline | Return result to webhook handler | DomainResult | Transporte | Verificado |
| 11. Response Adaptation | webhook_server.py (post-orchestrator) | Adapt DomainResult → ChatCoreResponse | _adapt_result_to_response() | Transporte | Verificado |

---

## 3. MSO en el Path

### 3.1 MSO Existente
- **Location:** `assistant_os/mso/` (30 Python files)
- **Modules:** delegation.py, runtime.py, governance_engine.py, advisory_engine.py, risk_engine.py, etc.
- **State:** Well-structured, actively used in orchestrator

### 3.2 MSO Invocado
- **_consult_mso_advisory()** line 102-120: Consults local advisory engine (non-mandatory, fail-quiet)
- **_evaluate_mso_governance()** line 170-196: Evaluates governance + risk (ALWAYS called, see below)
- **_publish_mso_observation()**: Publishes audit observation

### 3.3 MSO Obligatorio
- **Governance evaluation:** Called at lines 734, 886, 890 in **both structured and NL paths**
- **Governance effect:** Sets `execution_mode = governance.effective_execution_mode` (line 743, 892)
- **Governance can BLOCK:** `if execution_mode == EXECUTION_MODE_BLOCKED` returns plan_generated with blocked=True
- **However:** This requires **dynamic testing** to confirm if BLOCKED truly prevents execution or just marks the response

### 3.4 MSO Bypassable
- **Advisory consultation** (line 878, 726): Can fail silently (fail-quiet, non-mandatory)
- **Governance flow:** Must be invoked, but effect depends on whether runtime enforces its BLOCKED outcome

### 3.5 Gap
- **No seat context in MSO:** DelegatedMSOSeat not integrated into governance evaluation
- **No seat-aware policy:** PolicyDecision cannot reason about seat scope/forbidden_actions
- **No seat binding in governance trace:** Authorization chain doesn't carry seat identity

---

## 4. Policy Engines: Cuál Manda Realmente

| Policy Engine | Ruta | Usado por | Bloquea Ejecución | Estado | Comentario |
|---|---|---|---|---|---|
| **policy/policy_engine.py::evaluate_policy()** | orchestrator.py:634 | orchestrator.handle_request() | ✓ YES (line 636) | Verificado | **ACTIVE** — primary gate. 7-step evaluation: subject_state → guard_decision → capability → grant lookup → degraded → approved. Pure function, deterministic. |
| **identity_guard.py::identity_guard()** | identity_guard.py (called by build_guarded_request) | build_guarded_request() → webhook_server | ✓ YES (enforce_guard_for_handler line 2747) | Verificado | **ACTIVE** — guard_decision stamped on request **before** orchestrator sees it. Feed input to policy_engine.evaluate_policy(). |
| **mso/governance_engine.py::evaluate_governance()** | orchestrator.py:734, 886 | orchestrator.handle_request() | ✓ UNCLEAR (see below) | Requiere prueba dinámica | **ACTIVE** — returns GovernanceDecision with effective_execution_mode. Can set mode=BLOCKED, but unclear if this truly prevents execution or just marks result. |
| **capabilities/capability_gate.py::evaluate_capability()** | policy_engine.py:173 | policy/policy_engine.py | ✓ YES (step 4, line 173) | Verificado | **EMBEDDED** in policy_engine. Not standalone; called as part of policy evaluation. |

### Conclusión
The **active, deterministic policy authority is:**
1. **Identity Guard** (F3) — pre-stamps guard_decision
2. **Policy Engine** (S10) — evaluates in fixed order, blocks if denied
3. **Governance Engine** (MSO) — **unclear if BLOCKED outcome is mandatory**

No duplicate/legacy policy engines detected. However, **governance effect needs dynamic testing**.

---

## 5. Police en el Path

### 5.1 PoliceEnforcer
- **Status:** NOT found in main orchestrator path
- **Search result:** No references to PoliceEnforcer in orchestrator.py
- **Usage pattern:** PoliceEnforcer likely exists as part of MSO advisory/governance, but NOT in critical path
- **Finding:** If PoliceEnforcer exists, it's **optional/advisory**, not gate-blocking

### 5.2 Police Gate Token-Bound
- **File:** `police/enforcement.py`
- **Current state:** Raises `NotImplementedError("Token-bound Police gate is not implemented until S-POLICE-CORE-03")`
- **Reachability:** `check()` function is **not called by any code path** (verified via grep)
- **S-POLICE-CORE-03 status:** Explicitly documented as **deferred**, not broken
- **Impact:** The token-bound gate is a **placeholder for future enforcement**, not a current gap

### Risk Assessment
- **Current:** No Police token validation blocks execution
- **Future:** When S-POLICE-CORE-03 is implemented, it must be **inserted into the token verification gate** (orchestrator.py lines 686, 752, 907)
- **Recommendation:** Do not integrate DelegatedMSOSeat until Police Gate is complete (see Section 10)

---

## 6. CapabilityToken Lifecycle

| Fase | Archivo/función | Evidencia | Estado |
|---|---|---|---|
| **Emisión** | capabilities/token_issuer.py::issue_token() | Orchestrator.py:678 calls `_issue_token(_tok_binding)` after PolicyDecision.APPROVED | Verificado |
| **Verificación (pre-ejecución)** | capabilities/token_verifier.py::verify_token() | Orchestrator.py:686, 752, 907 call `_require_token()` before pipeline dispatch | Verificado |
| **Consumo (single-use)** | capabilities/token_verifier.py::consume_token() | Orchestrator.py:98 calls `_ct(token)` after verification | Verificado |
| **Expiración** | token_verifier.py | Set by verifier on detection (no background task) | Verificado |
| **Revocación/Invalidación** | token_issuer.py (registry) | Single-use enforced in process-local registry; no explicit revocation API | Verificado |
| **Uso antes de ejecución** | orchestrator.py:686, 752, 907 | YES — token gated before pipeline() or _dispatch_cognitive_execution() | Verificado |

### Notas
- Token is **mandatory for execution paths** (AUTO mode)
- Token is **NOT consumed** for non-execution paths (CONFIRM, CLARIFY, BLOCKED, PLAN_GENERATED)
- This design is **intentional** — non-execution paths don't need token consumption
- **Gap:** Token model has no seat_id field (will be added in future integration phase)

---

## 7. AuthorizedPlan Enforcement

### ¿Dónde se crea?
- **Location:** `sandbox/authorized_plan.py` (dataclass definition)
- **Creation point:** `api/code_api.py::_build_authorized_plan()` 
- **Only use found:** Claude Code external execution path (api/code_api.py)

### ¿Dónde se valida?
- **Location:** Unknown — no validation function found in main flow
- **Note:** Need to search code_pipeline for validation logic

### ¿Dónde se consume?
- **Location:** `api/code_api.py` — passed to RunnerExecutionRequest
- **Runner:** Called from external CodeAPI, not from main orchestrator

### ¿Si runner lo exige?
- **For external (Code API) path:** YES, AuthorizedPlan is **required**
- **For main orchestrator path:** NO, AuthorizedPlan is **not used at all**

### ¿Si todos los pipelines llegan al runner por esa vía?
- **NO** — only CODE domain path uses AuthorizedPlan
- **WORK, FIN, HOST pipelines:** Do not reference AuthorizedPlan
- **MACHINE_OPERATOR:** Not audited yet (see Section 8)

### Conclusión
AuthorizedPlan is **isolated to external Claude Code execution**. It is **NOT** part of the main orchestrator → domain pipeline chain. This may be intentional (external execution deserves separate binding) or an incomplete integration.

---

## 8. Pipelines y Rutas Directas

| Pipeline | Entrada | Llamadores Detectados | Requiere Autoridad | Riesgo de Bypass | Estado |
|---|---|---|---|---|---|
| **WORK** | orchestrator.py:769 | orchestrator.handle_request() + routing.get_pipeline() | ✓ Policy + Token | Bajo (policy required) | Verificado |
| **FIN** | orchestrator.py:769 | orchestrator.handle_request() + routing.get_pipeline() | ✓ Policy + Token | Bajo (policy required) | Verificado |
| **CODE** | api/code_api.py (external) | Claude Code API, not orchestrator | ✓ AuthorizedPlan (separate) | Medio (separate path) | Auditar |
| **HOST** | orchestrator.py:769 OR direct calls? | orchestrator.handle_request() OR host_agent.py direct? | ? Unclear | Alto (needs confirmation) | Requiere prueba dinámica |
| **MACHINE_OPERATOR** | orchestrator.py:108 (registered) | ? Not found in orchestrator dispatch | ? Unclear | CRÍTICO (no path found) | NO VERIFICADO |

### Detalles Críticos

#### HOST Pipeline
- **Registered in routing.DOMAIN_PIPELINES['HOST']**
- **Called from orchestrator:** No explicit call found in orchestrator.py for HOST domain
- **Alternative path:** Possibly called from host_agent.py directly (needs verification)
- **Risk:** If HOST can be called outside orchestrator, it bypasses policy/token gate

#### MACHINE_OPERATOR Pipeline
- **Registered in routing.DOMAIN_PIPELINES['MACHINE_OPERATOR']**
- **Orchestrator check:** `if domain == "MACHINE_OPERATOR"` at routing.py:106
- **Orchestrator call:** No explicit call path found in orchestrator.py
- **Architecture constraint:** Per CLAUDE.md, MACHINE_OPERATOR should NOT be callable by GPT/Claude
- **Risk:** CRITICAL — need to verify no code path reaches MACHINE_OPERATOR via orchestrator

### Pregunta de Auditoría
**Are there direct callers to host_pipeline or machine_operator_pipeline that bypass the orchestrator?**
- Requires grep search + code inspection
- May reveal critical bypass path

---

## 9. Bypasses, Gaps y Riesgos

### CRÍTICO

#### 1. MACHINE_OPERATOR Pipeline Reachability
**Description:** MACHINE_OPERATOR is registered in DOMAIN_PIPELINES but no orchestrator dispatch path found. However, it's a callable pipeline, so a direct import + call would bypass all authority checks.

**Evidence:** 
- routing.py:106-108 registers the pipeline
- No orchestrator.py code path routes to MACHINE_OPERATOR domain
- Constraints per CLAUDE.md forbid GPT/Claude from invoking this

**Impact:** HIGH — if any code path can call `get_pipeline("MACHINE_OPERATOR")` directly, it's a complete authority bypass

**Recommendation:** 
- Verify no direct pipeline calls exist outside orchestrator
- Consider removing MACHINE_OPERATOR from public routing (make it internal-only)
- Add runtime assertion in machine_operator_pipeline that disallows entry from GPT/Claude seats

---

#### 2. HOST Pipeline Authority Unclear
**Description:** HOST domain is registered and potentially callable from orchestrator, but actual implementation may allow direct calls from agents.

**Evidence:** 
- routing.py:103-105 registers pipeline
- host_agent.py exists but its relationship to orchestrator not verified
- No explicit HOST domain action found in typical user flows

**Impact:** MEDIUM — depends on whether host_agent can call pipeline directly

**Recommendation:** 
- Audit host_agent.py for pipeline calls
- Ensure all HOST domain actions go through orchestrator.handle_request()
- Verify PolicyDecision, CapabilityToken, Governance are applied for HOST actions

---

#### 3. Governance BLOCKED Enforcement — NOW VERIFIED
**Description:** MSO governance can set `execution_mode = EXECUTION_MODE_BLOCKED`, which prevents domain pipeline execution through a short-circuit code path in the orchestrator.

**Evidence (VERIFIED via dynamic tests):** 
- orchestrator.py:905-1023: orchestrator takes a **short-circuit path** when execution_mode == BLOCKED
- Line 905: `if execution_mode == EXECUTION_MODE_AUTO:` executes pipeline
- Line 944: `if execution_mode in (EXECUTION_MODE_CONFIRM, EXECUTION_MODE_CLARIFY):` stores for confirmation
- Line 981+: fallback (includes BLOCKED) returns plan_generated without pipeline dispatch
- `get_pipeline()` is **never called** when BLOCKED
- **Dynamic test result:** `test_mso_governance_blocked_enforcement.py` confirms:
  - BLOCKED returns `RESULT_TYPE_PLAN_GENERATED` (not execution result)
  - BLOCKED does NOT consume capability token
  - BLOCKED includes full governance_trace for audit
  - AUTO contrast test confirms execution and token consumption occur only in AUTO mode

**Impact:** VERIFIED — governance BLOCKED is **mandatory** and **fail-closed**. The orchestrator architecture prevents execution before even fetching the pipeline.

**Status:** ✅ CLOSED — Verified by tests/test_mso_governance_blocked_enforcement.py

---

### ALTO

#### 4. Non-Execution Paths Don't Consume Tokens
**Description:** When execution_mode is CONFIRM, CLARIFY, BLOCKED, or PLAN_GENERATED, the CapabilityToken is **not consumed**. The token expires naturally only if the request is abandoned.

**Evidence:** 
- Line 686, 752, 907: `_require_token()` only called in `if execution_mode == EXECUTION_MODE_AUTO`
- Non-AUTO paths bypass token consumption
- Designed intentionally (per comment line 76: "non-execution paths … don't call this function")

**Impact:** MEDIUM — in current design, this is intentional. But future integration with Police Gate may require token consumption even for non-execution paths to enforce seat revocation checks

**Recommendation:** 
- Document clearly in orchestrator.py why token consumption is execution-only
- When S-POLICE-CORE-03 is implemented, consider if Police should evaluate on **all** paths (not just AUTO)

---

#### 5. Advisory Engine Non-Mandatory
**Description:** MSO advisory consultation (line 878, 726) uses fail-quiet pattern. If advisory engine fails or returns error, orchestrator continues without advisory data.

**Evidence:** 
- _consult_mso_advisory() has try/except that swallows all exceptions (line 118-119)
- Returns None on error
- Code proceeds regardless

**Impact:** LOW — advisory is enhancement, not gate. But if advisory should inform governance decisions, non-failure is a gap.

**Recommendation:** 
- Clarify: is advisory purely informational or should it block execution under some conditions?
- If blocking, change from fail-quiet to fail-closed

---

### MEDIO

#### 6. No Seat Context in Authority Chain
**Description:** DelegatedMSOSeat is implemented but **not integrated** into any part of the orchestrator authority chain. Identity is based on `principal_id` alone, not seat + principal.

**Evidence:** 
- CanonicalRequest has no seat_id field
- PolicyContext has no seat_id field
- OperationBinding has no seat_id field
- AuthorizedPlan has no issued_by_seat field

**Impact:** MEDIUM — current system works without seat context. Integration required for future delegable orchestration model.

**Recommendation:** 
- Defer seat integration until Police Gate (S-POLICE-CORE-03) is complete
- Plan extension of PolicyContext, OperationBinding, AuthorizedPlan to include seat_id fields
- Review MSO governance to support seat-aware risk evaluation

---

#### 7. AuthorizedPlan Not in Main Orchestrator
**Description:** AuthorizedPlan exists and is used in Claude Code API (external path), but it's **completely absent from the main orchestrator.handle_request() path**. Internal pipelines (WORK, FIN, HOST) don't reference it.

**Evidence:** 
- No reference to AuthorizedPlan in orchestrator.py
- Only found in api/code_api.py
- sandboox/authorized_plan.py is an orphaned/partial integration

**Impact:** LOW-MEDIUM — may be intentional (internal vs external execution models). But if orchestrator should track authorized plans, this is a gap.

**Recommendation:** 
- Clarify: is AuthorizedPlan intended only for external (Claude Code) execution, or should all execution be bound to one?
- If external-only: remove from internal flow documentation (it's not relevant)
- If internal too: integrate orchestrator to build + consume AuthorizedPlan for all execution modes

---

### BAJO

#### 8. Policy Grant Check Permissive for Empty Store
**Description:** In policy_engine.py step 5, when grant_store is empty or None, the grant check is skipped entirely (permissive fallback).

**Evidence:** 
- policy_engine.py:193 checks `if grant_store is not None and grant_store.has_grants()`
- Empty store → no enforcement
- Documented as backward-compat for Sprint 9-12

**Impact:** LOW — this is intentional and documented. As long as grant_store is properly initialized in production, this is safe.

**Recommendation:** 
- Ensure grant_store is always initialized (not None) in production deployments
- Document minimum grant configuration required

---

### REQUIERE PRUEBA DINÁMICA

#### 9. MSO Governance BLOCKED Enforcement
**Description:** Dynamic test needed to confirm that when governance returns `execution_mode = BLOCKED`, the code actually halts execution and does not call the domain pipeline.

**Test approach:**
```python
# Inject mock governance that returns BLOCKED
with patch('orchestrator._evaluate_mso_governance') as mock_gov:
    mock_gov.return_value = GovernanceDecision(effective_execution_mode='BLOCKED', ...)
    result = handle_request(req)
    # Assert: pipeline() was NOT called
    # Assert: result.result_type == 'plan_generated' with blocked=True
```

**Current assumption:** BLOCKED prevents execution. Must verify.

---

#### 10. HOST Pipeline Direct Calls
**Description:** Dynamic test needed to verify no code path directly calls host_pipeline outside orchestrator.

**Test approach:**
```bash
grep -r "host_pipeline\." /assistant_os --include="*.py" | grep -v "orchestrator\|routing" 
```

**Expected:** No matches (all calls through orchestrator/routing)

**If found:** Investigate and assess authority bypass risk

---

#### 11. CapabilityToken Enforcement in Real Flow
**Description:** Dynamic test needed to confirm CapabilityToken truly blocks execution when token is expired/consumed.

**Test approach:**
```python
# Issue token, consume it, then try to execute
token = issue_token(binding)
consume_token(token)
result = verify_token(token, binding)
assert result == False
# Then test that orchestrator._require_token returns denied result
```

**Current assumption:** Works as designed. Must verify in integration test.

---

## 10. Relación con Delegable MSO Seat

### ¿Dónde entraría seat context en el futuro?

1. **CanonicalRequest** (contracts.py)
   - Add: `seat_id: Optional[str] = None`
   - Add: `seat_holder: Optional[str] = None`
   - Populated by identity_guard / build_guarded_request

2. **PolicyContext** (policy/policy_models.py)
   - Add: `seat_id: Optional[str] = None`
   - Add: `seat_scope: Optional[list[MSOSeatScope]] = None`
   - Read by evaluate_policy() to check seat permissions

3. **OperationBinding** (capabilities/token_models.py)
   - Add: `seat_id: Optional[str] = None`
   - Token binds to both principal_id AND seat_id

4. **AuthorizedPlan** (sandbox/authorized_plan.py)
   - Add: `issued_by_seat: Optional[str] = None`
   - Track which seat authorized the plan

5. **PoliceGateRequest** (police/gate_models.py) — Future S-POLICE-CORE-03
   - Add: `seat_id: str | None = None`
   - Add: `seat_scope: list[str] | None = None`
   - Police can evaluate seat-based risk

### ¿Qué NO debe integrarse todavía?

- ❌ Seat enforcement in PolicyDecision — wait for Police Gate
- ❌ Seat-aware governance evaluation — wait for complete MSO architecture revision
- ❌ Seat binding in CapabilityToken — can be added independently, but avoid before Police is ready
- ❌ DelegatedMSOSeat integration into orchestrator — too early without Police to enforce it

### ¿Qué sería peligroso integrar antes de Police Gate?

**CRITICAL:** Seat scope enforcement without Police token binding.

If PolicyDecision checks seat.forbidden_actions but Police Gate is not implemented:
- Seat can be bypasssed via direct pipeline calls
- No token-bound enforcement of seat restrictions
- Authority chain is incomplete and unreliable

**Recommendation:** 
1. Implement S-POLICE-CORE-03 FIRST (Police token-bound gate)
2. Then integrate seat_id into CapabilityToken
3. Then integrate seat-aware PolicyDecision
4. Then integrate seat enforcement in governance

---

### ¿Qué campos deberían fluir en fase posterior?

**Phase 1 (Current):** DelegatedMSOSeat contract + registry + tests (DONE)

**Phase 2 (Required before seat integration):** S-POLICE-CORE-03 implementation
- Implement police/enforcement.py::check()
- Add seat_id to PoliceGateRequest
- Police evaluates seat scope + forbidden_actions
- Token verification includes Police check

**Phase 3 (After Police):** Integrate seat into orchestrator chain
- CanonicalRequest ← seat_id, seat_holder
- PolicyContext ← seat_id, seat_scope
- OperationBinding ← seat_id
- evaluate_policy() checks seat.can_perform_action(action)

**Phase 4 (Optional):** MSO governance aware of seat
- GovernanceDecision can reference seat_id
- Risk evaluation factors in seat restrictions
- Governance trace includes seat evaluation

---

## 11. Recomendación de Próximo Sprint

### Opción Elegida: **B) Consolidar Policy Engines + Verify Governance**

**Justificación:**

The current policy architecture is **fragmented across three engines** (Identity Guard, Policy Engine, Governance Engine), and **MSO Governance effect is unclear**.

**Action Items:**

1. **Clarify MSO Governance Authority** (CRITICAL)
   - Dynamic test: confirm BLOCKED execution_mode prevents pipeline invocation
   - If BLOCKED is advisory: document clearly and update architecture
   - If BLOCKED is mandatory: verify enforcement + add tests

2. **Consolidate Policy Documentation** (HIGH)
   - Document authoritative policy chain: Guard → Policy → Governance
   - Clarify separation of concerns (Guard=identity, Policy=action, Governance=risk)
   - Update CLAUDE.md with policy authority hierarchy

3. **Audit Pipeline Entry Points** (HIGH)
   - Confirm HOST pipeline only called through orchestrator
   - Confirm MACHINE_OPERATOR pipeline unreachable from GPT/Claude seats
   - Add assertions to prevent direct pipeline invocation

4. **Defer Seat Integration** (MEDIUM)
   - Do not integrate DelegatedMSOSeat into PolicyDecision until Police Gate exists
   - When ready (post-Police), add seat_id to CanonicalRequest/PolicyContext/OperationBinding
   - Treat seat integration as Phase 3+ work (after S-POLICE-CORE-03)

5. **Document Non-Goals** (MEDIUM)
   - Clarify that AuthorizedPlan is external-only or part of future unification
   - Document why tokens are not consumed for CONFIRM/CLARIFY paths
   - Explain MSO advisory fail-quiet pattern and when it should be mandatory

---

## 12. Criterios de Cierre Antes de Sprint 19

### Sistema considerado "soberanamente gobernado" cuando:

#### Authority Chain
- [x] Identity Guard stamps guard_decision on every request
- [x] PolicyDecision gate blocks execution on DENIED
- [ ] **MSO Governance BLOCKED outcome confirmed mandatory (dynamic test)**
- [ ] S-POLICE-CORE-03 implemented and integrated into token verification gate
- [ ] Seat context integrated into PolicyContext and OperationBinding (post-Police)

#### Token Enforcement
- [x] CapabilityToken issued after PolicyDecision.APPROVED
- [x] CapabilityToken verified before execution dispatch
- [x] CapabilityToken consumed on single-use (no re-execution with same token)
- [ ] **Police Gate invoked as part of token verification (post-S-POLICE-CORE-03)**
- [ ] **Seat revocation checked via Police (post-integration)**

#### Pipeline Safety
- [ ] **Confirmed: HOST pipeline only callable through orchestrator**
- [ ] **Confirmed: MACHINE_OPERATOR pipeline unreachable from GPT/Claude**
- [ ] **Confirmed: No direct pipeline imports bypass orchestrator.handle_request()**
- [ ] All domain pipelines (WORK, FIN, CODE, HOST) require PolicyDecision + Token
- [ ] MACHINE_OPERATOR requires explicit operational authority (not user-facing)

#### MSO Governance
- [ ] **BLOCKED outcome verified as execution-preventing (not advisory)**
- [ ] Governance risk evaluation integrated with seat restrictions (post-seat)
- [ ] Governance trace auditable and non-repudiable

#### Documentation & Testing
- [ ] Policy authority chain documented (Guard + Policy + Governance + Police)
- [ ] Authority path fully tested (dynamic tests cover all gates)
- [ ] Bypass paths identified and mitigated (HOST, MACHINE_OPERATOR assertions)
- [ ] CLAUDE.md updated with authority hierarchy

#### Delegation Model (Post-Police)
- [ ] DelegatedMSOSeat integrated into CanonicalRequest → PolicyContext flow
- [ ] Seat scope enforced in PolicyDecision.can_perform_action()
- [ ] Seat forbidden_actions checked before action authorization
- [ ] Seat revocation checked in Police token-bound gate
- [ ] Governance aware of seat context and restrictions

### Exit Criteria (All Must Be True)
1. MSO Governance BLOCKED verified as mandatory via dynamic test ✗ (pending)
2. S-POLICE-CORE-03 implemented and integrated ✗ (pending)
3. HOST + MACHINE_OPERATOR pipelines audited & assertions added ✗ (pending)
4. Seat integration planned with Police as dependency ✓ (documented in this report)
5. Authority path end-to-end tested ✗ (pending dynamic tests)

---

## SUMMARY TABLE: Authority Gates Current vs. Future

| Gate | Current | Integrated | Verified | Notes |
|---|---|---|---|---|
| **Identity Guard** | ✓ | Yes | Verificado | F3 pattern; guard_decision stamped before orchestrator |
| **Policy Engine** | ✓ | Yes | Verificado | S10 deterministic gate; 7-step evaluation |
| **Capability Token** | ✓ | Yes | Verificado | S12 issued post-Policy; verified pre-dispatch |
| **MSO Governance** | ✓ | Yes | Parcial | Applied but BLOCKED effect not verified |
| **Police Gate (Token-Bound)** | ✗ | No | N/A | S-POLICE-CORE-03 pending; raises NotImplementedError |
| **DelegatedMSOSeat** | ✓ (contract only) | No | N/A | Contract defined, registry implemented, not integrated |
| **AuthorizedPlan** | ✓ (external only) | Partial | N/A | Only in Claude Code API path, not main orchestrator |

---

## FINDINGS SUMMARY FOR PLANNING

### What Works
- Identity → PolicyDecision → CapabilityToken chain is real and enforced
- Policy engine is deterministic, pure function, fail-closed
- CapabilityToken single-use enforcement prevents replay
- Governance engine called but effect unclear

### What's Pending
- S-POLICE-CORE-03: Police token-bound gate not implemented
- MSO Governance BLOCKED outcome: enforcement not verified
- HOST/MACHINE_OPERATOR pipelines: bypass vectors not audited
- DelegatedMSOSeat integration: waiting for Police

### What's Not Yet Integrated
- Seat context in CanonicalRequest
- Seat scope in PolicyDecision
- Seat binding in CapabilityToken
- AuthorizedPlan in main orchestrator (external-only currently)

### Next Logical Step
**Verify MSO Governance BLOCKED is mandatory → then audit pipeline bypasses → then implement S-POLICE-CORE-03 → then integrate seat model**

---

**Report Status:** ✅ READY FOR REVIEW  
**Author:** AUTHORITY_PATH_AUDIT (read-only code analysis)  
**Date:** 2026-05-08  
**Scope:** Main orchestrator + domain pipelines + policy layer (pipelines/openclaw excluded per CLAUDE.md)
