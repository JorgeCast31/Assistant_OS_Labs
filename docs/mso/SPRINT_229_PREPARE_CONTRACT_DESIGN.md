# Sprint #229 — Prepare Contract DESIGN ONLY

> Date: 2026-05-29
> Status: DESIGN — No implementation. No code changes.
> Prerequisite: Sprint #228 merged (Draft Persistence Implementation, no prepare).
> Principle: MSO is the only source of executable authority.
> Truth before power. Order before speed. MSO before execution.

---

## 0. Executive Summary

This sprint does not implement anything.

The objective is to design the formal contract for `prepare` as the bridge
from an operator Plan (in `mso_review` state) to a `PreparedAction` in the
confirm queue.

**Non-negotiable constraints for this design:**

- Prepare does **not** execute.
- Prepare does **not** authorize execution.
- Prepare does **not** emit tokens.
- Prepare does **not** create an `AuthorityArtifact` from the UI.
- Prepare does **not** call the Runner.
- Prepare does **not** call Machine Operator.
- Prepare does **not** set `execution_allowed = True` on any artifact.
- The Runner remains closed from Mission Control.
- MSO remains the only source of executable authority.

Approval of this document gates Sprint #230 (Prepare Contract Implementation).

---

## 1. Estado actual observado

| Capability | Status | Evidence |
|---|---|---|
| Draft Store | **Exists** | `assistant_os/mso/draft_store.py` — SQLite, MEMORY_DIR/draft_store/plans.db |
| Plan model | **Exists** | `assistant_os/mso/plan_model.py` — PlanRecord, states: draft/planning/mso_review |
| POST /mso/plans | **Exists** | `webhook_server.py:1769` |
| Plan transitions | **Exists** | `webhook_server.py:1773` — /mso/plans/{id}/transition |
| Plan in mso_review | **Exists** | State is terminal — Plan is frozen at this point |
| PreparedAction queue | **Exists** | `assistant_os/mso/prepared_action_queue.py` |
| ConfirmablePreparedAction | **Exists** | `assistant_os/mso/confirmable_prepared_action.py` |
| AuthorityPreparationRequest | **Exists** | `assistant_os/mso/authority_preparation.py` |
| MSOExecutionProposal | **Exists** | `assistant_os/mso/execution_proposal.py` |
| PolicyDecision | **Exists** | `assistant_os/mso/policy_review.py` — MSOPolicyDecisionDraft |
| GovernanceDecision | **Exists** | `assistant_os/mso/governance_engine.py` — evaluate_governance() |
| CapabilityRegistry | **Exists** | `assistant_os/mso/capability_registry.py` — check_capability() |
| AuthorityTrace | **Exists (snapshot)** | `assistant_os/mso/authority_trace.py` — architectural, not per-mission |
| POST /mso/plans/{id}/prepare | **Does not exist** | Endpoint not defined anywhere |
| Plan → PrepareRequest bridge | **Does not exist** | No artifact correlates Plan to authority chain |
| MSO ACK over Plan | **Does not exist** | No formal PlanMSOAck model |
| PrepareRequest model | **Does not exist** | No intermediate artifact between Plan and PreparedAction |
| mission-correlated trace | **Does not exist** | Trace cannot be correlated to plan_id yet |

**Critical gap:** The existing authority chain
(`MSOExecutionProposal → AuthorityPreparationRequest → ConfirmablePreparedAction`)
originates from cognitive orchestration, not from an operator Plan. There is no
bridge from `Plan(state=mso_review)` to this chain.

---

## 2. Definición del Prepare Contract

### What is Prepare

Prepare is the **operator-initiated, MSO-governed act of converting a frozen
Plan into a structured, reviewable artifact that can enter the confirm queue.**

Prepare:
- Takes a Plan in `mso_review` state as input.
- Evaluates the Plan's `target_actions` against policy, governance, and capability.
- If all pass → produces a `PrepareRequest` intermediate, then a `PreparedAction`
  in `waiting_for_human_confirmation` state.
- If any evaluation fails → fails closed with explicit reason.
- Produces no tokens, no authority artifacts, no execution.

### What Prepare is NOT

