# Command Center v0 — Implementation Backlog

> **Status:** DESIGN ONLY — `READY_FOR_CODEX_REVIEW`
> **Task:** TASK-0011-design-command-center-control-plane-v0
> **Baseline SHA:** `b0fbb5a` (`origin/main`)
> **Companions:** [`../architecture/COMMAND_CENTER_CONTROL_PLANE_V0.md`](../architecture/COMMAND_CENTER_CONTROL_PLANE_V0.md),
> [`../architecture/COMMAND_CENTER_UI_V0_SPEC.md`](../architecture/COMMAND_CENTER_UI_V0_SPEC.md)

> **This backlog authorizes nothing.** Each increment below is a *future, separate* task that requires
> its **own** `READY` in `main` by Jorge (design/review first, then — only if separately authorized —
> implementation). Listing an increment here does **not** make it authorized. No Runner, headless
> automation, cron, Actions, Docker, tunnel/VPS, or provider integration is authorized by this document.

---

## Global constraints (apply to every increment)

- **Source of truth:** `coordination/TASK.md.status` in `main`. No increment creates a parallel state
  store.
- **Projection-truth rule:** never assert execution not present in `main`;
  `execution_allowed`/`can_execute_now` stay `False`.
- **Forbidden everywhere:** `assistant_os/mso/`, `assistant_os/police/`, `assistant_os/policy/`, auth,
  `.env`, secrets, `.github/workflows/`, `HANDOFF_TO_MSO`, PR #258, merging/approving, writing canonical
  state from the UI.
- **Reversible & small:** every increment is independently revertible and gated by Codex review +
  Jorge's decision.

---

## Increment 1 — Read-only command center projection

- **Objective:** a read-only projection of the coordination queue/state, computed from `main`, reusing
  the Reporter's classification logic.
- **Scope:** a read-only data source (library reuse of `scripts/coordination_queue_reporter.py`
  classifier) + a minimal projection surface in Mission Control (Overview + Work Queue lens).
- **No-scope:** no writes; no new state store; no execution; no provider calls; no Reporter behavior
  change (it stays manual/read-only).
- **Estimated modules:** ~2–3 (a read-only projection module reusing the classifier; a Mission Control
  read-only panel; types).
- **Dependencies:** none beyond existing Reporter + Mission Control shell.
- **Definition of Done:** Overview + Work Queue render real classified tasks from `main`; execution-closed
  indicator present; source-of-truth SHA shown; nothing writes to the repo.
