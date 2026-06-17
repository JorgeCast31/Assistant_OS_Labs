# RUNNER MANUAL PROTOCOL — DRAFT (dry-run sin código)

> **Estado:** *draft* de apoyo a `RUNNER_DESIGN_REVIEW.md`. **No es contrato vigente. No es implementación.**
> Describe cómo un humano ejecutaría **a mano** la lógica del Runner para validarla **antes** de plantear cualquier código.
> Si este protocolo manual no produce resultados limpios y reproducibles, **no se implementa Runner**.

---

## Propósito

Probar la lógica del Runner como un **procedimiento de papel**: un operador humano hace lo que el Runner haría, leyendo solo `main`, sin escribir estado, sin mergear, sin ejecutar. Sirve como el dry-run de `RUNNER_DESIGN_REVIEW.md §12` y como especificación legible de comportamiento.

## Precondiciones

- Trabajar sobre una copia/lectura de `main` (nunca sobre una rama como autoridad).
- Tener a la vista el contrato vigente (`README.md`, `RULES_OF_ENGAGEMENT.md`, `AGENT_CONTRACT.md`, `schemas/`).
- No tocar ningún archivo canónico (`tasks/`, `decisions/`, etc.). La única salida permitida es un cuaderno de observaciones separado.

## Procedimiento (loop conservador)

Para **cada** `coordination/tasks/TASK-NNNN.md` en `main`:

1. **Leer** `status`, `blocked`, `last_legit_status`, `assigned_agent`, `reviewer`, `reviewer_delegate`, `next_action`.
2. **Validar fail-closed.** ¿Falta un campo `required`? ¿`status`/`authority` fuera de enum? ¿Artefactos contradicen el `status`? ¿`reviewer == assigned_agent`?
   - Si **sí** ⇒ marcar **BLOCKED-OBS** (anotar motivo), notificar a Jorge, **no** proponer acción. Pasar a la siguiente tarea.
3. **Mapear estado → acción legal + rol** (tabla de `RUNNER_DESIGN_REVIEW.md §6`):
   - `DRAFT` ⇒ notificar **Jorge** (fijar `READY` in-file).
   - `READY` / `CHANGES_REQUESTED` ⇒ notificar **Claude** (executor).
   - `EVIDENCE_READY` (con WORKLOG+FINAL_REPORT presentes y reviewer ≠ executor) ⇒ notificar **Codex** (reviewer).
   - `DECISION_PROPOSED` / candidato listo ⇒ notificar **Jorge** (decisión humana). **Nunca** promover el candidato.
   - `IN_PROGRESS` / `IN_REVIEW` ⇒ observar (esperar), sin notificar despacho.
   - `HUMAN_DECISION` / `HANDOFF_TO_MSO` / `CLOSED_REJECTED` / `ABORTED` ⇒ **no-op**.
   - `BLOCKED` ⇒ notificar al rol del tramo + Jorge.
4. **Anotar** en el cuaderno de observaciones: `TASK-NNNN | status | acción legal | rol destino | (BLOCKED-OBS si aplica)`.
5. **No mutar nada.** Ningún `status`, ningún artefacto de autoridad, ningún merge.

Al terminar el barrido: **consolidar la cola** (todas las tareas que esperan acción) y entregarla como un único reporte.

## Lo que el operador (y el futuro Runner) NUNCA hace

- Mergear, aprobar PR, push a `main`.
- Escribir `human_final` / `effective_authority` / `approved_by` / `decided_by`.
- Promover un `DECISION_CANDIDATE` a `decisions/`.
- Fijar `HUMAN_DECISION` / `HANDOFF_TO_MSO` / `CLOSED_REJECTED` / `ABORTED`.
- Tocar MSO / Police / Policy / Auth / secrets / workflows.
- Ejecutar una tarea funcional.
- Tratar el chat o una rama como autoridad.

## Criterio de éxito del dry-run

- La cola derivada a mano coincide con la cola "esperada" construida independientemente por un humano.
- Todos los casos de ambigüedad/conflicto/no-auto-review producen **BLOCKED-OBS** (nunca un avance).
- Ningún paso del protocolo requiere una capacidad de autoridad.

Si se cumple, el resultado alimenta la decisión humana de Jorge sobre si plantear el **MVP read-only** (`RUNNER_DESIGN_REVIEW.md §13`) en un PR aparte. Si no se cumple, el hallazgo se documenta y **no** se avanza.
