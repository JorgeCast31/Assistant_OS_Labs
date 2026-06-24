# Command Center UI v0 — Specification

> **Status:** DESIGN ONLY — `READY_FOR_CODEX_REVIEW`
> **Task:** TASK-0011-design-command-center-control-plane-v0
> **Baseline SHA:** `b0fbb5a` (`origin/main`)
> **Companion:** [`COMMAND_CENTER_CONTROL_PLANE_V0.md`](./COMMAND_CENTER_CONTROL_PLANE_V0.md)
> **Host:** `ui/components/sovereign/MissionControlView.tsx` (Planner / MSO / Arms / Orchestration / Outcome spaces).
> **This document specifies UI; it implements nothing.** No component is created or modified by this file.

---

## 1. Design principle

The Command Center is a **projection and a coordination surface**, never a cockpit that executes. Every
pixel obeys one rule:

> **The UI never asserts execution that the backend has not recorded in `main`.**

`execution_allowed` and `can_execute_now` are invariantly `False`
(`assistant_os/mso/authority_binding.py`); the UI must render this truthfully and must never imply
otherwise.

The Command Center is an **additive extension** of the existing Mission Control shell. It reuses existing
panels (`AuthorityTimeline`, `PreparedActionsReviewPanel`, `DraftStorePlansPanel`, `ConfirmFlowQueuePanel`,
`OutcomeStatusPanel`, `ExecutionNotOpenPanel`, etc.) rather than replacing them.

---

## 2. Information that must appear in Mission Control

For the active coordination cycle, Mission Control must make all of the following visible:

1. **Missions** and their priority (as defined by Jorge).
2. **Work queue** — tasks by actionability (mirrors `coordination_queue_reporter.py` classification).
3. **Per-actor state** — what Jorge / MSO / Claude / Codex are each responsible for *right now*.
4. **Evidence** — WORKLOG + FINAL_REPORT + `files_touched` + PR diff link, per Work Package.
5. **Pending decisions** — what awaits Jorge, shown as non-effective until his verifiable merge.
6. **Authority trace** — the chain of who proposed / reviewed / decided, with `authority` values shown.
7. **Execution status** — always shown as *closed* (`execution_allowed: False`, `can_execute_now: False`).

---

## 3. Minimum views (lenses)

All lenses are **read-only projections** unless explicitly marked "safe-prepare". v0 adds **no**
execution affordance.

### 3.1 Command Center Overview (read-only projection)
- Mission cards (§4) grouped by priority/status.
- Global banner: execution is closed (reuse `ExecutionNotOpenPanel.tsx` semantics).
- Source-of-truth indicator: "Projected from `main` @ `<sha>`".

### 3.2 Work Queue lens
- One row per TASK, classified by actionability (READY_FOR_EXECUTOR, IN_PROGRESS, AWAITING_REVIEW,
  AWAITING_HUMAN_DECISION, BLOCKED, etc.), reusing the Reporter's classification (§6 of the Reporter MVP).
- Each row links to its Mission card and Evidence lens.
- Branch-only proposed status is labeled **"proposed in branch — not effective"**.

### 3.3 Evidence & Review lens
- Renders the Evidence Bundle (WORKLOG append-only, FINAL_REPORT, `files_touched`, PR diff link) and the
  Review (`proposed_decision`, with `authority: proposed` shown).
- **Never** fabricates a passing result; if a validation was `unavailable`/`skipped`, it says so.

### 3.4 Human Decision lens
- Shows the pending decision (candidate/decision) and an explicit statement: **"Not effective until Jorge
  merges. An agent-merged/approved decision is invalid and null."**
- No button an agent could use to make a decision effective.

### 3.5 Authority Trace lens
- Reuse `AuthorityTimeline.tsx` / `AuthorityMatrixPanel.tsx` / `AuthorityArtifactCard.tsx`.
- Shows `execution_allowed: False`, `can_execute_now: False`, `used_execution: False` explicitly.

### 3.6 Safe Draft / Preparation lens *(safe-prepare, no execution)*
- Reuse `DraftStorePlansPanel.tsx`, `PreparedActionsReviewPanel.tsx`, `ConfirmFlowQueuePanel.tsx`.
- Shows existing drafts/prepared actions read-only. Any "prepare" affordance produces a **proposal
  artifact only**; it never executes and never writes canonical state.

