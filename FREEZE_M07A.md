# Baseline Freeze — M0.7A: Kernel ↔ HTTP Decoupling (classify_text)
**Fecha:** 2026-03-29
**Branch:** reconcile/baseline-freeze
**Commit base:** 9e689fc (M0.6 freeze)

---

## DIAGNÓSTICO

Dos dependencias invertidas Kernel → HTTP existían al inicio de M0.7:

| Capa | Función | Definida en | Tipo de fix |
|---|---|---|---|
| `core/semantic.py` | `classify_text` | `classifier.py` (re-exportada por webhook_server) | **M0.7A — quirúrgico** |
| `core/planning.py` | `_create_plan_from_intent` | `webhook_server.py` (150+ líneas) | **M0.7B — deferred** |

### Por qué M0.7A es quirúrgico

`classify_text` tiene su implementación real en `assistant_os/classifier.py`.
`webhook_server.py` solo la re-exporta con `from .classifier import classify_text`
en su encabezado (línea 60-64). El único cambio necesario en producción es
redirigir el lazy-import en `semantic.py`:

```python
# Pre-M0.7A (bug): dependencia invertida Kernel → HTTP
from ..webhook_server import classify_text  # ← webhook_server es solo un re-exportador

# Post-M0.7A: dependencia correcta Kernel → Classifier
from ..classifier import classify_text
```

### Por qué M0.7B es deferred

`_create_plan_from_intent` está **definida** en `webhook_server.py` (líneas 1202–1424,
~220 líneas). No es una re-exportación — es la implementación real. Moverla arrastra
un cluster de helpers privados:

| Helper | Definido en |
|---|---|
| `_apply_routing_overrides` | `webhook_server.py` |
| `_is_invalid_title` | `webhook_server.py` |
| `generate_delete_preview` | `webhook_server.py` (o parsers) |
| `generate_update_preview` | `webhook_server.py` (o parsers) |

Además, 22 tests importan directamente desde `webhook_server._create_plan_from_intent`
(imports directos, no patches). Mover requiere:
1. Nuevo módulo `assistant_os/core/planner.py`
2. Re-export temporal de compatibilidad en `webhook_server.py`
3. Actualización de 22 imports en tests
4. Validación de que ningún helper interno queda huérfano

Scope correcto para M0.7B como milestone dedicado.

---

## CAMBIO REALIZADO (M0.7A)

### `assistant_os/core/semantic.py`

**Import redirigido:**
```python
# Antes
from ..webhook_server import classify_text

# Después
from ..classifier import classify_text
```

**Docstring actualizado** para reflejar la nueva propiedad del símbolo.

### Tests actualizados

Todos los tests que van por `handle_request → core/semantic.classify → classify_text`
deben parchear `assistant_os.classifier.classify_text`, no `webhook_server.classify_text`.

| Archivo | Patches actualizados | Descripción |
|---|---|---|
| `tests/test_orchestrator_policy.py` | 8 → `classifier.classify_text` | Tests de `handle_request` |
| `tests/test_policy_decision.py` | 2 → `classifier.classify_text` | `TestRouteByClassificationIntegration` |

**Nota sobre `TestRouteByClassificationIntegration`:**
Aunque estos tests invocan `WebhookHandler._route_text_by_classification`, esa función
es un adaptador puro que delega inmediatamente a `handle_request`. El path completo
pasa por `core/semantic.classify`, por lo que el patch target correcto es
`classifier.classify_text`. Los patches restantes en `test_policy_decision.py`
que parchean `webhook_server.classify_text` son para tests que no pasan por el kernel.

---

## INVARIANTES VERIFICADOS

| Invariante | Estado |
|---|---|
| `core/semantic.py` no contiene imports ejecutables de `webhook_server` | ✓ |
| `core/semantic.py` importa `classify_text` desde `classifier` | ✓ |
| `core/planning.py` sigue importando de `webhook_server` (deferred M0.7B) | documentado |
| 0 patches `webhook_server.classify_text` en `test_orchestrator_policy.py` | ✓ |
| Suite core: 1578 passed, 0 failed | ✓ |
| `test_orchestrator_policy.py`: 8/8 passed | ✓ |
| `test_policy_decision.py`: 66/66 passed | ✓ |

---

## ALERTAS ARQUITECTÓNICAS

### ALERTA-1 RESUELTA: PolicyDecision ya es contrato REAL ✓
(Resuelta en M0.6)

### ALERTA-2 PARCIALMENTE RESUELTA: Kernel importa desde HTTP layer
- `core/semantic.py` → `classifier.classify_text` ✓ **RESUELTA en M0.7A**
- `core/planning.py` → `webhook_server._create_plan_from_intent` ⚠ **ACTIVA → M0.7B**

### ALERTA-3 ACTIVA: Lógica de dominio en capas incorrectas
`_create_plan_from_intent` y `classify_text` siguen en `webhook_server.py` como
punto de definición o re-export. `classify_text` es menor (solo re-export); el
verdadero problema es `_create_plan_from_intent`. Fuera de scope de M0.7A.

---

## SCOPE M0.7B (próximo milestone)

**Objetivo:** Extraer `_create_plan_from_intent` de `webhook_server.py` a un módulo
kernel-propiedad (`assistant_os/core/planner.py`).

**Pasos:**
1. Crear `assistant_os/core/planner.py` con `_create_plan_from_intent` y sus helpers privados
2. Agregar re-export en `webhook_server.py` para compatibilidad backward:
   `from .core.planner import _create_plan_from_intent`
3. Actualizar `core/planning.py`: `from ..webhook_server import _create_plan_from_intent`
   → `from .planner import _create_plan_from_intent`
4. Actualizar 22 imports directos en tests (o dejar el re-export permanentemente
   si los tests son de integración que validan la función directamente)
5. Validar suite y verificar invariante: `core/planning.py` no importa de `webhook_server`

**Riesgo principal:** helpers privados con acoplamiento implícito a otros símbolos
de `webhook_server.py`. Requiere auditoría de dependencias de `_apply_routing_overrides`
e `_is_invalid_title` antes de mover.

---

## CAMBIOS INCLUIDOS

| Archivo | Tipo | Descripción |
|---|---|---|
| `assistant_os/core/semantic.py` | Fix | Import `classify_text` redirigido de `webhook_server` → `classifier` |
| `tests/test_orchestrator_policy.py` | Test fix | 8 patches actualizados a `classifier.classify_text` |
| `tests/test_policy_decision.py` | Test fix | 2 patches actualizados a `classifier.classify_text` |