| Not this | Why |
|---|---|
| **Not execution** | Runner is unreachable. No action is performed on any external system. |
| **Not authorization** | Producing a PreparedAction does not authorize execution. Authorization requires full authority chain: Policy → CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate. |
| **Not a token emission** | No CapabilityToken is issued during prepare. |
| **Not an AuthorityArtifact creation** | AuthorityArtifacts (CapabilityToken, OperationBinding, AuthorizedPlan) are post-confirmation, post-authority-chain. |
| **Not automatic** | Prepare must be operator-initiated. No autonomous prepare. |
| **Not MSO escalation** | MSO escalation is the transition to mso_review. Prepare is a distinct, later step. |

### Artifacts distinguished

| Artifact | Origin | Authority | In authority chain? |
|---|---|---|---|
| `Plan` | Operator-authored intent | None — pre-authority | No |
| `PlanMSOAck` | MSO reads Plan | None — read receipt only | No |
| `PrepareRequest` | Operator requests prepare | None — structuring only | No (intermediate) |
| `MSOExecutionProposal` | Cognitive orchestrator output | None — cognitive only | Precedes chain |
| `AuthorityPreparationRequest` | Derived from MSOExecutionProposal | None — pending all steps | No (pre-chain) |
| `PreparedAction` (`ConfirmablePreparedAction`) | Result of prepare (this sprint) or cognitive orchestration | None — awaiting confirmation | Waiting |
| `HumanConfirmationRecord` | Operator confirms | Signal only, not authority | Bridge to chain |
| `MSOPolicyDecisionDraft` | Evaluated after confirmation | First authority step | Yes — step 1 |
| `CapabilityToken` | Future | Yes — step 2 | Yes |
| `OperationBinding` | Future | Yes — step 3 | Yes |
| `AuthorizedPlan` | Future | Yes — step 4 | Yes |
| `PoliceGate` | Future | Yes — step 5 | Yes |
| `AuthorityArtifact` | Post-full-chain | Yes — final | Yes |
| Execution | Runner | Only after full chain | Terminal |

---

## 3. MSO ACK sobre Plan (D-12)

### Decision proposed: D-12

**A formal `PlanMSOAck` record is required before `prepare` can proceed.**

Rationale: MSO must have explicitly "read" the Plan before the operator can
request prepare. Without an ACK signal, prepare could be requested against a
Plan that MSO has not yet reviewed. The ACK is the gate: no ACK → no prepare.

The ACK is **not** an authorization. It is a **sovereign read receipt** — a
record that MSO has read the intent, considered it, and either:
- `acknowledged`: MSO has read the Plan and does not object to the operator
  requesting prepare.
- `rejected_for_review`: MSO has read the Plan and requires additional review
  before prepare can be requested.

### PlanMSOAck model

```
ack_id:           str       — "ack_<timestamp_ms>_<uuid4_short>"
plan_id:          str       — the plan_id this ACK covers
operator_seat:    str       — the operator seat this ACK is issued to
acknowledged_at:  str       — ISO 8601 UTC timestamp
acknowledged_by:  str       — identity of MSO actor issuing the ACK
ack_status:       str       — "acknowledged" | "rejected_for_review"
note:             str | None — optional MSO note for the operator
source:           str       — "mso_kernel"
```

### Invariants on PlanMSOAck

- ACK does not change `Plan.state`. Plan remains `mso_review`.
- ACK does not authorize execution.
- ACK does not prepare anything.
- ACK does not emit tokens.
- ACK is immutable once issued.
- If `ack_status = "rejected_for_review"`: operator cannot request prepare.
  They must create a new Plan.
- ACK is persisted separately from the Plan (not in the Draft Store — Draft
  Store holds pre-authority operator records; ACK is an MSO-issued artifact).

### Storage decision for PlanMSOAck

PlanMSOAck should live in a new lightweight store, **not** in `draft_store`
(which holds operator intent) and **not** in `mso_store` (which holds full
authority-chain artifacts). PlanMSOAck is an MSO-layer read receipt.

Proposed path: `MEMORY_DIR / "mso_acks" / "plan_acks.db"` — SQLite,
same local-first pattern as Draft Store.

