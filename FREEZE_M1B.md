# FREEZE_M1B — Unified Execution Plane with Authorized Runs and Persistent Audit

**Fecha:** 2026-03-31
**Branch:** `reconcile/baseline-freeze`
**Estado:** COMPLETO — implementado, validado, sin regresiones

---

## DIAGNÓSTICO: DOS EXECUTION PLANES SIN UNIFICACIÓN

### Estado previo a M1B

Existían dos planos de ejecución paralelos e independientes:

**Plano A — RunnerService (`runners/`)**
- Entry point: `code_api.py` → `RunnerBackedExecutor` → `RunnerService.run()`
- Ejecución: `ApplyEngine` (filesystem write) + `TestEngine` (subprocess local)
- Sin Docker. Sin aislamiento. Sin governance binding.
- Persistencia: `var/runner/executions/{id}/metadata.json`, `report.json`, etc.

**Plano B — RunnerAPI (`sandbox/`)**
- Entry point: `tools/claude_code/apply_change_tool.py` → `_real_executor` → `RunnerAPI`
- Ejecución: `ContainerBackend` (Docker ephemeral, aislado)
- Audit: `AuditLog` in-memory (no persistente)
- `ExecutionRegistry` in-memory (no wired al path principal)
- `AuthorizedPlan` existía pero nunca se construía en el path `code_api`

### Consecuencias

| Invariante | Estado pre-M1B |
|---|---|
| `AuthorizedPlan` gobierna ejecución | VIOLADO — nunca construido en path activo |
| Audit persistente | VIOLADO — `AuditStore` implementado pero no wired |
| Ejecución aislada (Docker) | VIOLADO en path principal (`code_api`) |
| `ExecutionRegistry` activo | VIOLADO — en-memory, no wired |

---

## CAUSA RAÍZ

`RunnerService` nunca delegaba a `RunnerAPI`. Existían como implementaciones
alternativas del mismo concepto, no como capas de orquestación + ejecución.

`code_api.py` construía `RunnerExecutionRequest` sin `AuthorizedPlan`, lo que
dejaba el governance binding completamente ausente del path de producción activo.

`AuditStore` existía como infraestructura sin instancia de producción.

---

## SOLUCIÓN: UNIFICACIÓN DEL EXECUTION PLANE

### Cambios implementados

#### 1. `assistant_os/runners/runner_models.py`

Nuevos campos opcionales en `RunnerExecutionRequest` (backward-compatible):
- `authorized_plan: Optional[AuthorizedPlan]` — governance binding
- `code: Optional[str]` — código Python para ejecución en Docker

Nuevos campos en `RunnerExecutionResult` (backward-compatible):
- `authorized_plan_info: Optional[Dict]` — resumen del plan para metadata.json
- `sandbox_metadata: Optional[Dict]` — `ExecutionMetadata.to_dict()` del sandbox run

#### 2. `assistant_os/runners/runner_service.py`

`RunnerService` ahora tiene `__init__` con tres dependencias inyectables:
- `runner_api: RunnerAPI` — ejecutor Docker (singleton, inyectable para tests)
- `registry: ExecutionRegistry` — lifecycle tracking (singleton)
- `audit_store: AuditStore` — audit persistente en `var/runner/audit.jsonl`

Nueva **Phase 2.5** en `RunnerService.run()`:
```
preflight → workspace → apply → [sandbox Docker] → test → validate → report → notify
```

La Phase 2.5 se activa cuando `request.authorized_plan is not None and request.code is not None`.
Usa un sub-directorio aislado `_sandbox/` dentro del `execution_dir` para que
`WorkspaceModel.cleanup()` no afecte el workspace del repo.

Los campos `authorized_plan_info` y `sandbox_metadata` se persisten en `metadata.json`
vía `_write_final_metadata()`.

#### 3. `assistant_os/api/code_api.py`

