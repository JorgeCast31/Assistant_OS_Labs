# Sprint #225 — Planner Formal DESIGN ONLY

> Date: 2026-05-28
> Status: DESIGN — No implementation. No code changes.
> Principle: MSO is the only source of executable authority.
> Truth before power. Order before speed. MSO before execution.

---

## Preamble

This document formalizes the design of the Mission Control Planner as a
sovereign, non-executing entity. It is a design artifact, not an implementation
plan. No code is written or changed as a result of this sprint.

Approval of this document gates Sprint #226 (Draft Persistence DESIGN ONLY).

---

## 1. Qué es un Plan

A **Plan** is a structured, non-executing cognitive intent record produced by
Mission Control's Planner before any authority chain is engaged.

A Plan:

- Expresses **what the operator intends** to do — in human-readable, structured
  form.
- Is owned by the operator seat (MSO-governed), not by the execution layer.
- Has a defined lifecycle with explicit, bounded states.
- Is **read by MSO** when the operator decides to escalate. MSO is not involved
  in creating or mutating the Plan. MSO reads it at escalation time.
- Is **never** a trigger, a command, or an authorization.
- Cannot cause execution by existing.

A Plan answers: *"What does the operator want to do, before anyone decides if
it is allowed?"*

---

## 2. Qué es un Draft

A **Draft** is the earliest state of a Plan — an incomplete, uncommitted intent
record held in transient store.

A Draft:

- May be incomplete (required fields absent, sections empty).
- Has no authority implications whatsoever.
- Can be abandoned at any time with no side effects.
- Is never sent to MSO, Police, or Runner while in draft state.
- Does not exist in the authority chain until the operator explicitly escalates
  it.

A Draft answers: *"What is the operator thinking about, before they have decided
anything?"*

---

## 3. Qué NO es un Plan

This is the most important section. Violations of these boundaries would
collapse the authority architecture.

| What it is NOT | Why |
|---|---|
| **Not a PreparedAction** | PreparedAction is produced by the cognitive orchestrator after a `plan_request` interaction and enters the ConfirmablePreparedAction queue. A Plan exists before any orchestration occurs. |
| **Not an execution trigger** | A Plan has no mechanism to cause execution. Execution requires: PolicyDecision → CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate → Runner. A Plan does not touch any of those. |
| **Not an authorization** | A Plan does not grant, represent, or imply any authority. It is pre-authority cognitive intent. |
| **Not an AuthorityArtifact** | AuthorityArtifacts (PolicyDecision, CapabilityToken, etc.) are produced by the authority chain after MSO escalation. A Plan precedes escalation. |
| **Not an MSOExecutionProposal** | MSOExecutionProposal is produced by the seated model provider during cognitive orchestration. A Plan is produced by the operator — a human-authored intent record, not a model output. |
| **Not an AuthorityPreparationRequest** | AuthorityPreparationRequest is an MSO-internal bridge artifact derived from an MSOExecutionProposal. A Plan is not derived from a model output. |
| **Not a mission** | A mission is a runtime execution context. A Plan is a pre-execution intent record. |
| **Not a task** | Tasks (in the task registry) are execution-layer concerns. Plans are operator-layer concerns. |

---

## 4. Forma propuesta del plan_id

```
plan_<timestamp_ms>_<uuid4_short>
```

Example:
```
plan_1748476800000_a3f9c2e1
```

**Rationale:**

- Prefixed with `plan_` — unambiguous type identification, cannot be confused
  with a prepared_action_id, proposal_id, or any execution artifact.
- Timestamp milliseconds — human-readable ordering without database queries.
- Short UUID — collision resistance within the same millisecond.
- No sequential integers — avoids enumeration attacks.
- No mission_id embedded — a Plan is pre-mission. Embedding a mission_id at
  creation time would imply a mission already exists, which it does not.

**Pending decision (D-01):** See Section 11.

---

## 5. Estados permitidos

```
draft → planning → mso_review
```

| State | Meaning | Operator can edit? | Sent to MSO? |
|---|---|---|---|
| `draft` | Incomplete intent. Uncommitted. Transient. | Yes — fully editable | No |
| `planning` | Operator has committed the intent as complete. Awaiting operator review before escalation. | Yes — with audit log of changes | No |
| `mso_review` | Operator has explicitly escalated the Plan to MSO for sovereign review. | No — frozen at this point | Yes — read-only by MSO |

**What does NOT exist as a Plan state:**

- `executing` — execution is not a Plan state; it belongs to the runtime layer
- `approved` — approval is a PolicyDecision, not a Plan mutation
- `rejected` — rejection is a Police/Policy outcome, not a Plan state
- `completed` — completion is a mission outcome, not a Plan state
- `running` — same; runtime concern only
- `cancelled` — **Pending decision (D-02):** See Section 11

---

