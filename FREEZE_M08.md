# FREEZE M0.8 — Decouple Domain Pipelines from HTTP Layer
**Fecha:** 2026-03-30
**Branch:** reconcile/baseline-freeze
**Parent commit:** b676824 (M0.7B — extract planner from HTTP layer)

---

### DIAGNÓSTICO

**Coupling existente:** Los domain pipelines (`work_pipeline.py`,
`fin_pipeline.py`) importaban todos sus símbolos de integración directamente
desde `assistant_os/webhook_server.py` — un módulo HTTP — usando el patrón
de lazy-import:

```python
# work_pipeline.py — ANTES de M0.8
def _work_query_execute(plan, context_id):
    from ..webhook_server import check_notion_available, get_notion_status, ...
```

**Por qué era incorrecto arquitectónicamente:** `webhook_server.py` pertenece
a la capa HTTP (routing, parsing, serialización de responses). Los domain
pipelines son capa de dominio y no deben depender de la capa HTTP para ningún
propósito. El coupling `Domain Pipeline → HTTP Layer` viola el contrato de capas
de AssistantOS.

El coupling era **artificial**: ninguno de los 12 símbolos importados tenía
autoridad real en `webhook_server`. Todos eran re-exports que `webhook_server`
centralizaba desde módulos de integración. La dependencia pipeline→HTTP existía
por inercia del patrón de patcheo (los test mocks apuntaban a
`assistant_os.webhook_server.*`), no por necesidad funcional.

---

### CAMBIO REALIZADO

Se creó `assistant_os/integrations/work_gateway.py` como **capa de aggregation
no-HTTP real**. Es el único punto de entrada del pipeline WORK para todas sus
dependencias de integración.

`work_pipeline.py` (7 import sites) pasó de:
```python
from ..webhook_server import check_notion_available, ...
```
a:
```python
from ..integrations.work_gateway import check_notion_available, ...
```

`fin_pipeline.py` (1 import site) pasó de:
```python
from ..webhook_server import parse_expense
```
a:
```python
from ..fin_expense import parse_expense  # autoridad directa, sin gateway
```

`webhook_server.py` queda fuera de la cadena de dependencia de los domain
pipelines.

---

### NUEVA FRONTERA DE CAPA

**Los pipelines ya no dependen de `webhook_server.py`. La integración reusable
consumida por pipelines vive ahora en una capa no-HTTP
(`integrations/work_gateway.py`), separada del transporte HTTP.**

```
ANTES:
  work_pipeline ──► webhook_server (HTTP) ──► integrations/notion
                                           ──► context_store
                                           ──► parsers/work_update_parser

DESPUÉS:
  work_pipeline ──► integrations/work_gateway (no-HTTP) ──► integrations/notion
                                                         ──► context_store
                                                         ──► parsers/work_update_parser
  fin_pipeline  ──► fin_expense (directo)
```

`webhook_server.py` sigue importando esas integraciones para su propio uso
(HTTP handlers), pero ya no actúa como intermediario del pipeline.

---

### CAMBIOS INCLUIDOS

| Archivo | Tipo de cambio | Descripción |
|---|---|---|
| `assistant_os/integrations/work_gateway.py` | NUEVO | Capa de aggregation no-HTTP para work_pipeline. Re-exporta 10 símbolos desde autoridades reales. |
| `assistant_os/pipelines/work_pipeline.py` | MODIFICADO | 7 import sites redirigidos de `webhook_server` a `work_gateway`. Anomalía `ACTION_WORK_UPDATE_BULK` corregida. |
| `assistant_os/pipelines/fin_pipeline.py` | MODIFICADO | Import `parse_expense` redirigido de `webhook_server` a `fin_expense` (autoridad directa). |
| `tests/test_orchestrator_policy.py` | MODIFICADO | 6 patches actualizados: `webhook_server.*` → `work_gateway.*` (pipeline path). |
| `tests/test_policy_decision.py` | MODIFICADO | 2 patches actualizados: `webhook_server.*` → `work_gateway.*` (pipeline path). |
| `tests/test_work_delete_integration.py` | MODIFICADO | 3 patches actualizados: `webhook_server.*` → `work_gateway.*` (pipeline path). |
| `DIAG_M08_FASE1.md` | NUEVO | Diagnóstico estructural de fase 1 con análisis de opciones A/B y justificación de la ruta elegida. |
| `FREEZE_M08.md` | NUEVO | Este documento. |

