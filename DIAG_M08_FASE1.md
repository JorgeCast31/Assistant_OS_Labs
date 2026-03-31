# Diagnóstico M0.8 FASE 1 — Pipeline → webhook_server Coupling
**Fecha:** 2026-03-30
**Scope:** `assistant_os/pipelines/` → `assistant_os/webhook_server.py`
**Estado:** DIAGNÓSTICO ÚNICAMENTE — cero cambios aplicados

---

## RESUMEN EJECUTIVO

Los domain pipelines (`work_pipeline.py`, `fin_pipeline.py`) importan **12 símbolos**
desde `webhook_server` usando el patrón lazy-import-for-patchability. Ninguno de esos
símbolos tiene su autoridad real en `webhook_server`: todos son re-exports que
`webhook_server` centraliza en su encabezado. Las autoridades reales están en
4 módulos distintos. El coupling es estructuralmente distinto al de M0.7:
no es Kernel→HTTP, sino Domain→Aggregator-HTTP.

---

## DIAGNÓSTICO

### Mapa de imports activos

#### `work_pipeline.py` — 6 import sites, 11 símbolos

| Import site | Función | Símbolos |
|---|---|---|
| `_work_query_execute` | lazy | `check_notion_available`, `get_notion_status`, `format_work_query_response` |
| `_work_update_preview_execute` | lazy | `check_notion_available`, `get_notion_status`, `get_editable_field_options`, `search_work_items_with_filters`, `search_work_items_by_title`, `get_work_item_by_id`, `store_pending_plan`, `generate_update_preview`, `query_work_db`, `ACTION_WORK_UPDATE_BULK` |
| `_work_update_execute` | lazy | (continuación de preview — mismo scope) |
| `_work_update_bulk_execute` | lazy | subset de los anteriores |
| `_work_create_execute` | lazy | `check_notion_available`, `get_notion_status` |
| `_work_delete_execute` | lazy | `check_notion_available`, `get_notion_status` |

#### `fin_pipeline.py` — 1 import site, 1 símbolo

| Import site | Función | Símbolo |
|---|---|---|
| `_fin_expense_execute` | lazy | `parse_expense` |

---

### Clasificación por tipo de dependencia

| Símbolo | Tipo | Dueño real | Módulo real |
|---|---|---|---|
| `check_notion_available` | integración externa (Notion) | `integrations/notion.py` | línea 168 |
| `get_notion_status` | integración externa (Notion) | `integrations/notion.py` | línea 183 |
| `query_work_db` | integración externa (Notion) | `integrations/notion.py` | línea 543 |
| `format_work_query_response` | integración externa (Notion) | `integrations/notion.py` | línea 640 |
| `get_work_item_by_id` | integración externa (Notion) | `integrations/notion.py` | línea 1088 |
| `get_editable_field_options` | integración externa (Notion) | `integrations/notion.py` | línea 1442 |
| `search_work_items_by_title` | integración externa (Notion) | `integrations/notion.py` | línea 1483 |
| `search_work_items_with_filters` | integración externa (Notion) | `integrations/notion.py` | línea 1629 |
| `store_pending_plan` | estado / contexto | `context_store.py` | línea 137 |
| `generate_update_preview` | parser / formatting | `parsers/work_update_parser.py` | línea 592 |
| `ACTION_WORK_UPDATE_BULK` | contrato / constante | `contracts.py` | top-level |
| `parse_expense` | parser de dominio FIN | `fin_expense.py` | línea 521 |

**Categorías:**
- 8 × integración externa Notion
- 1 × estado de contexto
- 1 × parser/formatter
- 1 × constante de contrato (ya importada directamente en el top del pipeline — ver abajo)
- 1 × parser de dominio FIN

---

### Anomalía detectada: `ACTION_WORK_UPDATE_BULK` duplicada

`work_pipeline.py` importa `ACTION_WORK_UPDATE_BULK` desde `contracts` en su bloque
top-level (línea 26) **Y** la re-importa desde `webhook_server` como alias
`_ACTION_WORK_UPDATE_BULK` dentro de `_work_update_preview_execute` (lazy import).