## 6. Transiciones permitidas

```
[none] → draft          Operator creates a new plan
draft  → planning       Operator marks intent as complete
draft  → [abandoned]    Operator discards draft (no state record needed)
planning → draft        Operator reverts to editing
planning → mso_review   Operator escalates to MSO
mso_review → [terminal] MSO reads and acts; Plan is frozen
```

**Invariants on transitions:**

- No transition may occur without an explicit operator action. Plans do not
  transition autonomously.
- `mso_review` is a one-way gate. Once escalated, the Plan cannot be pulled
  back to `draft` or `planning`. If the operator needs to revise, they create a
  new Plan.
- Abandonment from `draft` produces no event, no audit entry, no notification.
  Drafts are ephemeral by design.
- Abandonment from `planning` **does** require an audit log entry (operator
  discarded a committed intent).

---

## 7. Campos mínimos del modelo

```
plan_id:         str       — canonical plan identifier (see Section 4)
title:           str       — human-readable operator-authored title
intent_summary:  str       — brief description of what the operator wants to do
domain:          str       — target domain or system area (e.g. "infrastructure", "data")
state:           str       — one of: draft | planning | mso_review
created_at:      datetime  — UTC timestamp of creation
updated_at:      datetime  — UTC timestamp of last mutation
operator_seat:   str       — identity of the operator seat that owns the plan
schema_version:  str       — "1" — explicit version for future migration safety
```

**Optional fields (may be absent in `draft`):**

```
risk_level:      str | None  — operator-assessed risk: low | medium | high | critical
target_actions:  list[str]   — rough list of intended actions (not binding)
notes:           str | None  — free-form operator notes
```

---

## 8. Campos prohibidos

These fields must never appear on a Plan object. Their presence would indicate
a boundary violation.

| Prohibited field | Why prohibited |
|---|---|
| `execution_allowed` | Execution is not a Plan concern. |
| `policy_decision_ref` | PolicyDecision is post-escalation. |
| `capability_token_ref` | CapabilityToken is post-escalation. |
| `operation_binding_ref` | OperationBinding is post-escalation. |
| `authorized_plan_ref` | AuthorizedPlan is a different artifact type entirely. |
| `police_decision_ref` | PoliceGate is post-escalation. |
| `runner_ref` | Runner is closed from Mission Control. |
| `mission_id` | A Plan precedes mission creation. |
| `used_execution` | Execution context does not belong here. |
| `cognitive_only` | That flag belongs to MSOExecutionProposal, not to Plan. |
| `pending_authority_steps` | Authority chain is not a Plan concern. |
| `auto` (any variant) | `policy_decision_ref: auto:` pattern must not appear in Plan. |
| `status` (as execution state) | Plan uses `state`, never `status`. Avoids confusion with execution status. |

---

## 9. Relación entre capas

```
Operator
  │
  ▼
[Plan: draft → planning]
  │
  │  operator escalates explicitly
  ▼
[Plan: mso_review]  ──read──▶  MSO kernel
                                  │
                                  │  MSO decides to proceed
                                  ▼
                            [Draft Store: future]
                                  │
                                  │  cognitive orchestrator produces
                                  ▼
                            [MSOExecutionProposal]
                                  │
                                  ▼
                            [AuthorityPreparationRequest]
                                  │
                                  ▼
                            [ConfirmablePreparedAction]
                                  │
                                  ▼
                            [ConfirmablePreparedActionQueue]
                                  │
                                  │  human confirms
                                  ▼
                            [Prepare Contract: future]
                                  │
                                  ▼
                            PolicyDecision → CapabilityToken → OperationBinding
                            → AuthorizedPlan → PoliceGate → Runner
```

**Key architectural boundaries in this chain:**

