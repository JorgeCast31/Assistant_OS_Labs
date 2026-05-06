# FREEZE_M1B — Wire Authorized Code Execution with Persistent Audit and Lifecycle

**Fecha:** 2026-03-31
**Branch:** `reconcile/baseline-freeze`
**Commit:** `3234ed4` → amend a `feat(execution): M1B — wire authorized code execution with persistent audit and lifecycle`
**Estado:** IMPLEMENTADO Y VALIDADO CON MOCKS — path autorizado conectado, Docker real no hardened en CI

---

## DIAGNÓSTICO

### Fragmentación pre-M1B

Antes de este sprint existían dos planos de ejecución sin conexión:

**Plano A — RunnerService (`runners/`)**
El path activo de `code_api.py` ejecutaba vía `ApplyEngine` (filesystem write) y
`TestEngine` (subprocess local). Sin Docker. Sin aislamiento de proceso. Sin governance.
`AuthorizedPlan` era un contrato definido pero nunca construido en este path.

**Plano B — RunnerAPI (`sandbox/`)**
Ejecutor Docker real con `ContainerBackend`, `ExecutionRegistry`, `RevocationManager`,
y `AuditStore` implementados. Completamente desconectado del path activo de `code_api`.

**Por qué `AuthorizedPlan` era decorativo:**
`handle_execute()` en `code_api.py` construía `RunnerExecutionRequest` sin ningún
`AuthorizedPlan`. El contrato de governance existía, pero nunca participaba en la
construcción de una ejecución real. El lifecycle de audit y registry era igualmente
inerte — `AuditStore` implementado sin instancia de producción, `ExecutionRegistry`
sin llamadores en el path principal.

---

## CAMBIO REALIZADO

### 1. `runner_models.py` — Extensión de contratos (backward-compatible)

`RunnerExecutionRequest` recibe dos nuevos campos opcionales:
- `authorized_plan: Optional[AuthorizedPlan]` — governance binding
- `code: Optional[str]` — código Python para ejecución en sandbox

`RunnerExecutionResult` recibe dos nuevos campos opcionales:
- `authorized_plan_info: Optional[Dict]` — resumen del plan (para metadata.json)
- `sandbox_metadata: Optional[Dict]` — `ExecutionMetadata.to_dict()` del run Docker

Todos con `default=None` — ningún caller existente necesita cambio.

### 2. `runner_service.py` — RunnerAPI integrado en el path de orquestación

`RunnerService` ahora tiene `__init__` con tres dependencias inyectables:

```python
RunnerService(
    runner_api=RunnerAPI(),           # ejecutor Docker — inyectable en tests
    registry=ExecutionRegistry(),     # lifecycle tracking
    audit_store=AuditStore(path),     # audit persistente JSONL
)
```

Se añade **Phase 2.5** entre apply y test:

```
preflight → workspace → apply → [Phase 2.5: RunnerAPI/Docker] → test → validate → report → notify
```

La Phase 2.5 se activa solo cuando `request.authorized_plan is not None and request.code is not None`.
Usa un sub-directorio `_sandbox/` dentro del `execution_dir` (aislado del repo workspace)
para que `WorkspaceModel.cleanup()` no interfiera con los artifacts del runner.

`_write_final_metadata()` persiste en `metadata.json`:
- `authorized_plan`: resumen del plan de governance
- `sandbox_execution`: `ExecutionMetadata` del Docker run

### 3. `code_api.py` — `AuthorizedPlan` real en cada request

Nueva función `_build_authorized_plan(execution_id, body) -> AuthorizedPlan`:

```
execution_id          → mismo que RunnerExecutionRequest.execution_id (identidad vinculada)
plan_id               → desde body o auto-generado (uuid)
policy_id             → validado contra KNOWN_POLICY_IDS, fallback a "default"
capability_scope      → desde body o ["code_execute"] por defecto
authorized_plan_hash  → SHA-256(json_canónico(campos de identidad)) — determinístico
```

`handle_execute()` ahora:
1. Llama `_build_authorized_plan()` antes de construir `RunnerExecutionRequest`
2. Llama `ap.validate()` — falla rápido si el plan es inválido
3. Loggea el binding: `AUTHORIZED_PLAN execution_id=... plan_id=... policy_id=...`
4. Pasa `authorized_plan` y `code` al request

`_build_request_snapshot()` incluye campos de governance para que reruns preserven el mismo plan binding.

---

## NUEVA ARQUITECTURA DEL PATH AUTORIZADO

El path autorizado de ejecución CODE ahora conecta governance, lifecycle,
auditoría persistente y reporting a través de RunnerService + RunnerAPI:

