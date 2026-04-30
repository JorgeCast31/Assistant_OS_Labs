# OPERABILITY CLOSURE REPORT — ALFA-FLIGHT-02

Date: 2026-04-29
Baseline: `main@d649db3`
Verdict: **GO**
Verification: real (pytest + tsc executed in this session)

---

## Problemas encontrados (operability gaps)

| Surface | Problema | Impacto operativo | Solución mínima |
| ------- | -------- | ----------------- | --------------- |
| System Chat | Guard 01.6 mostraba texto Blocked: pero **sin action buttons** | "Switch to MSO Direct" requería navegación manual; intent perdido entre superficies | RedirectActions chips clickeables que cambian view + pre-cargan texto |
| chat-view | Error path mostraba `errMsg` plano | Webhook caído → "Webhook server unavailable" sin siguiente paso | Aplicar `formatBlockedMessage` con domain/action/reason/suggestion + RedirectActions |
| chat-view | Fallback `'(sin respuesta)'` cuando `res.message` ausente | Silencio operativo | Sustituir por bloque canónico orientado a redirect |
| MSOView | `${response.error}` plano en handleSend y handleConfirm | Sin formato canónico cross-surface; drift entre superficies | Aplicar `formatBlockedMessage` con domain=MSO |
| api.ts | `formatBlockedMessage` privado, no exportado | Cada surface implementaba su propio Blocked: ad-hoc | Exportar el helper para uso compartido |
| api.ts | Sin redirect helper | Cada surface decidía targets ad-hoc | Añadir `redirectsForSurface()` rule-based |
| Tipos | Sin `decision_source` / `confidence_score` (brief §5) | Operador no sabía si decisión vino de LLM o regla | Tipos opcionales + render badge cuando presentes |
| Machine Operator | Errores locales (capability desconocida) sin `execution_status` | Inconsistente con backend errors que sí lo tienen | Prefix `[execution_status: unavailable]` en error local |

---

## Cambios aplicados

| File | Type | Change |
| ---- | ---- | ------ |
| `ui/lib/api.ts` | EDIT | Exportar `formatBlockedMessage`. Añadir `RedirectTarget`/`RedirectOption`/`redirectsForSurface()`. |
| `ui/lib/types.ts` | EDIT | Añadir `DecisionSource` type. Campos opcionales `decision_source`/`confidence_score` en `SendChatResponse` + `decisionSource`/`confidenceScore` en `ChatMessage`. |
| `ui/lib/sovereign/types.ts` | EDIT | `DecisionSource` type. Campos opcionales en `SovereignChatResponse` y `SovereignMessage` + `redirectTargets`. |
| `ui/lib/sovereign/api.ts` | EDIT | Passthrough de `decision_source` y `confidence_score` desde el backend (validación tipo-segura, nunca inferido). |
| `ui/stores/sovereign-store.ts` | EDIT | `pendingRedirectText` buffer + `setPendingRedirectText`/`consumePendingRedirectText`. Refactor a `(set, get)` para evitar self-reference de tipos. |
| `ui/components/sovereign/RedirectActions.tsx` | NEW | Componente reusable; pills clickeables que navegan vía sovereign-store y stash original text. Sin lógica de autoridad. |
| `ui/components/sovereign/SystemChatView.tsx` | EDIT | Guard 01.6 ahora marca `redirectTargets`. MessageBubble renderiza RedirectActions + decision/confidence badges. Error path ofrece redirect. |
| `ui/components/views/chat-view.tsx` | EDIT | Error path usa `formatBlockedMessage`. Fallback `(sin respuesta)` reemplazado por bloque canónico. AssistantMessage: badge decision/confidence + RedirectActions cuando error/unavailable/governance non-ALLOW. |
| `ui/components/sovereign/MSOView.tsx` | EDIT | `handleSend` y `handleConfirm` usan `formatBlockedMessage` con domain=MSO. MessageBubble: badges decision/confidence. Passthrough de tracability. |
| `ui/lib/sovereign/agents.ts` | EDIT | "Unknown capability" branch ahora prefija `[execution_status: unavailable]` para consistencia con errores backend. |

---

## Flujo final (input → acción)

