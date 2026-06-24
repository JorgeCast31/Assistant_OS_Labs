# Command Center / Control Plane v0 — Architecture Proposal

> **Status:** DESIGN ONLY — `READY_FOR_CODEX_REVIEW`
> **Task:** TASK-0011-design-command-center-control-plane-v0
> **Baseline SHA:** `b0fbb5a` (`origin/main`)
> **Authority:** `proposed` (Claude, executor). No human/executable authority is claimed by this document.
> **Scope of this document:** propose the contract and incremental design for a Command Center v0. It authorizes **nothing** to execute. It does not modify `coordination/` contracts, MSO, Police, Policy, auth, or the UI.

---

## 0. Reading guide

This is a **conceptual + contract** document. It is compatible-by-design with the existing
`coordination/` bus (v3.1) and the existing Mission Control UI. It introduces **no parallel state
system**: every state it names is either (a) already owned by `coordination/TASK.md.status` in `main`,
or (b) a **read-only projection** of that state. Where it proposes new artifacts, those artifacts are
proposed as **extensions compatible with the current schemas**, to be ratified in a separate, later
authorization — never assumed by this document.

Companion documents:

- UI specification: [`COMMAND_CENTER_UI_V0_SPEC.md`](./COMMAND_CENTER_UI_V0_SPEC.md)
- Implementation backlog: [`../roadmaps/COMMAND_CENTER_V0_IMPLEMENTATION_BACKLOG.md`](../roadmaps/COMMAND_CENTER_V0_IMPLEMENTATION_BACKLOG.md)

---

## 1. Problem and objective

### 1.1 Problem

Assistant OS already has the **pieces** of governance: a coordination bus (`coordination/`), a human
approval model (v3.1), a police gate before dispatch (`assistant_os/core/orchestrator.py`), a Draft
Store (`assistant_os/mso/draft_store.py`), prepared/confirmable actions
(`assistant_os/mso/confirmable_prepared_action.py`, `prepared_action_queue.py`), an authority trace
(`assistant_os/mso/authority_trace.py`), a read-only Queue Reporter
(`scripts/coordination_queue_reporter.py`), and an observational Mission Control UI
(`ui/components/sovereign/MissionControlView.tsx`).

What is **missing** is not components. It is an **operable coordination plane**: a single, coherent
projection where a mission moves Jorge → MSO → Claude → Codex → Jorge with full visibility and
**without any surface ever asserting execution that did not happen**.

### 1.2 Objective of v0

Define the **contract** and the **small, reversible increments** for a Command Center v0 that is:

- **Safe** — no surface creates authority, execution, or headless automation.
- **Visible** — the full mission lifecycle is observable from one place.
- **Truthful** — the UI is a projection of `main`; it never claims execution that the backend has not
  recorded. `execution_allowed` and `can_execute_now` remain invariantly `False`
  (`assistant_os/mso/authority_binding.py:102-103`, `authority_preparation.py:205`).

### 1.3 Explicit non-objective of v0

v0 does **not** enable autonomous execution, a Runner, headless agents, cron, GitHub Actions, Docker,
tunnels/VPS, or real provider integration with Claude/Codex. The seat/provider endpoints are
read-only metadata and are **not** a communication channel with any model. Any such capability requires
its **own separate design/authorization decision** under the existing contract (see STATE.md §"Next cycle").

---

## 2. Authority principles (inherited, not invented)

These are restated from `coordination/AGENT_CONTRACT.md` and `RULES_OF_ENGAGEMENT.md` (v3.1). The
Command Center **must not** weaken any of them.

1. **Single source of authority.** `main` is the only authoritative source of state.
   `coordination/TASK.md.status` in `main` is the one canonical state per task. The Command Center
   **projects** this; it never becomes a second source of truth. *("Si no está commiteado, no pasó.")*
2. **`authorship != authority`.** An agent may draft proposals/candidates; human authority
   (`human_final`) is materialized only by a **verifiable event of Jorge** (merge/approval/signed
   commit/auditable UI), never by typing markdown.
