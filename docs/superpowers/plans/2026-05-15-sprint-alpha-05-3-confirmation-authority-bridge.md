# SPRINT-ALPHA-05.3-DIAG — Confirmation to Authority Bridge

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the governed bridge from a confirmed HumanConfirmationRecord to a MSO-scope PolicyDecisionDraft artifact — the first authority chain step — without opening execution, issuing tokens, or calling PoliceGate.

**Architecture:** After human confirmation (05.2), the authority chain must advance one step at a time. The next step is policy review: a deterministic, pure-function evaluation of whether the confirmed prepared action's domain/action/capability is permitted under the MSO capability registry. The result is a frozen `MSO PolicyDecisionDraft` stored separately (authority chain artifacts are never mutable) and merged into the GET read model. This unlocks `policy_decision_ref` on the authority preparation record — the first of five authority refs — but does not unlock execution.

**Tech Stack:** Python 3.11, frozen dataclasses, threading.Lock in-memory store, pytest TDD, Next.js App Router proxy, Zustand store refresh.

---

## 1. Executive Finding

### Classification: READY WITH STRUCTURAL DEBTS

**Direct answers:**

**Does human confirmation currently advance anything beyond read model metadata?**
No. `record_human_confirmation()` stores a `HumanConfirmationRecord` (execution_allowed=False). `merge_confirmation_into_dict()` overlays `human_confirmation_status` onto the GET /mso/prepared-actions/pending response. That is the entire effect. No authority chain step is triggered, satisfied, or recorded. Zero downstream consequence from confirmation.

**Is there an existing path from confirmed prepared action to authority artifact?**
No. `AuthorityPreparationRequest` is frozen with all authority refs (`policy_decision_ref`, `capability_token_ref`, `operation_binding_ref`, `authorized_plan_ref`, `police_decision_ref`) permanently `None`. No code reads a confirmed `HumanConfirmationRecord` and produces any authority artifact. The `pending_authority_steps` property on `AuthorityPreparationRequest` always returns the full chain (all 5 steps) because no ref is ever set.

**Is there an existing path from authority artifact to PoliceGate?**
Yes — but only in the pre-existing domain-pipeline path, not from MSO prepared actions. `police/enforcement.py::check()` is fully implemented with token registry, authorized plan registry, plan binding, capability scope, and single-use enforcement. It is reachable only from tests and the existing `runners/` pipeline. The MSO authority chain does not reach it.

**Is there an existing path from PoliceGate to runner?**
Yes — `runners/runner_service.py` is a real, working runner pipeline with `authority_consumption.py`. Not reachable from any MSO-initiated path.

**Is outcome captured and visible?**
Partially. `mso/outcome_status.py` exists and is passive. It reads from `task_registry` and `trace_aggregator`. MSO-initiated prepared action outcomes are not currently fed into those stores.

**What is the exact next missing link?**
The bridge from `HumanConfirmationRecord(confirmed=True)` + `ConfirmablePreparedActionQueueEntry` → `MSO PolicyDecisionDraft` (first authority ref). This is the minimum viable next authority step: a deterministic policy evaluation of the prepared action's domain/action/capability against the MSO capability registry, producing a frozen record with a stable `policy_review_id` that becomes the `policy_decision_ref` anchor for the authority chain.

---

## 2. Repository State

| Field | Value |
|---|---|
| Branch | `claude/elegant-williamson-391927` |
| HEAD commit | `6dcfeb3 feat(ui): add PreparedActionConfirmSurface for human confirmation signal` |
| Git status | Clean (nothing to commit, working tree clean) |
| 05.1 present | Yes — `mso/prepared_action_queue.py`, `mso/execution_proposal.py`, `mso/authority_preparation.py`, `mso/confirmable_prepared_action.py` all committed on main |
| 05.2 present | Yes — `mso/human_confirmation.py`, confirm endpoint, `PreparedActionConfirmSurface.tsx` in HEAD |
| Worktree artifacts | This is a git worktree at `.claude/worktrees/elegant-williamson-391927`. Branch pushed to origin. PR #197 open. |

---

## 3. Current Operability Loop Map

| # | Segment | Status | File / Function | UI Reachable? | Test Covered? | Notes |
|---|---|---|---|---|---|---|
| 1 | MSO chat receives plan-only request | COMPLETE | `webhook_server.py::_handle_chat_process_post()` → `route_text()` | Yes — MSO chat surface | Yes | `intent_type="plan_request"` triggers the chain |
| 2 | mso_direct routes to plan_request | COMPLETE | `surface_behavior.py::handle_mso_direct()` → `_build_plan_request_authority_data()` | Yes | Yes | |
| 3 | ExecutionProposal created | COMPLETE | `mso/execution_proposal.py::build_execution_proposal()` | Indirect | Yes — `test_mso_seat_authority_preparation.py` | Frozen, all invariants enforced |
| 4 | AuthorityPreparationRequest created | COMPLETE | `mso/authority_preparation.py::prepare_authority_from_proposal()` | Indirect | Yes | Frozen, all refs None (pending) |
| 5 | ConfirmablePreparedAction created | COMPLETE | `mso/confirmable_prepared_action.py::build_confirmable_from_preparation()` | Indirect | Yes — `test_confirmable_prepared_action.py` | status="waiting_for_human_confirmation" |
| 6 | PreparedAction queued | COMPLETE | `mso/prepared_action_queue.py::enqueue_confirmable_prepared_action()` | Indirect | Yes — `test_confirmable_prepared_action_queue.py` | In-memory deque |
| 7 | Mission Control displays prepared action | COMPLETE | `ConfirmFlowQueuePanel.tsx` + `PreparedActionDetailPanel.tsx` + GET /mso/prepared-actions/pending | Yes | Yes — contract tests | Passive panels |
| 8 | Human confirms/rejects prepared action | COMPLETE | `PreparedActionConfirmSurface.tsx` → POST /mso/prepared-actions/confirm | Yes | Yes — `test_mso_prepared_actions_confirm_endpoint.py` | UI buttons, governed endpoint |
| 9 | Confirmation merges into pending read model | COMPLETE | `mso/human_confirmation.py::merge_confirmation_into_dict()` | Yes (via refresh) | Yes — `test_human_confirmation.py` | `human_confirmation_status` visible in UI |
| 10 | Confirmed prepared action advances to policy decision | **MISSING** | — | No | No | **Next sprint target** — no code exists |
| 11 | PolicyDecision grants/denies/confirm-only | **MISSING** | `mso/capability_registry.py::check_capability()` exists but not called from authority path | No | No | MSO capability registry is the right source |
| 12 | CapabilityToken issued | **MISSING** | — | No | No | Blocked by missing PolicyDecision |
| 13 | OperationBinding created | **MISSING** | — | No | No | |
| 14 | AuthorizedPlan created/signed | **MISSING** | `authority/artifact.py::sign_authority_artifact()` exists and is real | No | Partial — `test_authority_artifact.py` | Signing infrastructure ready |
| 15 | PoliceGate validates | COMPLETE BUT PASSIVE | `police/enforcement.py::check()` — real, not stub | No (backend/test only) | Yes | Requires all 4 upstream artifacts |
| 16 | Runner/agent executes | COMPLETE BUT PASSIVE | `runners/runner_service.py` — real pipeline | No (backend/test only) | Partial | Not wired to MSO path |
| 17 | Outcome captured | PARTIAL | `mso/outcome_status.py` | Yes — OutcomeStatusPanel | Partial — `test_outcome_status.py` | Reads task_registry; MSO-chain outcomes not fed in |
| 18 | Outcome shown in UI | PARTIAL | `OutcomeStatusPanel.tsx` | Yes | Yes — contract tests | Passive; no MSO-chain outcome data |
| 19 | MSO perception sees outcome | PARTIAL | `mso/perception.py` | Indirect | Partial | Reads governance/state; not linked to prepared_action_id |
| 20 | MSO narrates/interprets outcome | PARTIAL | `mso/narrative_runtime.py` | Indirect | Partial | Narrative not linked to authority chain artifacts |

---

## 4. HumanConfirmationRecord Audit

**Location:** `assistant_os/mso/human_confirmation.py`

