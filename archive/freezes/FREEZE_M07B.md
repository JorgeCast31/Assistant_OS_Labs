# Baseline Freeze — M0.7B: Kernel ↔ HTTP Decoupling (_create_plan_from_intent)
**Fecha:** 2026-03-30
**Branch:** reconcile/baseline-freeze
**Commit base:** 253fb68 (M0.7A freeze)

---

## DIAGNÓSTICO

### Dependencia invertida resuelta

`core/planning.py` importaba `_create_plan_from_intent` desde `webhook_server.py` —
una dependencia invertida Kernel→HTTP.  La función y su cluster de helpers
vivían en la capa HTTP sin justificación arquitectónica.

### Hallazgo crítico: parse_work_create_fields divergida

Al analizar el cluster, se encontró que `parse_work_create_fields` existía en
DOS lugares con implementaciones divergidas:

| Versión | Ubicación | Estado |
|---|---|---|
| `webhook_server.py` (línea 1081) | Copia stale | Menos status aliases, cleanup incompleto |
| `parsers/work_create_parser.py` | **Autoridad real** | Richer: más status aliases, limpieza de prefijo `prueba:`, mejor null handling |

Las 5 divergencias encontradas favorecían **todas** la versión del parser:
- `bloqueada` → parser mapea a WAITING, webhook deja como `BLOQUEADA`
- `urgente` → parser mapea a NEXT, webhook deja como `URGENTE`
- `nueva` → parser mapea a INBOX, webhook deja como `NUEVA`
- `Crea tarea de prueba: ui test` → parser extrae `ui test`, webhook da `prueba: ui test`
- `Título: .` → parser devuelve `None`, webhook devuelve `""` (ambos falsy)

Ningún test existente dependía del comportamiento stale de webhook.

---

## NUEVA FUENTE DE AUTORIDAD

**Módulo creado:** `assistant_os/core/planner.py`

Este módulo es el propietario real de toda la lógica de planificación del kernel.
Zero HTTP dependencies. Imports únicamente desde:
- `contracts.py` (Plan, make_plan, ACTION_*, RISK_*, TARGET_DB_*, DELETE_MODE_*, OP_*)
- `classifier.py` (is_work_query, parse_work_query_filters)
- `parsers/work_create_parser.py` (parse_work_create_fields — la versión richer)
- `parsers/work_delete_parser.py` (has_delete_intent, parse_work_delete_intent, etc.)
- `parsers/work_update_parser.py` (parse_work_update_intent, generate_update_preview)
- `parsers/work_mutation_parser.py` (lazy imports: is_bulk_delete, is_bulk_update)

### Funciones y constantes extraídas a `core/planner.py`

| Símbolo | Tipo | Línea original en webhook_server |
|---|---|---|
| `_TEST_INTENT_PATTERNS` | constant | 160 |
| `_TEST_TITLE_PREFIXES` | constant | 168 |
| `_TEST_RESET_PATTERNS` | constant | 171 |
| `_has_test_intent` | function | 177 |
| `_has_test_reset_intent` | function | 208 |
| `_INVALID_TITLE_PATTERNS` | constant | 256 |
| `_is_invalid_title` | function | 236 |
| `_WORK_CREATE_INTENT_PATTERN` | constant | 976 |
| `_WORK_CREATE_INTENT_REVERSED_PATTERN` | constant | 983 |
| `_has_create_intent` | function | 989 |
| `_WORK_QUERY_OVERRIDE_PATTERNS` | constant | 1016 |
| `_apply_routing_overrides` | function | 1026 |
| `_create_plan_from_intent` | function | 1113 |

**No movida:** `parse_work_create_fields` — ya tenía autoridad real en
`parsers/work_create_parser.py`. La copia stale en `webhook_server.py` fue
eliminada; `core/planner.py` importa directamente desde parsers.

---

## COMPATIBILIDAD / TESTS

### Re-exports en webhook_server.py

Para mantener backward compatibility con los 22+ test imports existentes,
`webhook_server.py` re-exporta explícitamente desde `core/planner.py`:

```python
# Re-exports explícitos — secundarios, no propietarios
from .core.planner import (
    _has_test_intent,
    _has_test_reset_intent,
    _is_invalid_title,
    _has_create_intent,
    _apply_routing_overrides,
    _create_plan_from_intent,
)
from .parsers.work_create_parser import parse_work_create_fields
```

El rol de estos re-exports es **explícitamente secundario**: la implementación
autoritativa vive en `core/planner.py` y `parsers/work_create_parser.py`.
`webhook_server` no es el owner.

### Tests: cero cambios necesarios

Los 22 imports directos de tests desde `webhook_server.*` siguen funcionando
via los re-exports. No se modificó ningún test en este sprint.

---

## INVARIANTES VERIFICADOS

| Invariante | Estado |
|---|---|
| `core/planning.py` no importa de `webhook_server` | ✓ |
| `core/planning.py` importa `_create_plan_from_intent` desde `core.planner` | ✓ |
| `_create_plan_from_intent` NO tiene `def` en `webhook_server.py` | ✓ |
| `webhook_server.py` re-exporta desde `core.planner` (explícitamente secundario) | ✓ |
| `parse_work_create_fields` re-exportada desde `parsers.work_create_parser` | ✓ |
| Suite core: 1578 passed, 0 failed | ✓ |
| Tests del cluster (185): 185 passed, 0 failed | ✓ |

---

## ALERTAS ARQUITECTÓNICAS POST-M0.7B

### ALERTA-2 COMPLETAMENTE RESUELTA ✓
- M0.7A: `core/semantic.py` desacoplado de `webhook_server` ✓
- M0.7B: `core/planning.py` desacoplado de `webhook_server` ✓

### Coupling residual documentado (fuera de scope de este sprint)

Los **domain pipelines** (`pipelines/work_pipeline.py`, `pipelines/fin_pipeline.py`)
siguen lazy-importando desde `webhook_server.py`:
- `work_pipeline.py`: `query_work_db`, `check_notion_available`, `get_notion_status`,
  `get_editable_field_options`, `update_work_item`
- `fin_pipeline.py`: `parse_expense`

Este coupling es **dominio → infraestructura HTTP**, no **kernel → HTTP**.
Los pipelines son domain layer y usar `webhook_server` como agregador de
integraciones HTTP es un patrón que puede mantenerse o refactorizarse en
un sprint dedicado. No es una violación del contrato kernel.

### Próximo candidato: extracción de integraciones HTTP

Si se quiere un desacople total, el siguiente paso sería crear un módulo
`assistant_os/integrations/notion.py` (u organizarlo por dominio) y hacer
que los pipelines importen desde ahí en lugar de `webhook_server`. Pero
ese es un sprint separado con mayor scope.

---

## CAMBIOS INCLUIDOS

| Archivo | Tipo | Descripción |
|---|---|---|
| `assistant_os/core/planner.py` | **NUEVO** | Módulo kernel con autoridad real de planificación |
| `assistant_os/core/planning.py` | Fix | Import desde `core.planner` (eliminada dependencia de webhook_server) |
| `assistant_os/webhook_server.py` | Refactor | Eliminadas ~450 líneas de definiciones; re-exports explícitos agregados |
