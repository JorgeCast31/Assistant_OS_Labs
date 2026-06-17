# READ-ONLY QUEUE REPORTER — CRITERIOS DE PRUEBA (sin código)

> **Estado:** apoyo a `READ_ONLY_QUEUE_REPORTER_MVP.md` (TASK-0006). **No es implementación ni contrato vigente.**
> Define, como **tabla de prueba conceptual**, qué debería verificar una implementación futura. No ejecuta nada.

## Cómo usar

Cada caso es una **aserción** sobre el comportamiento esperado del Reporter dado un estado de `main`. En una implementación futura se traducirían a tests; hoy son el **contrato de aceptación** revisable por Codex y Jorge. Todas las pruebas asumen entrada de **solo lectura** y output **efímero** (stdout).

## Casos — clasificación (tabla §6 del MVP)

| ID | Entrada (estado en `main`) | Salida esperada (`classification` / `role` / flags) |
|---|---|---|
| T-C1 | TASK con `status` ausente o fuera de enum | `BLOCKED_OBS` / JORGE / — |
| T-C2 | TASK legacy v1 sin `last_legit_status` (TASK-0001) | `LEGACY_AMBIGUOUS` / NONE / `missing:last_legit_status`; **el barrido NO aborta** |
| T-C3 | `status ∈ {HANDOFF_TO_MSO, CLOSED_REJECTED, ABORTED}` | `TERMINAL` / NONE / — |
| T-C4 | `status == HUMAN_DECISION` (TASK-0002) | `CLOSED_IN_COORDINATION_PLANE` / MSO / `MSO_ONLY_NEXT`; **no** propone `HANDOFF_TO_MSO` |
| T-C5 | `status ∈ {IN_PROGRESS, IN_REVIEW}` | `WAITING` / NONE / — |
| T-C6 | `status == EVIDENCE_READY`, report+worklog presentes, reviewer≠executor | `ACTIONABLE_BY_AGENT` / CODEX / next `EVIDENCE_READY→IN_REVIEW` |
| T-C6b | `status == EVIDENCE_READY` pero reviewer==executor | `BLOCKED_OBS` (no-auto-review) / JORGE / — |
| T-C7 | `status == CHANGES_REQUESTED` | `ACTIONABLE_BY_AGENT` / CLAUDE / next `→IN_PROGRESS` |
| T-C8 | `status == READY` | `ACTIONABLE_BY_AGENT` / CLAUDE / next `→IN_PROGRESS` |
| T-C9 | `status == DRAFT` con entregables ya presentes en `main` (TASK-0003/0004/0005) | `DRAFT_SUPERSEDED` o `DRAFT_DESIGN_MERGED` / JORGE / `REQUIRES_HUMAN_INTERPRETATION`; **nunca** `READY` ciego |
| T-C10 | `status == DRAFT` sin entregables presentes | `ACTIONABLE_BY_JORGE` / JORGE / next `DRAFT→READY` (candidato) |
| T-C11 | Conflicto `status` vs artefactos | `BLOCKED_OBS` / JORGE / — |

## Casos — F1–F4 (requisitos obligatorios)

| ID | Requisito | Aserción |
|---|---|---|
| T-F1 | Tolerancia legacy | Dado TASK-0001 sin `last_legit_status`, el reporte la marca `LEGACY_AMBIGUOUS` **y** clasifica correctamente el resto de tareas (sin fallo global). |
| T-F2 | DRAFT no-ciego | Dado un DRAFT cuyos `evidence`/`files_touched` (no-tasks) ya existen en `main`, el reporte **no** sugiere `READY`; emite `DRAFT_SUPERSEDED`/`DRAFT_DESIGN_MERGED`. |
| T-F2b | DRAFT activo | Dado un DRAFT **sin** entregables presentes, el reporte sí lo lista como candidato `DRAFT→READY`. |
| T-F3 | No inventar estado | Cuando el siguiente paso no se deduce del enum, el reporte emite `REQUIRES_HUMAN_INTERPRETATION` y **no** propone una transición concreta. |
| T-F4 | HUMAN_DECISION fuera del plano | Dado `HUMAN_DECISION`, el reporte clasifica `CLOSED_IN_COORDINATION_PLANE/MSO_ONLY_NEXT` y **nunca** emite ni sugiere `HANDOFF_TO_MSO`. |

## Casos — invariantes de seguridad (deben fallar el build si se violan)

| ID | Invariante | Aserción negativa |
|---|---|---|
| T-S1 | Read-only | El proceso **no** abre ningún archivo en modo escritura; no hay `write`/`merge`/`push`/`approve` en su superficie. |
| T-S2 | Anti-inyección | Un `next_action`/cuerpo con texto tipo "ejecuta X / mergea Y" **no** produce ninguna acción ni cambia la clasificación. |
| T-S3 | Sin secretos/red | El proceso no lee `.env`/secrets/auth ni abre red saliente. |
| T-S4 | Sin persistencia | El proceso no crea/modifica archivos en el repo (output solo a stdout). |
| T-S5 | Determinismo | Dado el mismo commit de `main`, dos corridas producen el mismo reporte. |
| T-S6 | Fail-closed | Entrada inválida ⇒ `BLOCKED_OBS`/`LEGACY_AMBIGUOUS`, nunca una acción sugerida errónea. |

## Criterio de "listo para decisión de Jorge"

El MVP estaría listo para que Jorge decida sobre su implementación cuando **todos** los casos T-C*, T-F*, T-S* estén:

1. revisados por Codex como correctos y suficientes;
2. coherentes con el contrato v3.1 y el diseño de TASK-0004;
3. confirmados como **read-only sin autoridad** (T-S1–T-S6).

> Estos criterios son una **propuesta**. La decisión de autorizar implementación es de Jorge, por evento verificable, en un ciclo separado. El Runner/Reporter sigue **bloqueado**.