```
POST /api/code/execute
        │
        ▼
code_api.handle_execute()
        │
        ├── _build_authorized_plan()
        │     execution_id  ──────────────────────────────────────────────────────┐
        │     plan_id                                                              │
        │     policy_id (validado)                                                 │
        │     authorized_plan_hash (SHA-256 determinístico)                       │
        │     capability_scope                                                     │
        │                                                                          │
        ├── RunnerExecutionRequest(authorized_plan=ap, code=code, ...)            │
        │                                                                          │
        ▼                                                                          │
RunnerBackedExecutor.execute(request)                                             │
        │                                                                          │
        ▼                                                                          │
RunnerService.run(request)   ← ORQUESTADOR                                       │
        │                                                                          │
        ├── preflight + workspace                                                  │
        ├── ApplyEngine (cambios filesystem)                                       │
        │                                                                          │
        ├── Phase 2.5: RunnerAPI.execute()   ← EJECUTOR DOCKER                   │
        │     workspace: _sandbox/  (aislado)                                     │
        │     authorized_plan ─────── propagado ──────────────────────────────────┘
        │     registry:    ExecutionRegistry  ← lifecycle: PENDING→RUNNING→*
        │     audit_log:   AuditStore JSONL   ← audit events persistentes
        │
        ├── TestEngine (subprocess local sobre workspace)
        ├── ValidationEngine
        ├── ReportBuilder
        ├── NotificationEngine
        └── metadata.json: authorized_plan + sandbox_execution persistidos
```

---

## CONTRATOS REALES (dejaron de ser ornamentales)

### `AuthorizedPlan`
**Antes:** contrato definido, nunca construido en el path activo.
**Ahora:** construido en `handle_execute()` para todo request, validado via `ap.validate()`,
propagado hasta `RunnerAPI.execute()` donde gobierna lifecycle, registry y audit.
`execution_id` en `AuthorizedPlan` siempre coincide con `RunnerExecutionRequest.execution_id`.

### `RunnerExecutionRequest` con governance
**Antes:** solo `execution_id`, `repo_path`, `changes`, `test_spec`.
**Ahora:** también `authorized_plan` y `code` — el binding de governance viaja
con el request desde HTTP hasta `RunnerAPI`.

### `ExecutionRegistry` — lifecycle tracking
**Antes:** implementado, sin instancia activa en el path de producción.
**Ahora:** singleton en `RunnerService.__init__`, pasado a `RunnerAPI.execute()`.
Registra lifecycle: `PENDING → RUNNING → COMPLETED | FAILED | ABORTED`.

### `AuditStore` — persistencia de audit
**Antes:** implementado, sin instancia activa en el path de producción.
**Ahora:** singleton en `RunnerService.__init__`, apunta a `var/runner/audit.jsonl`.
Persiste execution events, secret events, output events, artifact events — cross-process.

### `metadata.json` con governance
**Antes:** persistía ejecución y resultado, sin campos de governance.
**Ahora:** incluye `authorized_plan` (plan_id, policy_id, hash) y `sandbox_execution`
(ExecutionMetadata del Docker run) en cada `var/runner/executions/{id}/metadata.json`.

---

## VALIDACIÓN

### Tests corridos

| Suite | Resultado |
|---|---|
| `tests/runners/` | 152 passed, 0 failed |
| `tests/test_sandbox.py` + `tests/test_code_api.py` + `tests/test_runner.py` | 97 passed, 13 skipped |
| **Total** | **249 passed, 0 failed** |

### Invariantes verificados con mocks

Los siguientes invariantes fueron verificados con `RunnerAPI` mockeado
(retorna `ExecutionResult` exitoso sin Docker):

| Invariante | Resultado |
|---|---|
| `authorized_plan.execution_id == request.execution_id` | ✅ PASS |
| `authorized_plan.validate()` pasa para todos los requests de `code_api` | ✅ PASS |
| `RunnerService.__init__` crea `RunnerAPI`, `ExecutionRegistry`, `AuditStore` | ✅ PASS |
| `AuditStore.path.suffix == '.jsonl'` (no directorio) | ✅ PASS |
| Phase 2.5 pasa `authorized_plan`, `registry`, `audit_log` a `RunnerAPI.execute()` | ✅ PASS |
| `authorized_plan_info` y `sandbox_execution` presentes en `metadata.json` | ✅ PASS |
| Backward compatibility: requests sin `code` siguen el path legacy sin error | ✅ PASS |
| Regresiones en tests pre-existentes: ninguna introducida por M1B | ✅ PASS |

### Qué fue validado con mocks vs sin mocks

**Validado con mocks (RunnerAPI mockeado, sin Docker):**
- Construcción y propagación de `AuthorizedPlan`
- Integración Phase 2.5 en `RunnerService.run()`
- Persistencia de governance en `metadata.json`
- Routing de errores sandbox hacia el pipeline validate/report/notify
- `ExecutionRegistry` y `AuditStore` wired como dependencias

