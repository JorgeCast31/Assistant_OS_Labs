# AOS-P0 REALITY LOCK

**Audit identifier:** AOS-P0  
**Branch:** `audit/aos-p0-reality-lock`  
**Cleanroom:** `C:\Users\Jorge\AOS_P0_Cleanroom`  
**Canonical baseline SHA:** `b2fa39b9ef1dd7dbee7a1c7fa4603ec42f57675d` (`origin/main`, 2026-06-24)  
**Quarantined checkout:** `C:\Users\Jorge\Assistant_OS_Labs` — NOT INSPECTED, NOT USED AS EVIDENCE  
**Date:** 2026-06-24  
**Status:** VERIFIED FINDINGS DOCUMENTED — decisions still required from Jorge

---

## Purpose

This document records the AOS-P0 cleanroom reality lock: a characterization-only audit of the authority surface as it exists in canonical main. It does not authorize any runtime change, execution, Runner, provider integration, ModelBridge, policy change, Police change, or authority change.

---

## Finding A — Police `check()` as Token-Bound Enforcement Gate

**File:** `assistant_os/police/enforcement.py:85–264`

### What `check()` is

`check()` is a **token-bound enforcement gate**. It validates the structural integrity and binding consistency of an execution request against registered tokens and authorized plans. It does NOT evaluate policy. It does NOT call `evaluate_policy()` or `evaluate_governance()`. It is NOT the sole policy engine.

### Validation sequence (V1–V5)

| Check | Condition | Semantics |
|---|---|---|
| V1 | `if not request.token_ref` | Token reference present |
| V1.5 | `_lookup(request.token_ref) is None` | Token registered in police registry |
| V1.6 | `_entry["status"] == _STATUS_EXPIRED` | Token not expired |
| V1.7 | `_entry["status"] == _STATUS_SPENT` | Token not already consumed |
| V2 | `if not request.governance_ref` | Governance ref present (structural) |
| V3 | `if not request.policy_decision_ref` | Policy decision ref present (structural, non-empty) |
| V4 | `if not request.binding_ref` | Binding ref present |
| V4.5 | `request.binding_ref != _expected_binding` | Binding ref matches registered constraint |
| V4.6 | Plan binding: execution_id, token_ref, binding_ref, status | Authorized plan binding consistent |
| V5 | `capability_name not in capability_scope` | Capability within plan scope |

**Critical observation — V3 and V2 are structural-only:** V3 (`policy_decision_ref`) and V2 (`governance_ref`) only check for non-empty string presence. Police does NOT verify that these refs were produced by an actual policy or governance evaluation. It does not call `evaluate_policy()`, it does not validate ref format, and it does not look up the ref in any policy or governance store.

### Authority chain roles — distinct components

| Role | File | Function | Notes |
|---|---|---|---|
| Policy producer | `assistant_os/policy/policy_engine.py` | `evaluate_policy(context, grant_store)` | Pure deterministic, no LLM, no side effects. Sprint 10. |
| Governance producer | `assistant_os/mso/governance_engine.py` | `evaluate_governance(...)` | Dynamic MSO decision: ALLOW/BLOCK/DEGRADE/REQUIRE_CONFIRMATION |
| Context/enrichment | `assistant_os/identity_guard.py`, `assistant_os/cognition/context_resolver.py`, `assistant_os/core/enrichment.py` | Various | Stamps `guard_decision`, `action_type`, `subject_state` onto requests |
| Enforcement gate | `assistant_os/police/enforcement.py` | `check(request)` | Token-bound gate, V1–V5 structural validation |
| Legacy/compat path | `assistant_os/policy_engine.py` (root level) | `evaluate_policy(...)` | Called from identity_guard; separate from `policy/policy_engine.py` |
| Direct-call path | `assistant_os/agents/registry.py:130–243` | `_host_launcher_entrypoint`, `_machine_operator_entrypoint` | BOTH build `PoliceGateRequest` with `token_ref=None` and call `check()`. Police V1 (TOKEN_MISSING) denies immediately. Fail-closed by design. Historical bypass concern is REMEDIATED in canonical main — see Finding A.1 below. |

### Finding A.1 — Registry Direct-Call Path: Fail-Closed (Not Bypassed)

**Files:** `assistant_os/agents/registry.py:130–243`  
**Functions:** `_host_launcher_entrypoint` (line 130), `_machine_operator_entrypoint` (line 181)

Both entrypoints:
1. Build a `PoliceGateRequest` with all authority refs set to `None` (`token_ref=None`, `binding_ref=None`, `authorized_plan_ref=None`, `governance_ref=None`, `policy_decision_ref=None`).
2. Call `check(police_request)` unconditionally before any delegation.
3. Check `if police_decision.outcome != PoliceOutcome.PERMITTED` → return error result without executing.

**Result in canonical main:** Police V1 (`if not request.token_ref`) denies immediately with `TOKEN_MISSING`. Neither `execute_host_action` nor `_mo_execute` is ever reached via this path.

**Historical bypass concern (from prior audits):** Any claim that the direct-call registry path bypasses Police is a characterization of a historical state. In canonical main at SHA `b2fa39b9`, the bypass is REMEDIATED. The path does invoke `check()` and fails closed.

