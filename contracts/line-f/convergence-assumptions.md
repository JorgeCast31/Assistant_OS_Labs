> [!WARNING]
> **Historical / Frozen Contract Reference**
> This document belongs to a frozen/historical contract set. It is useful for traceability, but it may not reflect current runtime behavior.
> Current implementation source of truth must be verified in code before use.

<!-- agent:do-not-treat-as-source-of-truth -->

---

# Convergence Assumptions — Line F (MACHINE_OPERATOR / OpenClaw)

## 1. Purpose

This file captures the concrete assumptions that Line F currently depends on to enforce MACHINE_OPERATOR execution boundaries.

These assumptions are temporary convergence anchors and must be reviewed against the final hardened MSO / Police branch before merge.

## 2. Current Line F Guarantees

Line F currently guarantees the following:

- Authority artifact validation is enforced before backend dispatch.
- Sovereign gate enforcement occurs before runtime execution.
- Execution is fail-closed when authority artifacts are invalid.
- Execution is fail-closed when sovereign decision is blocked.
- Negative validation coverage exists for missing/partial/expired/mismatched authority artifacts.
- Minimal interim audit emission is present and best-effort (non-blocking).

## 3. Deferred Dependencies on Core

### 3.1 Authority artifact schema

- Assumption:
  - The authority artifact shape includes `approval_id`, `expires_at`, and `capability_scope` with required semantics used by Line F.
- Where it lives in code today:
  - `assistant_os/mso/machine_operator_adapter.py` (authority artifact extraction/validation for backend payload)
  - `assistant_os/mso/contracts.py` (approval normalization and validation)
- What breaks if it changes:
  - Backend dispatch can be blocked unexpectedly (`authority_artifact_invalid` / `not_executed` paths).
  - Scope selection and capability authorization propagation become inconsistent.

### 3.2 policy_decision_ref semantics

- Assumption:
  - `policy_decision_ref` is a stable decision identifier and is required for backend dispatch context.
- Where it lives in code today:
  - `assistant_os/mso/machine_operator_adapter.py` (context to backend payload propagation)
  - `assistant_os/openclaw_backend/server.py` (request validation and sovereign query construction)
- What breaks if it changes:
  - Validation and audit correlation degrade.
  - Sovereign query traceability can become ambiguous or non-resolvable.

### 3.3 governance_ref semantics

- Assumption:
  - `governance_ref` is a required governance linkage key propagated end-to-end.
- Where it lives in code today:
  - `assistant_os/mso/machine_operator_adapter.py` (policy_context extraction)
  - `assistant_os/openclaw_backend/server.py` (request validation and sovereign query)
- What breaks if it changes:
  - Requests fail validation or become under-contextualized for sovereign checks.
  - Audit events lose governance correlation.

### 3.4 capability_scope semantics

- Assumption:
  - Adapter receives list scope (`list[str]`) and selects a single scope string for backend payload.
  - Wildcard scope matching (`prefix.*`) is valid and authoritative.
- Where it lives in code today:
  - `assistant_os/mso/machine_operator_adapter.py` (`capability_scope` selection logic)
  - `contracts/line-f/adapter-contract-v1.json`
- What breaks if it changes:
  - Legitimate requests may be denied or unauthorized requests may be incorrectly accepted.
  - Contract freeze artifacts diverge from runtime behavior.

### 3.5 SovereignStateStore interface

- Assumption:
  - Backend depends on `is_execution_allowed(query)` returning a deterministic allow/block decision with reason and kill-switch state.
- Where it lives in code today:
  - `assistant_os/mso/sovereign_state_store.py` (interface contract)
  - `assistant_os/mso/mso_sovereign_state_store.py` (current read model implementation)
  - `assistant_os/openclaw_backend/server.py` (pre-dispatch enforcement call)
- What breaks if it changes:
  - Backend cannot enforce sovereign gate consistently before runtime.
  - Blocked execution guarantees may regress.

### 3.6 Kill-switch semantics

- Assumption:
  - Kill-switch posture is derived from persisted control-plane signals and surfaced through SovereignStateStore.
  - Current token/status logic is provisional and conservative (fail-closed on uncertainty).
- Where it lives in code today:
  - `assistant_os/mso/mso_sovereign_state_store.py` (kill-switch derivation)
  - `assistant_os/openclaw_backend/server.py` (blocked enforcement when decision is not allowed)
  - `contracts/line-f/kill-switch-assumption.md`