El alias `_ACTION_WORK_UPDATE_BULK` se usa únicamente en esa función. La constante
ya disponible en el módulo es idéntica. Este es un remanente del patrón lazy-import
que no tiene justificación: `ACTION_WORK_UPDATE_BULK` es una constante de `contracts`,
no una función patcheable en tests. No requiere lazy-import.

---

## ANÁLISIS DE IMPACTO EN TESTS

### Patches activos via `webhook_server.*` namespace

| Símbolo | Patches totales | Archivos afectados |
|---|---|---|
| `get_editable_field_options` | 11 | `test_confirm_flow.py` (5), `test_domain_result.py` (6) |
| `check_notion_available` | 11 | `test_domain_result.py` (4), `test_orchestrator_policy.py` (4), `test_policy_decision.py` (1), `test_work_delete_integration.py` (2) |
| `query_work_db` | 6 | `test_domain_result.py` (3), `test_orchestrator_policy.py` (3), `test_policy_decision.py` (1), `test_webhook.py` (1) |
| `get_notion_status` | 4 | `test_domain_result.py` (1), `test_work_delete_integration.py` (1), `test_work_update_singular.py` (2) |
| `format_work_query_response` | 2 | `test_domain_result.py` (2) |

**Total patches a migrar si se redirigen imports directamente: ~34 patches**

### Por qué funcionan hoy

`webhook_server.py` importa estos símbolos a nivel de módulo desde sus dueños
reales (no son lazy-imports en `webhook_server`):

```python
# webhook_server.py — top-level imports (lines 56–103)
from .context_store import store_pending_plan, ...
from .fin_expense import parse_expense, ...
from .integrations.notion import (
    query_work_db, format_work_query_response,
    check_notion_available, get_notion_status, get_work_item_by_id,
    search_work_items_by_title, search_work_items_with_filters,
    get_editable_field_options,
)
from .parsers.work_update_parser import generate_update_preview, ...
```

Cuando un pipeline hace `from ..webhook_server import check_notion_available`
en tiempo de ejecución del test, Python resuelve el nombre en el namespace de
`webhook_server`. El patch sobre `assistant_os.webhook_server.check_notion_available`
reemplaza ese nombre en ese namespace → el mock se activa correctamente.

Si el pipeline importara directamente desde `integrations.notion`, el patch target
correcto sería `assistant_os.integrations.notion.check_notion_available`. Los
34 patches actuales serían inefectivos sin actualización.

---

## CAUSA RAÍZ DEL COUPLING

El patrón `lazy-import-from-webhook_server` en los pipelines no surgió de una
decisión arquitectónica: surgió de la necesidad práctica de que los mocks de test
funcionen, en un momento en que `webhook_server` era el único punto de entrada
conocido del sistema. Con el tiempo se convirtió en la convención de facto.

`webhook_server` no añade lógica entre el pipeline y las integraciones —
es un pass-through puro. El coupling es **artificial**: no existe por necesidad
funcional sino por inercia del patrón de patcheo.

---

## OPCIONES DE REFACTOR

### Opción A — Redirección directa con migración de patches
**Qué hace:** Pipelines importan lazy desde sus dueños reales.
Patches se actualizan al nuevo namespace.

```
work_pipeline.py:
  from ..webhook_server import check_notion_available
  → from ..integrations.notion import check_notion_available

test_domain_result.py:
  @patch("assistant_os.webhook_server.check_notion_available", ...)
  → @patch("assistant_os.integrations.notion.check_notion_available", ...)
```

**Ventajas:** Dependencias explícitas. `webhook_server` deja de ser relevante
para los pipelines. Arquitectura limpia por capas.

**Costos:** ~34 patches a migrar en 6 archivos de test. Riesgo moderado de
regresiones si algún patch se actualiza incorrectamente. El refactor toca
el pipeline + todos los tests que lo cubren en un mismo commit.

**Viabilidad:** Alta, pero requiere disciplina. Cada símbolo debe actualizarse
atómicamente (pipeline + todos sus patches a la vez).

---

### Opción B — webhook_server como Integration Hub explícito (re-export hub)
**Qué hace:** Los pipelines siguen importando desde `webhook_server`, pero se
documenta explícitamente que `webhook_server` actúa como **Integration Aggregator**
para los domain pipelines — no como autoridad real. Se añade un bloque de
re-exports explícitos y comentados (análogo al bloque de planner en M0.7B).

