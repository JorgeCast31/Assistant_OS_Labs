# Baseline Freeze — M0.6: PolicyDecision Authority Alignment
**Fecha:** 2026-03-29
**Branch:** reconcile/baseline-freeze
**Commit base:** 8cbf835 (M0.5A + M0.5B freeze)

---

## DIAGNÓSTICO

`PolicyDecision` era un contrato ornamental.

`core/policy.py` construía un objeto `PolicyDecision` completo con `execution_mode`,
`risk_level`, `routing_action` y todos los campos del contrato v1. Pero
`core/orchestrator.py` nunca lo leía. La decisión de routing usaba
`plan.requires_confirmation` directamente:

```python
# Pre-M0.6 (bug): policy calculado y descartado
policy = build_policy(req, intent, plan)  # ← asignado, nunca leído

if not plan.get("requires_confirmation"):  # ← señal real usada
    pipeline = get_pipeline(...)
    if pipeline:
        return pipeline(...)
```

Esto violaba el principio rector del sistema:
> *"Los contratos intermedios deben ser reales, no ornamentales."*

Adicionalmente, `_AUTO_EXECUTE_WHITELIST` no reflejaba todos los casos donde
`_create_plan_from_intent` establece `requires_confirmation=False` por intención
de diseño, haciendo imposible usar `execution_mode` como señal única sin
cambiar el comportamiento observable.

---

## CAMBIO REALIZADO

### Paso 1 — Alinear el whitelist con la realidad

`_AUTO_EXECUTE_WHITELIST` en `contracts.py` fue extendido para reflejar todos
los casos donde `_create_plan_from_intent` establece `requires_confirmation=False`:

| Entrada añadida | Justificación |
|---|---|
| `(WORK_UPDATE, RISK_LOW)` | Phase 1 es read-only preview; no hay side effects. El planner siempre asigna `requires_confirmation=False`. |
| `(FIN_EXPENSE, RISK_MEDIUM)` | "Single expense auto-executes" — comentario explícito en `_create_plan_from_intent`. |

`ACTION_COMMAND` fue añadido al conjunto bloqueado en `determine_execution_mode()`.
No tiene pipeline registrado; producir `plan_confirmation_required` para él sería
semánticamente incorrecto. Ahora produce `EXECUTION_MODE_BLOCKED` → `plan_generated`.

### Paso 2 — Hacer el orchestrator leer PolicyDecision

`core/orchestrator.py` ahora extrae `execution_mode` del objeto `PolicyDecision`
y despacha exclusivamente sobre él:

```python
# Post-M0.6: policy.execution_mode es la señal autoritativa
policy = build_policy(req, intent, plan)
execution_mode = policy.get("execution_mode", EXECUTION_MODE_CONFIRM)

if execution_mode == EXECUTION_MODE_AUTO:
    pipeline = get_pipeline(action_domain(action))
    if pipeline:
        return pipeline(plan_for_exec, context_id)

if execution_mode in (EXECUTION_MODE_CONFIRM, EXECUTION_MODE_CLARIFY):
    return make_domain_result(RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED, ...)

# EXECUTION_MODE_BLOCKED → plan_generated
return make_domain_result(RESULT_TYPE_PLAN_GENERATED, ...)
```

`plan.requires_confirmation` sigue existiendo como metadata en el plan
(preservado para UI, audit y downstream consumers), pero ya **no se lee en el
orchestrator** como señal de decisión.

---

## CONTRATO RESULTANTE

> **`PolicyDecision.execution_mode` gobierna la decisión de ejecución en el orchestrator.**

El contrato es real. La asignación `policy = build_policy(...)` tiene efecto
observable. Cambiar `execution_mode` cambia el comportamiento del sistema.

Mapping autoritativo:

| `execution_mode` | Comportamiento del orchestrator |
|---|---|
| `"auto"` | Ejecuta el pipeline registrado para el dominio de la acción |
| `"confirm"` | Retorna `plan_confirmation_required` — espera aprobación del usuario |
| `"clarify"` | Tratado como `confirm` (sin response type dedicado aún) |
| `"blocked"` | Retorna `plan_generated` — routing informacional, sin ejecución |