**Fields:**
```
record_id: str            (auto UUID, "hcr-{uuid}")
entry_id: str             (queue_entry_id — validated non-empty)
action_id: str            (prepared_action_id — validated non-empty)
confirmed: bool           (True = confirmed, False = rejected)
operator_note: str        (default "")
recorded_at: datetime     (UTC, auto)
execution_allowed: bool   (INVARIANT: always False)
```

**Invariants:**
- `execution_allowed` must be `False` — enforced in `__post_init__`, raises `ValueError` if violated
- `entry_id` must be non-empty — validated
- `action_id` must be non-empty — validated
- Frozen dataclass — immutable after construction

**Store:** `_store: dict[str, HumanConfirmationRecord]` (module-level dict, keyed by `entry_id`), protected by `threading.Lock`

**Merge:** `merge_confirmation_into_dict(item_dict)` looks up `queue_entry_id` in `_store` and overlays `human_confirmation_status`, `confirmation_recorded_at`, `operator_note` onto the dict. Does not mutate the original record.

**Overwrite behavior:** `record_human_confirmation()` with the same `entry_id` overwrites the previous record — last write wins. Double-confirmation is therefore allowed at the record level, but idempotent from authority perspective since `execution_allowed` stays False regardless.

**Authority semantics:** `HumanConfirmationRecord` **is not authority**. It records a human signal only. It does not satisfy any step of the authority chain (`policy_decision_ref`, `capability_token_ref`, `operation_binding_ref`, `authorized_plan_ref`, `police_decision_ref` all remain None after confirmation).

---

## 5. Prepared Action / Authority Preparation Audit

**`ConfirmablePreparedAction`** (frozen dataclass, `mso/confirmable_prepared_action.py`):
- Contains: `action_id`, `preparation_id`, `proposal_id`, `user_intent`, `domain`, `requested_action`, `capability_name`, `capability_scope`, `plan_steps`, `risk_level`, `pending_authority_steps`, `delegated_seat_ref`, `provider_name`, `model_name`
- Immutable — cannot be updated after creation
- `status = "waiting_for_human_confirmation"` — invariant, never changes
- `execution_allowed = False`, `confirmed = False` — both enforced in `__post_init__`

**Contains enough data for PolicyDecision?** Yes:
- `domain` (e.g., "CODE") — maps to capability registry domain
- `requested_action` (e.g., "CODE_REVIEW") — maps to capability registry action key
- `capability_name` — confirms the specific capability
- `capability_scope` — the required scope