**Limitation:** This is a static code observation from canonical main. Whether any prior version of these entrypoints lacked the Police call, and what the quarantined local checkout contains, is not verifiable within the AOS-P0 cleanroom scope.

---

## Finding B — Synthetic Reference Families

Two distinct reference families exist. They serve different roles in the authority chain and must NOT be conflated.

### B.1 — `policy_decision_ref = "auto:<intent_id>"`

**Emission site:** `assistant_os/webhook_server.py:6448`

```python
"policy_decision_ref": f"auto:{intent_id}",
```

Emitted for N0 (read-only, `approval_mode=none`) MACHINE_OPERATOR browser capabilities. `intent_id` is a freshly generated UUID at the call site (`line 6438`).

**Where consumed:**
- Passed as `policy_context["policy_decision_ref"]` to the machine operator kernel.
- Reaches Police gate V3 if the execution path goes through `enforcement.check()`.
- Reaches OpenClaw backend server at `openclaw_backend/server.py:203–211`.

**What validates it:**
- **Police V3** (`enforcement.py:145`): `if not request.policy_decision_ref` — presence-only. Accepts any non-empty string including `"auto:..."`.
- **OpenClaw server** (`server.py:204`): `_REF_ID_RE.fullmatch(policy_decision_ref.strip())` where `_REF_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$")` — format-only (6–128 chars, alnum/._:-). Does NOT verify semantic provenance.

**Downstream path (static call-chain only):** `"auto:<intent_id>"` is the standard ref stamped for N0 read-only executions in the webhook N0 path. Static call-chain analysis shows it is passed downstream toward the sovereign gate at `server.py:441`. End-to-end runtime reachability and execution are UNVERIFIED in AOS-P0 — no runtime trace was captured, no N0 execution was observed, and whether the server is enabled or reachable is unknown from code alone.

**Semantic provenance verified:** NO — neither Police V3 nor the OpenClaw server verifies that this ref was produced by a real policy evaluation. The ref is synthetic: constructed from a locally generated UUID at the webhook server, not returned from `evaluate_policy()`.

### B.2 — `approval:auto:<intent_id>`

**Emission site:** `assistant_os/mso/machine_operator_adapter.py:1852`

```python
synthetic_approval_id = f"approval:auto:{intent_id}"
```

Emitted in the N0 compatibility path when `approval_mode=none` and no explicit approval artifact is provided (lines 1845–1859).

**Where consumed:**
- Returned as `approval_id` in a synthetic approval dict (not a real authority artifact).
- Used by the downstream execution path as the `approval_id` for N0 flows.

**What validates it:**
- The compatibility path in `machine_operator_adapter.py` accepts it by construction; no Police gate validation applies to this ref as a token.
- It is NOT a Police `token_ref` — it is an `approval_id` in a compatibility artifact.

**Downstream path (static call-chain only):** `"approval:auto:<intent_id>"` is used as the `approval_id` in the synthetic N0 artifact returned by the compat path. Static call-chain analysis indicates it is passed downstream in N0 flows. End-to-end runtime reachability and execution are UNVERIFIED in AOS-P0 — no runtime trace was captured, no N0 execution was observed.

**Semantic provenance:** Synthetic by construction. Created by the adapter itself, not produced by a prior authority decision.

### B.3 — Distinctness statement

These two families are DISTINCT:

- `"auto:<intent_id>"` is a `policy_decision_ref` — a correlation ref for the policy evaluation context.
- `"approval:auto:<intent_id>"` is an `approval_id` — a synthetic approval artifact identifier for N0 compatibility flows.
- They do not share a code path. They do not converge before execution in the N0 flow.
- Police does not reject `"auto:..."` as a `policy_decision_ref` — the exact code at V3 (`enforcement.py:145`) only checks `if not request.policy_decision_ref`, which a non-empty `"auto:..."` string passes.

**Unverified claim (do NOT assert):** Police rejects `auto:` prefixed `policy_decision_ref` values. The code proves the opposite: V3 is presence-only.

---

## Finding C — OpenClaw Runtime Boundary

**File:** `assistant_os/openclaw_backend/runtime.py`  
**Class:** `PlaywrightRuntimeDispatcher`  
**Method:** `execute()` at line 216

### Precise characterization

| Label | Status | Evidence |
|---|---|---|
| Method is importable | CONFIRMED | `runtime.py` is a valid Python module; class and method are public |
| Method is internally callable | CONFIRMED | Standard Python method call on a `PlaywrightRuntimeDispatcher` instance |
| Method has no local sovereign gate | CONFIRMED | `execute()` validates only `capability_name in SUPPORTED_CAPABILITIES` (line 228) and `_validate_url(arguments)` (line 230). No sovereign store, no Police check, no policy evaluation inside the method. |
| Known production HTTP call-site | CONFIRMED | `openclaw_backend/server.py:492` — `self.server.runtime_dispatcher.execute(...)` |
| Known gate before that production call-site | CONFIRMED | `_sovereign_store.is_execution_allowed(_sovereign_query)` at `server.py:441`, runs AFTER auth + request validation, BEFORE `execute()`. Denied → HTTP 403, execution blocked. |
| Externally exploitable bypass | UNPROVEN | See below. |