---

## CAMBIOS INCLUIDOS

| Archivo | Tipo de cambio | Descripción |
|---|---|---|
| `assistant_os/contracts.py` | Fix | `_AUTO_EXECUTE_WHITELIST` +2 entradas: `(WORK_UPDATE, RISK_LOW)`, `(FIN_EXPENSE, RISK_MEDIUM)` |
| `assistant_os/contracts.py` | Fix | `determine_execution_mode()`: `ACTION_COMMAND` agregado al conjunto bloqueado |
| `assistant_os/core/orchestrator.py` | Fix | Dispatch reescrito sobre `policy.execution_mode`; `plan.requires_confirmation` removido como señal decisoria |
| `tests/test_policy_decision.py` | Tests | +12 tests: `TestWhitelistAlignment` + `TestCommandActionBlocked` |
| `tests/test_orchestrator_policy.py` | Tests (nuevo) | 8 tests: auto-execute path, confirm path, `TestOrchestratorPolicyIsAuthoritative` (patch directo de `build_policy`) |
| `tests/test_plan_first.py` | Test fix | `test_fin_expense_medium_risk_does_not_auto_execute` → `test_fin_expense_medium_risk_auto_executes` (comportamiento correcto) |

---

## VALIDACIÓN

### Suite base
Worktree original contra live source post-M0.6:
```
844 passed, 0 failed — sin regresión
```

### Tests de zona M0.6
```
106 passed, 0 failed
```

### Invariantes verificados programáticamente

| Invariante | Verificado |
|---|---|
| `orchestrator.handle_request` no hace branch sobre `plan.requires_confirmation` | ✓ |
| `orchestrator.handle_request` lee `policy.execution_mode` | ✓ |
| `_AUTO_EXECUTE_WHITELIST` contiene `(WORK_UPDATE, RISK_LOW)` | ✓ |
| `_AUTO_EXECUTE_WHITELIST` contiene `(FIN_EXPENSE, RISK_MEDIUM)` | ✓ |
| `determine_execution_mode(ACTION_COMMAND, ...) == "blocked"` | ✓ |
| `WORK_QUERY → execution_mode=auto → result_type=work_query` | ✓ |
| `WORK_CREATE → execution_mode=confirm → result_type=plan_confirmation_required` | ✓ |
| Forzar `build_policy` a retornar `confirm` bloquea pipeline de WORK_QUERY | ✓ |
| Forzar `build_policy` a retornar `blocked` produce `plan_generated` | ✓ |

---

## ALERTAS ARQUITECTÓNICAS

### ALERTA-1 RESUELTA: PolicyDecision ya es contrato REAL ✓
`PolicyDecision.execution_mode` gobierna el orchestrator. El contrato tiene
efecto observable y verificable mediante test.

### ALERTA-2 ACTIVA: Kernel importa desde HTTP layer
`core/semantic.py` y `core/planning.py` siguen haciendo lazy-import de
`webhook_server.classify_text` y `_create_plan_from_intent`. Dependencia
invertida Kernel → HTTP no resuelta. Fuera de scope de M0.6.

### ALERTA-3 ACTIVA: Lógica de dominio en capas incorrectas
`_create_plan_from_intent` y `classify_text` siguen en `webhook_server.py`.
Fuera de scope de M0.6.

---

## RIESGOS / NOTAS

- **`EXECUTION_MODE_CLARIFY`** se trata como `confirm` por ahora. No se produce
  en ningún path real (requiere `missing_fields` en `build_policy`, que nunca se
  pasa en el flujo actual). Deuda identificada, no activa.

- **Whitelist como fuente de verdad dual**: `_AUTO_EXECUTE_WHITELIST` es ahora la
  fuente que tanto `should_auto_execute()` como `determine_execution_mode()`
  consultan. Los dos siguen siendo consistentes entre sí.

- **`plan.requires_confirmation` sigue en el plan**: no fue removido del contrato
  `Plan` ni de `_create_plan_from_intent`. Es metadata válida para UI y audit.
  Solo se removió como señal de decisión en el orchestrator.