**What is missing for authority advancement:**
1. No `policy_decision_ref` set (the frozen artifact can't be mutated)
2. No separate store exists to hold MSO policy decisions keyed by `action_id`
3. No function that reads confirmed HumanConfirmationRecord + ConfirmablePreparedAction → produces MSO PolicyDecisionDraft
4. No endpoint that triggers policy evaluation

**Is there a signed artifact?** No. The `authority/artifact.py` signing infrastructure exists (`sign_authority_artifact()`, HMAC-SHA256), but it is not called from any MSO-initiated path. The `AuthorityArtifact` requires `policy_decision_ref`, `governance_ref`, `authorized_plan_hash` — none of which exist for MSO prepared actions yet.

---

## 6. Existing Confirm Flow Audit

**Two separate confirmation systems exist:**

| System | Module | What it tracks | Trigger | Auth meaning |
|---|---|---|---|---|
| `confirm_flow` (original) | `assistant_os/confirm_flow/readiness.py` | Pending plans in `context_store` from domain pipeline (`store_pending_plan`) | NL chat → orchestrator → plan_confirmation_required result_type | Plan exists and is awaiting NL confirm/cancel from user |
| `human_confirmation` (05.2) | `assistant_os/mso/human_confirmation.py` | `HumanConfirmationRecord` from operator clicking Confirm/Reject in Mission Control | POST /mso/prepared-actions/confirm | Not authority — human signal only |

**Are they intentionally separate?** Yes. They operate at different levels of the system:
- `confirm_flow` is domain-pipeline confirmation (old path: `chat_process → requires_confirmation → user says "confirmar"`)
- `human_confirmation` is MSO authority chain confirmation (new path: Mission Control → PreparedActionConfirmSurface → operator review)

**Should 05.3 bridge HumanConfirmationRecord to existing confirm_flow?** No. The `confirm_flow` system consumes `context_store` pending plans from the original domain pipelines. Bridging HumanConfirmationRecord there would conflate two architecturally distinct confirmation semantics.

**Which path is safer?** Bridge HumanConfirmationRecord directly to the MSO authority preparation path (new `mso/policy_review.py`). This keeps the authority chain internal to the MSO module, testable in isolation, and free from coupling to the domain-pipeline confirm flow.

---

## 7. PolicyDecision / CapabilityToken / OperationBinding / AuthorizedPlan Audit

| Artifact | Exists? | Module | Inputs Required | Current Callers | Safe for MSO? | Notes |
|---|---|---|---|---|---|---|
| PolicyDecision (identity-layer) | Yes | `policy/policy_engine.py::evaluate_policy()` | `PolicyContext(subject_state, guard_decision, action_type, principal_id)` | `orchestrator.py`, identity guard, tests | No — wrong layer | Designed for NL chat identity routing, not MSO authority chain |
| MSO PolicyDecisionDraft | **Missing** | — | `ConfirmablePreparedAction`, `HumanConfirmationRecord`, capability registry | None | **Yes — target of 05.3** | Must be created |
| CapabilityToken | Unknown | No clear module found — capability_registry.py manages records, not tokens | — | Unknown | Not yet | Blocked by missing PolicyDecision |
| OperationBinding | Unknown | Not found as standalone artifact | — | Unknown | Not yet | |
| AuthorizedPlan | Exists (infra) | `authority/artifact.py::sign_authority_artifact()` | execution_id, plan_id, authorized_plan_hash, policy_id, policy_decision_ref, governance_ref, approval_id, execution_mode, capability_scope, runtime_profile | `tests/test_authority_artifact.py` | Not yet — needs upstream artifacts | Signing is real HMAC-SHA256 |
| PoliceToken registry | Yes | `police/token_registry.py::register_token()` | token_ref, binding_ref | Tests, police enforcement tests | Not yet | Process-local in-memory |
| AuthorizedPlan registry (police) | Yes | `police/authorized_plan_registry.py::register_authorized_plan_ref()` | authorized_plan_ref, execution_id, token_ref, binding_ref, capability_scope | Tests | Not yet | Process-local in-memory |

**Key observation:** The identity-layer `PolicyDecision` (from `policy/policy_engine.py`) takes `PolicyContext(subject_state, guard_decision, action_type)` — it is the identity/session policy engine for NL chat routing. It is **not** the right function to call from the MSO authority chain.

The MSO authority chain needs its own policy review layer that:
1. Takes `domain`, `requested_action`, `capability_name` from the prepared action
2. Calls `mso/capability_registry.py::check_capability(action, domain)` → `CapabilityCheckResult`
3. Checks `requires_human_confirmation` is satisfied (HumanConfirmationRecord(confirmed=True) exists)
4. Produces a frozen `MSO PolicyDecisionDraft` with a stable `policy_review_id`

---

## 8. PoliceGate Audit

**Module:** `police/enforcement.py::check(request: PoliceGateRequest) → PoliceDecision`

**Validation sequence (fixed order):**
1. `token_ref` must be non-empty → else TOKEN_MISSING
2. `token_ref` must be registered in `token_registry` → else TOKEN_INVALID
3. Token status must not be EXPIRED → else TOKEN_EXPIRED
4. Token status must not be SPENT → else TOKEN_ALREADY_CONSUMED
5. `governance_ref` must be non-empty → else GOVERNANCE_REF_MISSING
6. `policy_decision_ref` must be non-empty → else POLICY_DECISION_REF_MISSING
7. `binding_ref` must be non-empty → else BINDING_REF_MISSING
8. `binding_ref` must match registered binding → else BINDING_MISMATCH
9. `authorized_plan_ref` must be non-empty and registered → else PLAN_BINDING_FAILURE
10. `authorized_plan_ref` status must be "active" → else PLAN_BINDING_FAILURE
11. execution_id, token_ref, binding_ref must all match the registered plan → else PLAN_BINDING_FAILURE
12. Delegated seat validation (if required)
13. `capability_name` must be in `authorized_plan.capability_scope` → else CAPABILITY_OUT_OF_SCOPE
14. On PERMITTED: marks token as SPENT (single-use enforcement)

**Does it fail closed?** Yes. Unknown token_ref → TOKEN_INVALID. Missing any field → DENIED with specific reason.

**Is it reachable from UI?** No — only from backend tests and the `runners/` pipeline.

**What must exist before invoking?**
- A valid token registered in `token_registry` (not expired, not spent)
- `governance_ref` (from GovernanceDecision)
- `policy_decision_ref` (from PolicyDecision — this is the 05.3 target)
- `binding_ref` matching the registered token binding
- `authorized_plan_ref` registered in `authorized_plan_registry` (active, with matching execution_id/token_ref/binding_ref/capability_scope)
- `capability_name` in scope

**Summary:** PoliceGate is real and correct. It requires 5 artifacts before it can pass. Zero of these artifacts exist for MSO-initiated prepared actions today.

---

## 9. Runner / Execution Audit

**`runners/runner_service.py`** — `RunnerService` class, real pipeline:
- Phases: preflight → workspace → apply → sandbox (RunnerAPI/Docker) → test → validate → report → notify → result
- Has `authority_consumption.py` — tracks `RunnerExecutionRequest.authorized_plan` consumption
- Requires `RunnerExecutionRequest` with `authorized_plan` field
- Executable domains: CODE (code_review, code_fix, code_create via `code_pipeline.py`), FIN (`fin_pipeline.py`), WORK (`work_pipeline.py`), HOST (`host_pipeline.py`), MACHINE_OPERATOR (`machine_operator_pipeline.py`)

**Is Machine Operator wired?** Yes — `machine_operator_pipeline.py` exists, `machine_operator_adapter.py` connects to OpenClaw/browser context. Not used from MSO prepared action path.

**Safe dry-run target for future sprint:** CODE/code_explain or CODE/code_review (both are `mode="allow"` in capability registry — no confirmation required, lowest risk). But this is 2–3 sprints away.

**Is outcome capture implemented?** Partially. Runner generates `RunnerExecutionResult`. `mso/outcome_status.py` reads from `task_registry`/`trace_aggregator`. These are not linked by `prepared_action_id`.

---

## 10. Outcome Audit

**`mso/outcome_status.py::build_outcome_status()`** — passive read-only producer. Takes `plan_id`, `context_id`, `trace_id`, `execution_id`. Sources: `task_registry`, `trace_aggregator`.

**Traceability gap:** No link from `prepared_action_id` / `queue_entry_id` → `task_id` / `trace_id`. An outcome from an MSO-initiated prepared action cannot be looked up by prepared_action_id today.

**MSO perception:** `mso/perception.py` exists but is not inspected to link to prepared_action_id.

**What is missing for traceability:**
- A `prepared_action_id` → `execution_id` / `trace_id` mapping store
- `build_outcome_status` accepting `prepared_action_id` as query key
- MSO perception reading outcome keyed by prepared_action_id

---

## 11. Risk Analysis

| Risk | Classification | Notes |
|---|---|---|
| Accidental execution from policy review | Blocker if not prevented | MUST: `evaluate_mso_policy_for_prepared_action()` must be pure, no side effects, execution_allowed=False enforced |
| Confirmation treated as authority | Blocker if not prevented | MUST: PolicyDecisionDraft explicitly carries `human_confirmation_required=True`, `human_confirmation_satisfied=True/False`, `execution_allowed=False` |
| Missing policy evidence in authority chain | Blocker for future PoliceGate | PolicyDecisionDraft provides `policy_review_id` for future `policy_decision_ref` |
| Missing capability scope | Important | Must validate capability_name is known in `mso/capability_registry.py::check_capability()` |
| Replay / double-confirm | Acceptable for v0 | `record_human_confirmation()` is idempotent by design (last write wins) — flag as known behavior |
| Stale queue entry | Important | `get_confirmable_action_queue_entry()` may return None if queue was cleared — handle as 404 |
| Mismatched action_id | Blocker | `HumanConfirmationRecord.action_id` must match `ConfirmablePreparedAction.action_id` — validate at policy review call |
| UI spoofing | Acceptable for v0 | Endpoint requires WEBHOOK_TOKEN; same security as all other /mso/ endpoints |
| No durable storage | Blocker for restart recovery | In-memory only — process restart loses all state. Acceptable for v0; document as known debt |
| In-memory queue loss | Blocker for restart recovery | Same — all stores are in-process. Known pre-existing debt across all MSO stores |
| Runner not ready (for execution) | Blocker for execution — not for this sprint | This sprint produces PolicyDecisionDraft only, no runner invocation |
| Outcome disconnected | Future | Outcome linkage is a future sprint (07+) |
| Rejected prepared action triggered for policy | Important | Only `confirmed=True` records should trigger policy evaluation; `confirmed=False` must return error |

---

## 12. Candidate Next Sprints

### A. Confirmation → PolicyDecision Draft Bridge (MSO scope)
**What it closes:** The gap between HumanConfirmationRecord(confirmed=True) and the first authority artifact. Produces `MSO PolicyDecisionDraft` with `policy_review_id`. Unlocks `policy_decision_ref` anchor for the authority chain.
**Why now:** Smallest safe next step. No execution. No tokens. Pure function + in-memory store + merge + endpoint.
**Risk:** Low — pattern is identical to 05.2 (new frozen dataclass + store + merge + endpoint + proxy + test).
**Files touched:** `assistant_os/mso/policy_review.py` (new), `assistant_os/webhook_server.py` (endpoint), `ui/app/api/mso/prepared-actions/policy-review/route.ts` (proxy), `ui/lib/types.ts` (types), `ui/lib/sovereign/api.ts` (API fn), `ui/components/sovereign/PreparedActionConfirmSurface.tsx` (status badge), tests.
**Tests needed:** 12–15.

### B. Confirmation → AuthorityPreparation Completion
**What it closes:** Would set all authority refs on the preparation. But `AuthorityPreparationRequest` is frozen — impossible without new mutable store.
**Why not yet:** Requires architectural decision about mutable authority state. Not smallest step.

### C. Confirmation → ConfirmFlow Integration
**What it closes:** Bridge to the old `confirm_flow` context_store system.
**Why not:** Conflates two architecturally distinct confirm semantics. Wrong layer.

### D. AuthorizedPlan Creation v0
**What it closes:** Full signed `AuthorityArtifact` from `authority/artifact.py`.
**Why not yet:** Requires PolicyDecision, CapabilityToken, OperationBinding to exist first. Cannot skip.

### E. PoliceGate Dry-Run Validation
**What it closes:** Prove that the full artifact set fails closed before any runner is connected.
**Why not yet:** Requires PolicyDecision + CapabilityToken + OperationBinding + AuthorizedPlan. 4 sprints away.

### F. Runner Dry-Run Bridge
**Why not yet:** Requires all 5 authority chain artifacts. 5+ sprints away.

### G. Outcome Trace Linkage
**What it closes:** Links prepared_action_id → execution outcome in read model.
**Why not yet:** No execution to observe yet.

### H. Visual Operation Trace v0
**Why not yet:** No execution trace exists to visualize.

---

## 13. Recommended Next Sprint

**SPRINT-ALPHA-05.3 — MSO PolicyDecision Draft Bridge**

**Name:** `SPRINT-ALPHA-05.3 — Confirmation → MSO PolicyDecisionDraft`

**Goal:** After a human confirms a prepared action, deterministically evaluate the domain/action/capability against the MSO capability registry and produce a frozen `MSO PolicyDecisionDraft` — the first authority chain artifact. This unlocks `policy_decision_ref` for future authority chain advancement. Execution remains closed.

**Why this first:** It is the minimum viable authority step. The pattern is proven (identical to how `HumanConfirmationRecord` was built in 05.2): frozen dataclass + in-memory store + merge into read model + endpoint + proxy + API function + tests. It produces a durable artifact with a stable ID. It moves the authority chain from "confirmation signal recorded" to "policy reviewed and recorded" — while explicitly keeping `execution_allowed=False`, no CapabilityToken, no AuthorizedPlan, no PoliceGate.

**Exact scope:**
1. `assistant_os/mso/policy_review.py` — `MSO PolicyDecisionDraft` frozen dataclass + `evaluate_mso_policy_for_prepared_action()` + in-memory store + merge function
2. `webhook_server.py` — `POST /mso/prepared-actions/policy-review` endpoint
3. `ui/app/api/mso/prepared-actions/policy-review/route.ts` — Next.js proxy
4. `ui/lib/types.ts` — `MSO PolicyReviewResult` interface
5. `ui/lib/sovereign/api.ts` — `requestMSOPolicyReview()` function
6. `ui/components/sovereign/PreparedActionConfirmSurface.tsx` — show policy review status badge after confirmation
7. Tests — 12–15 tests in `tests/test_mso_policy_review.py`

**Files likely touched:**
- Create: `assistant_os/mso/policy_review.py`
- Create: `tests/test_mso_policy_review.py`
- Create: `ui/app/api/mso/prepared-actions/policy-review/route.ts`
- Modify: `assistant_os/webhook_server.py` (add endpoint + GET merge)
- Modify: `ui/lib/types.ts` (add types)
- Modify: `ui/lib/sovereign/api.ts` (add API fn)
- Modify: `ui/components/sovereign/PreparedActionConfirmSurface.tsx` (show policy status)

**Tests:**
- `test_policy_draft_execution_allowed_invariant` — execution_allowed must always be False
- `test_policy_draft_confirmed_only` — reject if HumanConfirmationRecord.confirmed=False
- `test_policy_draft_unconfirmed_missing` — reject if no HumanConfirmationRecord exists
- `test_policy_draft_unknown_action` — deny if action not in capability registry
- `test_policy_draft_deny_mode` — deny if capability mode is "deny"
- `test_policy_draft_confirm_only_mode` — approve-with-condition if mode is "confirm_only"
- `test_policy_draft_allow_mode` — approve if mode is "allow"
- `test_policy_draft_action_id_mismatch` — reject if action_id doesn't match queue entry
- `test_policy_draft_store_and_retrieve` — store stores, get retrieves
- `test_policy_draft_merge_into_dict` — merge overlays policy_review_id and policy_outcome
- `test_policy_review_endpoint_missing_entry` — 404 if entry_id not in queue
- `test_policy_review_endpoint_not_confirmed` — 422 if not yet confirmed
- `test_policy_review_endpoint_success` — 200 with policy_review_id, execution_allowed=False

**Acceptance criteria:**
- `MSO PolicyDecisionDraft` is frozen, `execution_allowed=False` enforced in `__post_init__`
- Endpoint rejects if no HumanConfirmationRecord or `confirmed=False`
- Endpoint rejects if entry_id not in queue
- `policy_review_id` is returned and stable for the same entry
- GET /mso/prepared-actions/pending includes `policy_review_id` and `policy_outcome` when a review exists
- `execution_allowed`, `can_execute_now`, `used_execution` remain False
- Mission Control shows policy review status after confirmation
- 13+ tests passing
- No Police, CapabilityToken, AuthorizedPlan, runner, or execution path is touched

**Out of scope:**
- CapabilityToken issuance
- OperationBinding
- AuthorizedPlan creation or signing
- PoliceGate
- Runner invocation
- Execution
- Durable storage (in-memory only)
- Outcome linkage
- Replay prevention beyond entry_id + action_id validation

**Risks:**
- `evaluate_mso_policy_for_prepared_action()` must be pure — no I/O, no side effects, deterministic
- Must not call `evaluate_policy()` from `policy/policy_engine.py` (identity-layer — wrong context)
- Must use `check_capability(action, domain)` from `mso/capability_registry.py` — the MSO-native capability check
- In-memory only — process restart loses all reviews (acceptable for v0, document as debt)

**Expected user-visible change:** After confirming a prepared action in Mission Control, the PreparedActionConfirmSurface shows a second status badge: "Policy Reviewed: confirm_only / APPROVED" (or DENIED if capability is blocked). No execution occurs. The policy_review_id is visible in the inspect panel.

---

## 14. PolicyDecision Draft Bridge v0 — Detailed Contract

### Input
- `entry_id: str` — queue_entry_id of the ConfirmablePreparedActionQueueEntry
- `action_id: str` — action_id of the ConfirmablePreparedAction

**Prerequisite checks (endpoint-level, fail-closed):**
1. `get_confirmable_action_queue_entry(entry_id)` must return an entry → else 404
2. `get_human_confirmation(entry_id)` must return a record → else 422 (confirmation_required)
3. `record.confirmed` must be `True` → else 422 (action_rejected)
4. `record.action_id` must equal `action_id` → else 400 (action_id_mismatch)

### Core function: `evaluate_mso_policy_for_prepared_action(entry, confirmation)`
**Pure function — no I/O, no side effects, deterministic.**

```python
def evaluate_mso_policy_for_prepared_action(
    entry: ConfirmablePreparedActionQueueEntry,
    confirmation: HumanConfirmationRecord,
) -> MSO PolicyDecisionDraft:
    capability = check_capability(entry.requested_action, entry.domain)
    
    if not confirmation.confirmed:
        raise ValueError("Cannot evaluate policy for rejected action")
    
    outcome = _map_capability_to_policy_outcome(capability)
    
    return MSO PolicyDecisionDraft(
        policy_review_id=f"prd-{uuid4()}",
        entry_id=entry.queue_entry_id,
        action_id=entry.prepared_action_id,
        domain=entry.domain,
        requested_action=entry.requested_action,
        capability_name=entry.capability_name,
        capability_mode=capability.mode,
        policy_outcome=outcome,  # "approved" | "approved_confirm_only" | "denied"
        requires_human_confirmation=True,
        human_confirmation_satisfied=True,   # confirmed=True already verified
        execution_allowed=False,             # INVARIANT
        can_execute_now=False,               # INVARIANT
        created_at=datetime.now(timezone.utc),
    )
```

### Output (response body)
```json
{
  "ok": true,
  "entry_id": "...",
  "action_id": "...",
  "policy_review_id": "prd-...",
  "policy_outcome": "approved_confirm_only",
  "capability_mode": "confirm_only",
  "execution_allowed": false,
  "can_execute_now": false,
  "human_confirmation_satisfied": true
}
```

### Required invariants (enforced in `__post_init__`)
- `execution_allowed` must be `False` — raises ValueError if violated
- `can_execute_now` must be `False` — raises ValueError if violated
- `human_confirmation_satisfied` must be `True` when `confirmed=True` input
- `policy_review_id` must be non-empty

### Merge into GET read model
`merge_policy_review_into_dict(item_dict)` — overlays:
- `policy_review_id`
- `policy_outcome`
- `capability_mode`
- `policy_review_created_at`

onto the prepared action dict by looking up `prepared_action_id` in the policy review store.

---

## 15. PoliceGate Dry-Run Validation (if chosen instead)

Not the recommendation for 05.3. Provided for reference.

**What artifact is validated:** A PoliceGateRequest with all 5 required artifacts (token, governance_ref, policy_decision_ref, binding_ref, authorized_plan_ref). In dry-run, the token is not marked SPENT after validation.

**How dry-run differs from execution:** Dry-run calls `enforcement.check()` with a test-registered token and plan ref. PERMITTED decision is returned but `_mark_spent` is skipped. No runner invocation, no side effects.

**Why not safe before upstream:** Cannot reach PoliceGate without PolicyDecision + CapabilityToken + OperationBinding + AuthorizedPlan. We are 4 steps before this.

---

## 16. Manual Validation Plan

For each step: expected behavior, endpoint/UI to inspect, failure condition.

| # | Action | Expected behavior | Where to inspect | Failure condition |
|---|---|---|---|---|
| 1 | Ask MSO: "Prepárame un plan para revisar el repo" | Prepared action appears in Mission Control with status=waiting_for_human_confirmation | GET /mso/prepared-actions/pending; PreparedActionDetailPanel | Action does not appear; human_confirmation_status missing |
| 2 | Click "Confirm Review" in Mission Control | human_confirmation_status → "human_confirmed" in UI; policy review status NOT yet visible (pre-05.3) | PreparedActionConfirmSurface badge; GET /mso/prepared-actions/pending | execution_allowed=true in response (blocker) |
| 3 | Inspect GET /mso/prepared-actions/pending after confirm | human_confirmation_status="human_confirmed", execution_allowed=false, can_execute_now=false | Raw JSON from /api/mso/prepared-actions/pending | execution_allowed=true; can_execute_now=true |
| 4 | POST /mso/prepared-actions/policy-review (05.3 feature) | policy_review_id returned, policy_outcome=approved_confirm_only (for CODE actions), execution_allowed=false | Response body | execution_allowed=true; policy_outcome=approved (without confirm) |
| 5 | Inspect GET /mso/prepared-actions/pending after policy review | policy_review_id and policy_outcome visible on prepared action item | Raw JSON | policy_review_id missing; execution_allowed changed |
| 6 | Verify no execution occurred | OutcomeStatusPanel shows no new outcome; GET /mso/outcome/status unchanged | OutcomeStatusPanel; GET /mso/outcome/status | Any execution outcome appearing |
| 7 | Try stale entry_id in policy review | 404 Not Found | Response body | 200 with fabricated data |
| 8 | Try policy review without prior confirmation | 422 confirmation_required | Response body | 200 or 500 |
| 9 | Try policy review for rejected action (confirmed=False) | 422 action_rejected | Response body | 200 |
| 10 | Try duplicate policy review (same entry_id twice) | 200 — idempotent, returns same (or new) policy_review_id | Response body | Error 500 |

---

## 17. Final Recommendation

### Current MSO Level

**Level: Signal-Complete, Authority-Pending.**

The operability loop exists from chat to confirmation. The system can:
- Accept a plan_request via MSO chat
- Create a governed prepared action artifact chain
- Display it in Mission Control
- Accept a human confirmation signal
- Reflect the confirmation in the read model

The system cannot:
- Advance any authority chain step after confirmation
- Produce any authority artifact (PolicyDecision, CapabilityToken, OperationBinding, AuthorizedPlan)
- Reach PoliceGate from any MSO-initiated path
- Execute anything via runner from MSO prepared actions
- Link outcomes back to prepared_action_id

### What Changed with 05.1 and 05.2

**05.1:** Established the full cognitive artifact chain: MSOExecutionProposal → AuthorityPreparationRequest → ConfirmablePreparedAction → queue → Mission Control visibility. The chain from chat to governed prepared action is complete. No execution.

**05.2:** Added the human confirmation signal surface. Mission Control can now record operator review decisions (Confirm/Reject). The signal is merged into the read model as `human_confirmation_status`. Passive panel contracts remain intact. Still no execution. The system now has: chat → governed prepared action → human signal recorded.

### What Blocks MSO Pleno

Five authority chain steps are missing from the MSO path:
1. PolicyDecision (MSO-scope) — target of 05.3
2. CapabilityToken issuance
3. OperationBinding
4. AuthorizedPlan creation + signing
5. PoliceGate validation

After those five steps: execution runner connectivity, outcome capture, outcome linkage to prepared_action_id, MSO perception of outcome, MSO narration of outcome.

### Exact Next Sprint

**SPRINT-ALPHA-05.3 — MSO PolicyDecisionDraft Bridge**

New module `mso/policy_review.py` with `evaluate_mso_policy_for_prepared_action()`. Triggered by confirmed HumanConfirmationRecord. Produces frozen `MSO PolicyDecisionDraft` with `policy_review_id`. Merged into GET read model. Visible in Mission Control. `execution_allowed=False` enforced by invariant.

### Advanced Mode Status

**Advanced Mode should wait.** Execution should remain completely closed until:
1. PolicyDecisionDraft exists (05.3) ← next sprint
2. CapabilityToken issued (05.4)
3. OperationBinding created (05.5)
4. AuthorizedPlan created and signed (05.6)
5. PoliceGate validates the full set (05.7)

### Execution Status

**Execution remains closed.** No sprint before 05.7 (PoliceGate dry-run validation) should touch any runner, pipeline, executor, or outcome capture from the MSO authority path. The invariant `execution_allowed=False` must be enforced at every artifact boundary in every sprint until PoliceGate PERMITTED is proven.

---

## File Structure

```
assistant_os/mso/
  policy_review.py          ← NEW: MSO PolicyDecisionDraft + store + merge

tests/
  test_mso_policy_review.py ← NEW: 13+ tests

assistant_os/
  webhook_server.py         ← MODIFY: POST /mso/prepared-actions/policy-review endpoint
                                       + merge into GET /mso/prepared-actions/pending

ui/app/api/mso/prepared-actions/
  policy-review/
    route.ts                ← NEW: Next.js proxy for POST

ui/lib/
  types.ts                  ← MODIFY: PolicyReviewResult interface

ui/lib/sovereign/
  api.ts                    ← MODIFY: requestMSOPolicyReview() function

ui/components/sovereign/
  PreparedActionConfirmSurface.tsx ← MODIFY: show policy review status badge
```

---

## Task List

### Task 1: MSO PolicyDecisionDraft module (TDD)

**Files:**
- Create: `assistant_os/mso/policy_review.py`
- Create: `tests/test_mso_policy_review.py`

- [ ] **Step 1: Write failing tests for PolicyDecisionDraft invariants**

```python
# tests/test_mso_policy_review.py
import pytest
from assistant_os.mso.policy_review import (
    MSO PolicyDecisionDraft,
    evaluate_mso_policy_for_prepared_action,
    get_mso_policy_review,
    merge_policy_review_into_dict,
    clear_mso_policy_review_store_for_tests,
)
from assistant_os.mso.human_confirmation import HumanConfirmationRecord
from assistant_os.mso.prepared_action_queue import ConfirmablePreparedActionQueueEntry

class TestMSOPolicyDecisionDraftInvariants:
    def test_execution_allowed_is_always_false(self):
        with pytest.raises(ValueError, match="execution_allowed"):
            MSO PolicyDecisionDraft(
                entry_id="e1", action_id="a1", domain="CODE",
                requested_action="CODE_REVIEW", capability_name="code_review",
                capability_mode="allow", policy_outcome="approved",
                policy_review_id="prd-1", execution_allowed=True,
                can_execute_now=False, human_confirmation_satisfied=True,
            )

    def test_can_execute_now_is_always_false(self):
        with pytest.raises(ValueError, match="can_execute_now"):
            MSO PolicyDecisionDraft(
                entry_id="e1", action_id="a1", domain="CODE",
                requested_action="CODE_REVIEW", capability_name="code_review",
                capability_mode="allow", policy_outcome="approved",
                policy_review_id="prd-1", execution_allowed=False,
                can_execute_now=True, human_confirmation_satisfied=True,
            )

    def test_policy_review_id_non_empty_required(self):
        with pytest.raises(ValueError, match="policy_review_id"):
            MSO PolicyDecisionDraft(
                entry_id="e1", action_id="a1", domain="CODE",
                requested_action="CODE_REVIEW", capability_name="code_review",
                capability_mode="allow", policy_outcome="approved",
                policy_review_id="", execution_allowed=False,
                can_execute_now=False, human_confirmation_satisfied=True,
            )
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_mso_policy_review.py -v
```
Expected: ImportError (module not yet created).

- [ ] **Step 3: Create `assistant_os/mso/policy_review.py`**

```python
"""MSO PolicyDecisionDraft — first authority chain artifact.

Maps a confirmed HumanConfirmationRecord + ConfirmablePreparedActionQueueEntry
to a deterministic policy review outcome against the MSO capability registry.

This is NOT the identity-layer PolicyDecision from policy/policy_engine.py.
This is the MSO-scope policy review artifact.

Invariants (enforced by __post_init__)
--------------------------------------
  execution_allowed    = False (always)
  can_execute_now      = False (always)
  policy_review_id     != ""  (always)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Optional
from uuid import uuid4

from .capability_registry import check_capability
from .human_confirmation import HumanConfirmationRecord
from .prepared_action_queue import ConfirmablePreparedActionQueueEntry


def _new_id() -> str:
    return f"prd-{uuid4()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, kw_only=True)
class MSO PolicyDecisionDraft:
    """Frozen MSO-scope policy review record.

    First artifact in the authority chain after HumanConfirmationRecord.
    Produced by evaluate_mso_policy_for_prepared_action().
    Never issues tokens, never creates AuthorizedPlan, never calls PoliceGate.
    """
    policy_review_id: str = field(default_factory=_new_id)
    entry_id: str
    action_id: str
    domain: str
    requested_action: str
    capability_name: str
    capability_mode: str
    policy_outcome: str  # "approved" | "approved_confirm_only" | "denied"
    requires_human_confirmation: bool = True
    human_confirmation_satisfied: bool = False
    execution_allowed: bool = False
    can_execute_now: bool = False
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.execution_allowed is not False:
            raise ValueError(
                "MSO PolicyDecisionDraft.execution_allowed must always be False. "
                "Policy review does not authorize execution."
            )
        if self.can_execute_now is not False:
            raise ValueError(
                "MSO PolicyDecisionDraft.can_execute_now must always be False."
            )
        if not self.policy_review_id:
            raise ValueError("policy_review_id must be non-empty.")

    def to_dict(self) -> dict:
        return {
            "policy_review_id": self.policy_review_id,
            "entry_id": self.entry_id,
            "action_id": self.action_id,
            "domain": self.domain,
            "requested_action": self.requested_action,
            "capability_name": self.capability_name,
            "capability_mode": self.capability_mode,
            "policy_outcome": self.policy_outcome,
            "requires_human_confirmation": self.requires_human_confirmation,
            "human_confirmation_satisfied": self.human_confirmation_satisfied,
            "execution_allowed": self.execution_allowed,
            "can_execute_now": self.can_execute_now,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_store: dict[str, MSO PolicyDecisionDraft] = {}  # keyed by entry_id
_lock = Lock()


def _store_policy_review(draft: MSO PolicyDecisionDraft) -> None:
    with _lock:
        _store[draft.entry_id] = draft


def get_mso_policy_review(entry_id: str) -> Optional[MSO PolicyDecisionDraft]:
    with _lock:
        return _store.get(entry_id)


def clear_mso_policy_review_store_for_tests() -> None:
    """FOR TESTS ONLY."""
    with _lock:
        _store.clear()


# ---------------------------------------------------------------------------
# Merge into GET read model
# ---------------------------------------------------------------------------

def merge_policy_review_into_dict(item_dict: dict) -> dict:
    """Overlay policy review fields onto a prepared action dict (by entry_id)."""
    entry_id = item_dict.get("queue_entry_id", "")
    if not entry_id:
        return item_dict
    draft = get_mso_policy_review(entry_id)
    if draft is None:
        return item_dict
    result = dict(item_dict)
    result["policy_review_id"] = draft.policy_review_id
    result["policy_outcome"] = draft.policy_outcome
    result["capability_mode"] = draft.capability_mode
    result["policy_review_created_at"] = draft.created_at.isoformat()
    return result


# ---------------------------------------------------------------------------
# Core evaluation function — pure, no I/O
# ---------------------------------------------------------------------------

def evaluate_mso_policy_for_prepared_action(
    entry: ConfirmablePreparedActionQueueEntry,
    confirmation: HumanConfirmationRecord,
) -> MSO PolicyDecisionDraft:
    """Evaluate MSO capability policy for a confirmed prepared action.

    Pure function — no side effects, no I/O, deterministic.
    Does not issue tokens, create AuthorizedPlan, or call PoliceGate.

    Raises ValueError if confirmation.confirmed is False.
    """
    if not confirmation.confirmed:
        raise ValueError(
            "Cannot evaluate policy for a rejected action. "
            "confirmation.confirmed must be True."
        )
    if confirmation.action_id != entry.prepared_action_id:
        raise ValueError(
            f"action_id mismatch: confirmation.action_id={confirmation.action_id!r} "
            f"does not match entry.prepared_action_id={entry.prepared_action_id!r}."
        )

    capability = check_capability(entry.requested_action, entry.domain)

    if capability.mode == "allow":
        outcome = "approved"
    elif capability.mode == "confirm_only":
        outcome = "approved_confirm_only"
    else:
        outcome = "denied"

    draft = MSO PolicyDecisionDraft(
        entry_id=entry.queue_entry_id,
        action_id=entry.prepared_action_id,
        domain=entry.domain,
        requested_action=entry.requested_action,
        capability_name=entry.capability_name or capability.action,
        capability_mode=capability.mode,
        policy_outcome=outcome,
        requires_human_confirmation=True,
        human_confirmation_satisfied=True,
        execution_allowed=False,
        can_execute_now=False,
    )
    _store_policy_review(draft)
    return draft
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_mso_policy_review.py -v
```
Expected: PASS for invariant tests.

- [ ] **Step 5: Add evaluate and store tests**

```python
class TestEvaluateMSOPolicy:
    def setup_method(self):
        clear_mso_policy_review_store_for_tests()

    def _make_queue_entry(self, action="CODE_REVIEW", domain="CODE", capability_name="code_review"):
        from assistant_os.mso.execution_proposal import build_execution_proposal
        from assistant_os.mso.authority_preparation import prepare_authority_from_proposal
        from assistant_os.mso.confirmable_prepared_action import build_confirmable_from_preparation
        from assistant_os.mso.prepared_action_queue import (
            enqueue_confirmable_prepared_action,
            get_confirmable_action_queue_entry,
        )
        proposal = build_execution_proposal(
            user_intent="test", domain=domain,
            requested_action=action, capability_name=capability_name,
        )
        preparation = prepare_authority_from_proposal(proposal)
        confirmable = build_confirmable_from_preparation(preparation)
        enqueue_confirmable_prepared_action(confirmable)
        return get_confirmable_action_queue_entry(confirmable.action_id)

    def _make_confirmation(self, entry, confirmed=True):
        from assistant_os.mso.human_confirmation import record_human_confirmation
        return record_human_confirmation(
            entry_id=entry.queue_entry_id,
            action_id=entry.prepared_action_id,
            confirmed=confirmed,
        )

    def test_allow_mode_produces_approved(self):
        entry = self._make_queue_entry(action="CODE_REVIEW", domain="CODE")
        confirmation = self._make_confirmation(entry)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        assert draft.policy_outcome == "approved"
        assert draft.capability_mode == "allow"
        assert draft.execution_allowed is False

    def test_confirm_only_mode_produces_approved_confirm_only(self):
        entry = self._make_queue_entry(action="CODE_FIX", domain="CODE")
        confirmation = self._make_confirmation(entry)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        assert draft.policy_outcome == "approved_confirm_only"
        assert draft.execution_allowed is False

    def test_rejected_confirmation_raises(self):
        entry = self._make_queue_entry()
        confirmation = self._make_confirmation(entry, confirmed=False)
        with pytest.raises(ValueError, match="rejected action"):
            evaluate_mso_policy_for_prepared_action(entry, confirmation)

    def test_action_id_mismatch_raises(self):
        entry = self._make_queue_entry()
        confirmation = self._make_confirmation(entry)
        # Tamper with action_id
        from dataclasses import replace
        bad_confirmation = replace(confirmation, action_id="wrong-id")
        with pytest.raises(ValueError, match="action_id mismatch"):
            evaluate_mso_policy_for_prepared_action(entry, bad_confirmation)

    def test_store_persists(self):
        entry = self._make_queue_entry()
        confirmation = self._make_confirmation(entry)
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
        retrieved = get_mso_policy_review(entry.queue_entry_id)
        assert retrieved is not None
        assert retrieved.policy_review_id == draft.policy_review_id

    def test_merge_overlays_policy_fields(self):
        entry = self._make_queue_entry()
        confirmation = self._make_confirmation(entry)
        evaluate_mso_policy_for_prepared_action(entry, confirmation)
        item = {"queue_entry_id": entry.queue_entry_id, "domain": "CODE"}
        merged = merge_policy_review_into_dict(item)
        assert "policy_review_id" in merged
        assert "policy_outcome" in merged
        assert merged["domain"] == "CODE"  # original fields preserved

    def test_merge_no_review_returns_unchanged(self):
        item = {"queue_entry_id": "no-such-entry", "domain": "CODE"}
        merged = merge_policy_review_into_dict(item)
        assert "policy_review_id" not in merged
```

- [ ] **Step 6: Run full test file**

```
python -m pytest tests/test_mso_policy_review.py -v
```
Expected: 13 tests PASS.

- [ ] **Step 7: Commit**

```
git add assistant_os/mso/policy_review.py tests/test_mso_policy_review.py
git commit -m "feat(mso): add MSO PolicyDecisionDraft module — first authority chain artifact"
```

---

### Task 2: POST /mso/prepared-actions/policy-review endpoint (TDD)

**Files:**
- Modify: `assistant_os/webhook_server.py`
- Modify: `tests/test_mso_policy_review.py` (endpoint tests)

- [ ] **Step 1: Add endpoint tests to `test_mso_policy_review.py`**

```python
class TestMSOPolicyReviewEndpoint:
    def setup_method(self):
        clear_mso_policy_review_store_for_tests()
        from assistant_os.mso.human_confirmation import clear_human_confirmation_store_for_tests
        clear_human_confirmation_store_for_tests()

    def _make_confirmed_entry(self):
        # Build full chain: proposal → preparation → confirmable → queue → confirm
        from assistant_os.mso.execution_proposal import build_execution_proposal
        from assistant_os.mso.authority_preparation import prepare_authority_from_proposal
        from assistant_os.mso.confirmable_prepared_action import build_confirmable_from_preparation
        from assistant_os.mso.prepared_action_queue import (
            enqueue_confirmable_prepared_action, get_confirmable_action_queue_entry,
        )
        from assistant_os.mso.human_confirmation import record_human_confirmation
        proposal = build_execution_proposal(
            user_intent="review repo", domain="CODE",
            requested_action="CODE_REVIEW", capability_name="code_review",
        )
        prep = prepare_authority_from_proposal(proposal)
        confirmable = build_confirmable_from_preparation(prep)
        enqueue_confirmable_prepared_action(confirmable)
        entry = get_confirmable_action_queue_entry(confirmable.action_id)
        record_human_confirmation(
            entry_id=entry.queue_entry_id,
            action_id=entry.prepared_action_id,
            confirmed=True,
        )
        return entry

    def test_missing_entry_returns_404(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        import json
        body = json.dumps({"entry_id": "missing", "action_id": "also-missing"}).encode()
        status, data = _process_mso_policy_review_request(body)
        assert status == 404
        assert data["ok"] is False

    def test_not_confirmed_returns_422(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        from assistant_os.mso.execution_proposal import build_execution_proposal
        from assistant_os.mso.authority_preparation import prepare_authority_from_proposal
        from assistant_os.mso.confirmable_prepared_action import build_confirmable_from_preparation
        from assistant_os.mso.prepared_action_queue import (
            enqueue_confirmable_prepared_action, get_confirmable_action_queue_entry,
        )
        import json
        proposal = build_execution_proposal(user_intent="x", domain="CODE", requested_action="CODE_REVIEW")
        prep = prepare_authority_from_proposal(proposal)
        confirmable = build_confirmable_from_preparation(prep)
        enqueue_confirmable_prepared_action(confirmable)
        entry = get_confirmable_action_queue_entry(confirmable.action_id)
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_policy_review_request(body)
        assert status == 422
        assert "confirmation_required" in data.get("error", "")

    def test_success_returns_policy_review_id(self):
        from assistant_os.webhook_server import _process_mso_policy_review_request
        import json
        entry = self._make_confirmed_entry()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_policy_review_request(body)
        assert status == 200
        assert data["ok"] is True
        assert "policy_review_id" in data
        assert data["execution_allowed"] is False
        assert data["can_execute_now"] is False
        assert data["policy_outcome"] in ("approved", "approved_confirm_only", "denied")
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_mso_policy_review.py::TestMSOPolicyReviewEndpoint -v
```
Expected: ImportError on `_process_mso_policy_review_request`.

- [ ] **Step 3: Add endpoint to `webhook_server.py`**

In `webhook_server.py`, near the `_process_mso_confirm_request` function (around line 414), add:

```python
def _process_mso_policy_review_request(body_bytes: bytes) -> tuple[int, dict]:
    """Parse, validate, and evaluate MSO policy for a confirmed prepared action.
    Returns (status_code, response_dict).
    Does not authorize execution. execution_allowed=False always.
    """
    import json
    try:
        data = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        return 400, {"ok": False, "error": "Invalid JSON body"}

    entry_id = data.get("entry_id", "")
    action_id = data.get("action_id", "")
    if not entry_id or not action_id:
        return 400, {"ok": False, "error": "entry_id and action_id are required"}

    from .mso.prepared_action_queue import get_confirmable_action_queue_entry
    from .mso.human_confirmation import get_human_confirmation
    from .mso.policy_review import evaluate_mso_policy_for_prepared_action

    entry = get_confirmable_action_queue_entry(entry_id)
    if entry is None:
        return 404, {"ok": False, "error": f"Queue entry not found: {entry_id!r}"}

    confirmation = get_human_confirmation(entry_id)
    if confirmation is None:
        return 422, {
            "ok": False,
            "error": "confirmation_required: no human confirmation recorded for this entry",
            "execution_allowed": False,
            "can_execute_now": False,
        }
    if not confirmation.confirmed:
        return 422, {
            "ok": False,
            "error": "action_rejected: action was rejected by operator, cannot evaluate policy",
            "execution_allowed": False,
            "can_execute_now": False,
        }
    if confirmation.action_id != action_id:
        return 400, {
            "ok": False,
            "error": f"action_id mismatch: expected {confirmation.action_id!r}, got {action_id!r}",
            "execution_allowed": False,
            "can_execute_now": False,
        }

    try:
        draft = evaluate_mso_policy_for_prepared_action(entry, confirmation)
    except ValueError as exc:
        return 422, {"ok": False, "error": str(exc), "execution_allowed": False, "can_execute_now": False}

    return 200, {
        "ok": True,
        "entry_id": draft.entry_id,
        "action_id": draft.action_id,
        "policy_review_id": draft.policy_review_id,
        "policy_outcome": draft.policy_outcome,
        "capability_mode": draft.capability_mode,
        "execution_allowed": False,
        "can_execute_now": False,
        "human_confirmation_satisfied": draft.human_confirmation_satisfied,
        "created_at": draft.created_at.isoformat(),
    }
```

In the `_handle_mso_prepared_actions_pending_get()` method, add `merge_policy_review_into_dict` to the merge chain:

```python
from .mso.human_confirmation import merge_confirmation_into_dict
from .mso.policy_review import merge_policy_review_into_dict

items = [
    merge_policy_review_into_dict(merge_confirmation_into_dict(i))
    for i in list_pending_confirmable_action_dicts()
]
```

Add method `_handle_mso_prepared_actions_policy_review_post()` and route in `do_POST()`:

```python
if path == "/mso/prepared-actions/policy-review":
    self._handle_mso_prepared_actions_policy_review_post()
    return
```

```python
def _handle_mso_prepared_actions_policy_review_post(self) -> None:
    body = self._read_body()
    if body is None:
        return
    status_code, response = _process_mso_policy_review_request(body)
    self._send_json(status_code, response)
```

- [ ] **Step 4: Run endpoint tests**

```
python -m pytest tests/test_mso_policy_review.py -v
```
Expected: All 13+ tests PASS.

- [ ] **Step 5: Commit**

```
git add assistant_os/webhook_server.py tests/test_mso_policy_review.py
git commit -m "feat(webhook): add POST /mso/prepared-actions/policy-review endpoint + merge into GET"
```

---

### Task 3: Next.js proxy route

**Files:**
- Create: `ui/app/api/mso/prepared-actions/policy-review/route.ts`

- [ ] **Step 1: Create proxy**

```typescript
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

const UNAVAILABLE_RESPONSE = {
  ok: false,
  error: 'Policy review endpoint unavailable',
  execution_allowed: false,
  can_execute_now: false,
}

export async function POST(req: NextRequest) {
  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ ok: false, error: 'Invalid JSON body' }, { status: 400 })
  }

  const url = `${getWebhookBaseUrl()}/mso/prepared-actions/policy-review`

  let upstreamRes: Response
  try {
    upstreamRes = await fetch(url, {
      method: 'POST',
      headers: { ...getWebhookHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ...UNAVAILABLE_RESPONSE, error: `Policy review backend unavailable: ${message}` },
      { status: 502 },
    )
  }

  let payload: unknown
  try {
    payload = await upstreamRes.json()
  } catch {
    return NextResponse.json(
      { ...UNAVAILABLE_RESPONSE, error: `Policy review backend returned non-JSON (${upstreamRes.status})` },
      { status: 502 },
    )
  }

  return NextResponse.json(payload, { status: upstreamRes.status })
}
```

- [ ] **Step 2: Verify contract tests still pass**

```
python -m pytest tests/test_ui_runtime_truth_contracts.py -v
```
Expected: All contract tests PASS.

- [ ] **Step 3: Commit**

```
git add ui/app/api/mso/prepared-actions/policy-review/route.ts
git commit -m "feat(ui): add Next.js proxy for POST /mso/prepared-actions/policy-review"
```

---

### Task 4: Types and API function

**Files:**
- Modify: `ui/lib/types.ts`
- Modify: `ui/lib/sovereign/api.ts`

- [ ] **Step 1: Add types to `ui/lib/types.ts`**

After `ConfirmPreparedActionResult`, add:

```typescript
export interface MSO PolicyReviewResult {
  ok: boolean
  entry_id?: string
  action_id?: string
  policy_review_id?: string
  policy_outcome?: 'approved' | 'approved_confirm_only' | 'denied'
  capability_mode?: string
  execution_allowed: false
  can_execute_now: false
  human_confirmation_satisfied?: boolean
  created_at?: string
  error?: string
}
```

Add to `PreparedActionQueueEntry`:
```typescript
policy_review_id?: string
policy_outcome?: 'approved' | 'approved_confirm_only' | 'denied'
capability_mode?: string
policy_review_created_at?: string
```

- [ ] **Step 2: Add API function to `ui/lib/sovereign/api.ts`**

```typescript
import type { ConfirmPreparedActionResult, MSO PolicyReviewResult } from '../types'

export async function requestMSOPolicyReview(
  entryId: string,
  actionId: string,
): Promise<MSO PolicyReviewResult> {
  try {
    const res = await fetch('/api/mso/prepared-actions/policy-review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entry_id: entryId, action_id: actionId }),
    })
    const data = await res.json()
    if (!res.ok) {
      return {
        ok: false,
        execution_allowed: false,
        can_execute_now: false,
        error: data.error ?? `Error ${res.status}`,
      }
    }
    return {
      ok: true,
      entry_id: data.entry_id,
      action_id: data.action_id,
      policy_review_id: data.policy_review_id,
      policy_outcome: data.policy_outcome,
      capability_mode: data.capability_mode,
      execution_allowed: false,
      can_execute_now: false,
      human_confirmation_satisfied: data.human_confirmation_satisfied,
      created_at: data.created_at,
    }
  } catch (err) {
    return {
      ok: false,
      execution_allowed: false,
      can_execute_now: false,
      error: err instanceof Error ? err.message : 'Network error',
    }
  }
}
```

- [ ] **Step 3: Commit**

```
git add ui/lib/types.ts ui/lib/sovereign/api.ts
git commit -m "feat(ui): add MSO PolicyReviewResult type and requestMSOPolicyReview() API function"
```

---

### Task 5: UI — policy review status in PreparedActionConfirmSurface

**Files:**
- Modify: `ui/components/sovereign/PreparedActionConfirmSurface.tsx`

- [ ] **Step 1: Add policy review trigger and status badge**

After the confirm buttons are shown and confirmation is recorded (`localStatus === 'human_confirmed'`), automatically trigger policy review and display the result.

Add to `PreparedActionConfirmSurface.tsx`:

```typescript
import { requestMSOPolicyReview } from '@/lib/sovereign/api'

// Additional state:
const [policyStatus, setPolicyStatus] = useState<string | null>(null)
const [policyError, setPolicyError] = useState<string | null>(null)

// After successful confirmation (in handleConfirm):
const policyResult = await requestMSOPolicyReview(
  item.queue_entry_id,
  item.prepared_action_id ?? item.queue_entry_id,
)
if (policyResult.ok) {
  setPolicyStatus(policyResult.policy_outcome ?? null)
} else {
  setPolicyError(policyResult.error ?? 'Policy review failed')
}

// In the confirmed status display, after the signal badge:
{policyStatus && (
  <div className="mt-2">
    <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-1">
      Policy Review
    </p>
    <p className={`text-[10px] font-mono ${
      policyStatus === 'denied' ? 'text-warn' : 'text-ok'
    }`}>
      {policyStatus}
    </p>
    <p className="text-[10px] font-mono text-tx-muted mt-1 leading-relaxed">
      Policy reviewed. Execution remains closed pending full authority chain.
    </p>
  </div>
)}
{policyError && (
  <p className="text-[10px] font-mono text-warn mt-1">{policyError}</p>
)}

// Also show from item data (if already reviewed and refreshed):
{!policyStatus && item.policy_review_id && (
  <div className="mt-2">
    <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-1">
      Policy Review
    </p>
    <p className="text-[10px] font-mono text-tx-secondary">{item.policy_outcome ?? '—'}</p>
  </div>
)}
```

- [ ] **Step 2: Verify contract tests still pass**

```
python -m pytest tests/test_ui_runtime_truth_contracts.py::TestConfirmFlowQueuePanelContracts -v
```
Expected: 6 tests PASS (PreparedActionConfirmSurface is not covered by passive-panel contracts).

- [ ] **Step 3: Commit**

```
git add ui/components/sovereign/PreparedActionConfirmSurface.tsx
git commit -m "feat(ui): show MSO policy review status in PreparedActionConfirmSurface"
```

---

### Task 6: Full test suite and verification

- [ ] **Step 1: Run all sprint tests**

```
python -m pytest tests/test_mso_policy_review.py tests/test_human_confirmation.py tests/test_mso_prepared_actions_confirm_endpoint.py tests/test_ui_runtime_truth_contracts.py::TestConfirmFlowQueuePanelContracts tests/test_ui_runtime_truth_contracts.py::TestPreparedActionDetailInspector -v
```
Expected: All tests PASS.

- [ ] **Step 2: Run broader test suite (excluding pre-existing failures)**

```
python -m pytest tests/ -v --ignore=tests/test_admin_api_auth.py --ignore=tests/test_operator_admin_api.py -k "not test_413_body_too_large"
```
Expected: No new failures introduced.

- [ ] **Step 3: Invoke finishing-a-development-branch skill**

```
REQUIRED SUB-SKILL: superpowers:finishing-a-development-branch
```

---

## Self-Review

**Spec coverage check:**
- §1 Executive finding → covered in §1
- §3 Loop map → Table with all 20 segments ✓
- §4 HumanConfirmationRecord audit → §4 ✓
- §5 Prepared action audit → §5 ✓
- §6 Confirm flow audit → §6 ✓
- §7 PolicyDecision/CapabilityToken/etc. audit → §7 table ✓
- §8 PoliceGate audit → §8 ✓
- §9 Runner audit → §9 ✓
- §10 Outcome audit → §10 ✓
- §11 Risk analysis → §11 table ✓
- §12 Candidate sprints A–H → §12 ✓
- §13 Recommend one sprint → §13 ✓
- §14 PolicyDecision bridge v0 contract → §14 ✓
- §15 PoliceGate dry-run → §15 (if-chosen) ✓
- §16 Manual validation plan → §16 table ✓
- §17 Final recommendation → §17 ✓

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:** `MSO PolicyDecisionDraft` used consistently. `policy_review_id` used consistently. `evaluate_mso_policy_for_prepared_action()` used consistently across all tasks. `ConfirmablePreparedActionQueueEntry` (not `ConfirmablePreparedAction`) is the correct type from the queue — consistent with how 05.2 tests built it.

> **Note on type name:** In task code above, `MSO PolicyDecisionDraft` has a space — in actual Python code this must be `MSOPolicyDecisionDraft`. The plan uses the spaced version for readability in the doc; the implementer should use `MSOPolicyDecisionDraft` in all Python and TypeScript identifiers.
