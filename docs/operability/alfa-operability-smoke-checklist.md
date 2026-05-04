# ALFA Operability Smoke Checklist

Sistema: Assistant_OS_Labs
Clasificación: ALFA — local únicamente
Fecha de última revisión: 2026-05-03

---

## Alcance

Este checklist valida el stack de outcome observability como sistema ALFA operable en
entorno local. Cubre preflight, servicios, monitoreo, cognición, ejecución
backend-controlada, y superficie UI observacional.

No sustituye tests de regresión. No autoriza cambios a producción. No concede permisos
de ejecución adicionales.

---

## 1. Preflight Git

```powershell
git switch main
git pull
git status --short
```

**Resultado esperado:**

- Branch activo: `main`
- Pull sin conflictos
- `git status --short` retorna vacío (working tree limpio)

**BLOCKED si:**

- Hay cambios sin commitear que afecten `assistant_os/`, `ui/`, o `tests/`
- El pull falla por conflictos no resueltos

---

## 2. Servicios a levantar

Levantar en el orden indicado. Cada servicio debe estar en estado ready antes de
continuar al siguiente.

### 2.1 Backend AssistantOS (requerido)

```powershell
python -m assistant_os --server
```

Puerto: `http://127.0.0.1:8787`
Señal de ready: log `Webhook server listening on...` o respuesta HTTP 200 en `/health`

### 2.2 UI Next.js (opcional, requerido para sección 6)

```powershell
cd ui
npm run dev
```

Puerto: `http://localhost:3100`
Señal de ready: `Ready - started server on 0.0.0.0:3100`

### 2.3 Local LLM (opcional, requerido para sección 4)

Si cognición local está configurada:

```powershell
# llama.cpp (si aplica)
# puerto: http://127.0.0.1:8081

# Ollama (si aplica)
# puerto: http://127.0.0.1:11434
```

Señal de ready: respuesta OK en `/health` del proveedor respectivo.

### 2.4 Code API (opcional)

```powershell
python run_code_api.py
```

Puerto: `http://localhost:8000`
Solo requerido si el operador quiere validar la superficie CODE.

---

## 3. Monitoreo — Readiness de endpoints

Todos los GETs son no-autenticados o requieren `X-Assistant-Token`. Sustituir
`<TOKEN>` por el valor de `WEBHOOK_TOKEN`.

### 3.1 Backend health

```powershell
curl -s http://127.0.0.1:8787/health
```

**Resultado esperado:** `{"ok": true, ...}`

### 3.2 MSO state

```powershell
curl -s -H "X-Assistant-Token: <TOKEN>" http://127.0.0.1:8787/mso/state
```

**Resultado esperado:** `{"ok": true, "operational_mode": "...", ...}`

### 3.3 MSO governance status

```powershell
curl -s -H "X-Assistant-Token: <TOKEN>" http://127.0.0.1:8787/mso/governance/status
```

**Resultado esperado:** `{"ok": true, "operational_mode": "...", "governance_decisions_count": ...}`

### 3.4 MSO authority status

```powershell
curl -s -H "X-Assistant-Token: <TOKEN>" http://127.0.0.1:8787/mso/authority/status
```

**Resultado esperado:** `{"ok": true, "authority_posture": {...}}`

### 3.5 Confirm pending (sin planes activos debería estar vacío)

```powershell
curl -s -H "X-Assistant-Token: <TOKEN>" "http://127.0.0.1:8787/confirm/pending?limit=10"
```

**Resultado esperado:** `{"ok": true, "pending_count": 0, "pending": []}`

### 3.6 Outcome status (sin plan activo)

```powershell
curl -s -H "X-Assistant-Token: <TOKEN>" "http://127.0.0.1:8787/mso/outcome/status"
```

**Resultado esperado:** `{"ok": true, "found": false, ...}` — fail-soft, no error

### 3.7 Agents registry

```powershell
curl -s -H "X-Assistant-Token: <TOKEN>" http://127.0.0.1:8787/agents/registry
```

**Resultado esperado:** `{"ok": true, "agents": [...]}` con al menos `HOST_AGENT`

### 3.8 System capabilities

```powershell
curl -s -H "X-Assistant-Token: <TOKEN>" http://127.0.0.1:8787/system/capabilities
```

**Resultado esperado:** `{"ok": true, ...}` con capabilities listadas

---

**Criterio de sección:** Todos los endpoints retornan HTTP 200 con `"ok": true`.

**FAIL si:** Cualquier endpoint retorna 500, body vacío, o `"ok": false` sin justificación (un `found: false` en outcome es correcto en esta etapa).