### Externally exploitable bypass — unproven

Being an importable Python method does NOT equate to an external bypass. The absence of a gate inside `execute()` means the gate lives upstream at the HTTP server level (`server.py:441`). External exploitability depends on:
- Whether the HTTP server is network-reachable (`config.OPENCLAW_RUNTIME_ENABLED`, listening address, port).
- Whether authentication can be bypassed (server enforces `_enforce_auth()` before `_sovereign_store.is_execution_allowed()`).
- These are deployment and configuration questions, not provable from code alone in a static audit.

An actor with **direct Python process access** (not HTTP) could call `execute()` without the sovereign gate — but this is an in-process access concern, not an external HTTP-level bypass. This distinction must be preserved.

### `NullRuntimeDispatcher` note

`create_default_runtime_dispatcher()` (`runtime.py:522`) returns `NullRuntimeDispatcher()` if `config.OPENCLAW_RUNTIME_ENABLED` is False. `NullRuntimeDispatcher.execute()` raises `RuntimeUnavailableError` unconditionally (`runtime.py:108–112`). Whether `PlaywrightRuntimeDispatcher` or `NullRuntimeDispatcher` is active depends on the runtime configuration, not on the code structure alone.

---

## Finding D — Canonical vs Non-Canonical Evidence

| Source | Status | Notes |
|---|---|---|
| GitHub `origin/main` at SHA `b2fa39b9` | CANONICAL | All findings in this document are from this baseline |
| Cleanroom (`C:\Users\Jorge\AOS_P0_Cleanroom`) | CLEANROOM OBSERVATION | Fresh clone, verified clean, matches canonical main |
| Historical audit documents (ALFA flights, sprint docs) | HISTORICAL | Reflect system state at time of writing; not treated as current canonical |
| Quarantined local checkout (`C:\Users\Jorge\Assistant_OS_Labs`) | QUARANTINED | NOT inspected, NOT used as evidence for any finding in this document |

### `governed_execution.py` — not present in canonical main

`assistant_os/mso/governed_execution.py` does NOT exist in canonical main. Confirmed by direct inspection of the cleanroom (clone of canonical main). Any reference to this file in prior audits, reports, or the quarantined checkout does not reflect the current canonical state. Findings made about this file in prior audits are historical, not current.

---

## Characterization Tests

`tests/test_aos_p0_characterization.py` — 7 targeted non-productive tests.

**What the tests prove:**
- Finding B.1: Police V3 accepts `"auto:<intent_id>"` when all other bindings are structurally valid (presence-only validation confirmed).
- Finding B.1: Police V3 denies `None` and empty-string `policy_decision_ref` (structural rejection confirmed).
- Finding B.2: The `approval:auto:` pattern is produced by the N0 compat path of `machine_operator_adapter._build_authority_artifact_policy_payload()`.
- Finding B.3: `"auto:<id>"` and `"approval:auto:<id>"` are distinct (different fields, different code paths).

**What the tests do NOT prove (code inspection only):**
- Police `check()` does not invoke `evaluate_policy()` or `evaluate_governance()`. This claim is based on direct code inspection of `enforcement.py:85–264`: none of those calls appear in the function body. The tests prove structural acceptance/rejection of `policy_decision_ref` values, not the absence of all possible evaluation calls via runtime instrumentation.
- End-to-end runtime reachability of N0 flows (not tested, not proven).
- Registry direct-call fail-closed behavior (Finding A.1) is code inspection only; no characterization test was added for it in this audit.

Test commands and raw results: `coordination/reports/TASK-0012.FINAL_REPORT.md`.

---

## Decisions Required from Jorge

The following questions cannot be resolved by a static code audit and require Jorge's decision:

1. **N0 synthetic ref provenance:** The `policy_decision_ref = "auto:<intent_id>"` is Police-accepted but semantically unverified (no real policy evaluation was called). Is this acceptable for N0 read-only capabilities, or is a provenance-verified ref required?

2. **`approval:auto:` in N0 path:** The `approval:auto:<intent_id>` compatibility artifact is an authority envelope with no prior authorization event. Is this the intended design for N0 browser capabilities, or should it be replaced with a real authority artifact?

3. **OpenClaw runtime reachability:** Is the OpenClaw HTTP server currently bound to a network-reachable interface? If yes, is the auth layer (`_enforce_auth()`) sufficient for the threat model?

4. **In-process access risk:** Does the system threat model include actors with direct Python process access? If yes, the absence of a gate inside `PlaywrightRuntimeDispatcher.execute()` is a design decision that should be explicitly documented.

---

## Explicit Non-Authorization Statement

This audit document:
- Authorizes NO runtime change
- Authorizes NO execution
- Authorizes NO Runner
- Authorizes NO provider integration
- Authorizes NO ModelBridge change
- Authorizes NO policy change
- Authorizes NO Police change
- Authorizes NO authority change
- Does NOT merge any branch
- Does NOT modify any production code

All changes in branch `audit/aos-p0-reality-lock` are documentary only.
