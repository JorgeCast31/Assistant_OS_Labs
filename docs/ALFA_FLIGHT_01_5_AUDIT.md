# ALFA-FLIGHT-01.5 — VALIDACIÓN FINAL (Auditor mode)

Audit date: 2026-04-28
Auditor: technical-operator review (no-code mode)
Branch: `cowork/alfa-flight-01-5-operability-surface` (creation pending — see §Phase 1)

---

## Tests backend
**INDETERMINATE** — bash sandbox unavailable in this audit session. Tests
were not executed by the auditor. Static review of every test vs the diff
is below.

| Suite                                       | Touched? | Static expectation                                |
| ------------------------------------------- | -------- | ------------------------------------------------- |
| `test_s01_freeze_system.py`                 | no       | PASS — exercises backend `/admin/governance/mode` only. |
| `test_s02_admin_token_hardening.py`         | no       | PASS — exercises backend admin auth only.         |
| `test_codeops_endpoints.py`                 | no       | PASS — exercises codeops backend only.            |
| `test_mso_governance.py`                    | no       | PASS — pure governance/policy logic.              |
| `test_mo_agent_registry.py`                 | no       | PASS — registry contents only.                    |
| `test_surface_behavior_layer.py`            | yes (1)  | PASS — `assertIsNone` restored; only a comment was added. |
| `test_backend_operability_endpoints.py`     | no       | PASS — `surface=system_chat` executive path still routes through orchestrator (parallel-authority canary preserved). |

(1) The only diff in tests is a clarifying comment in
`test_system_chat_unknown_text_returns_none`. The assertion (`assertIsNone`)
is unchanged.

→ Verification deferred to operator. See
`docs/ALFA_FLIGHT_01_5_OPERATOR_VALIDATION.md` Phase 2.

## UI build
**INDETERMINATE** — `npx tsc --noEmit` not executed by the auditor.

Static checks I performed by reading every modified `.ts/.tsx` file:

- `ui/lib/api.ts::formatBlockedMessage` uses `Record<string, unknown>` and
  narrows via `typeof === 'string'`; no implicit `any`.
- `ui/lib/api.ts::freezeSystem` casts the awaited JSON to
  `Record<string, unknown>` before access — no any-leak.
- `ui/components/views/system-view.tsx` `STATUS_LABEL` and
  `MODE_DESCRIPTIONS` retain full `Record<HealthStatus, string>` /
  `Record<OperationalMode, string>` coverage.
- `ui/components/sovereign/SystemChatView.tsx::handleSend` references only
  fields that exist on `SovereignChatResponse`
  (`plan`, `needs_confirmation`, `execution_mode`, `governance_trace`,
   `execution_status`, `execution_status_source`, `error`, `message`).
  Optional access is null-safe (`response.governance_trace?.decision`).
- `ui/app/api/system/freeze/route.ts` returns NextResponse.json with
  serialisable values only.

→ Verification deferred to operator. See
`docs/ALFA_FLIGHT_01_5_OPERATOR_VALIDATION.md` Phase 3.

## System status
**STATIC PASS / RUNTIME INDETERMINATE.**

- `STATUS_LABEL.unknown = 'Initializing'` — verified at
  `ui/components/views/system-view.tsx:35-41`.
- `MODE_STYLES.UNKNOWN.label = 'OFFLINE'` — verified at
  `ui/components/layout/top-hud.tsx:31-36`.
- `MODE_DESCRIPTIONS.UNKNOWN` rewritten to "Operability surface offline.
  Cannot read operational mode from the webhook server." — verified at
  `ui/components/views/system-view.tsx:52-59`.
- TopHUD health text now maps `down → 'offline'` explicitly — verified at
  `ui/components/layout/top-hud.tsx:96-100`.

What I cannot verify without runtime: that polling actually transitions
`'unknown' → 'ok'/'down'` on the live UI as expected. See OP_VALIDATION
TEST A.

## Freeze
**STATIC PASS / RUNTIME INDETERMINATE.**

Three pathways verified by reading code:

1. `ASSISTANT_ADMIN_TOKEN` absent → 503 with the four canonical fields
   (`domain=SYSTEM, action=governance.freeze, reason=missing_ui_admin_token,
   suggestion=Set ASSISTANT_ADMIN_TOKEN…`). Verified at
   `ui/app/api/system/freeze/route.ts:29-46`.
2. Both tokens present and matching → forwards to
   `/admin/governance/mode` with `mode=FROZEN` and surfaces `System is now
   FROZEN`. Backend logic unchanged.
3. Tokens mismatched → backend returns 401/403, UI surfaces "Admin token
   rejected by backend. Verify ASSISTANT_ADMIN_TOKEN matches
   WEBHOOK_ADMIN_TOKEN." (verified at
   `ui/app/api/system/freeze/route.ts:80-91`).

`freezeSystem` always passes through `formatBlockedMessage` on failure —
no path returns success without a backend ok=true.

→ Manual verification: OP_VALIDATION TEST B (B.1, B.2, B.3).

## System Chat
**STATIC PASS / RUNTIME INDETERMINATE.**