**Decision for Jorge (D-20):** Should PlanMSOAck use SQLite (consistent with
Draft Store) or the existing file-per-record JSON pattern (consistent with
mso_store)? Recommendation: SQLite for same reasons as D-03 (mutable, queryable
by plan_id).

---

## 4. PrepareRequest intermedio (D-13)

### Decision proposed: D-13 — Use a PrepareRequest intermediate

**Recommendation: YES — use `PrepareRequest` before producing `PreparedAction`.**

Rationale:
1. **Separates operator intent from authority artifact.** A Plan is operator
   cognitive intent. A PreparedAction is an artifact waiting for human
   confirmation. Conflating them would make Plan a direct authority artifact.
2. **Enables fail-closed policy/governance/capability evaluation.** If
   PolicyDecision denies or GovernanceDecision denies, the failure is recorded
   on the PrepareRequest — not on the Plan (which must not be mutated in
   `mso_review`) and not silently dropped.
3. **Enables auditability.** The PrepareRequest captures the exact moment the
   operator requested prepare, the operator_seat, and the outcome — including
   denials.
4. **Avoids direct Plan → PreparedAction coupling.** MSOExecutionProposal and
   AuthorityPreparationRequest are cognitive-orchestration artifacts derived
   from a seated model provider. Plan is operator-authored. The Plan must not
   be confused with a cognitive proposal. PrepareRequest is the explicit bridge.
5. **Trazabilidad.** PrepareRequest carries `plan_id` and produces
   `prepare_request_id`, both of which propagate to PreparedAction. This enables
   authority trace correlation from Plan to outcome.

### PrepareRequest model (fields)

```
prepare_request_id:         str       — "prep_req_<timestamp_ms>_<uuid4_short>"
plan_id:                    str       — source Plan (must exist, must be in mso_review)
ack_id:                     str       — source PlanMSOAck (must be acknowledged)
operator_seat:              str       — operator seat requesting prepare
requested_at:               str       — ISO 8601 UTC
requested_by:               str       — operator identity
source:                     str       — "draft_store" (always)
intent_summary:             str       — copied from Plan.intent_summary
domain:                     str       — copied from Plan.domain
target_actions:             list[str] — copied from Plan.target_actions
risk_level:                 str | None — copied from Plan.risk_level
capability_scope_candidate: list[str] — derived by prepare layer mapper (not registry)
policy_context:             dict      — policy evaluation context
governance_context:         dict      — governance evaluation context
correlation_id:             str       — plan_id (the root of intent)
prepare_status:             str       — "requested" | "evaluating" | "prepared" |
                                        "rejected" | "requires_review"
policy_outcome:             str | None — "approved" | "approved_confirm_only" | "denied" | None
governance_outcome:         str | None — "approved" | "not_required" | "denied" | None
prepared_action_id:         str | None — if prepare produced a PreparedAction
fail_closed_reason:         str | None — why prepare failed, if it did
```

### Prohibited fields on PrepareRequest

These fields must NEVER appear on a PrepareRequest:

```
execution_allowed           (execution is not a prepare concern)
used_execution              (no execution occurs)
capability_token_ref        (token is post-confirmation, post-authority-chain)
authority_artifact_ref      (post-chain)
runner_ref                  (runner is closed)
mission_id                  (mission does not exist yet)
policy_decision_ref: "auto:" (auto refs are prohibited)
execution_status            (not an execution artifact)
```

### prepare_status lifecycle

```
requested      — PrepareRequest created; evaluation not yet run
evaluating     — Policy/Governance/Capability evaluation in progress
prepared       — All evaluations passed; PreparedAction enqueued
rejected       — One or more evaluations denied; fail-closed
requires_review — Governance requires additional operator decision
```

Note: These statuses are **PrepareRequest statuses**, not Plan states and not
execution statuses. They must never be used as Plan.state values.

---

## 5. Policy / Governance / Capability design (D-14, D-15, D-16)

### D-14 — PolicyDecision: evaluated DURING prepare