**NO validado sin mocks (requiere Docker real en el entorno):**
- Ejecución de código Python real dentro de un container efímero
- Ciclo de vida completo `PENDING → RUNNING → COMPLETED` en un Docker container real
- Escritura de audit events a `audit.jsonl` desde un container run real (no mock)
- Captura de artifacts desde `out/` de un container real
- Enforcement de timeout y revocación sobre un container real

---

## FORMULACIÓN HONESTA DEL ESTADO

El execution plane está **conectado arquitectónicamente** pero **no endurecido end-to-end con Docker real**.

**Lo que quedó real:**
- Governance binding: `AuthorizedPlan` se construye, valida y propaga en todo request CODE
- Audit wiring: `AuditStore` está instanciado y recibirá eventos cuando Docker ejecute
- Registry wiring: `ExecutionRegistry` está instanciado y recibirá transiciones de lifecycle
- Persistencia de governance: `metadata.json` incluye `authorized_plan` y `sandbox_execution`
- Contratos extendidos: `RunnerExecutionRequest` y `RunnerExecutionResult` tienen campos de governance reales

**Lo que requiere hardening adicional:**
- La Phase 2.5 solo se activa cuando el caller pasa `code` en el HTTP body.
  Requests sin `code` ejecutan por el path legacy (ApplyEngine + TestEngine local) — sin Docker.
- Docker real no fue validado en este sprint. El `ContainerBackend` requiere Docker instalado.
  Si Docker no está disponible, la Phase 2.5 retorna `ExecutionResult(ok=False)` y el run
  continúa hacia validate/report con un error no-fatal auditado.
- `TestEngine` (Phase 3) sigue siendo subprocess local no aislado.
- `RunnerBackedExecutor` no expone los nuevos `__init__` args de `RunnerService`,
  lo que limita la inyección de governance deps vía ese wrapper.

---

## ALERTAS ARQUITECTÓNICAS

### Alerta 1 — Docker real no hardened en este sprint
**Severidad: MEDIA**
La integración con `RunnerAPI` es real en código, pero la validación fue realizada
con `RunnerAPI` mockeado. El path completo con Docker real (container spin-up,
stdout/stderr capture, exit code, artifact collection) no fue ejercido en este sprint.
El siguiente sprint debe ejecutar un run Docker real e-to-e y verificar el JSONL de audit.

### Alerta 2 — `code` field opcional implica que la Phase 2.5 no es universal
**Severidad: MEDIA**
Requests sin `code` en el body omiten la Phase 2.5 y ejecutan por el path legacy
sin aislamiento ni governance binding real en `RunnerAPI`. Para hacer el sandbox
obligatorio, `code` debería ser un campo required o la Phase 2.5 debería activarse
por `authorized_plan` solo.

### Alerta 3 — CODE domain ausente del orchestrator
**Severidad: BAJA para M1B, ALTA para M2**
El orchestrator (`core/orchestrator.py`) sigue sin routing para CODE domain.
`code_api.py` opera como servidor HTTP independiente. El flujo completo
`CanonicalRequest → PolicyDecision → CODE pipeline` no existe todavía.

### Alerta 4 — `TestEngine` no aislado
**Severidad: BAJA para M1B**
Phase 3 ejecuta `pytest` como subprocess local en el workspace. No hay
aislamiento de proceso, no hay Docker. Esto es deliberado en M1B — el foco
fue la governance layer, no el hardening del test runner.

---

## SIGUIENTE SPRINT RECOMENDADO: M1C — Docker Real Validation

**Objetivo:** Validar el path Docker real end-to-end y hacer obligatorio el governance binding.

**Slices:**
1. Ejecutar un `POST /api/code/execute` con Docker real, verificar que:
   - `var/runner/audit.jsonl` tiene eventos `execution_started`, `execution_completed`
   - `metadata.json` tiene `sandbox_execution.status == "completed"`
   - `ExecutionRegistry` tiene el run en estado COMPLETED
2. Hacer `code` field requerido en el path CODE (o activar Phase 2.5 solo con `authorized_plan`)
3. Conectar CODE domain al orchestrator (routing `CanonicalRequest → CODE pipeline → RunnerService`)
4. Reemplazar `TestEngine` con invocación Docker real o validar que el scope es diferente

---

## ARCHIVOS MODIFICADOS EN M1B

```
assistant_os/runners/runner_models.py   — campos authorized_plan + code + governance en result
assistant_os/runners/runner_service.py  — __init__ con RunnerAPI/Registry/AuditStore + Phase 2.5
assistant_os/api/code_api.py            — _build_authorized_plan() + governance binding en todo request
FREEZE_M1B.md                           — este documento
```