1. **Planner → Draft Store**: The Plan (operator intent) feeds the Draft Store
   (transient persistence). The Draft Store is not yet implemented (Sprint #226).
   The Planner does not call MSO directly — it surfaces a frozen Plan record
   that MSO reads.

2. **Draft Store → MSO Escalation**: MSO reads the Plan at escalation time. MSO
   does not subscribe to or poll the Draft Store. The operator triggers
   escalation explicitly.

3. **MSO Escalation → Prepare Contract (future)**: After MSO reads the Plan and
   decides to proceed, the cognitive orchestrator enters the preparation flow.
   The Prepare Contract (Sprint #227 or later) defines what MSO commits to
   before the full authority chain begins.

4. **Mission Control remains read-model**: Mission Control surfaces the Plan's
   state for operator visibility. It does not execute, does not call MSO,
   does not trigger escalation autonomously.

---

## 10. Invariantes soberanas

These invariants are non-negotiable. Any implementation that violates one is
rejected regardless of test results.

```
INV-PLAN-01   A Plan cannot cause execution by existing.
INV-PLAN-02   A Plan cannot be in state mso_review and still be editable.
INV-PLAN-03   A Plan must not contain any field from the prohibited list (Section 8).
INV-PLAN-04   plan_id must follow the canonical format: plan_<timestamp_ms>_<uuid4_short>.
INV-PLAN-05   Transitions must be operator-initiated. No autonomous transitions.
INV-PLAN-06   Mission Control must not trigger MSO escalation on behalf of the operator.
INV-PLAN-07   The Plan model must not import from execution_proposal, authority_preparation,
              confirmable_prepared_action, prepared_action_queue, or police modules.
INV-PLAN-08   The Draft Store (Sprint #226) must not accept Plans in state mso_review.
INV-PLAN-09   MSO reads a Plan; it does not mutate a Plan.
INV-PLAN-10   Runner is unreachable from the Planner layer. No path from Plan to Runner exists.
```

---

## 11. Decisiones pendientes para Jorge

These are open questions that require explicit operator decision before Sprint
#226 can proceed.

| ID | Question | Options | Impact |
|---|---|---|---|
| **D-01** | plan_id format: millisecond timestamp + short UUID vs. pure UUID4 | (a) `plan_<ts_ms>_<uuid_short>` (b) pure UUID4 with no prefix (c) prefixed UUID4 without timestamp | Affects readability, debuggability, and sort order in store |
| **D-02** | Is `cancelled` a valid Plan state? | (a) Yes — operator can cancel a committed plan (b) No — only draft can be abandoned silently | Affects state machine complexity and audit requirements |
| **D-03** | Where does Draft Store live? | (a) In-memory (process-local, like current queue) — simplest, non-durable (b) SQLite file on disk — durable, local, no service dependency (c) Separate microservice — complex, not justified at this readiness level | Determines Sprint #226 scope entirely |
| **D-04** | Does escalation to `mso_review` require explicit operator confirmation in the UI, or is it a single-click action? | (a) Explicit confirmation dialog (b) Single click | Affects UI design and accidental-escalation risk |
| **D-05** | Schema versioning: Is `schema_version: "1"` sufficient, or is a migration strategy required before first persistence? | (a) Version field only, migration deferred (b) Migration strategy required before any persistence | Affects Sprint #226 scope |
| **D-06** | Should `target_actions` be a free-form list of strings, or a structured enum tied to capability registry? | (a) Free-form strings (b) Structured: must be values from capability registry | Ties Planner to capability registry coupling — may be premature |
| **D-07** | Should Mission Control display a Plan's `state` badge in the UI now (design only), or defer all UI changes to Sprint #226+? | (a) Design the badge now, implement in #226 (b) Defer entirely | Affects Sprint #226 UI scope |

**Jorge must resolve D-01 through D-07 before Sprint #226 begins.**
No assumption will be made. No default will be picked. If unresolved, Sprint #226
is blocked.

---

## 12. Criterios de aceptación para pasar a #226

Sprint #226 (Draft Persistence DESIGN ONLY) may begin if and only if:

| Criterion | Status |
|---|---|
| This document is reviewed and approved by Jorge | Pending |
| D-01 (plan_id format) is resolved | Pending |
| D-02 (cancelled state) is resolved | Pending |
| D-03 (Draft Store location) is resolved | Pending |
| D-04 (escalation confirmation UX) is resolved | Pending |
| D-05 (schema versioning strategy) is resolved | Pending |
| D-06 (target_actions structure) is resolved | Pending |
| D-07 (UI badge scope) is resolved | Pending |
| No code was written in this sprint | Confirmed |
| No /plans endpoint was created | Confirmed |
| No /prepare endpoint was created | Confirmed |
| MSO, Police, Runner, tokens unchanged | Confirmed |
| Machine Operator not connected to Mission Control | Confirmed |

Sprint #226 is **DESIGN ONLY** — it will produce a Draft Store design document,
not an implementation. Implementation begins no earlier than Sprint #227, pending
design approval of both #225 and #226.

---

## Cierre: Recomendación GO / NO-GO para #226

### Recomendación: **CONDITIONAL GO**

Sprint #226 (Draft Persistence DESIGN ONLY) is approved to proceed **under the
condition that all 7 open decisions (D-01 through D-07) are resolved by Jorge
before the sprint begins**.

**Rationale:**

- The Planner formal design is internally consistent.
- No invariant violations detected.
- No authority boundary is crossed in this design.
- The Draft Store cannot be designed without knowing where it lives (D-03) and
  whether cancelled state exists (D-02).
- Starting Sprint #226 without resolving D-03 would force a retro-decision that
  could invalidate the persistence design entirely.

**If Jorge does not resolve the 7 decisions: NO-GO.**

No implementation sprint (#227+) may begin until both #225 and #226 designs are
approved.

---

> Truth before power.
> Order before speed.
> MSO before execution.