3. **Separation of powers.** Propose / Review / Decide / Execute are performed by distinct subjects
   (agent / other agent / Jorge / MSO). No agent merges, approves PRs, pushes to `main`, or confers
   authority.
4. **Access control is the enforcement, not honor system.** Agents have no merge/approve/push rights;
   even an erroneously written `human_final` cannot produce its effect.
5. **Fail-closed.** Missing required field, exceeded scope, attempted `forbidden` write, or an illegal
   transition ⇒ `blocked`; never assume behavior.
6. **Nothing in this plane executes.** The plane coordinates; MSO/Police execute, outside this plane.

---

## 3. Actors and responsibilities

| Actor | Role in Command Center v0 | May do | May never do |
|---|---|---|---|
| **Jorge** | Human authority | Define mission + priority; set `READY` in-file in `main`; approve/merge PRs; set `HUMAN_DECISION`/`CLOSED_REJECTED`/`ABORTED`; cancel/reprioritize | — |
| **MSO** | Execution authority (outside this plane) | Interpret, prioritize, translate a mission into a verifiable Work Package; evaluate outcome; set `HANDOFF_TO_MSO` (only after Jorge's approval) | Be invoked/executed by anything in `coordination/` or the Command Center UI |
| **Claude** | Executor (bounded collaborator) | Produce evidence inside an authorized Work Package on a branch; draft candidates; propose status transitions in-branch | Merge, approve, push to `main`, confer authority, execute domain actions, work outside an authorized Work Package |
| **Codex** | Reviewer (bounded collaborator) | Review evidence + PR diff; emit `proposed_decision ∈ {GO, NO-GO, NEEDS_CHANGES}`; set `IN_REVIEW`/`CHANGES_REQUESTED`/`DECISION_PROPOSED` | Auto-review own work; merge/approve; confer authority |
| **Command Center UI** | Projection + coordination surface | Render state, evidence, decisions, authority trace; offer safe-prepare/draft affordances | Create silent execution; assert execution; confer authority |
| **GitHub** | Shared memory + persistent channel | Hold tasks, evidence, PRs, reviews as the durable record models coordinate through | Be an authority by itself (only Jorge's verifiable events confer `human_final`) |

---

## 4. Existing reusable components (verified against `b0fbb5a`)

| Capability | Where it lives | Reuse in Command Center v0 |
|---|---|---|
| Canonical task state + state machine | `coordination/tasks/TASK-*.md`, `schemas/TASK.schema.md`, `RULES_OF_ENGAGEMENT.md` | **Source of truth** the Command Center projects. No change. |
| Read-only queue classification | `scripts/coordination_queue_reporter.py` (+ `tests/test_coordination_queue_reporter.py`, 33 tests) | The **projection engine** for the read-only command-center view (Increment 1). Manual, read-only, no-authority — preserved exactly. |
| Human approval model (v3.1) | `coordination/AGENT_CONTRACT.md`, `RULES_OF_ENGAGEMENT.md`, `schemas/DECISION.schema.md` | The decision contract the "Human Decision" lens renders. No change. |
| Police gate before dispatch | `assistant_os/core/orchestrator.py` | Already enforced before dispatch; Command Center only **displays** that execution is closed. Not modified. |
| Draft Store | `assistant_os/mso/draft_store.py`, UI `DraftStorePlansPanel.tsx` | The "Safe draft/preparation flow" lens (Increment 4) projects existing drafts; creates none silently. |
| Prepared / confirmable actions | `assistant_os/mso/confirmable_prepared_action.py`, `prepared_action_queue.py`, `prepare_contract.py`, `plan_prepare_status.py`; UI `PreparedAction*Panel.tsx`, `ConfirmFlowQueuePanel.tsx` | Displayed as-is. `execution_allowed`/`can_execute_now` shown as `False`. |
| Authority trace / binding / preparation | `assistant_os/mso/authority_trace.py`, `authority_binding.py`, `authority_preparation.py`; UI `AuthorityTimeline.tsx`, `AuthorityMatrixPanel.tsx`, `AuthorityArtifactCard.tsx` | The "Authority Trace" lens. Invariant `execution_allowed = can_execute_now = False`. |
| Mission Control shell + spaces | `ui/components/sovereign/MissionControlView.tsx` (Planner / MSO / Arms / Orchestration / Outcome) | The **host** for the Command Center projection. Extended additively in later increments, not rewritten. |
| Seat / entity status (read-only metadata) | `assistant_os/mso/entity_status.py`, `mso_chat_provider.py`, UI `MSOProviderSelector.tsx` | Shown explicitly as **metadata, not a channel to a model**. |

---

## 5. Conceptual data model

> **Important:** these are **conceptual** entities for the projection and the contract. Only **Mission**,
> **Work Package**, **Human Decision**, and **Outcome** require a *durable* representation, and where
> they do, the representation is an **extension of the existing `coordination/` schemas** — not a new
> store. The rest are **read-only lenses** computed from artifacts that already exist in `main`.

### 5.1 Mission
The human intent + priority Jorge defines. Conceptually maps to a **TASK** at the top of a chain
(`coordination/tasks/TASK-NNNN.md`). Fields reuse the TASK front-matter (`id`, `title`, `author`,
`authority`, `status`, priority expressed via existing fields/labels). A Mission is **not** a new file
type in v0; it is a **role** a TASK plays. Authority and `READY` follow the existing rules (only Jorge).

### 5.2 Work Package
The verifiable unit MSO translates a Mission into, and the only thing Claude is authorized to execute
against. Maps to a **TASK** with a bounded `scope` + `permissions.write_proposal` + `forbidden`
whitelist (already required by `TASK.schema.md`). "Claude does not advance outside an authorized Work
Package" = "executor only acts on a TASK that is `READY` in `main`". No new authority surface.

### 5.3 Context Packet *(read-only lens)*
The minimal context a reviewer/decider needs, assembled **from existing artifacts** (the TASK body,
linked proposals, scope). It is a **view**, not a stored object, and explicitly **not** a transport that
confers context-as-authority. Jorge "does not need to transport context" (RULES §Jorge) — the packet is
just a convenient assembly of what is already in `main`.

### 5.4 Evidence Bundle *(read-only lens)*
The executor's evidence for a Work Package: `worklogs/TASK-NNNN.WORKLOG.md` (append-only),
`reports/TASK-NNNN.FINAL_REPORT.md`, `files_touched`, and the PR diff. The Command Center renders these;
it never writes them on the executor's behalf and never fabricates a passing result.

### 5.5 Review Request / Review *(read-only lens)*
Codex's verdict: `reviews/TASK-NNNN.REVIEW.md` + `proposed_decision`. Rendered with its `authority:
proposed` clearly shown. The Command Center does not let a reviewer review their own work (UI mirrors
the `assigned_agent ≠ reviewer` invariant; it does not enforce it — the contract does).

### 5.6 Human Decision
The decision artifact: `candidates/TASK-NNNN.DECISION_CANDIDATE.md` (agent-drafted, `effective_authority:
none`) and, when applicable, `decisions/TASK-NNNN.DECISION.md`. **Materialized only by Jorge's verifiable
merge.** The Command Center surfaces the pending decision and the **fact** that it is not effective until
Jorge merges; it offers no button that an agent could use to make it effective.

### 5.7 Outcome
MSO's evaluation after a decision: the TASK reaching a terminal state (`HANDOFF_TO_MSO` — MSO-only;
`CLOSED_REJECTED` — Jorge-only) and any `FINAL_REPORT`/decision record. Rendered read-only.

### 5.8 Relationship summary

```
Mission (TASK as top-of-chain)
   └─ Work Package (TASK with bounded scope, READY in main by Jorge)
        ├─ Context Packet     [lens over TASK body + linked proposals]
        ├─ Evidence Bundle    [lens over WORKLOG + FINAL_REPORT + diff]   (written by Claude, in-branch)
        ├─ Review             [reviews/TASK-NNNN.REVIEW.md]               (written by Codex, in-branch)
        ├─ Human Decision     [candidate/decision; effective only on Jorge's merge]
        └─ Outcome            [terminal status + records]                 (HANDOFF_TO_MSO = MSO only)
```

---

## 6. State machine (compatible with `coordination/`)

The Command Center introduces **no new state machine**. It projects the existing one
(`schemas/TASK.schema.md` §"Enum status", `RULES_OF_ENGAGEMENT.md` §"Transiciones permitidas"):

```
DRAFT → READY → IN_PROGRESS → EVIDENCE_READY → IN_REVIEW
      → { CHANGES_REQUESTED → IN_PROGRESS | DECISION_PROPOSED }
      → HUMAN_DECISION → { HANDOFF_TO_MSO | CLOSED_REJECTED }
Transversal: BLOCKED (recoverable), ABORTED (terminal)
```

Ownership the UI must respect (display-only; the contract enforces):

| Transition | Owner | Command Center surface |
|---|---|---|
| `DRAFT → READY` | **Jorge** (in-file in `main`) | Shows "awaiting Jorge"; never an agent-actionable button |
| `READY → IN_PROGRESS → EVIDENCE_READY` | Claude (executor) | Shows executor progress; no execution claim |
| `EVIDENCE_READY → IN_REVIEW → {CHANGES_REQUESTED, DECISION_PROPOSED}` | Codex (reviewer) | Shows review state + `proposed_decision` |
| `DECISION_PROPOSED → {HUMAN_DECISION, CLOSED_REJECTED}` | **Jorge** | Shows pending human decision; effect only via Jorge's merge |
| `HUMAN_DECISION → HANDOFF_TO_MSO` | **MSO only** | Shows as MSO-exclusive; never agent/UI-actionable |
| `→ BLOCKED` / `→ ABORTED` | agent (own leg) / Jorge | Shows block reason; ABORTED-final is Jorge's |

**Projection truth rule:** the Command Center shows `status` exactly as it is in `main`. A status that
only lives in a branch is rendered as **"proposed in branch (not effective)"**, never as the effective
state.

---

## 7. Flow: Jorge → MSO → Claude → Codex → Jorge

```
1. Jorge defines Mission + priority.
   → TASK created (DRAFT). Jorge sets READY in-file in main (verifiable event).

2. MSO interprets, prioritizes, and translates into a verifiable Work Package.
   → bounded scope/permissions/forbidden on the TASK (still governed by existing schema).

3. Claude executes ONLY the authorized Work Package, on branch coordination/task-NNNN.
   → WORKLOG (append-only) + FINAL_REPORT + files_touched; status IN_PROGRESS → EVIDENCE_READY.
   → proposes via PR; never merges.

4. Codex reviews evidence + PR diff.
   → REVIEW + proposed_decision; status IN_REVIEW → {CHANGES_REQUESTED | DECISION_PROPOSED}.

5. Jorge keeps the merge decision.
   → approves/merges (materializes human_final) → HUMAN_DECISION; or CLOSED_REJECTED.
   → reprioritization / cancellation / sensitive decisions are Jorge's.

6. Mission Control shows the full cycle WITHOUT asserting execution that did not happen.
   → execution_allowed / can_execute_now stay False; outcome rendered from main only.

7. GitHub is the shared memory and persistent coordination channel between the models
   (tasks, evidence, PRs, reviews live there; chat is never authority).
```

---

## 8. Boundaries: UI vs backend vs GitHub vs providers

| Boundary | Rule |
|---|---|
| **UI ↔ backend** | UI is a **projection**. It reads backend/coordination state; it never writes canonical state. Any "action" it offers is a *preparation/draft* affordance that produces a proposal artifact, never an execution. |
| **Backend ↔ GitHub** | `main` is authoritative; GitHub is where the durable record + PR/review channel lives. The backend reflects `main`; it does not let the UI bypass `main`. |
| **Coordination plane ↔ MSO/Police** | Nothing in `coordination/` or the Command Center invokes or executes MSO/Police. MSO receives approved work via the normal sovereign flow. |
| **System ↔ providers** | Seat/provider endpoints are **read-only metadata**. The Command Center must label them as metadata and must **not** present them as a live channel to Claude/Codex. No provider adapter is implemented in v0 (Increment 5 is *discovery only*). |

---

## 9. Inter-model communication contract (via artifacts)

### 9.1 Three planes (normative distinction)

Coordination spans **three distinct planes**. Conflating them is the core risk this design must prevent.
Only the **authority plane** authorizes work; the other two **never** confer authority.

#### Plane 1 — Authority plane (canonical)
- `main`, the TASK and its `scope` / `permissions` / `forbidden` / `status`, decisions, and **Jorge's
  verifiable merge**.
- **The only plane that authorizes work.**
- Chat, UI, provider metadata, a PR branch, or notifications **do not** create authority. *("Si no está
  commiteado, no pasó.")*

#### Plane 2 — Delivery / attention plane (non-authoritative)
- Messages from ChatGPT/MSO to Claude or Codex, links to a TASK/PR, future provider notifications, or
  manual invocations.
- **May only direct attention** toward a task. They do **not** change `status`, do **not** authorize
  execution, and do **not** substitute for verification against `main`.
- **A recipient (Claude/Codex) must stop unless it independently verifies in `main`:**
  - exact **TASK-ID**;
  - a valid **baseline SHA** or reference;
  - `status: READY` **effective in `main`**;
  - the correct **`assigned_agent`**;
  - compatible **`scope` / `forbidden`**;
  - absence of conflict or any **stop condition**.
- If any check fails or is ambiguous ⇒ **fail-closed** (stop, do not act on the delivery alone).

#### Plane 3 — Evidence plane (verifiable)
- Branch, PR, `WORKLOG`, `FINAL_REPORT`, `REVIEW`, checks, and decision artifacts.
- Lets a party **demonstrate, review, and decide** — but **grants no authority by itself**. An open PR
  (even mergeable) is evidence, not authorization; only Jorge's verifiable merge confers `human_final`.

| Plane | Examples | Can authorize? | Can change `TASK.status`? |
|---|---|---|---|
| Authority | `main` TASK/status, Jorge's merge, MSO `HANDOFF_TO_MSO` | **Yes** (Jorge/MSO only) | **Yes** (owner of the state) |
| Delivery / attention | chat msg, TASK/PR link, provider notification, manual invocation | No | No |
| Evidence | branch, PR, WORKLOG, FINAL_REPORT, REVIEW, checks | No | No |

### 9.2 Artifact channel (authority plane)

Within the **authority/evidence** planes, models coordinate **only** through committed artifacts in
`main`, never through chat:

- **Jorge → MSO/Claude:** a `READY` TASK in `main` (the authorization).
- **MSO → Claude:** the bounded Work Package (scope/permissions on the TASK).
- **Claude → Codex:** `WORKLOG` + `FINAL_REPORT` + PR diff (the Evidence Bundle).
- **Codex → Jorge:** `REVIEW` + `proposed_decision` (and optionally a `DECISION_CANDIDATE`).
- **Jorge → MSO:** the verifiable merge → `HUMAN_DECISION` (then MSO, and only MSO, may set
  `HANDOFF_TO_MSO`).

Invariant: **"If it isn't committed, it didn't happen."** The Command Center renders these planes; it
does not replace the authority plane with a side-channel, and it never promotes a delivery/attention
signal into authority.

---

## 10. Threats and controls

| # | Threat | Control |
|---|---|---|
| T1 | UI silently triggers execution | UI is projection-only; no write path to canonical state; `execution_allowed`/`can_execute_now` invariantly `False` (enforced in `authority_binding.py`). |
| T2 | A model self-assigns authority | Access control (no merge/approve/push for agents) + `authorship != authority`; UI never exposes an agent-usable "approve/merge" affordance. |
| T3 | Provider metadata mistaken for a real channel | Explicit "metadata, not a channel" labeling; no provider adapter implemented in v0. |
| T4 | Covert Runner / headless automation | No cron/daemon/Actions/Docker/tunnel/VPS; Reporter stays manual, read-only, ephemeral stdout; Runner remains blocked (STATE.md §"Runner status"). |
| T5 | Duplicate / parallel state | No second state store; the Command Center is a projection of `coordination/TASK.md.status` in `main`. |
| T6 | UI asserts execution that did not happen | "Projection truth rule" (§6): branch-only status rendered as *proposed (not effective)*; outcome rendered only from `main`. |
| T7 | Reviewer reviews own work | UI mirrors `assigned_agent ≠ reviewer`; the contract enforces; invalid artifacts are null. |
| T8 | Decision made effective without Jorge | `human_final` only via Jorge's verifiable merge; agent-merged/approved decision is invalid and null (RULES §11.1). |
| T9 | A delivery/attention signal (chat msg, TASK/PR link, provider notification) treated as authorization | §9.1 three-plane rule: delivery plane only directs attention; recipient must independently verify in `main` (TASK-ID, baseline SHA, `READY`, `assigned_agent`, scope/forbidden, no stop condition) or fail-closed. An open/mergeable PR is evidence, not authority. |

---

## 11. Explicitly out of scope for v0

- Any Runner, headless agent, cron, GitHub Actions, Docker, tunnel/VPS.
- Real provider integration / adapters with Claude or Codex (v0 = **discovery only**).
- Autonomous execution or auto-promotion of candidates.
- Any modification of `assistant_os/mso/`, `assistant_os/police/`, `assistant_os/policy/`, auth,
  `.env`, secrets, `.github/workflows/`.
- Any change to `coordination/` contracts/schemas, `HANDOFF_TO_MSO`, or PR #258.
- Writing canonical state from the UI.

---

## 12. Decisions that require Jorge

1. **Mission/priority model:** is priority expressed via existing TASK fields/labels, or does Jorge want
   a dedicated `priority` field added to `TASK.schema.md` (a contract change, separate authorization)?
2. **Work Package ↔ Mission chaining:** accept "TASK as Mission/Work-Package role" (no schema change), or
   introduce an explicit parent/child link field (contract change)?
3. **Projection source:** should the read-only projection reuse `coordination_queue_reporter.py`'s
   classifier as a library, or be a separate read-only endpoint that imports the same logic?
4. **First code increment authorization:** which increment (recommended: Increment 1, read-only
   projection) Jorge authorizes as the next *separate* task — design/review first, not implementation.
5. **Provider discovery depth:** how far Increment 5 (discovery, no implementation) may go before a
   separate authorization is required.

These are **open questions for Jorge**, not decisions taken by this document.

---

## 13. Compatibility statement (for Codex)

- **No new state machine, no parallel authority.** Everything projects `coordination/TASK.md.status` in
  `main`.
- **No bypass of authority.** No UI/agent path makes `READY`, `HUMAN_DECISION`, `human_final`, or
  `HANDOFF_TO_MSO` effective; only Jorge's verifiable events / MSO do.
- **Three planes kept separate (§9.1).** Authority (`main` + Jorge's merge) is the only plane that
  authorizes; delivery/attention (chat/links/notifications) and evidence (branch/PR/WORKLOG/REVIEW)
  never confer authority. An open/mergeable PR is evidence, not authorization.
- **No covert Runner.** No headless execution proposed; Reporter stays manual/read-only.
- **No execution / provider integration.** `execution_allowed`/`can_execute_now` stay `False`; providers
  are metadata only.
- **UI ↔ backend coherence.** The "projection truth rule" forbids asserting execution not present in
  `main`.
