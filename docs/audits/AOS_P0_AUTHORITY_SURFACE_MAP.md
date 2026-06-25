# AOS-P0 Authority Surface Map

**Canonical baseline SHA:** `b2fa39b9ef1dd7dbee7a1c7fa4603ec42f57675d`  
**Date:** 2026-06-24  
**Scope:** Cleanroom read-only characterization of the authority surface.  
**Not authoritative for:** quarantined checkout, historical states, or future changes.

---

## Authority Chain — Component Map

```
Operator Intent
     │
     ▼
[Plan] (draft_store)
  assistant_os/mso/plan_model.py
  assistant_os/mso/draft_store.py
  ── pre-authority, no execution fields, no auto: refs permitted ──
     │
     ▼
[Prepare Layer] (confirm queue)
  assistant_os/mso/prepare_contract.py
  ── execution_allowed=False always; creates PreparedAction ──
     │
     ▼
[Identity Guard / Context Enrichment]
  assistant_os/identity_guard.py            → guard_decision, action_type, subject_state
  assistant_os/cognition/context_resolver.py
  assistant_os/core/enrichment.py
     │
     ▼
[Policy Producer]
  assistant_os/policy/policy_engine.py      evaluate_policy(context, grant_store)
  ── pure deterministic; 7-step evaluation; no LLM ──
     │
     ▼
[Governance Producer]
  assistant_os/mso/governance_engine.py     evaluate_governance(...)
  ── MSO dynamic decision: ALLOW/BLOCK/DEGRADE/REQUIRE_CONFIRMATION ──
  ── FROZEN mode: kills all execution ──
     │
     ▼
[Authority Preparation]
  assistant_os/mso/authority_preparation.py  AuthorityPreparationRequest
  assistant_os/mso/authority_binding.py
  ── assembles authority artifact before Police gate ──
     │
     ▼
[Police Gate — Enforcement]
  assistant_os/police/enforcement.py         check(request: PoliceGateRequest)
  ── token-bound; V1–V5 structural; marks token spent on PERMITTED ──
     │
     ▼
[Capability Token / Runner]
  assistant_os/capabilities/
  assistant_os/runners/
     │
     ▼
[Execution]
```

---

## N0 / Read-Only MACHINE_OPERATOR Path (Distinct from above)

```
Webhook Server (N0 path)
  assistant_os/webhook_server.py:6438–6463
  ── generates intent_id (UUID) ──
  ── stamps policy_decision_ref = "auto:<intent_id>" (synthetic, no evaluate_policy call) ──
     │
     ▼
[Machine Operator Adapter — N0 compat path]
  assistant_os/mso/machine_operator_adapter.py:1842–1859
  ── if approval_mode=none and no approval artifact: ──
  ── creates synthetic_approval_id = f"approval:auto:{intent_id}" ──
     │
     ▼
[MSO Kernel / Sovereign Gate]
  assistant_os/mso/kernel.py
  assistant_os/mso/mso_sovereign_state_store.py  is_execution_allowed()
     │
     ▼
[OpenClaw Backend Server — Sovereign Gate]
  assistant_os/openclaw_backend/server.py:423–488
  ── _sovereign_store.is_execution_allowed(_sovereign_query) ──
  ── denied → HTTP 403; no fallback ──
     │ (if allowed)
     ▼
[PlaywrightRuntimeDispatcher.execute()]
  assistant_os/openclaw_backend/runtime.py:216
  ── no internal sovereign gate; validates capability_name + URL only ──
```

---

## Reference Families — Where Emitted, Where Consumed, What Validates

| Reference | Format | Emitted at | Consumed at | Validated by | Provenance | Runtime reachability |
|---|---|---|---|---|---|---|
| `policy_decision_ref = "auto:<intent_id>"` | `auto:<uuid4>` | `webhook_server.py:6448` | Police V3, OpenClaw server | Police: non-empty check; OpenClaw: regex format | SYNTHETIC — no `evaluate_policy()` call | UNVERIFIED — static call-chain only |
| `approval:auto:<intent_id>` | `approval:auto:<str>` | `machine_operator_adapter.py:1852` | N0 downstream flows as `approval_id` | N0 compat path accepts by construction | SYNTHETIC — created by adapter, not by authority decision | UNVERIFIED — static call-chain only |
| `policy_decision_ref = "decision:<plan_id>"` | `decision:<str>` | `core/orchestrator.py:179,486` | Police V3, downstream consumers | Police: non-empty; downstream: format varies | Derived from plan_id; Police-unverified semantic provenance | UNVERIFIED |
| `governance_ref = "governance:<ts>:<action>"` | `governance:...:...` | `mso/governance_engine.py:69,95,...` | Police V2, authority context | Police: non-empty only | Produced by governance engine; provenance = governance decision | UNVERIFIED |