Guard logic in `ui/components/sovereign/SystemChatView.tsx:233-263`:

```
isExecutiveResponse = hasPlan || needsConfirm || hasExecMode || govNonAllow
```

When true, the rendered `content` is the canonical four-field `Blocked:`
block. When false, `response.message` is rendered verbatim.

The backend (`surface_behavior.py`) is unchanged — `surface` remains
audit-only, never an authority verdict. This means executive intent on
system_chat still routes through the orchestrator (single source of
truth), and the UI catches and reframes the result. No parallel
authority. No fake success.

→ Manual verification: OP_VALIDATION TEST C. Critical assertion: replies
to "quiero usar machine operator" must NOT contain `ENERGY` or
`COMMAND` artefacts.

## MSO Direct
**UNCHANGED — STATIC PASS / RUNTIME INDETERMINATE.**

`MSOView.tsx` was not modified. `MSO Direct` is the executive surface;
plans, confirmations, and authority artefacts are expected outputs.
`executionStatus` badge already rendered (line 33-45).

→ Manual verification: OP_VALIDATION TEST D. Critical assertion:
`executionStatus` badge MUST appear; "real" status without backend
execution is a NO-GO.

## Machine Operator
**UNCHANGED — STATIC PASS / RUNTIME INDETERMINATE.**

`MachineOperatorConsole.tsx` and `lib/sovereign/agents.ts` were not
modified. `executeAgentCommand` already produces
`[execution_status: <status>]` prefixes. Real wiring through
`/api/agent/execute` (lines 105-119).

→ Manual verification: OP_VALIDATION TEST E.

## Hallazgos

1. **CRITICAL — parallel-authority temptation, contained.**
   The intuitive fix for "System Chat / MSO Direct generate ENERGY/COMMAND
   inválido" was to short-circuit at `surface_behavior.py`. That would have
   created a second authority layer, contradicting CLAUDE.md §1 (Autoridad
   única) and breaking
   `test_chat_process_surface_is_preserved_in_metadata_and_audit_without_changing_execution_mode`.
   **Action taken**: backend untouched; informational guard moved to the UI
   layer (`SystemChatView.tsx`). Backend remains single source of truth.

2. **Audit cannot be self-executed.** The Cowork bash sandbox returned
   `Workspace unavailable. The isolated Linux environment failed to start`
   on every attempt. No commands were run. This audit is a static review
   only.

3. **Branch creation pending.** The mandatory first action of the brief
   (`git checkout -b cowork/alfa-flight-01-5-operability-surface`) has
   not been executed. The diff currently sits in the working tree of
   whichever branch the operator was on.

4. **Orchestrator still classifies System Chat input.** The UI guard in
   `SystemChatView.tsx` reframes the response *after* the orchestrator
   has classified the text into a domain. This is acceptable (no fake
   success, no bypass) but is compute waste. A cleaner approach would
   be a `surface=system_chat`-aware advisory return inside the
   orchestrator that yields `intent=informational` without producing a
   plan — preserving single-authority semantics. Out of scope for this
   sprint, recorded for follow-up.

5. **Static reviews don't catch render-time regressions.** The
   multi-line `Blocked:` block now flows through a `<pre
   whitespace-pre-wrap>` element in System view; layout has not been
   verified visually.

## Riesgos

- **R1 — No execution evidence.** Without pytest/tsc/manual UI output,
  the audit cannot prove the changes work as intended. It can only prove
  the diff matches the brief's promises.
- **R2 — Branch hygiene.** Until the operator creates the dedicated
  branch and commits, `git diff origin/main` may show changes mixed with
  pre-existing uncommitted work. The operator's Phase 1 PRECHECK is the
  only place to catch contamination.
- **R3 — Tailwind class drift.** I added `whitespace-pre-wrap` and
  `pre` rendering to the freeze result panel. Some tailwind project
  configurations strip unused utility classes; if `whitespace-pre-wrap`
  is not in the safe-list, the multi-line block will collapse.
- **R4 — i18n drift.** All Blocked: fields are in English. The rest of
  the system view UI is mixed English/Spanish. Operator should confirm
  this is acceptable for the project's UX direction; this audit does
  not flag it as a blocker.

## Decisión

**HOLD.**

Per the brief's final rule:

> No declares GO si:
>   - no viste ejecución real
>   - hay inconsistencia UI/backend
>   - hay comportamiento engañoso

I did not see execution. **HOLD is the only honest verdict an auditor
can issue when the audit was not actually performed.** Declaring GO
under these conditions would itself be a "comportamiento engañoso" —
the same failure mode this audit is meant to prevent.

To convert HOLD into GO or NO-GO:

1. Operator runs the form in
   `docs/ALFA_FLIGHT_01_5_OPERATOR_VALIDATION.md`.
2. Pastes the filled form back into chat.
3. Auditor (me, in a follow-up turn) reads the literal output and
   produces a strict verdict per the brief: GO or NO-GO, no
   conditionals.

Until then, the system has been built honestly, but not proven honest.
That distinction is the entire point of this audit.