Nueva función `_build_authorized_plan(execution_id, body) -> AuthorizedPlan`:
- Construida para CADA ejecución que entra por `code_api`
- `execution_id` en `AuthorizedPlan` siempre coincide con `RunnerExecutionRequest.execution_id`
- `authorized_plan_hash` = SHA-256 de los campos de identidad del plan (determinístico)
- `policy_id` validado contra `KNOWN_POLICY_IDS`; fallback a `"default"` si inválido
- `capability_scope` desde body o `["code_execute"]` por defecto

`handle_execute()` ahora:
1. Construye `AuthorizedPlan` antes de `RunnerExecutionRequest`
2. Loggea el binding: `AUTHORIZED_PLAN execution_id=... plan_id=... policy_id=...`
3. Pasa `authorized_plan` y `code` al `RunnerExecutionRequest`

`_build_request_snapshot()` incluye campos de governance para reruns.

---

## NUEVA ARQUITECTURA DEL EXECUTION PLANE

```
HTTP: POST /api/code/execute
          │
          ▼
    code_api.handle_execute()
          │
          ├─ _build_authorized_plan()     ← governance binding real
          │       - execution_id (coincide con RunnerExecutionRequest)
          │       - plan_id (body o auto-gen)
          │       - policy_id (validado)
          │       - authorized_plan_hash (SHA-256 determinístico)
          │       - capability_scope
          │
          ├─ RunnerExecutionRequest(authorized_plan=ap, code=code, ...)
          │
          ▼
    RunnerBackedExecutor.execute(request)
          │
          ▼
    RunnerService.run(request)          ← ORQUESTADOR
          │
          ├─ Phase 1: preflight + workspace
          ├─ Phase 2: ApplyEngine (cambios en repo workspace)
          ├─ Phase 2.5: RunnerAPI.execute()     ← EJECUTOR DOCKER
          │       workspace: execution_dir/_sandbox/   (aislado)
          │       authorized_plan: AuthorizedPlan
          │       registry: ExecutionRegistry     (lifecycle tracking)
          │       audit_log: AuditStore           (audit persistente JSONL)
          ├─ Phase 3: TestEngine (tests en workspace)
          ├─ Phase 4: ValidationEngine
          ├─ Phase 5: ReportBuilder
          ├─ Phase 6: NotificationEngine
          └─ metadata.json: contiene authorized_plan + sandbox_execution
```

---

## CONTRATOS ACTIVOS (AuthorizedPlan ahora real)

### `AuthorizedPlan` (ya no decorativo)

```python
AuthorizedPlan(
    execution_id=execution_id,          # coincide con RunnerExecutionRequest.execution_id
    plan_id=plan_id,                    # desde body o auto-generado
    authorized_plan_hash=sha256(plan),  # hash determinístico de identidad del plan
    policy_id="default",               # validado contra KNOWN_POLICY_IDS
    capability_scope=["code_execute"],  # scope real de capabilities
    runtime_profile="python3.11",      # runtime validado
)
```

### Lifecycle de governance (por request):

1. `code_api.handle_execute()` → construye `AuthorizedPlan` + `RunnerExecutionRequest`
2. `RunnerService.run()` → pasa `AuthorizedPlan` a `RunnerAPI.execute()`
3. `RunnerAPI.execute()` → valida `AuthorizedPlan`, registra en `ExecutionRegistry`,
   emite audit events a `AuditStore`
4. `AuditStore` → escribe JSONL en `var/runner/audit.jsonl` (cross-process persistent)
5. `metadata.json` → persiste `authorized_plan` + `sandbox_execution` por ejecución

---

## VALIDACIÓN

### Tests

| Suite | Resultado |
|---|---|
| `tests/runners/` (152 tests) | ✅ 152 passed, 0 failed |
| `tests/test_sandbox.py` + `test_code_api.py` + `test_runner.py` (97+13 skip) | ✅ 97 passed |
| Suite completa (exc. pre-existing failures) | ✅ Sin regresiones de M1B |