- **Tests:** unit tests on the projection/classifier reuse (mirror the 33 Reporter tests' style);
  UI snapshot test that no execution/approve/merge control renders.
- **Risk:** Low. Pure read/projection.
- **Stop condition:** any need to write canonical state, call MSO/Police, or run headless ⇒ stop, report
  as finding.
- **Needs Codex:** Yes (review classification reuse + projection-truth).
- **Needs human decision:** Yes (Jorge authorizes the task + merges).

## Increment 2 — Mission / Work Package viewer

- **Objective:** Mission cards + per-actor status strip + Work Package detail (scope/permissions/forbidden,
  next-transition owner).
- **Scope:** Mission card component, per-actor strip (reuse `MSOInvariantStrip` styling), Work Package
  detail lens; all read-only.
- **No-scope:** no priority schema change (use existing fields unless Jorge authorizes a contract change);
  no execution; no authority writes.
- **Estimated modules:** ~3–4 (Mission card, actor strip, WP detail, types).
- **Dependencies:** Increment 1 (projection).
- **Definition of Done:** every Mission renders status (from `main`), next-transition owner, and links to
  Evidence/Authority lenses; branch-only status labeled "proposed — not effective".
- **Tests:** unit tests for next-owner derivation from `status`; UI tests for projection-truth labels.
- **Risk:** Low–Medium (state-ownership mapping must exactly match `RULES_OF_ENGAGEMENT.md`).
- **Stop condition:** any ambiguity in state ownership ⇒ fail-closed, report.
- **Needs Codex:** Yes. **Needs human decision:** Yes.

## Increment 3 — Evidence and review lens

- **Objective:** render the Evidence Bundle (WORKLOG/FINAL_REPORT/`files_touched`/PR diff link) and the
  Review (`proposed_decision` with `authority: proposed`).
- **Scope:** Evidence lens + Review lens, read-only; honest rendering of unavailable validations.
- **No-scope:** no fabricated results; no writing evidence on an agent's behalf; no merge/approve.
- **Estimated modules:** ~2–3.
- **Dependencies:** Increment 2.
- **Definition of Done:** evidence + review render from `main`; missing/`unavailable` validations shown as
  such; reviewer ≠ executor reflected in display.
- **Tests:** unit tests that a missing FINAL_REPORT renders as "not present", never as pass; review
  authority shown as `proposed`.
- **Risk:** Medium (truthfulness of evidence rendering is safety-critical).
- **Stop condition:** any path that could imply a passing result from a missing artifact ⇒ stop.
- **Needs Codex:** Yes. **Needs human decision:** Yes.

## Increment 4 — Safe draft / preparation flow

- **Objective:** surface existing Draft Store / prepared actions read-only, plus a *safe-prepare*
  affordance that emits a **proposal artifact only**.
- **Scope:** reuse `DraftStorePlansPanel`, `PreparedActionsReviewPanel`, `ConfirmFlowQueuePanel`;
  safe-prepare path produces a draft/proposal, never an execution or canonical-state write.
- **No-scope:** no execution; no `execution_allowed`/`can_execute_now` flip; no confirm-to-execute; no
  authority writes.
- **Estimated modules:** ~2–4.
- **Dependencies:** Increments 1–3; existing prepare/draft backend (unchanged).
- **Definition of Done:** drafts/prepared actions visible read-only; safe-prepare produces only a proposal
  artifact; execution stays closed.
- **Tests:** tests that safe-prepare never sets execution flags and never writes canonical state.
- **Risk:** Medium–High (closest to an execution surface — must stay strictly preparation-only).
- **Stop condition:** any design that lets the UI move toward execution ⇒ stop, escalate to Jorge.
- **Needs Codex:** Yes (high scrutiny). **Needs human decision:** Yes.

## Increment 5 — Provider adapter discovery (NO implementation)

- **Objective:** *discovery only* — document what a real provider channel to Claude/Codex would require,
  without building any adapter.
- **Scope:** a discovery document + read-only display labeling seat/provider data as "metadata, not a
  channel".
- **No-scope:** no adapter, no network calls to providers, no credentials, no real integration; not a
  channel.
- **Estimated modules:** 0 code modules (documentation + label-only UI copy).
- **Dependencies:** Increments 1–2 (to label existing seat/provider panels).
- **Definition of Done:** discovery doc enumerates requirements/risks; UI explicitly labels provider data
  as metadata; no integration code added.
- **Tests:** UI test that provider panels carry the "metadata, not a channel" label.
- **Risk:** Medium (risk of overreach into real integration — explicitly forbidden here).
- **Stop condition:** any move from discovery to implementation ⇒ stop; that is a separate authorization.
- **Needs Codex:** Yes. **Needs human decision:** Yes.

## Increment 6 — Eventual integration (ONLY after separate authorization)

- **Objective:** placeholder for any real integration/execution capability — **explicitly deferred**.
- **Scope:** none in v0. Requires its **own** separate design → review → human-authorization cycle under
  the existing contract, exactly as the Reporter pipeline did (STATE.md §"Next cycle").
- **No-scope:** everything — nothing here is authorized by this backlog.
- **Estimated modules:** N/A (not authorized).
- **Dependencies:** a separate, future authorization decision by Jorge; not implied by any prior
  increment.
- **Definition of Done:** N/A in v0.
- **Tests:** N/A in v0.
- **Risk:** High by nature — gated entirely behind separate authorization.
- **Stop condition:** **default-stop.** Do not begin without a separate `READY` + human decision.
- **Needs Codex:** Yes. **Needs human decision:** Yes (mandatory, separate).

---

## Sequencing summary

```
1 (read-only projection)
   → 2 (mission/WP viewer)
       → 3 (evidence & review lens)
           → 4 (safe draft/preparation)
   5 (provider discovery, no impl) — can run parallel after 1–2, doc-first
   6 (integration) — DEFERRED; separate authorization only
```

**Recommended first code increment:** **Increment 1** — and even that begins as a *new, separately
authorized* task (design/review first), not as work implied by this document.