PolicyDecision is evaluated as part of PrepareRequest resolution:
1. Operator calls POST /mso/plans/{plan_id}/prepare.
2. Backend resolves Plan, validates PlanMSOAck.
3. Backend maps `target_actions` → `capability_scope_candidate`.
4. If any target_action is unmappable → reject, fail closed.
5. Backend calls `check_capability(action, domain)` for each capability in scope.
6. If any capability is `deny` or `revoked` → policy outcome = `"denied"` →
   PrepareRequest status = `"rejected"`, fail closed.
7. If all capabilities are `allow` or `confirm_only` → policy outcome =
   `"approved"` or `"approved_confirm_only"`.
8. PolicyDecision is recorded on PrepareRequest. No MSOPolicyDecisionDraft is
   created yet (that artifact is for post-human-confirmation, per existing chain).

**Rationale:** Policy must run before enqueuing, not after. Enqueuing a
PreparedAction that will be immediately denied by policy is wasteful and
confusing for the operator. Fail-closed before the queue.

### D-15 — GovernanceDecision: evaluated DURING prepare

GovernanceDecision is evaluated as part of PrepareRequest resolution, after
PolicyDecision:

- If the Plan implies operations that require governance review (risk_level =
  `high` or `critical`, or any `confirm_only` capability in scope) →
  call `evaluate_governance()` from `governance_engine.py`.
  - If governance blocks (FROZEN mode or active interventions) →
    `governance_outcome = "denied"` → PrepareRequest status = `"rejected"`.
  - If governance approves → `governance_outcome = "approved"`.
  - If governance requires additional operator decision →
    `governance_outcome = "requires_review"` →
    PrepareRequest status = `"requires_review"`.
- If none of the above apply (e.g., risk_level = `low`, no `confirm_only`
  capabilities) → `governance_outcome = "not_required"` with explicit reason:
  `"No governed operations in capability scope at this risk level."` This is
  not a skip — it is an explicit determination.

**Invariant:** GovernanceDecision never sets `execution_allowed = True`.
The existing `governance_engine.evaluate_governance()` already enforces this.

### D-16 — Capability scope mapping

`Plan.target_actions` are **free-form strings** (per D-06 resolution).
They must NOT be used as capability registry keys directly. Doing so would
couple the Plan model to the capability registry at authoring time, which
was explicitly deferred.

**Proposed mechanism: Prepare Layer Mapper**

A new prepare-layer function `map_target_actions_to_capability_scope()`:
- Input: `target_actions: list[str]` (free-form), `domain: str`
- Output: `capability_scope_candidate: list[str]` (known capability keys)
- Logic: Normalize → match against known capability keys via a conservative
  mapping table. Unknown strings → fail closed.
- This function lives in the prepare layer, NOT in `capability_registry.py`
  and NOT in `plan_model.py`.
- It does NOT modify the Plan or the capability registry.
- The mapping table should be explicit and minimal — only actions that can be
  unambiguously mapped.

**Conservative mapping invariant:**
- Any target_action that cannot be mapped with high confidence → fail closed
  (`prepare_status = "rejected"`,
  `fail_closed_reason = "unmappable target_action: '<value>'"`)
- Never silently ignore unmappable actions.
- Never infer capabilities from partial string matches.

**Why not bind earlier (at Plan creation)?**
The D-06 decision explicitly kept `target_actions` as free-form strings in ALFA
to avoid premature coupling. The prepare layer is the right place to perform
this translation — close to the authority chain where it matters.

---

## 6. Correlation model (D-17)

### Decision proposed: D-17

**`plan_id` is the root of intent and serves as the primary `correlation_id`.**

Rationale:
- The operator's intent originates in the Plan. All downstream artifacts
  (PrepareRequest, PreparedAction, authority chain artifacts) are traceable
  back to this Plan.
- Using `plan_id` as `correlation_id` makes it unambiguous which mission
  originated from which operator intent.
- `prepare_request_id` identifies the specific prepare operation (useful if
  prepare is retried after a first rejection).
- `prepared_action_id` identifies the artifact in the confirm queue.

### Propagation chain

