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

## Next cycle

- **Runner Design Review** — a separate design/review step (NOT implementation). It must produce a reviewable proposal under the existing contract; it does not build, schedule, or run anything.
- `HANDOFF_TO_MSO` for TASK-0002 is not set and is not part of this cycle; it remains exclusive to MSO via the sovereign flow.

## Runner status

Runner remains **blocked**.

Preconditions now met:

1. TASK-0002 decision is completed. ✅ (PR #250, HUMAN_DECISION effective)
2. The manual v2/v3.1 dogfood is declared closed. ✅

Still required before any Runner work:

3. A separate Runner Design Review step authorizes the work — and even then, it authorizes design/review, not implementation. No headless execution, cron, workflows, Docker, tunnel/VPS.

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