```python
# webhook_server.py
# ---------------------------------------------------------------------------
# Integration Hub — re-exports for domain pipelines (backward compatibility)
# Authoritative implementations live in integrations/notion.py, context_store,
# parsers/work_update_parser, fin_expense.
# ---------------------------------------------------------------------------
from .integrations.notion import (
    check_notion_available, get_notion_status, query_work_db,
    format_work_query_response, get_work_item_by_id,
    search_work_items_by_title, search_work_items_with_filters,
    get_editable_field_options,
)
from .context_store import store_pending_plan, ...
from .parsers.work_update_parser import generate_update_preview, ...
from .fin_expense import parse_expense, ...
```

**Ventajas:** Cero cambios en tests. Bajo riesgo. Acepta `webhook_server`
como aggregator explícito (patrón bien establecido en microservicios HTTP).
La autoridad real ya está documentada en este diagnóstico.

**Costos:** `webhook_server` mantiene una responsabilidad de aggregation.
El coupling Domain→`webhook_server` persiste, aunque es explícito y trazable.
Requiere disciplina para no añadir lógica real en los re-exports.

**Viabilidad:** Alta. Es el mismo patrón que M0.7B aplicó exitosamente para
los 22 imports de test de `_create_plan_from_intent`.

---

### Recomendación

**Opción B para M0.8**, con conversión de los imports de `webhook_server` a
imports explícitamente marcados como "secondary re-exports" en el encabezado
del archivo. Razones:

1. La violación no es kernel→HTTP sino domain→aggregator, que es un patrón
   aceptable si está explícitamente documentado.
2. Los domain pipelines **deben** importar integraciones de algún lado — la
   pregunta es si ese lado es `webhook_server` (aggregator) o `integrations.notion`
   directamente. Ambos son HTTP layer desde la perspectiva del pipeline.
3. 34 patches son un scope de testing significativo; la migración atómica
   es posible pero agrega riesgo sin beneficio arquitectónico inmediato.
4. La Opción A es correcta pero es M0.9 o posterior, cuando se puedan
   actualizar los tests con cobertura end-to-end verificada.

**Excepción clara:** `ACTION_WORK_UPDATE_BULK` — este símbolo debe eliminarse
del lazy-import en `_work_update_preview_execute`. Es una constante de `contracts`,
ya está disponible en el módulo, y no requiere patcheo. Cambio seguro y de
bajo riesgo que puede hacerse en M0.8 sin impacto en tests.

---

## INVARIANTES REQUERIDOS POST-M0.8

| Invariante | Estrategia |
|---|---|
| `work_pipeline.py` no importa lógica de negocio desde `webhook_server` | ✓ ya cumplido (solo integraciones) |
| `webhook_server` re-exports marcados explícitamente como secundarios | pendiente — Opción B |
| `ACTION_WORK_UPDATE_BULK` importada desde `contracts` únicamente | pendiente — fix puntual |
| Autoridad real documentada para cada símbolo | ✓ este documento |
| Suite completa: 0 regresiones | validar post-cambio |

---

## SCOPE PROPUESTO PARA M0.8

**FASE 1** (este diagnóstico): ✓ COMPLETO

**FASE 2 — Opción B:**
1. Auditar el bloque de imports en `webhook_server.py` (líneas 56–103): confirmar
   que todos los re-exports del Integration Hub están agrupados y comentados
   con "secondary re-export — authority in [módulo real]".
2. Eliminar el lazy-import redundante de `ACTION_WORK_UPDATE_BULK` en
   `_work_update_preview_execute` (usar la constante ya importada en top-level).
3. Actualizar docstring de `work_pipeline.py` para reflejar que `webhook_server`
   actúa como integration aggregator (no autoridad real).
4. Validar suite completa post-cambio.

**FASE 3 (futuro — M0.9):** Migración Opción A — redirección de imports a
`integrations.notion` con actualización atómica de los 34 patches de test.
Candidato para cuando se construya un integration test layer que no dependa
del patcheo por namespace.