### Integration checks

| Invariante | Verificado |
|---|---|
| `AuthorizedPlan.execution_id == RunnerExecutionRequest.execution_id` | ✅ |
| `AuthorizedPlan.validate()` pasa para todo request de `code_api` | ✅ |
| `RunnerService.__init__` crea `RunnerAPI`, `ExecutionRegistry`, `AuditStore` | ✅ |
| `AuditStore` apunta a `var/runner/audit.jsonl` (file, no dir) | ✅ |
| Phase 2.5 pasa `authorized_plan`, `registry`, `audit_log` a `RunnerAPI` | ✅ |
| `authorized_plan_info` persiste en `metadata.json` | ✅ |
| `sandbox_execution` (ExecutionMetadata) persiste en `metadata.json` | ✅ |
| Backward compatibility: requests sin `code`/`authorized_plan` siguen funcionando | ✅ |

### Failures pre-existentes en baseline (no de M1B)

- `test_chaperon.py::test_inherited_currency`
- `test_classifier.py::test_health_rutina_operativo`
- `test_domain_result.py::test_notion_unavailable_returns_error`
- `test_work_update_singular.py::TestWorkUpdateNotionUnavailable` (2 tests)
- `test_work_update_singular.py::TestWorkUpdateFieldValidation::test_allowed_field_domain_accepted`

---

## ALERTAS RESTANTES

### Alerta 1 — `RunnerBackedExecutor` no pasa `__init__` args a `RunnerService`

`RunnerBackedExecutor` en `executors/runner_backed_executor.py` hace
`RunnerService()` sin args. Esto usa los singletons default (correcto en producción),
pero si se quiere inyectar diferentes instancias en tests vía `RunnerBackedExecutor`,
habría que extender su constructor. **Impacto actual: ninguno** — tests de integración
inyectan directamente en `RunnerService`.

### Alerta 2 — Sandbox Docker requiere Docker instalado

La Phase 2.5 solo se activa cuando `authorized_plan is not None and code is not None`.
Si Docker no está disponible, `ContainerBackend` retorna `ExecutionResult(ok=False, error="Docker not found...")`,
lo que se captura como `apply_error` y fluye al pipeline de validación/reporte
como un fallo. No es un crash — es un fallo auditado. Pero requests con `code`
sin Docker siempre producirán `final_status: failed`.

### Alerta 3 — `AuditStore` en-proceso es singleton por instancia de `RunnerService`

Si múltiples instancias de `RunnerService` coexisten en el mismo proceso,
cada una tiene su propio `AuditStore` apuntando al mismo archivo JSONL.
`AuditStore` usa `threading.Lock` por instancia, no un lock cross-process.
Escrituras concurrentes de múltiples procesos al mismo JSONL pueden producir
interleaving de líneas. **Impacto actual: bajo** — `code_api` crea un `_EXECUTOR`
singleton que crea una sola instancia de `RunnerService`.

### Alerta 4 — CODE domain aún no está en el orchestrator

El orchestrator (`core/orchestrator.py`) sigue sin una rama para CODE domain.
`code_api.py` opera como servidor HTTP independiente. La unificación arquitectónica
completa (CODE domain en el kernel) es scope de un sprint posterior (M1C o M2).

### Alerta 5 — `TestEngine` sigue ejecutando subprocesses locales

Phase 3 (`TestEngine`) no fue reemplazada por sandbox Docker. Se ejecuta como
subprocess directo sobre el workspace (no aislado). Esto es deliberado para M1B:
la Phase 2.5 introduce Docker para code execution; reemplazar TestEngine con Docker
es scope futuro.

---

## ARCHIVOS MODIFICADOS

```
assistant_os/runners/runner_models.py   — nuevos campos en Request y Result
assistant_os/runners/runner_service.py  — __init__ + Phase 2.5 + metadata
assistant_os/api/code_api.py            — _build_authorized_plan + governance binding
```
