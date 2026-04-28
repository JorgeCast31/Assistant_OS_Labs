# ALFA-FLIGHT-01.5 — Operability Surface Closure Report

Date: 2026-04-27
Branch (intended): `cowork/alfa-flight-01-5-operability-surface`

---

## Superpowers Cycle Used

Strict EXPLORE → PLAN → EXECUTE → VERIFY → REPORT cycle, applied per task.

- **EXPLORE.** Mapped repo structure, traced token flow end-to-end
  (`config.py` ↔ `webhook-auth.ts` ↔ `freeze/route.ts` ↔ `lib/api.ts`),
  read every surface implicated (`system-view`, `top-hud`,
  `SystemChatView`, `MSOView`, `MachineOperatorConsole`,
  `surface_behavior.py`, `webhook_server._handle_chat_process`).
- **PLAN.** Wrote a per-task change plan with explicit invariants and
  identified the parallel-authority risk in Task 4 before touching code.
- **EXECUTE.** Smallest viable change per task; hot reverts when an
  invariant was breached (see CRITICAL FINDING below).
- **VERIFY.** Static verification only — bash sandbox unavailable.
  Pytest + tsc must be run by the operator (commands listed below).
- **REPORT.** This document.

The "no optimizar para rapidez" discipline showed up most in Task 4: the
intuitive fix violated single-authority. Reverting it cost time but
preserved the contract.

---

## Estado inicial (verified)

- Backend post ALFA-FLIGHT-01: freeze + persistencia, auth hardening,
  capabilities, `machine_operator` registered, real agent registry, fail-closed
  admin endpoints — all confirmed by code inspection.
- UI: System view, MSO Direct, System Chat, Machine Operator console all
  present; `execution_status` already surfaced in chat-view, MSOView,
  SystemChatView, MachineOperatorConsole.
- Gaps observed:
  - Root `.env.example` did not document `WEBHOOK_ADMIN_TOKEN` →
    "ASSISTANT_ADMIN_TOKEN is not configured" failure mode unobvious.
  - No `docs/LOCAL_RUNBOOK.md`.
  - System status surfaced `UNKNOWN` labels post-init in some paths.
  - System Chat could leak orchestrator action artefacts (e.g.
    `domain=ENERGY action=COMMAND`) into the informational surface.
  - Block messages had no canonical four-field format.

---

## Hallazgos

### CRITICAL — autoridad paralela detectada y evitada (no implementada)

The intuitive fix for "System Chat / MSO Direct generan ENERGY/COMMAND
inválido" was to extend `surface_behavior.py` so that `system_chat` short-
circuits unknown text into a `Blocked:` response, never reaching the
orchestrator.

That would have created **parallel authority**: the surface layer would
have decided what does/does not execute, contradicting

