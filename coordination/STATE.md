# Assistant OS Coordination — Live State

## Current status

- Coordination Flow V2 is merged into main via PR #241.
- TASK-0001 is preserved as a useful failed dogfood attempt.
- TASK-0002 was authorized correctly via in-file READY merged to main via PR #242.
- TASK-0002 executor phase was completed by Claude in PR #243.
- TASK-0002 reviewer phase was completed by Codex in PR #243 with proposed_decision: GO.
- PR #243 has already been merged into main, so the executor evidence (WORKLOG + FINAL_REPORT) and the Codex review (coordination/reviews/TASK-0002.REVIEW.md) now live in main.
- TASK-0002 is currently at DECISION_PROPOSED in main (status: DECISION_PROPOSED, proposed_decision: GO, authority: proposed).
- Human decision is still pending: no coordination/decisions/TASK-0002.DECISION.md exists yet (the decisions/ folder only contains .gitkeep).

## Pending contractual step

Create a minimal human decision PR:

- add coordination/decisions/TASK-0002.DECISION.md
- update coordination/tasks/TASK-0002.md to HUMAN_DECISION
- do not touch anything outside coordination/
- Jorge must merge it

## Runner status

Runner remains blocked.

Runner may only be considered after:

1. TASK-0002 decision is completed.
2. The manual v2 dogfood is declared closed.
3. A separate design/review step authorizes Runner work.

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
