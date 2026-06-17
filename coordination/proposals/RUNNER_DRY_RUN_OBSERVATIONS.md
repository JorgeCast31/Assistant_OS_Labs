# RUNNER DRY-RUN — OBSERVACIONES Y AJUSTES PROPUESTOS

> **Estado:** observaciones de apoyo a `TASK-0005` (dry-run manual). **No es contrato vigente. No es implementación. No es autoridad.**
> Insumo para una eventual `TASK-0006 — MVP Read-Only Queue Reporter Proposal`. Solo Jorge decide si se abre ese ciclo.

## Origen

Estas observaciones salen de simular **a mano** (Claude, leyendo `main`, sin código) el protocolo de `RUNNER_MANUAL_PROTOCOL_DRAFT.md` sobre las 4 tareas en `main` (`TASK-0001..0004`). Detalle: `worklogs/TASK-0005.WORKLOG.md` y `reports/TASK-0005.FINAL_REPORT.md`.

## Resultado en una línea

El dry-run manual **funciona sin código**, la cola es **útil**, el protocolo **no requiere autoridad** — y reveló **4 fricciones** que conviene resolver **antes** de implementar un MVP.

## Fricciones → ajustes propuestos (para el MVP, todos read-only)

| # | Fricción observada | Ajuste propuesto (sin dar autoridad al Runner) |
|---|---|---|
| F1 | TASK-0001 carece de `last_legit_status` (campo `required` v3); es un dogfood fallido **preservado a propósito** (naming v1). Fail-closed estricto la marcaría ambigua para siempre. | El MVP reconoce un conjunto de tareas **históricas/archivadas/exentas** (p. ej. por naming v1 o por un marcador explícito in-file) y las clasifica como `ARCHIVED/INFORMATIVE`, no como BLOCKED-OBS accionable. La decisión de exención es de Jorge, no del Runner. |
| F2 | TASK-0003 está en `DRAFT` pero su contenido **ya es contrato activo** (#246/#247/#249). `DRAFT → "Jorge fija READY"` es engañoso. | El MVP **no propone transición** para una DRAFT cuyo entregable detecta ya presente/adoptado en `main`; la marca `DRAFT-SUPERSEDED?` y la deja para que Jorge la cierre/aborte. El Runner **no** cierra nada. |
| F3 | El "siguiente paso" real de una DRAFT a veces vive en prosa (`next_action`), que el diseño manda **ignorar** como instrucción (§R5). Enum-solo es insuficiente. | El MVP se limita a **reportar y marcar**: para DRAFTs ambiguas no inventa la acción; muestra `status` + bandera (`SUPERSEDED?`/`AWAITING-READY?`) y delega el juicio a Jorge. Mantiene §R5 (no ejecuta prosa). Si se quisiera desambiguar de forma machine-readable, sería un cambio de **schema** (estado nuevo), revisable aparte. |
| F4 | `HUMAN_DECISION` aparece como terminal-en-plano, pero el enum lista `HANDOFF_TO_MSO` como "siguiente" (exclusivo de MSO, fuera del plano). | El MVP etiqueta `HUMAN_DECISION` como `AWAITING-MSO (out-of-plane)` → **no-op** del Runner, no accionable. |

## Invariantes que cualquier ajuste debe preservar

- El Runner sigue siendo **solo lectura sobre `main`**; ninguno de estos ajustes le da merge/approve/promote/execute.
- Ningún ajuste hace que el Runner **cierre, aborte o promueva** tareas; como máximo **marca y reporta** para que decida Jorge.
- Se mantienen `authorship != authority`, fail-closed, no auto-review, y "si no está en `main`, no pasó".

## Recomendación

Proceder a **`TASK-0006 — MVP Read-Only Queue Reporter Proposal`** (diseño, no implementación), tomando F1–F4 como **restricciones de entrada**. El MVP debe ser un **lector que ordena y marca la cola**, nunca un actor con autoridad. Esta recomendación es una **propuesta**; la decisión es de Jorge por evento verificable.