```
Plan.plan_id
  │
  │  (MSO reads and issues)
  ▼
PlanMSOAck.plan_id  ← plan_id
  │
  │  (operator requests prepare)
  ▼
PrepareRequest.plan_id       = plan_id         ← root
PrepareRequest.correlation_id = plan_id         ← same as root
PrepareRequest.prepare_request_id               ← identifies prepare op
  │
  │  (prepare produces)
  ▼
PreparedAction.plan_id        = plan_id         ← propagated
PreparedAction.correlation_id = plan_id         ← propagated
PreparedAction.prepare_request_id               ← propagated
  │
  │  (operator confirms)
  ▼
HumanConfirmationRecord.action_id               ← prepared_action_id
  │
  │  (policy review)
  ▼
MSOPolicyDecisionDraft.entry_id                 ← queue entry id
  │  (future authority chain steps carry plan_id)
  ▼
CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate → Runner
  │
  ▼
AuthorityTrace: correlation_id = plan_id        ← mission-correlated
```

This propagation enables the authority trace to become mission-correlated
(resolving the #224 gap: "Authority trace is snapshot, not per-mission").

---

## 7. Endpoint futuro (designed, not implemented)

### POST /mso/plans/{plan_id}/prepare

```
Route:   POST /mso/plans/{plan_id}/prepare
Auth:    Bearer WEBHOOK_TOKEN (same as existing MSO routes)
```

**Input body:**

```json
{
  "operator_seat":              "string (required)",
  "confirmation_acknowledged":  true,
  "notes":                      "string (optional)"
}
```

`confirmation_acknowledged: true` is a required explicit signal from the
operator. Prepare cannot be called without this. The UI must surface a
confirmation dialog before calling this endpoint (consistent with D-04
resolution for escalation: explicit confirmation required).

**Output (success — prepared):**

```json
{
  "ok": true,
  "source": "prepare_contract",
  "plan_id": "plan_<ts>_<uid>",
  "prepare_request_id": "prep_req_<ts>_<uid>",
  "prepared_action_id": "cpa-<uuid>",
  "correlation_id": "plan_<ts>_<uid>",
  "prepare_status": "prepared",
  "execution_allowed": false,
  "used_execution": false,
  "runner_reachable_from_ui": false
}
```

**Output (failure — rejected):**

```json
{
  "ok": false,
  "source": "prepare_contract",
  "plan_id": "plan_<ts>_<uid>",
  "prepare_request_id": "prep_req_<ts>_<uid>",
  "prepare_status": "rejected",
  "fail_closed_reason": "string — why prepare was rejected",
  "execution_allowed": false,
  "used_execution": false,
  "runner_reachable_from_ui": false
}
```

**Output (requires review):**

```json
{
  "ok": false,
  "source": "prepare_contract",
  "plan_id": "plan_<ts>_<uid>",
  "prepare_request_id": "prep_req_<ts>_<uid>",
  "prepare_status": "requires_review",
  "fail_closed_reason": "Governance requires additional operator decision before prepare can proceed.",
  "execution_allowed": false,
  "used_execution": false,
  "runner_reachable_from_ui": false
}
```

**Constraints on this endpoint:**

- Only callable when Plan.state = `mso_review`.
- Only callable when PlanMSOAck exists and ack_status = `"acknowledged"`.
- Only callable by the operator_seat that owns the Plan.
- `confirmation_acknowledged` must be `true`. If `false` or absent → 400.
- No prepare from `draft` or `planning` — 422 with explicit reason.
- No global `/mso/prepare` without plan_id — not valid in ALPHA 1.
- This endpoint does not execute. Does not call Runner. Does not emit tokens.

---

## 8. State transition design

### Plan states (unchanged from Sprint #228)

```
draft → planning → mso_review
```

Plan states do NOT change during prepare. The Plan remains `mso_review`
regardless of prepare outcome.

### Prepare-related statuses (separate from Plan state)

These are statuses of the `PrepareRequest` artifact, not the Plan:

```
requested        — PrepareRequest created; evaluation not yet run
evaluating       — Policy/Governance/Capability evaluation in progress
prepared         — All evaluations passed; PreparedAction enqueued
rejected         — One or more evaluations denied; fail-closed
requires_review  — Governance requires additional operator decision
```

These must **never** be used as `Plan.state` values.

### PreparedAction statuses (from existing confirmable_prepared_action.py)

```
waiting_for_human_confirmation    — artifact exists in confirm queue
```

PreparedAction enters confirm queue always in `waiting_for_human_confirmation`.
This is the existing invariant from `ConfirmablePreparedAction.__post_init__`.

### Explicit non-states

These states must **never** appear anywhere in the prepare flow:

```
running, executing, completed, live, approved, authorized
```

---

## 9. Failure modes / fail-closed (D-19)

All failure cases below must produce an explicit error response. No silent
coercion. No fallback execution. No partial success.

| Failure case | HTTP status | fail_closed_reason |
|---|---|---|
| `plan_id` not found in Draft Store | 404 | `"plan_not_found: <plan_id>"` |
| `plan_id` format invalid | 400 | `"invalid_plan_id_format"` |
| Plan exists but `operator_seat` mismatch | 403 | `"operator_seat_mismatch"` |
| Plan is in `draft` state | 422 | `"plan_not_in_mso_review: current_state=draft"` |
| Plan is in `planning` state | 422 | `"plan_not_in_mso_review: current_state=planning"` |
| PlanMSOAck does not exist | 422 | `"mso_ack_not_found: plan has not been acknowledged by MSO"` |
| PlanMSOAck exists but `ack_status = "rejected_for_review"` | 422 | `"mso_ack_rejected: MSO has flagged this plan for review before prepare"` |
| `schema_version` unknown on Plan read | 500 | `"unknown_schema_version: fail-closed"` |
| `target_actions` empty | 422 | `"empty_target_actions: cannot map empty action list to capability scope"` |
| Any `target_action` unmappable | 422 | `"unmappable_target_action: '<value>'"` |
| `confirmation_acknowledged` is `false` or absent | 400 | `"confirmation_required: operator must explicitly acknowledge before prepare"` |
| Policy `check_capability` returns `deny` | 422 | `"policy_denied: capability '<action>' in domain '<domain>' is denied"` |
| Policy `check_capability` returns `revoked` | 422 | `"policy_denied: capability '<action>' is revoked — reason: <reason>"` |
| Governance returns BLOCK (system FROZEN) | 422 | `"governance_blocked: system is FROZEN. All execution blocked until operator clears freeze."` |
| Governance intervention blocks action | 422 | `"governance_blocked: <intervention_reason>"` |
| Governance requires review | 422 | `"governance_requires_review: additional operator decision required"` |
| `policy_decision_ref: "auto:"` detected in any input | 400 | `"auto_ref_prohibited: auto: pattern is not permitted in prepare contract"` |
| Attempt to set `execution_allowed = True` detected | 500 | `"execution_allowed_violation: invariant breach — this is a bug"` |
| Duplicate PrepareRequest for same plan_id | 409 | `"duplicate_prepare_request: plan_id has an existing PrepareRequest in status <status>"` |
| `operator_seat` field absent from request body | 400 | `"operator_seat_required"` |

---

## 10. Tests requeridos para #230

These test requirements must be satisfied **before** Sprint #230 can be
considered complete. They are not exhaustive — they are the minimum floor.

### Backend tests (pytest)

```
test_prepare_rejects_draft_state
    — POST /mso/plans/{plan_id}/prepare with plan in draft → 422

test_prepare_rejects_planning_state
    — POST /mso/plans/{plan_id}/prepare with plan in planning → 422

test_prepare_accepts_only_mso_review
    — POST /mso/plans/{plan_id}/prepare with plan in mso_review + valid ack → ok

test_prepare_requires_operator_seat
    — POST without operator_seat → 400

test_prepare_rejects_operator_mismatch
    — POST with wrong operator_seat → 403

test_prepare_requires_mso_ack
    — POST without PlanMSOAck → 422

test_prepare_rejects_mso_ack_rejected
    — POST with ack_status=rejected_for_review → 422

test_prepare_requires_confirmation_acknowledged
    — POST without confirmation_acknowledged:true → 400

test_prepare_creates_prepare_request
    — Successful prepare creates PrepareRequest with correct plan_id and correlation_id

test_prepare_does_not_execute
    — PrepareRequest and PreparedAction both have execution_allowed=False

test_prepare_does_not_emit_tokens
    — No CapabilityToken, OperationBinding, or AuthorizedPlan is created

test_prepare_does_not_create_authority_artifact
    — No AuthorityArtifact is produced

test_prepare_does_not_call_runner
    — No runner module is imported or called during prepare

test_prepare_no_auto_refs
    — PrepareRequest does not contain any field with "auto:" pattern

test_unmappable_target_actions_fail_closed
    — target_actions with unrecognized action string → 422

test_policy_deny_fail_closed
    — target_action maps to capability with mode=deny → 422

test_governance_deny_fail_closed
    — system FROZEN → 422 with governance_blocked reason

test_correlation_id_propagates
    — PreparedAction.correlation_id == Plan.plan_id

test_prepared_action_carries_plan_id
    — PreparedAction has plan_id and prepare_request_id fields

test_duplicate_prepare_request_rejected
    — Second POST /prepare for same plan_id → 409

test_prepare_request_status_lifecycle
    — PrepareRequest transitions: requested → evaluating → prepared | rejected

test_prepared_action_is_waiting_for_confirmation
    — PreparedAction.status == "waiting_for_human_confirmation"

test_plan_state_unchanged_after_prepare
    — Plan.state remains "mso_review" after successful prepare
```

### UI/proxy tests (vitest)

```
test_prepare_button_requires_explicit_confirmation
    — UI must not call /prepare without a confirmation dialog

test_no_prepare_from_draft
    — Prepare action is not available on Plans in draft state

test_no_prepare_from_planning
    — Prepare action is not available on Plans in planning state

test_ui_displays_prepared_as_review_only
    — Prepared status displays as "Awaiting Confirmation" not "Approved" or "Ready"

test_no_running_executing_live_labels
    — No component renders "running", "executing", "live" text after prepare

test_prepare_shows_pending_confirmation
    — After successful prepare, UI shows PreparedAction in pending confirmation state
```

### Static tests (structural)

```
test_no_machine_operator_import_in_prepare
    — grep/import check: prepare module must not import from machine_operator_adapter

test_no_api_agent_execute_reference
    — prepare module must not reference /api/agent/execute

test_no_runner_import_in_prepare
    — prepare module must not import runner or any runner pipeline

test_no_auto_policy_ref_in_prepare
    — prepare module must not contain "auto:" string as a policy_decision_ref value

test_no_execution_status_in_plan
    — PlanRecord model must not have execution_status field

test_prepare_request_prohibited_fields_absent
    — PrepareRequest dataclass must not define: capability_token_ref,
      authority_artifact_ref, runner_ref, execution_allowed=True, used_execution=True
```

---

## 11. Scope for #230

### Sprint #230 MAY implement

- `PlanMSOAck` model (new dataclass).
- `PlanMSOAck` store (SQLite, `MEMORY_DIR/mso_acks/plan_acks.db`).
- `PrepareRequest` model (new dataclass, fields as defined in Section 4).
- `PrepareRequest` store (SQLite or in-memory, TBD per D-21).
- `map_target_actions_to_capability_scope()` function (prepare layer, not registry).
- `prepare_contract.py` — the prepare resolution function (pure function, no I/O
  except stores).
- `POST /mso/plans/{plan_id}/prepare` endpoint in webhook_server.py.
- Proxy route `/api/mso/plans/[plan_id]/prepare` in Next.js if needed for UI.
- All backend tests listed in Section 10.
- UI static tests listed in Section 10.
- UI label/status tests listed in Section 10.

### Sprint #230 MUST NOT implement

- Execution of any kind.
- Runner invocation.
- Token emission (CapabilityToken, OperationBinding).
- AuthorityArtifact creation.
- Full authority trace correlation (that requires downstream chain).
- Automatic prepare loop (no autonomous prepare).
- WORK handler authority chain fix (separate, documented debt).
- Machine Operator lane changes.
- `execution_allowed = True` on any artifact.
- `running`, `executing`, `completed`, `live` state on any UI surface.
- Full MSOPolicyDecisionDraft from prepare (that artifact is post-confirmation,
  per existing chain; prepare records policy_outcome on PrepareRequest only).

---

## 12. Decisions for Jorge

The following decisions remain open and must be resolved before Sprint #230
begins. Recommendations are provided where the design has strong preference.

| ID | Question | Recommendation | Impact |
|---|---|---|---|
| **D-20** | Should `PlanMSOAck` use SQLite (like Draft Store) or file-per-record JSON (like mso_store)? | **SQLite** — queryable by plan_id, same local-first posture | Determines ack store implementation |
| **D-21** | Should `PrepareRequest` persist to SQLite or stay in-memory (like MSOPolicyDecisionDraft store)? | **SQLite** — PrepareRequests are audit artifacts; process restart must not lose them | Determines prepare_request store scope |
| **D-22** | Should duplicate PrepareRequest (same plan_id, different request) be rejected as 409, or should it supersede the previous PrepareRequest? | **Reject as 409** — fail-closed; operator must create a new Plan if prepare needs to restart | Affects retry behavior |
| **D-23** | Who issues the PlanMSOAck in ALPHA 1 — the operator (simulating MSO read), or an automated signal? | **Operator-issued, simulated** — MSO is not automated in ALPHA 1; operator explicitly marks plan as "MSO read" via a separate UI action | Determines ACK endpoint design |
| **D-24** | Should `POST /mso/plans/{plan_id}/ack` (the MSO ACK endpoint) be implemented in Sprint #230 along with prepare, or in a separate sprint? | **Same sprint** — prepare requires ACK; implementing prepare without ACK endpoint forces a manual workaround | Determines Sprint #230 scope boundary |
| **D-25** | Should Mission Control display a "Prepare" button immediately in Sprint #230, or only design the button and defer UI to Sprint #231? | **Design and implement the button in #230** — the endpoint will exist; deferring the UI creates visible inconsistency | Determines UI scope in #230 |
| **D-26** | What is the UI label for a Plan after successful prepare? Options: "Prepared — Awaiting Confirmation", "In Confirm Queue", "Pending Review" | **"Prepared — Awaiting Confirmation"** — explicit, not execution-implying, consistent with `waiting_for_human_confirmation` status | UI string only |

**Jorge must resolve D-20 through D-26 before Sprint #230 begins.**

D-20, D-21, D-22, D-23, D-24 are blocking for implementation.
D-25, D-26 are blocking for UI implementation but not for backend.

---

## 13. Recommendation

### GO for Sprint #230 — Prepare Contract Implementation, no execution

**Rationale:**

1. The design is internally consistent with the existing authority chain
   (`MSOExecutionProposal → AuthorityPreparationRequest → ConfirmablePreparedAction`).
2. The PrepareRequest intermediate correctly separates Plan from PreparedAction
   without creating authority artifacts.
3. The correlation model (`plan_id` as `correlation_id`) is traceable end-to-end
   and resolves the mission-correlation gap identified in Sprint #224.
4. The fail-closed rules cover all known failure modes without fallback execution.
5. No invariant violations are introduced:
   - `execution_allowed` remains `False` throughout prepare.
   - Runner remains unreachable from UI.
   - No tokens are emitted.
   - Plan model is unchanged.
   - Draft Store is unchanged.
   - Police and Machine Operator are unchanged.
6. The test requirements are explicit and do not require implementation judgment.
7. D-20 through D-26 are all resolvable with strong recommendations — no
   unbounded design uncertainty remains.

**Condition:** D-20 through D-24 must be resolved by Jorge before Sprint #230
implementation begins. Without ACK storage (D-20) and PrepareRequest storage
(D-21) decisions, the implementation cannot proceed without forced assumptions.

**If D-20 through D-24 are unresolved: CONDITIONAL GO (design approved,
implementation blocked pending decisions).**

---

## 14. Cierre

> Truth before power.
> Order before speed.
> MSO before execution.

The prepare contract is designed.
The Runner remains closed.
No authority has been issued.
No execution has occurred.
The system is coherent.