---

## 4. Mission card

Each Mission card shows:

- `id` + `title` + priority.
- Current `status` (from `main`) with the projection-truth label if branch-only.
- Owner of the next transition (Jorge / MSO / Claude / Codex) — i.e., "who acts next".
- Links: Work Queue row, Evidence lens, Authority Trace lens.
- A persistent execution-closed indicator.

Card must **never** show a "Run", "Execute", "Approve", or "Merge" control. Agent-actionable controls do
not exist in v0.

---

## 5. Per-actor status

A compact strip (reuse `MSOInvariantStrip.tsx` styling) showing, per actor:

| Actor | What is shown |
|---|---|
| Jorge | Pending human actions (set READY / decide / merge) — informational, performed by Jorge outside the agent path |
| MSO | Interpreting / preparing / evaluating; or "idle". Execution authority shown as closed in this plane. |
| Claude | Executing Work Package N (IN_PROGRESS) / EVIDENCE_READY / blocked — never an execution claim |
| Codex | Reviewing / CHANGES_REQUESTED / DECISION_PROPOSED |

---

## 6. Indicators that must NEVER assert execution

- No indicator may read "executed", "running", "done (executed)", "live", or imply a domain action ran.
- Allowed truthful states: `projected`, `proposed (branch)`, `READY (main)`, `in progress (evidence)`,
  `reviewed`, `awaiting Jorge`, `decided`, `blocked`, `execution closed`.
- The execution-closed indicator is **always present** and reflects `execution_allowed = can_execute_now
  = False`.

---

## 7. Allowed vs not-allowed actions in the UI

| Allowed (v0) | Not allowed (v0) |
|---|---|
| Navigate/inspect missions, queue, evidence, decisions, authority trace | Trigger execution of any kind |
| Open the PR / diff on GitHub (link out) | Merge / approve a PR from the UI |
| View existing drafts/prepared actions | Make a decision effective (`human_final`) from the UI |
| Produce a *proposal/draft artifact* via safe-prepare | Set `READY` / `HUMAN_DECISION` / `HANDOFF_TO_MSO` from the UI |
| Refresh the projection | Write canonical state / mutate `main` from the UI |

---

## 8. Empty, error, and unavailable states

- **Empty:** "No missions in the current cycle." (not an error).
- **Backend unavailable:** explicit "Projection unavailable — could not read `main` state." Never render
  stale data as if live; never invent a state.
- **Partial/missing artifact:** show the gap honestly (e.g., "FINAL_REPORT not present yet"); fail-closed
  in presentation — do not infer a passing state from a missing artifact.
- **Invalid TASK (missing required field):** render as `BLOCKED`/invalid per fail-closed, with the reason.

---

## 9. Visual and functional acceptance criteria

- [ ] **AC-V1.** Every Command Center surface shows the execution-closed indicator; nowhere does the UI
  assert execution that is not recorded in `main`.
- [ ] **AC-V2.** No agent-actionable "Run / Execute / Approve / Merge / make-effective" control exists.
- [ ] **AC-V3.** Branch-only proposed status is always labeled "proposed in branch — not effective".
- [ ] **AC-V4.** Provider/seat data is labeled "metadata, not a channel to a model".
- [ ] **AC-V5.** Evidence lens never fabricates a passing result; unavailable validations are shown as
  unavailable.
- [ ] **AC-V6.** Human Decision lens states decisions are effective only via Jorge's verifiable merge.
- [ ] **AC-V7.** Authority Trace shows `execution_allowed / can_execute_now / used_execution = False`.
- [ ] **AC-V8.** Empty/error/unavailable states are explicit and never rendered as live/success.
- [ ] **AC-V9.** The Command Center is additive: existing Mission Control spaces still work unchanged.
- [ ] **AC-V10.** Source-of-truth indicator shows the `main` SHA the projection was computed from.

---

## 10. Out of scope for the UI in v0

- No execution controls, no Runner UI, no headless triggers.
- No provider integration UI beyond read-only metadata display.
- No new state store in the frontend; the UI holds projected state only.
- No modification of governance/authority semantics — UI mirrors the contract; it does not enforce or
  weaken it.
