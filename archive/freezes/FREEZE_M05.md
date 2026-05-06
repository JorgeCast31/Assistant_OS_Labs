# Baseline Freeze — M0.5A + M0.5B
**Fecha:** 2026-03-29
**Branch:** reconcile/baseline-freeze
**Commit base:** e0e11f6

---

## Estado del Baseline

Suite completa: **844 passed, 0 failed** (validado post-M0.5B desde tmp).

---

## Cambios Incluidos

### M0.5A — Test Environment Stabilization
**Archivo:** `tests/test_code_agent.py`
**Causa:** `shutil.rmtree()` y `Path.unlink()` lanzan `PermissionError: [Errno 1]` en tearDown cuando el proceso Linux intenta eliminar archivos en el mount NTFS de Windows.
**Fix:** Ambos `tearDown` wrapeados en `try/except PermissionError` con comentario explicativo. Las aserciones del test completan antes del cleanup, por lo que el resultado del test no se ve afectado.
**Impacto:** Suite pasó de `5 failed, 839 passed` → `844 passed`.

### M0.5B — Public Response Semantic Fix
**Archivo:** `assistant_os/webhook_server.py` — función `_adapt_result_to_response()`
**Causa:** Priority inversion en el transport adapter. El branch `if domain == "WORK"` se evaluaba antes del check de `result_type`, interceptando resultados de tipo `plan_confirmation_required` con `domain="WORK"` y produciendo `agent="work", status="ok"` en lugar de `agent="interpreter", status="pending"`.
**Fix:** Los checks cross-domain (`RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED`, `RESULT_TYPE_PLAN_GENERATED`) se movieron ANTES de los checks por dominio. Docstring actualizado con invariante explícito: `result_type` es la señal semántica autoritativa; `domain` es secundario.
**Impacto:**
- WORK_CREATE con confirmación pendiente → `agent="interpreter"`, `status="pending"` ✓
- WORK_QUERY ejecutado → `agent="work"`, `status="ok"` (sin regresión) ✓
- Suite: 844 passed, 0 failed ✓

---

## Divergencias Abiertas

1. **CRLF en working tree**: ~60 archivos tienen CRLF (Windows) vs LF (HEAD). No son cambios de contenido. No entran en este commit. Recomendado: normalizar con `.gitattributes` en sprint dedicado.
2. **Untracked files en raíz**: `CHAT.md`, `FINAL_REPORT.md`, `PHASE1_BASELINE.md`, `TASK_00.md`, `TASK_01.md`, `WORKLOG.md`, `agent_contract.md`, `chat_core.py`, `code_api.py`, `webhook_server.py` — archivos de análisis/exploración previos. No entran en este commit. Evaluar si se archivan, se gitignorean o se borran.

---

## Alertas Arquitectónicas

### ALERTA-1: PolicyDecision es decorativo
`core/policy.py` construye un objeto `PolicyDecision` completo (riesgo, modo de ejecución, ttl). `core/orchestrator.py` **no lo lee**. El routing usa `plan.requires_confirmation` directamente, ignorando `policy_decision.execution_mode` y `policy_decision.risk_level`.

**Consecuencia concreta:** Es imposible hoy modificar el comportamiento de routing por política sin tocar el orchestrator. El contrato `PolicyDecision` es ornamental.

### ALERTA-2: Inverted dependency — Kernel importa desde HTTP layer
`core/semantic.py` y `core/planning.py` hacen lazy-import de `webhook_server.classify_text` y funciones relacionadas. Un módulo del Kernel (capa de orquestación) tiene acoplamiento estructural a la capa HTTP. Viola el principio de que el Kernel es domain-agnostic e independiente del transporte.

### ALERTA-3: Lógica de dominio en Kernel
`core/orchestrator.py` (y parcialmente `core/planning.py`) contienen lógica de interpretación que debería estar en Domain Pipelines o en el Semantic Layer. El boundary entre "interpretar intent" y "ejecutar pipeline" no está claramente trazado.

---

## Reporte de Contratos

| Contrato | Estado | Nota |
|---|---|---|
| `CanonicalRequest v1` | **Real** | Producido por `normalize_request()`, consumido por `handle_request()`. |
| `ExecutionPlan v1` | **Real** | Producido por `core/planning.py`, consumido por `core/orchestrator.py`. |
| `DomainResult v1` | **Real** | Producido por Domain Pipelines y por orchestrator para estados kernel. Consumido por `_adapt_result_to_response()`. Fix M0.5B restauró la semántica correcta en el transport adapter. |
| `PolicyDecision v1` | **Decorativo** | Producido por `core/policy.py`. **No consumido** por `core/orchestrator.py`. El routing bypasea este contrato. **ALERTA-1 activa.** |

---

## Recomendación — Siguiente Sprint (M0.6)

**Objetivo:** Hacer PolicyDecision un contrato real.

Tareas concretas:
1. `core/orchestrator.py` debe leer `policy_decision.execution_mode` para determinar si ejecutar, pausar o rechazar — en lugar de usar `plan.requires_confirmation` directamente.
2. `core/orchestrator.py` debe exponer `policy_decision` en el `DomainResult` cuando sea relevante para el consumidor.
3. Agregar tests que verifiquen que cambiar `PolicyDecision.execution_mode` cambia el comportamiento observable del sistema.
4. (Secundario) Resolver inverted dependency: extraer `classify_text` y helpers de intención a un módulo en `core/` o `assistant_os/classification.py` para que el Kernel no importe desde `webhook_server`.

Este sprint no toca FIN, CODE ni chat_core.
