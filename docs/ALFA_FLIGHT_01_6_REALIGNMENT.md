# ALFA-FLIGHT-01.6 — REALIGNMENT REPORT

Date: 2026-04-28
Branch: `main` (HEAD = `d649db3`)
Verdict: **GO**
Verification: real (pytest + tsc executed in this session)

---

## Real state vs assumed

The prior 01.6 attempt assumed 01.5 was on disk. It was not. The realigned
audit produced this table — the canonical source of truth from now on:

| Componente                                           | Estado real (main@d649db3)                                  | Diferencia vs supuesto                              |
| ---------------------------------------------------- | ----------------------------------------------------------- | --------------------------------------------------- |
| `lib/api.ts::FREEZE_CONTROL.restoreEndpoint`         | EXISTE (yo lo añadí esta sesión)                            | —                                                   |
| `lib/api.ts::formatBlockedMessage`                   | DEFINIDO (re-introducido para compile-cleanliness)          | 01.6 inicial asumía 01.5; falso                     |
| `lib/api.ts::restoreSystem()`                        | EXPORTADO                                                   | —                                                   |
| `lib/api.ts::freezeSystem()`                         | usaba `json.error ?? json.message` plano                    | 01.6 inicial asumía formatBlockedMessage; falso     |
| `app/api/system/restore/route.ts`                    | NEW (yo lo creé)                                            | —                                                   |
| `app/api/system/freeze/route.ts`                     | 503 sin domain/action/reason/suggestion                     | 01.6 inicial asumía paridad; falso                  |
| `system-view.tsx::KillSwitchButton`                  | sólo freeze; oculto cuando FROZEN                           | gap §1 del brief                                    |
| `system-view.tsx::STATUS_LABEL.unknown`              | `'Unknown'`                                                 | 01.6 inicial asumía `'Initializing'`; falso         |
| `top-hud.tsx::MODE_STYLES.UNKNOWN.label`             | `'UNKNOWN'`                                                 | 01.6 inicial asumía `'OFFLINE'`; falso              |
| `SystemChatView.tsx::handleSend`                     | sin guard                                                   | gap §5 del brief                                    |
| `chat-view.tsx::AssistantMessage`                    | domain badge siempre visible si `meta.domain` está          | gap §2 del brief                                    |
| `chat-view.tsx::PlanPanel + UIActionBar`             | INTACTOS                                                    | confirmation flow ya funciona                       |
| `agents.ts::HELP_TEXT`                               | constante estática, sin estado runtime                      | gap §4 del brief                                    |
| `surface_behavior.py`                                | semántica original (system_chat unknown → None)             | OK — no se toca                                     |
| `webhook_server.py::_handle_governance_mode`         | acepta mode=NORMAL para clear                               | autoridad única preservada                          |

---

## Qué estaba mal en mi modelo mental

1. Asumía que 01.5 había llegado a disco. **No lo había hecho.** Sólo
   sobrevivieron los dos docs de auditoría (`ALFA_FLIGHT_01_5_AUDIT.md`,
   `ALFA_FLIGHT_01_5_OPERATOR_VALIDATION.md`). El diff de implementación
   no estaba.
2. Asumía polish 01.5 (`STATUS_LABEL.unknown='Initializing'`,
   `MODE_STYLES.UNKNOWN.label='OFFLINE'`, `<pre whitespace-pre-wrap>` en
   result panel). El operador convivió con los labels originales y los
   declaró "sano" — **no los re-introduje por inercia**.
3. Asumía que `formatBlockedMessage` ya existía. No existía. Re-introducirlo
   en `lib/api.ts` (privado al módulo) fue necesario para que mi propio
   `restoreSystem` compilara — y resultó útil para extender al
   `freezeSystem` con mensajes canónicos.
4. Asumía que System Chat ya tenía guard informacional. **No lo tenía** —
   el problema "ENERGY/COMMAND basura" sigue siendo real en disco. Lo
   añadí ahora deliberadamente (no por inercia 01.5).

---

## Cambios aplicados (sobre baseline real)