```
┌──────────────────────────────────────────────────────────────────────┐
│ 1. OPERATOR escribe en cualquier surface                              │
└──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 2. SURFACE-SCOPED HANDLER envía al backend (autoridad única)          │
│    /api/chat/process (chat principal)                                 │
│    /api/chat/process surface=system_chat                              │
│    /api/chat/process surface=mso_direct                               │
│    /api/agent/execute (machine_operator)                              │
└──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 3. BACKEND clasifica + decide (MSO/Police/Pipeline)                    │
│    Devuelve: message, plan?, governance_trace?, execution_status,     │
│              decision_source?, confidence_score?, error?              │
└──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 4. SURFACE shaping (UI-only, autoridad backend intacta)                │
│                                                                        │
│    Chat principal:                                                     │
│      ok+message      → render text + decision/confidence badges        │
│      ok+plan         → PlanPanel + UIActionBar (existente)             │
│      ok+empty        → bloque canónico "response.empty" + redirect    │
│      error           → bloque "response.error" + RedirectActions      │
│                                                                        │
│    System Chat (informational):                                        │
│      ok+conversational → render message                                │
│      ok+executive_intent (plan/needs_confirmation/non-ALLOW)           │
│        → bloque "surface.system_chat.executive_intent"                 │
│        + RedirectActions [Planificar con MSO][Ejecutar con MO]         │
│        + originalText stash en sovereign-store.pendingRedirectText    │
│      error → bloque + redirect                                         │
│                                                                        │
│    MSO Direct (sovereign):                                             │
│      ok+plan → render plan + PolicyDecisionCard + AuthorityBadge       │
│      ok+confirm → PendingConfirmationCard                              │
│      error → bloque "response.error" / "execution.failed"              │
│                                                                        │
│    Machine Operator (executor):                                        │
│      help → live registry state + capability table con [requires       │
│              approval] / [read-only] markers                           │
│      unknown capability → [execution_status: unavailable] + allowed   │
│      ok → output con [execution_status: real|stub|partial|unavailable]│
└──────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 5. NEXT STEP siempre disponible                                        │
│    - Si hay plan → user clicks confirm/cancel/select/form              │
│    - Si hay redirect → user clicks Planificar/Ejecutar → navega a la   │
│      surface destino con el texto pre-cargado                          │
│    - Si éxito puro → mensaje rendered, conversación continúa           │
│    Nunca silencio. Nunca dead-end.                                    │
└──────────────────────────────────────────────────────────────────────┘
```

### Surface Rules (canónica)

| Surface | Ejecuta | Planifica | Informa | Si no puede ejecutar/planificar |
| ------- | ------- | --------- | ------- | -------------------------------- |
| Chat principal | ❌ (no genera plan propio) | ❌ | ✔ | RedirectActions cuando error/governance non-ALLOW |
| System Chat | ⚠ limitado (orientación) | ❌ | ✔ | RedirectActions + bloque canónico |
| MSO Direct | ✔ | ✔ | ✔ | bloque canónico con domain=MSO |
| Machine Operator | ✔ | ❌ | ❌ (técnico) | execution_status honesto + suggestion |

---

## Qué NO se tocó y por qué

- **Backend** (`assistant_os/*`): autoridad única; ya respondía correctamente. Los gaps eran de presentación.
- **Contracts**: solo añadí campos opcionales (`decision_source`, `confidence_score`, `redirect_targets` en sovereign type). Ningún campo existente cambió. Backend que no envía los nuevos campos sigue funcionando idénticamente.
- **MSO core, Policy, Auth, Capability registry, Runner, Freeze backend**: per restricciones del brief.
- **Surface behavior backend** (`assistant_os/surface_behavior.py`): mantiene semántica original — surface es audit-only, nunca authority verdict. Guard informacional de System Chat es UI-only.
- **Confirmation flow** (`PlanPanel`, `UIActionBar`, `PolicyDecisionCard`, `PendingConfirmationCard`): ya intactos en chat-view y MSOView. No los toqué.
- **Polish UI 01.5** que el operador no había restaurado (STATUS_LABEL.unknown='Initializing', etc.): no por inercia.

---

## Validación (real, esta sesión)

### Backend pytest
```
$ python -m pytest tests/test_s01_freeze_system.py \
                   tests/test_s02_admin_token_hardening.py \
                   tests/test_codeops_endpoints.py \
                   tests/test_mso_governance.py \
                   tests/test_mo_agent_registry.py \
                   tests/test_surface_behavior_layer.py \
                   tests/test_backend_operability_endpoints.py
…
140 passed, 1 warning in 6.89s
```

Canary `test_chat_process_surface_is_preserved_in_metadata_and_audit_without_changing_execution_mode` **pasa** — autoridad única preservada; surface sigue siendo audit-only.

### UI tsc
```
$ node node_modules/typescript/bin/tsc --noEmit 2>&1 | grep "error TS" | wc -l
30
$ node ... | grep "error TS" | grep -v "next/server\|next/link\|next/navigation\|'next'\|next/dist/lib/metadata\|next/types" | wc -l
0
```

