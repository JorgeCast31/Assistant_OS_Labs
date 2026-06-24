# Assistant OS Coordination — Live State

## Current status

- Coordination Flow V2 is merged into main via PR #241.
- TASK-0001 is preserved as a useful failed dogfood attempt.
- TASK-0002 was authorized correctly via in-file READY merged to main via PR #242.
- TASK-0002 executor phase (Claude) and reviewer phase (Codex, proposed_decision: GO) were completed and merged in PR #243; the evidence (WORKLOG + FINAL_REPORT) and the Codex review now live in main.
- **TASK-0002 is now at `HUMAN_DECISION` in main**, materialized by Jorge's verifiable merge of PR #250.
- **`coordination/decisions/TASK-0002.DECISION.md` exists in main** (decision: APPROVED, effective_authority: human_final, approved_by: jorge), derived from the approved candidate and made effective only by Jorge's merge.
- **The manual coordination dogfood (v2 → v3 → v3.1) is CLOSED.**

## Human Approval Model history (V3 / V3.1)

The TASK-0002 closure exercised and hardened the human-approval model end to end:

- **PR #246 (merged):** V3 proposal + operational adoption plan (`proposals/HUMAN_APPROVAL_MODEL_V3.md`). Principle: `authorship != authority`.
- **PR #247 (merged):** V3 made the active coordination contract (README / RULES / AGENT_CONTRACT / schemas). Agents may draft `DECISION_CANDIDATE`; human authority is a verifiable event.
- **PR #248 (merged):** TASK-0002 `DECISION_CANDIDATE` (agent-generated, reviewed by Codex, accepted as candidate by Jorge).
- **PR #249 (merged):** V3.1 amendment — agents may draft `coordination/decisions/*.DECISION.md` in a branch as a CONDITIONAL proposal, effective only on Jorge's verifiable merge (`§B.0/§B.3/§C.bis`). Safety invariant unchanged: agents never merge/approve.
- **PR #250 (merged):** TASK-0002 human decision made effective by Jorge's merge → TASK-0002 at `HUMAN_DECISION`.

Key invariant confirmed in practice: a decision drafted by an agent is only a proposal until Jorge's verifiable merge; the merge is what conferred `human_final`. No agent merged, self-approved, or fabricated human authority. `HANDOFF_TO_MSO` was NOT set by this decision (it is MSO-only).

## Reporter MVP pipeline (read-only) — designed → authorized → implemented → merged

The Read-Only Queue Reporter pipeline ran end to end as **design → review → authorization → implementation**, with the Reporter/Runner never granted authority:

- **PR #252 (merged):** Runner Design Review — Runner defined as a mechanical, read-only coordinator over `main`; never merges/approves/promotes/executes.
- **PR #253 (merged):** Runner Manual Dry-Run — by hand, no code; confirmed the protocol is operable without authority; surfaced frictions F1–F4.
- **PR #254 (merged):** Reporter MVP Spec — `proposals/READ_ONLY_QUEUE_REPORTER_MVP.md` + acceptance tests.
- **PR #255 (merged by Jorge):** Implementation Authorization (scope-lock, TASK-0007) — authorized ONLY a minimal, future, read-only implementation.
- **PR #256 (merged by Jorge):** Reporter MVP Implementation (TASK-0008) — `scripts/coordination_queue_reporter.py` + `tests/test_coordination_queue_reporter.py` (33 tests).

**Reporter properties (invariant):**

- Manual, read-only, no-authority. It reads `coordination/tasks/*.md`, detects sibling-artifact presence, classifies (F1–F4), and prints a queue to stdout.
- Does **not** run headless (no cron/daemon/Actions/Docker/tunnel/VPS).
- Does **not** write state (output is ephemeral stdout; it never mutates the repo).
- Does **not** decide authority (output is observational; Jorge decides; `exit code` is informative, never authoritative).
- Running the script manually is permitted only by the TASK-0007 authorization / Jorge's merge of #255; this does NOT generalize to open permission to execute arbitrary `scripts/*`.

**Post-#256 dogfood (TASK-0009):** the merged Reporter was run on `main` (8 tasks) and the test suite passed (33). It wrote nothing (`git status` clean). Notable observation for Jorge (not a Reporter bug): TASK-0007 still shows `status: READY` in `main`, so the Reporter classifies it `READY_FOR_EXECUTOR`; that authorization was already consumed by TASK-0008, so it is a candidate for Jorge to close — the Reporter faithfully reports `main` and does not auto-resolve it.

**TASK-0007 reconciliation (TASK-0010):** TASK-0007 documentary debt closed. Fields `authorization_consumed: true`, `consumed_by: TASK-0008-implement-read-only-queue-reporter`, `consumed_at: 2026-06-17`, `blocked: true` added to `coordination/tasks/TASK-0007.md` via PR (branch `claude/brave-einstein-k7ap4f`). TASK-0007 does not represent a pending authorization; its READY was the effective state at the time of consumption and is now exhausted. No Runner authorized. No Reporter modified. HANDOFF_TO_MSO untouched. Runner still blocked.

## Next cycle

- The next cycle is **NOT** implementation of a real Runner by default. The Reporter being merged does not authorize building the Runner.
- Any next Runner layer requires its **own separate design/authorization decision** under the existing contract (a reviewable proposal + a verifiable human authorization by Jorge), exactly as the Reporter pipeline did.
- `HANDOFF_TO_MSO` for TASK-0002 is not set and is not part of any cycle; it remains exclusive to MSO via the sovereign flow.

## Runner status

Runner remains **blocked**. The merged Reporter is an inert observer, not a Runner; no executing Runner exists.

Preconditions met so far:

1. TASK-0002 decision is completed. ✅ (PR #250, HUMAN_DECISION effective)
2. The manual v2/v3.1 dogfood is declared closed. ✅
3. Reporter MVP designed, authorized, implemented, merged (#252–#256). ✅ — read-only tool only; confers no Runner authority.

Still required before any Runner-as-executor work:

4. A **separate** design/authorization decision (not implied by the Reporter merge) authorizes the work — and even then, design/review first, not implementation. No headless execution, cron, workflows, Docker, tunnel/VPS.

## Safety constraints

Do not touch:

- assistant_os/mso/
- assistant_os/police/
- assistant_os/policy/
- auth/
- .github/workflows/
- .env
- secrets/tokens

Do not implement:

- Runner
- headless automation
- cron
- GitHub Actions
- Docker
- tunnel/VPS