**BLOCKED si:** Backend no responde en `/health`.

---

## 4. Cognición — Request de prueba sin ejecución directa

Este paso valida que el pipeline cognitivo produce un plan pendiente sin ejecutar
directamente.

```powershell
$env:WEBHOOK_TOKEN = "<TOKEN>"

curl -s -X POST http://127.0.0.1:8787/host/action `
  -H "Content-Type: application/json" `
  -H "X-Assistant-Token: <TOKEN>" `
  -d '{"action":"create_directory","payload":{"path":"C:\\Users\\Jorge\\Documents\\assistant_sandbox\\smoke_test_pending","confirmed":true}}'
```

**Resultado esperado:**

```json
{
  "ok": true,
  "result_type": "plan_confirmation_required",
  "data": {
    "plan_id": "<PLAN_ID>",
    ...
  }
}
```

- `result_type` debe ser `plan_confirmation_required`
- `data.plan_id` debe ser un UUID no vacío
- El plan NO debe ejecutar automáticamente

**Verificar que el plan quedó pendiente:**

```powershell
curl -s -H "X-Assistant-Token: <TOKEN>" "http://127.0.0.1:8787/confirm/pending?limit=10"
```

Resultado esperado: `"pending_count": 1` con el `plan_id` capturado arriba.

**FAIL si:**

- `result_type` no es `plan_confirmation_required`
- No aparece `plan_id` en la respuesta
- El plan ejecuta directamente sin confirmación

**BLOCKED si:** El backend no tiene un agente HOST activo o la clasificación de riesgo cambió.

---

## 5. Ejecución backend-controlada

Usa el demo script para validar el flujo completo de cuatro pasos.

### Variables de entorno requeridas

```powershell
$env:WEBHOOK_TOKEN = "<TOKEN>"
```

### Dry run (sin backend, verifica configuración)

```powershell
python scripts/demo_backend_outcome_flow.py --dry-run
```

**Resultado esperado:**

```
[demo] dry run only; no backend requests will be sent
[demo] base_url=http://127.0.0.1:8787
[demo] token_env=WEBHOOK_TOKEN
[demo] sandbox_demo_path=C:\Users\Jorge\Documents\assistant_sandbox\backend_outcome_demo_<ts>_<hash>
[demo] POST /host/action body: {...}
```

### Ejecución real

```powershell
python scripts/demo_backend_outcome_flow.py
```

**Resultado esperado (output completo):**

```
[demo] submitting request to POST /host/action
[demo] request submitted
[demo] plan_id captured: <UUID>
[demo] checking GET /confirm/pending
[demo] pending confirmation found
[demo] submitting confirmation to POST /host/confirm
[demo] confirm submitted
[demo] outcome fetched
[demo] final outcome.status: completed
```

**Criterio de sección:** Exit code 0, `final outcome.status: completed`.

**FAIL si:**

- Exit code distinto de 0
- `outcome.status` no es `completed`
- El plan no aparece en `/confirm/pending` después del paso 1
- Error de token, backend, o sandbox

**BLOCKED si:** Token no está en `WEBHOOK_TOKEN` o el backend no responde.

---

## 6. UI observacional

**Prerrequisito:** UI Next.js corriendo en `http://localhost:3100`.

Navegar a `http://localhost:3100` y validar las siguientes superficies.

### 6.1 SystemView — estado general

**Verificar:**
- La vista carga sin errores de red o de consola
- Se muestra el estado del sistema (modo operacional, capabilities)
- No hay botones de ejecución directa de acciones HOST

### 6.2 Authority Matrix (MSO Authority Status)

**Verificar:**
- La tabla o panel muestra el posture de autoridad actual
- Los datos provienen de `/mso/authority/status` (verificar en DevTools > Network)
- No hay controles de modificación de autoridad

### 6.3 Confirm Queue (panel de confirmaciones pendientes)

**Verificar:**
- El panel muestra confirmaciones pendientes si existen, o vacío si no hay
- Los datos provienen de `/api/confirm/pending` o proxy equivalente
- No hay botón que ejecute directamente sin confirmar desde el backend

### 6.4 Outcome Panel (OutcomeStatusPanel)

**Verificar:**
- El panel muestra el último estado de outcome conocido
- Después del paso 5, `outcome.status` debe aparecer como `completed`
- El polling está activo (indicador "Polling..." o timestamp "Last polled")
- No hay botones, inputs, selects ni forms en el panel
- El texto de nota dice: "Outcome status is observational; it does not grant execution permission."

### 6.5 No UI execution