- What breaks if it changes:
  - False allow or false block behavior risk increases.
  - Convergence checks against core kill-switch semantics fail.

### 3.7 Audit event schema

- Assumption:
  - Interim events include at least: `timestamp`, `intent_id`, `correlation_id`, `approval_id`, `capability_name`, `policy_decision_ref`, `governance_ref`, `outcome`, `reason_code`, and `kill_switch_state` (when applicable).
- Where it lives in code today:
  - `assistant_os/openclaw_backend/audit_interim.py`
  - `assistant_os/openclaw_backend/server.py` (event emission points)
- What breaks if it changes:
  - Downstream parsing and reconciliation scripts may fail.
  - Convergence evidence for decision path may become incomplete.

### 3.8 Replay prevention expectations

- Assumption:
  - Replay prevention is not finalized in Line F; uniqueness/correlation fields are propagated for future enforcement (`intent_id`, `correlation_id`, references).
- Where it lives in code today:
  - `assistant_os/openclaw_backend/server.py` (request validation and propagation)
  - `assistant_os/mso/machine_operator_adapter.py` (request shaping)
- What breaks if it changes:
  - Future replay hardening may not be backportable without interface changes.
  - Audit-to-execution correlation may weaken.

### 3.9 Result taxonomy / failure semantics

- Assumption:
  - Line F relies on stable failure outcomes and reason semantics across adapter/backend boundaries.
  - Blocked sovereign outcomes are explicit and pre-runtime.
- Where it lives in code today:
  - `assistant_os/mso/machine_operator_adapter.py` (adapter-level status and metadata mapping)
  - `assistant_os/openclaw_backend/server.py` (HTTP-level blocked/failed surfaces)
  - `contracts/line-f/sovereign-store-interface-v1.md`
- What breaks if it changes:
  - Existing negative validation tests become invalid.
  - Operator-facing failure interpretation drifts across branches.

## 4. What Line F Must Not Break

- Fail-close invariant:
  - Any authority or sovereign uncertainty must end in non-execution.
- Pre-dispatch sovereign gate position:
  - Sovereign decision check must occur after request validation and before runtime dispatch.
- Completeness of propagated authority fields:
  - `approval_id`, `capability_scope`, `expires_at`, `policy_decision_ref`, and `governance_ref` must remain complete and explicit.
- Backend must not negotiate governance:
  - Backend consumes governance references but does not reinterpret or renegotiate governance intent.
- Main must not adapt to fit Line F:
  - Line F must converge to hardened core contracts; main-side interfaces must not drift to preserve temporary Line F assumptions.

## 5. Provisional Components

The following Line F components are provisional and must be replaced or reconciled at convergence:

- MSO-backed read model:
  - `assistant_os/mso/mso_sovereign_state_store.py` (explicitly marked provisional).
- Interim audit channel:
  - `assistant_os/openclaw_backend/audit_interim.py` and `logs/openclaw_audit.ndjson`.
- Kill-switch assumption:
  - Current signal-token derivation semantics pending final core alignment.
- Temporary result/error mapping:
  - Current adapter/backend reason/status mapping may require normalization against hardened core taxonomy.

## 6. Convergence Review Checklist

- [ ] confirmed / not confirmed: authority artifact schema in hardened core matches Line F contract freeze.
- [ ] confirmed / not confirmed: `policy_decision_ref` semantics are unchanged and still required end-to-end.
- [ ] confirmed / not confirmed: `governance_ref` semantics are unchanged and still required end-to-end.
- [ ] confirmed / not confirmed: capability_scope selection and wildcard behavior match hardened core expectations.
- [ ] confirmed / not confirmed: SovereignStateStore interface contract is compatible with Line F pre-dispatch enforcement.
- [ ] confirmed / not confirmed: kill-switch semantics align with hardened core definitions.
- [ ] confirmed / not confirmed: interim audit fields map cleanly to final audit schema.
- [ ] confirmed / not confirmed: replay prevention expectations are satisfied without Line F interface drift.
- [ ] confirmed / not confirmed: result taxonomy and failure semantics align between branches.
- [ ] confirmed / not confirmed: fail-close invariant remains intact across merged paths.
- [ ] confirmed / not confirmed: backend sovereign gate remains pre-runtime and non-bypassable.

## 7. Branch Isolation Statement

Line F is self-contained and must converge into main without requiring main-side interface drift.

If any assumption in this file is invalidated by hardened MSO / Police, Line F must be reconciled to core contracts rather than altering main to preserve Line F behavior.