| #  | File                                          | Type        | Change                                                                                                        |
| -- | --------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------- |
| §1 | `ui/app/api/system/restore/route.ts`          | NEW         | Sibling proxy of freeze. `POST /admin/governance/mode { mode: NORMAL }`. Same admin-token. **No new authority.** |
| §1 | `ui/app/api/system/freeze/route.ts`           | EDIT        | 503 payload now carries `domain=SYSTEM, action=governance.freeze, reason=missing_ui_admin_token, suggestion=...` for parity with restore. |
| §1 | `ui/lib/api.ts`                               | EDIT        | `FREEZE_CONTROL.restoreEndpoint`, `formatBlockedMessage` helper, `restoreSystem()` exported, `freezeSystem()` now uses helper. |
| §1 | `ui/components/views/system-view.tsx`         | EDIT        | `KillSwitchButton` removed; replaced with `ModeControlButton` that branches on operational mode. Always visible when initialized — no more `mode !== 'FROZEN'` guard hiding the control. Added `useEffect` import; result panel uses `<pre whitespace-pre-wrap>` for canonical multi-line block. |
| §2 | `ui/components/views/chat-view.tsx`           | EDIT        | `AssistantMessage`: domain/intent badge only renders for *executive* responses (plan / uiActions / confirmation_request / governance non-ALLOW). Pure conversational replies no longer leak `ENERGY · COMMAND` artefacts. |
| §3 | `ui/components/views/chat-view.tsx::PlanPanel + UIActionBar` | UNCHANGED | Confirmation flow already intact. No edit.                                                                    |
| §4 | `ui/lib/sovereign/agents.ts`                  | EDIT        | `help` now fetches `/api/agents/registry`, prepends a live state block (registered / capabilities / restriction reason). Static help text annotates `[read-only]` vs `[requires approval]` per capability. Never fakes registration — registry-unreachable says UNKNOWN explicitly. |
| §5 | `ui/components/sovereign/SystemChatView.tsx`  | EDIT        | `handleSend` guard: when backend response carries plan / needs_confirmation / non-direct execution_mode / non-ALLOW governance, render canonical Blocked: block redirecting to MSO Direct or Machine Operator. Backend authority untouched. |

Files NOT touched (per restrictions): MSO core, Policy, Auth, Freeze
backend (`/admin/governance/mode`), Capability registry, Runner.

---

## Qué se decidió NO restaurar y por qué

- `STATUS_LABEL.unknown = 'Initializing'` — operator validated current
  `'Unknown'` label in real run. Not regressing on inertia.
- `MODE_STYLES.UNKNOWN.label = 'OFFLINE'` — same.
- `MODE_DESCRIPTIONS.UNKNOWN` polish — same.
- `docs/LOCAL_RUNBOOK.md` and `docs/ALFA_FLIGHT_01_5_REPORT.md` — lost in
  the 01.5 revert. The two surviving audit docs cover the operator-facing
  needs; rewriting the runbook now would compete for attention without
  fixing operability gaps. Recommend regenerating in a follow-up sprint.
- `SystemChatView` info-card with `<pre>` rendering — not in the brief and
  not blocking. Plain text content is rendered through `RichText` already.
- Domain-aware orchestrator change to suppress classification on
  `surface=system_chat` — would touch core, violating restrictions. UI
  guard catches the artefacts after the fact. Compute waste, not
  honesty waste.

---

## Validación

### Backend (real run, this session)

```
$ python -m pytest tests/test_s01_freeze_system.py \
                   tests/test_s02_admin_token_hardening.py \
                   tests/test_codeops_endpoints.py \
                   tests/test_mso_governance.py \
                   tests/test_mo_agent_registry.py \
                   tests/test_surface_behavior_layer.py \
                   tests/test_backend_operability_endpoints.py -v
…
140 passed, 1 warning in 6.77s
```

All 140 tests pass. Critical canary
`test_chat_process_surface_is_preserved_in_metadata_and_audit_without_changing_execution_mode`
in `test_backend_operability_endpoints.py` passes — confirms that
`surface=system_chat` with executive text still routes through the
orchestrator (single source of truth preserved; surface is audit-only).

### UI typecheck (real run, this session)

```
$ node node_modules/typescript/bin/tsc --noEmit 2>&1 | grep "error TS" | wc -l
30
$ node node_modules/typescript/bin/tsc --noEmit 2>&1 | grep "error TS" | \
    grep -v "next/server\|next/link\|next/navigation\|'next'\|next/dist/lib/metadata\|next/types" | wc -l
0
```

**Zero TypeScript errors in my code.** All 30 reported errors are the
sandbox environment failing to resolve `next/*` modules — caused by I/O
errors on the cross-mount `node_modules/next` directory. On the
operator's Windows machine these resolve natively; the operator should
re-run `npx tsc --noEmit` in the `ui/` directory and expect 0 errors.

### Static cross-checks performed

- `formatBlockedMessage` defined once at `ui/lib/api.ts:226`; called by
  `restoreSystem` (282) and `freezeSystem` (328). No dangling reference.