**Corrección de anomalía incluida:** `ACTION_WORK_UPDATE_BULK` era lazy-importada
desde `webhook_server` como alias `_ACTION_WORK_UPDATE_BULK` dentro de dos
funciones del pipeline, siendo que la misma constante ya estaba disponible en el
top-level del módulo desde `contracts`. Eliminado el import redundante; los dos
sitios de uso ahora referencian el símbolo del top-level directamente.

---

### VALIDACIÓN

**Tests corridos (scope M0.8):**

```
tests/test_orchestrator_policy.py       8/8   ✓
tests/test_policy_decision.py          66/66  ✓
tests/test_work_delete_integration.py  10/10  ✓
─────────────────────────────────────────────
Total M0.8 scope:                      84/84  ✓
```

**Scan estructural:**
```python
# AST scan — cero imports de webhook_server en pipelines
grep pipelines/ → 0 matches (AST verified)
```

**Baseline (tests no relacionados con M0.8):**
- 1804 passed (sin runners) — idéntico al baseline pre-M0.8
- 46 failures pre-existentes — ninguna introducida por M0.8
  - `test_work_update_singular`, `test_confirm_flow`, `test_domain_result`:
    fallan en `WebhookHandler._execute_work_update/bulk` — código no tocado
  - `test_code_propose_executor`, `test_code_review_executor`: fallan por API key
  - `test_chaperon`, `test_chat_layers`, `test_classifier`: pre-existing

**Invariantes verificadas:**

| Invariante | Estado |
|---|---|
| Cero imports `webhook_server` en `work_pipeline.py` (AST) | ✓ |
| Cero imports `webhook_server` en `fin_pipeline.py` (AST) | ✓ |
| `work_gateway.py` tiene cero imports HTTP / cero imports `webhook_server` | ✓ |
| `ACTION_WORK_UPDATE_BULK` única fuente: `contracts` top-level | ✓ |
| 84/84 en scope M0.8 | ✓ |
| 0 regresiones introducidas | ✓ |

---

### ALERTAS ARQUITECTÓNICAS

**El coupling `pipeline → HTTP` quedó RESUELTO. El desacople es real, no cosmético:**

- El código fuente de los pipelines ya no contiene ninguna referencia ejecutable
  a `webhook_server` (verificado por AST scan, no solo por grep de texto).
- `work_gateway.py` es un módulo real sin lógica de negocio y sin dependencias
  HTTP: es un re-export hub de integración puro.
- El cambio de patch target en los tests (de `webhook_server.*` a
  `work_gateway.*`) confirma que la frontera de mock es ahora la capa correcta.

**Coupling que queda pendiente (no introducido por M0.8):**

El `webhook_server.py` sigue importando directamente desde `integrations/notion`,
`context_store`, etc. para sus propios HTTP handlers. Esos 23 patches de tests
de webhook-path (`test_confirm_flow`, `test_domain_result`,
`test_work_update_singular`) apuntan a `webhook_server.*`. Esto es correcto:
son tests de la capa HTTP, no del pipeline. El coupling `WebhookHandler →
integrations` es estructuralmente legítimo.

---

### RIESGOS / NOTAS

**`work_gateway.py` como gateway estable vs. transición:**
El módulo es estable como capa de aggregation para el pipeline WORK. No es una
medida temporal: constituye la interfaz entre el dominio pipeline y la capa de
integraciones. En M0.9 se puede evaluar si los pipelines deben importar
directamente desde `integrations/notion` (Opción A del diagnóstico FASE 1),
lo que requeriría migrar los 23 patches de tests de webhook-path.

**Tests de webhook-path aún en `webhook_server.*`:**
Los 23 patches restantes en `test_confirm_flow`, `test_domain_result`,
`test_work_update_singular` y `test_webhook` cubren `WebhookHandler.*` — código
HTTP que legítimamente usa los mismos símbolos de integración desde su propio
namespace. No representan deuda técnica inmediata: representan tests de la capa
HTTP ejerciendo la capa HTTP.

**Candidato M0.9:** Pre-existing failures en `test_work_update_singular` y
`test_confirm_flow` (9 tests) exponen bugs en `WebhookHandler._execute_work_update`
que no fueron abordados en esta serie de dispatches.