---

## Direct-Call Registry Path — Fail-Closed (Canonical Main)

**File:** `assistant_os/agents/registry.py:130–243`

Historical audits may describe a direct-call bypass through the agent registry. In canonical main at SHA `b2fa39b9` this concern is REMEDIATED:

```
Direct call → _host_launcher_entrypoint (registry.py:130)
               or _machine_operator_entrypoint (registry.py:181)
     │
     ▼
Build PoliceGateRequest(
    token_ref=None,
    binding_ref=None,
    authorized_plan_ref=None,
    governance_ref=None,
    policy_decision_ref=None,
    ...
)
     │
     ▼
check(police_request)                              ← Police V1
     │  token_ref is None → TOKEN_MISSING → DENIED
     ▼
if decision.outcome != PERMITTED → return error    ← fail-closed
     │
     ▼
(execute_host_action / _mo_execute never reached)
```

Both entrypoints call `check()` unconditionally before delegating. Any direct-call request has no authorization context and is denied at V1. This is the canonical main behavior. Whether prior versions or the quarantined checkout had a different structure is not characterizable within AOS-P0 cleanroom scope.

---

## Police Gate — Capability Boundary

The Police gate is the enforcement boundary between authority preparation and capability execution. Key properties:

- **Token registry** (`police/token_registry.py`): process-local, in-memory, no I/O. No imports from capabilities/sandbox/policy/mso/core.
- **Authorized plan registry** (`police/authorized_plan_registry.py`): process-local, in-memory. Binds execution_id + token_ref + binding_ref + capability_scope.
- **Single-use enforcement**: `_mark_spent()` called on PERMITTED; subsequent calls denied with `TOKEN_ALREADY_CONSUMED`.
- **Fail-closed**: unknown `token_ref` → `TOKEN_INVALID` (not a soft denial — hard DENIED).

---

## OpenClaw Runtime — Reachability Surface

| Surface | Status | Notes |
|---|---|---|
| Python import | REACHABLE | `from assistant_os.openclaw_backend.runtime import PlaywrightRuntimeDispatcher` |
| HTTP endpoint (`POST /v1/execute`) | REACHABLE IF ENABLED | Depends on `config.OPENCLAW_RUNTIME_ENABLED` and network binding |
| Auth gate at HTTP server | PRESENT | `_enforce_auth()` at `server.py:385` before sovereign gate |
| Sovereign gate at HTTP server | PRESENT | `_sovereign_store.is_execution_allowed()` at `server.py:441` before `execute()` |
| Gate INSIDE `execute()` | ABSENT | `execute()` has no internal sovereign/police gate |
| External bypass via HTTP | UNPROVEN | Requires auth bypass + sovereign bypass; network reachability unconfirmed from code |
| In-process bypass | POSSIBLE | Direct Python call to `execute()` without going through server bypasses sovereign gate |

---

## Files NOT Present in Canonical Main

The following files were referenced in prior audits or local state but do NOT exist in canonical `main` at SHA `b2fa39b9`:

- `assistant_os/mso/governed_execution.py` — does not exist
- Any audit findings about these files are from historical state or the quarantined checkout, NOT canonical

---

## Quarantine Boundary

`C:\Users\Jorge\Assistant_OS_Labs` (quarantined checkout):
- NOT inspected
- NOT used as evidence
- MUST NOT be treated as canonical project state
- Any divergence between it and canonical main is unknown and uncharacterized in this audit

---

## Unresolved Questions (Require Jorge's Decision)

See `AOS_P0_REALITY_LOCK.md` § "Decisions Required from Jorge" for the full list.

Summary:
1. Is N0 synthetic `policy_decision_ref` provenance acceptable?
2. Is N0 `approval:auto:` synthetic artifact the intended design?
3. Is the OpenClaw HTTP server currently network-bound and if so is auth sufficient?
4. Does the threat model include in-process actors (no server path)?