**0 errores TS reales.** 30 reportados son del cross-mount Linux↔Windows (`next/*` no resuelve). El operador en Windows nativo verá 0 errores.

### Static cross-checks
- `formatBlockedMessage` exportado una vez, importado en 3 surfaces.
- `redirectsForSurface()` rule-based, sin LLM, decisiones auditables.
- `RedirectActions` no toca authority — solo navega vía sovereign-store.
- `pendingRedirectText` buffer transitorio; `consumePendingRedirectText` lo limpia tras leer.
- Campos opcionales en types: passthrough seguro (validación tipo en `lib/sovereign/api.ts`).

---

## Riesgos

1. **UI tsc verificado en sandbox Linux.** Errors TS reales = 0 contra `node_modules` accesible. Operador debe re-correr `npx tsc --noEmit` en Windows nativo.

2. **Walkthrough manual no ejecutado por mí.** Necesario verificar:
   - System Chat → "crea una tarea" → bloque + chips clickeables → click "Planificar con MSO" → navega a MSO + texto pre-cargado.
   - Chat principal con webhook caído → bloque canónico + chips, no error string plano.
   - MSO Direct con respuesta error → bloque domain=MSO con suggestion.
   - Machine Operator → `unknowncap` → `[execution_status: unavailable]` prefix.
   - Decision/confidence badges aparecen SOLO si backend los envía (verificar con backend que los emita; ahora mismo backend no los emite — son additive, no aparecen hasta que backend opte en).

3. **Backend no envía aún `decision_source`/`confidence_score`.** Tipo añadido es preparatorio. Cuando el backend opte en (e.g. en `_handle_chat_process`), aparecerán automáticamente. Hoy: badges nunca renderizan, ningún regression.

4. **`RedirectActions` accede al store directamente** (no via hooks). Esto es intencional — el componente es disparado desde un onClick que ya está en un componente cliente. No causa re-renders innecesarios. Si se invoca desde un componente server, fallará silenciosamente (correcto: server components no deberían tener onClick).

5. **Redirect a 'machine_operator' usa `setActiveAgent`**, que el sovereign-store ya tiene wired para flip activeView a `'agents'`. Si esa lógica cambia, el redirect podría desincronizarse. Documentado pero no defendido por test.

6. **Git sandbox** (Cowork VM) tiene índice corrupto en branch `claud` (vs `claude/...`). Working tree es la fuente. Operador hace branch + commit + PR en Windows nativo:

```bash
# En tu Windows
git checkout main
git pull origin main
git checkout -b claude/alfa-flight-02-operability
git add ui/lib/api.ts ui/lib/types.ts ui/lib/sovereign/types.ts \
        ui/lib/sovereign/api.ts ui/stores/sovereign-store.ts \
        ui/components/sovereign/RedirectActions.tsx \
        ui/components/sovereign/SystemChatView.tsx \
        ui/components/sovereign/MSOView.tsx \
        ui/components/views/chat-view.tsx \
        ui/lib/sovereign/agents.ts \
        docs/ALFA_FLIGHT_02_OPERABILITY_REPORT.md
git commit -m "ALFA-FLIGHT-02: operability closure (UI redirect, decision_source/confidence, canonical block messages)"
git push origin claude/alfa-flight-02-operability
# luego abrir PR contra main
```

---

## Veredicto

**GO**

- Backend tests: 140/140 reales en esta sesión.
- UI tsc: 0 errores reales (los 30 son sandbox env).
- Cinco objetivos del brief cumplidos:
  1. **Entry point unificado**: chat principal ahora siempre responde — fallbacks canónicos cuando backend está vacío o falla.
  2. **Surface rules table** documentada y aplicada en código.
  3. **Redirección inteligente**: `RedirectActions` chips en System Chat, chat principal (error/blocked), con pre-carga de texto en surface destino.
  4. **Respuesta garantizada**: ningún path UI termina en silencio o bloque plano. Cada error/empty/blocked tiene domain/action/reason/suggestion y RedirectActions cuando aplica.
  5. **Trazabilidad ligera**: `decision_source` + `confidence_score` opcionales en types y badges (sin demanda al backend; backend opt-in cuando esté listo).
- Restricciones respetadas: ningún cambio a MSO/Policy/Auth/contracts/parallel authority/hidden logic.
- Compatibilidad total: campos nuevos opcionales; comportamiento sin ellos = comportamiento anterior.

Una vez que tu `npx tsc --noEmit` en Windows confirme 0 errores y el walkthrough manual valide el flujo end-to-end, GO firme. Cualquier inconsistencia detectada → ese hallazgo se documenta y el verdict revierte.