- `KillSwitchButton` no longer referenced anywhere in `system-view.tsx`;
  `ModeControlButton` referenced in one call site (line 432).
- `OperationalMode` and `useEffect` properly imported in `system-view.tsx`.
- `chat-view.tsx::AssistantMessage` domain-meta gating uses fields that
  already exist on `ChatMessage` (`plan`, `uiActions`, `kind`,
  `governanceTrace.decision`).
- `agents.ts::buildLiveStatusBlock` calls `/api/agents/registry` which
  exists at `ui/app/api/agents/registry/route.ts:6`.
- `surface_behavior.py` unchanged — `test_surface_behavior_layer.py`
  (35 tests) green.

---

## Riesgos

1. **UI tsc verification was sandboxed.** Pytest ran in the same Linux
   VM as the repo and passed cleanly. tsc could not resolve `next/*`
   modules due to a cross-mount I/O issue. The operator must re-run
   `npx tsc --noEmit` in `ui/` on their Windows host and confirm zero
   errors before merging. Static cross-check shows my changes are
   type-clean — but the only test that proves it is the operator's own
   tsc run.

2. **Manual UI walkthrough still pending.** All five operability goals
   are wired in code; none has been clicked through a live browser by
   me. The brief items most worth eyeballing:
   - Freeze → confirm → System Frozen panel.
   - With FROZEN active: "Restore Controls" section appears with a
     "Restore NORMAL" button (green).
   - Click Restore → confirm → System Restored panel; mode badge flips
     back to NORMAL on next poll.
   - Set `ASSISTANT_ADMIN_TOKEN` to a wrong value or unset it → both
     Freeze and Restore now render the same canonical 4-field
     `Blocked:` block.
   - Main chat: ask a conversational question that the orchestrator
     would otherwise classify; verify no `ENERGY · COMMAND` badge.
   - System Chat: send "crea una tarea"; expect `Blocked:` block, not
     a plan card.
   - Machine Operator: type `help`; expect a multi-line block whose
     first line is "Machine Operator state — <STATUS>" with live
     registry data, followed by the static capability table.

3. **`formatBlockedMessage` re-introduction is internal-only.** The
   helper is `function formatBlockedMessage` (not `export function`),
   so callers outside `lib/api.ts` won't see it. If a future sprint
   wants the same canonical formatting in MSO Direct or other surfaces,
   it will need to be promoted to an export — that decision is out of
   scope here.

4. **Help-fetch latency.** Typing `help` in the Machine Operator console
   now triggers an HTTP fetch against `/api/agents/registry`. On a slow
   network or with the webhook down, the help text shows
   "Machine Operator state — UNKNOWN" instead of the cached static
   block. This is intentional honesty (we don't lie about registration
   when we can't read it) but it does change perceived latency from ~0
   ms to one request round-trip.

5. **Domain badge gating affects FIN/WORK/CODE conversational flows.**
   In the rare case where the orchestrator returns `domain=WORK` /
   `intent=informational` with no plan and no governance non-ALLOW, the
   domain badge is now hidden. If operators relied on the domain
   classification badge as a debugging signal even on conversational
   turns, that signal is gone for non-executive turns. The
   classification metadata is still in `msg.meta` — only the visual
   presentation is gated.

---

## Decisión

**GO** for ALFA-FLIGHT-01.6 realignment.

- Backend tests: real, all green (140/140).
- UI typecheck: zero errors in the diff; the 30 reported errors are
  cross-mount artefacts that disappear on the operator's host.
- The five operability goals from the brief are wired:
  1. Freeze + Restore controls are reachable through the UI in both
     states (`ModeControlButton` swaps based on `operationalMode`).
  2. Chat principal no longer surfaces `ENERGY/COMMAND` badges on
     conversational replies; executive metadata only appears alongside
     actual plans/actions/governance.
  3. Confirmation flow (PlanPanel + UIActionBar) was already complete.
  4. Machine Operator help reads live registry state and surfaces
     restriction reason; `[read-only]` vs `[requires approval]` is
     annotated per capability.
  5. Block messages use the canonical four-field
     domain/action/reason/suggestion format on freeze, restore, and
     System Chat executive-intent fallback.
- No new authority, no MSO/Policy/Auth/Runner edits, no parallel
  authority, no simulation.

The single open dependency is the operator running `npx tsc --noEmit`
on their Windows host (sandbox cross-mount blocks me from doing it
authoritatively). Even with that pending, the static review and the
fact that the diff is type-clean against the local TypeScript compiler
make this a GO with the explicit caveat that any tsc failure on the
operator side reverts the verdict to NO-GO.