**Verificar en toda la vista:**
- No hay botón que envíe directamente un POST a `/host/action`
- No hay botón que envíe directamente un POST a `/host/confirm`
- La UI es lectura y monitoreo únicamente

**FAIL si:**

- Cualquier panel no carga o muestra error no-fail-soft
- OutcomeStatusPanel muestra `status: pending` después del paso 5 (indica gap en polling)
- Se encuentran controles de ejecución directa en la UI

**BLOCKED si:** UI no inicia o no puede conectar con el backend.

---

## 7. Criterios PASS / FAIL / BLOCKED

| Sección | PASS | FAIL | BLOCKED |
|---------|------|------|---------|
| 1. Preflight Git | Working tree limpio, pull OK | Conflictos sin resolver | Repo inaccesible |
| 2. Servicios | Backend responde en /health | Backend no inicia | Puerto ocupado |
| 3. Monitoreo | Todos los endpoints ok=true | Cualquier 500 o ok=false inesperado | Backend no responde |
| 4. Cognición | plan_confirmation_required con plan_id | Ejecución directa o error de clasificación | Agente HOST no activo |
| 5. Ejecución | Exit 0, outcome.status=completed | Exit 1 o status≠completed | Token no configurado |
| 6. UI | Todos los paneles cargan, no hay ejecución directa | Panel con error o UI execution | UI no inicia |

**Veredicto final:**

- **ALFA PASS**: todas las secciones PASS
- **ALFA PASS con advertencias**: 1–2 FAIL menores no-críticos documentados
- **ALFA FAIL**: cualquier FAIL en secciones 4, 5 o 6.4
- **ALFA BLOCKED**: cualquier BLOCKED en secciones 1, 2 o 3

---

## 8. Riesgos residuales conocidos

### R1 — `execution_status` siempre `unknown` en HOST pipeline

El campo `outcome.execution_status` permanece `null` o `"unknown"` en toda ejecución
HOST porque el pipeline no lo establece. No es un defecto del endpoint ni del panel.
El criterio fuerte de ALFA es `outcome.status="completed"`, no `execution_status`.

**Sprint recomendado si se requiere resolución:**
S-OPERABILITY-EXECUTION-STATUS-01 — Normalizar `execution_status` en HOST pipeline.

### R2 — Observabilidad efímera en memoria

`task_registry` vive en el proceso. Un reinicio del backend borra todo el historial de
outcomes. Un plan ejecutado correctamente no es recuperable después del reinicio.

**Sprint recomendado si se requiere resolución:**
S-OPERABILITY-PERSISTENCE-01 — Persistencia de task_registry (diseño requerido antes
de implementación, `mso_store` ya existe como candidato).

### R3 — Query manual de outcome en UI (UI-C pendiente)

El `OutcomeStatusPanel` hace polling pasivo sin capacidad de consultar un `plan_id`
específico. No hay campo de input en la UI para consultar el estado de un plan
arbitrario. El endpoint GET `/mso/outcome/status?plan_id=...` soporta la consulta
pero la UI no la expone.

**Sprint recomendado:**
S-RESULT-OBS-01C-UI-C — Input manual de plan_id en OutcomeStatusPanel.

### R4 — Dependencia de token y entorno local

El demo y el monitoreo requieren `WEBHOOK_TOKEN` configurado en el entorno local. No
hay mecanismo de fallback ni bootstrapping automático. Si la variable no está presente,
todos los endpoints autenticados retornan 401 o el script falla antes de conectar.

**Mitigación actual:** documentación del token en cada sección que lo requiere.

---

## 9. Próximo sprint recomendado según resultado

| Resultado | Sprint recomendado |
|-----------|-------------------|
| ALFA PASS | S-RESULT-OBS-01C-UI-C — Input manual de plan_id en UI (demo guiada habilitada) |
| ALFA PASS | S-DEMO-GUIDED-01 — Demo guiada end-to-end con narrativa de operador |
| FAIL en sección 3 (monitoreo) | Reparar endpoints afectados antes de continuar |
| FAIL en sección 4 (cognición) | Revisar classifier y orchestrator; verificar agente HOST activo |
| FAIL en sección 5 (ejecución) | Revisar `_publish_confirm_observation()` y `remove_pending_plan` en orchestrator |
| FAIL en sección 6.4 (outcome panel) | Revisar polling hook, proxy route y store de outcome status en UI |
| FAIL en sección 6.5 (UI execution) | Bloqueo crítico; no continuar hasta resolver |
| ALFA BLOCKED | Resolver la condición de bloqueo antes de ejecutar el checklist |

---

*Checklist generado para sprint S-ALFA-OPERABILITY-GATE-01. No modificar código.*