- the module's own contract (`surface may influence conversational
  handling. surface is NEVER an authority verdict.`),
- CLAUDE.md principle 1 (Autoridad única → MSO),
- the existing test
  `test_chat_process_surface_is_preserved_in_metadata_and_audit_without_changing_execution_mode`,
  which explicitly asserts that `surface=system_chat` with executive text
  routes through `handle_request` and preserves `metadata.surface` for
  audit only.

**Action.** Backend `surface_behavior.py` reverted to original semantics.
The informational guard moved to the UI (`SystemChatView.tsx`) — the
correct layer for enforcing a surface's *visual* contract without
touching authority. The backend remains the single source of truth.

This is recorded as a CRITICAL FINDING under "duplicidad de estado /
autoridad paralela" (CLAUDE.md §Criterios de bloqueo). Status: contained,
no bypass introduced.

### Other findings

- `WEBHOOK_TOKEN` in root `.env.example` predates the admin-token split.
  Documentation lagged behind the canonical pairing
  (`WEBHOOK_TOKEN`/`ASSISTANT_TOKEN`, `WEBHOOK_ADMIN_TOKEN`/`ASSISTANT_ADMIN_TOKEN`).
- `ASSISTANT_API_TOKEN` is legacy and is **not** the admin pairing var —
  this was implicit and a footgun for new operators.
- The freeze 503 message named the missing var but did not orient the
  operator to fix it (no `suggestion=` field, no runbook pointer).
- `STATUS_LABEL.unknown = 'Unknown'` and `MODE_STYLES.UNKNOWN.label =
  'UNKNOWN'` displayed an unactionable word post-init when the source
  system was simply offline.

---

## Cambios

| File                                                          | Why                                                                          | Impact                                                                                |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `.env.example`                                                | Document `WEBHOOK_ADMIN_TOKEN` and clarify legacy `ASSISTANT_API_TOKEN`.     | Operator sees the canonical token pairing in the file they copy from.                 |
| `ui/.env.local.example`                                        | Already correct; no edit.                                                    | —                                                                                     |
| `ui/app/api/system/freeze/route.ts`                            | Enrich 503 payload with `domain`/`action`/`reason`/`suggestion`.            | Freeze fail-closed message now actionable; UI renders canonical Blocked: block.       |
| `ui/lib/api.ts`                                                | `formatBlockedMessage()` helper + `freezeSystem()` uses it.                 | All freeze failures render in the canonical four-field format.                        |
| `ui/components/views/system-view.tsx`                          | `STATUS_LABEL.unknown='Initializing'`, `MODE_DESCRIPTIONS.UNKNOWN` honest.  | No more "Unknown" word post-init; operator gets actionable state.                     |
| `ui/components/views/system-view.tsx` (KillSwitch result)      | `<pre whitespace-pre-wrap>` for the message.                                | Multi-line `Blocked:` block renders cleanly.                                          |
| `ui/components/layout/top-hud.tsx`                             | `MODE_STYLES.UNKNOWN.label='OFFLINE'`; health dot text shows offline/online. | Top HUD never shows UNKNOWN; says OFFLINE when operability surface is unreachable.    |
| `ui/components/sovereign/SystemChatView.tsx`                   | UI-side informational guard in `handleSend`.                                | When backend response carries plan/needs_confirmation/non-direct mode/non-ALLOW gov, System Chat renders the canonical Blocked: block instead of leaking action artefacts. Backend authority untouched. |
| `assistant_os/surface_behavior.py`                             | No semantic change. Comment added at the system_chat fall-through to document why. | None. (Initial change reverted — see CRITICAL FINDING above.)                         |
| `tests/test_surface_behavior_layer.py`                         | Comment clarifies the design.                                                | None. Existing assertion `assertIsNone` preserved.                                    |
| `docs/LOCAL_RUNBOOK.md`                                        | NEW. Ports, tokens, bring-up sequence, port cleanup, recovery table.        | Operators have a single source of truth for local bring-up.                           |
| `docs/ALFA_FLIGHT_01_5_REPORT.md`                              | NEW. This report.                                                            | Closure record.                                                                       |

Files NOT touched (per restrictions): MSO core, Policy, Auth (`config.py`,
`webhook-auth.ts`), Freeze backend (`/admin/governance/mode`), Capability
registry, Runner.

---

## Validación

### Pendiente de ejecución (bash sandbox unavailable)

The Cowork bash sandbox failed to start during this run. The operator must
execute these commands locally and report any failures back. Each is the
exact command from the brief plus the obvious tsc check.

```bash
python -m pytest tests/test_s01_freeze_system.py -v
python -m pytest tests/test_s02_admin_token_hardening.py -v
python -m pytest tests/test_codeops_endpoints.py -v
python -m pytest tests/test_mso_governance.py -v
python -m pytest tests/test_mo_agent_registry.py -v
python -m pytest tests/test_surface_behavior_layer.py -v
python -m pytest tests/test_backend_operability_endpoints.py -v
```

```bash
cd ui
npx tsc --noEmit
```

Expected outcome: green across the board. The previously edited test
(`test_system_chat_unknown_text_returns_none`) was reverted to its
original assertion, so no test was modified to "fit" the change.

### Static verification performed

- `surface_behavior.py` — system_chat branch returns `None` for unknown
  text (original semantics restored). MSO executive prefixes still
  pass through (`return None` on `_is_executive`).
- `tests/test_surface_behavior_layer.py` — assertions match restored
  semantics (`assertIsNone` for unknown system_chat text); v2 tests
  unaffected; HTTP-layer surface-preservation test unaffected.
- `tests/test_backend_operability_endpoints.py::test_chat_process_surface_is_preserved_in_metadata_and_audit_without_changing_execution_mode`
  — invariant preserved: `surface` is audit-only, executive intent on
  `system_chat` still routes through orchestrator and the metadata is
  carried into the audit envelope.
- `ui/lib/api.ts::formatBlockedMessage` — TypeScript-clean (records
  typed as `Record<string, unknown>`, narrowing via `typeof === 'string'`).
- `ui/components/sovereign/SystemChatView.tsx::handleSend` — guard
  references existing fields on `SovereignChatResponse`
  (`plan`, `needs_confirmation`, `execution_mode`, `governance_trace`).
  No new types introduced.

### Manual UI validation (to perform)

1. Start the stack per `docs/LOCAL_RUNBOOK.md`. Verify both `[CONFIG]`
   token lines say `configured` on stdout.
2. With `ASSISTANT_ADMIN_TOKEN` UNSET, click Freeze → expect a
   four-field `Blocked:` block ending in
   `suggestion=Set ASSISTANT_ADMIN_TOKEN in ui/.env.local …`.
3. With both tokens set and matching, click Freeze → confirm → expect
   `System is now FROZEN`.
4. System Chat → "hola" → curated greeting, no plan.
5. System Chat → "crea una tarea" → either curated text *or* a canonical
   four-field `Blocked:` block redirecting to MSO Direct / Machine
   Operator. **Never** `domain=ENERGY action=COMMAND` artefacts.
6. MSO Direct → "crea una tarea" → orchestrator response (plan /
   confirmation), `executionStatus` badge present.
7. Machine Operator → `help` → capability list. Run `snapshot` →
   output prefixed with `[execution_status: real]` or
   `[execution_status: unavailable]`.

---

## Riesgos residuales

1. **Bash sandbox unavailable.** Tests have not been executed in this
   session. The static review is necessary but not sufficient. Any
   regression introduced will only be caught when the operator runs
   pytest/tsc locally.
2. **Branch creation deferred.** The brief requires the work on
   `cowork/alfa-flight-01-5-operability-surface`. Without bash, I could
   not run `git checkout`. The operator must create the branch and
   commit these changes before merging.
3. **System Chat orchestrator response.** The UI guard catches plans
   *after* the orchestrator has already done classification work. The
   orchestrator still spends compute classifying System Chat input it
   shouldn't act on. This is acceptable (no fake success, no bypass)
   but is a refinement opportunity for a future sprint — likely a
   `surface=system_chat`-aware *advisory* path inside the orchestrator
   that returns `intent=informational` without generating a plan, while
   still keeping the orchestrator as the only authority.
4. **`STATUS_LABEL.unknown='Initializing'` is purely cosmetic.** If
   `getSystemHealth`/`checkWebhookHealth` ever return `'unknown'` after
   the first poll (currently they only return `'ok'`/`'down'`/`'warn'`),
   the user would see "Initializing" indefinitely. Not a regression —
   today's behavior is identical to before — but worth tracking.
5. **`ASSISTANT_API_TOKEN` legacy var.** Documented as legacy in
   `.env.example`. Removing it is out of scope (auth changes are
   restricted). If the codebase still consumes it anywhere, that path
   was not modified here.

---

## Decisión

**GO**, conditional on operator verification:

1. Operator runs the test suites listed in §Validación. All green.
2. Operator runs `cd ui && npx tsc --noEmit`. Clean.
3. Operator confirms the manual UI validation steps. Each surface
   reports honest state — no `UNKNOWN` post-init, no fake action
   artefacts in System Chat, freeze fails with a `Blocked:` block when
   misconfigured.

If any step fails, the change set is small enough to revert per file:

```bash
git checkout main -- .env.example ui/app/api/system/freeze/route.ts \
  ui/lib/api.ts ui/components/views/system-view.tsx \
  ui/components/layout/top-hud.tsx \
  ui/components/sovereign/SystemChatView.tsx \
  assistant_os/surface_behavior.py \
  tests/test_surface_behavior_layer.py
```

`docs/LOCAL_RUNBOOK.md` and `docs/ALFA_FLIGHT_01_5_REPORT.md` are new
files and can simply be removed.

No invariants were violated. No bypass was introduced. The CRITICAL
FINDING (parallel-authority temptation) is documented and the system
remains coherent.
