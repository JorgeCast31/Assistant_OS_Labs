# RULES_OF_ENGAGEMENT — coordination/ — **v2**

> Reglas de quién puede escribir qué y cuándo. **Fail-closed:** ante ambigüedad, campo faltante o transición no permitida, la tarea se **bloquea**; no se avanza ni se asume comportamiento.
> **Principio rector v2:** `main` es la única fuente autoritativa. Las ramas proponen. El chat nunca es autoridad. **"Si no está commiteado, no pasó."**

## Roles

- **Iniciador** — Jorge, o un agente *proponiendo* una tarea. Crea `TASK.md`. **Solo Jorge** puede fijar `READY` in-file en `main`.
- **Ejecutor (executor)** — agente que produce evidencia. Por defecto: **Claude**.
- **Revisor (reviewer)** — agente que verifica la evidencia. Por defecto: **Codex**. Puede haber `reviewer_delegate` registrado in-file.
- **Autoridad humana** — **solo Jorge**. Decide.
- **Autoridad de ejecución** — **solo MSO** (fuera de este plano).

Ejecutor y revisor (y `reviewer_delegate`) deben ser agentes **distintos** en una misma tarea (no auto-revisión).

## Propiedad de estado (quién puede fijar cada `status`)

| status | Lo fija | Nunca lo fija |
|---|---|---|
| `DRAFT` | iniciador | — |
| `READY` | **solo Jorge/iniciador** (in-file en `main`) | **cualquier agente** |
| `IN_PROGRESS` | executor (Claude) | revisor, Jorge-as-agent |
| `EVIDENCE_READY` | executor (Claude) | revisor |
| `IN_REVIEW` | reviewer (Codex / delegate) | executor |
| `CHANGES_REQUESTED` | reviewer | executor |
| `DECISION_PROPOSED` | reviewer (convergencia) | — |
| `HUMAN_DECISION` | **solo Jorge** | **cualquier agente** |
| `HANDOFF_TO_MSO` | **solo MSO** (tras aprobación de Jorge) | **cualquier agente** |
| `CLOSED_REJECTED` | **solo Jorge** (al rechazar) | **cualquier agente** |
| `BLOCKED` | **cualquier agente** (su propio tramo; recuperable) | — (no decide final) |
| `ABORTED` | **iniciador / Jorge** (o MSO/Police por clasificación) | **agente** (solo lo propone) |

**Invariante:** un rol no puede mover una tarea a un estado cuya propiedad es de otro rol. Un agente que detecta que debería avanzar a un estado ajeno **se detiene** y deja `next_action`.

## Transiciones permitidas

| Transición | La ejecuta |
|---|---|
| `DRAFT → READY` | Jorge / iniciador (in-file en `main`) |
| `READY → IN_PROGRESS` | executor |
| `IN_PROGRESS → EVIDENCE_READY` | executor |
| `EVIDENCE_READY → IN_REVIEW` | reviewer (≠ executor) |
| `IN_REVIEW → CHANGES_REQUESTED` | reviewer |
| `IN_REVIEW → DECISION_PROPOSED` | reviewer |
| `CHANGES_REQUESTED → IN_PROGRESS` | executor (retoma) |
| `DECISION_PROPOSED → HUMAN_DECISION` | solo Jorge |
| `DECISION_PROPOSED → CLOSED_REJECTED` | solo Jorge |
| `HUMAN_DECISION → HANDOFF_TO_MSO` | solo MSO (tras aprobación de Jorge) |
| `<estado activo> → BLOCKED` | cualquier agente, su propio tramo |
| `BLOCKED → last_legit_status` | el agente del tramo, tras corregir |
| `<cualquiera> → ABORTED` | iniciador / Jorge (agente solo propone) |

Estados activos desde los que se puede `BLOCKED`: `READY`, `IN_PROGRESS`, `EVIDENCE_READY`, `IN_REVIEW`, `CHANGES_REQUESTED`.

## Autoridad in-file / `main` (regla dura)

1. `READY` **solo** es real cuando existe en `main` por acción humana verificable de Jorge.
2. **La autorización por chat no equivale a `READY`.** Un ejecutor que arranca con `status: DRAFT` en `main` está **fuera de contrato** (este fue el fallo de `TASK-0001`).
3. Toda transición de estado debe estar **commiteada** para ser real. Una corrección que solo vive en el chat **no cuenta**.

## Fallo y retractación

1. **Avance ilegítimo:** si un agente fija un `status` que no le corresponde o sin precondición in-file, el avance es **inválido** desde que ocurre y debe **retractarse**.
2. **No se borra evidencia:** `WORKLOG` es append-only; la corrección es una **entrada nueva**. `FINAL_REPORT` puede recibir un banner de corrección, sin borrar el análisis previo.
3. **Cómo retractar:** `status` vuelve a `last_legit_status` (o a `BLOCKED`), `blocked=true`, `blocked_reason` no nulo.
4. **Quién retracta:** el agente puede retractar **su propio** avance ilegítimo; el **aborto terminal** (`ABORTED`) lo confirma el iniciador/Jorge (o MSO/Police por clasificación). El agente no decide `ABORTED`.
5. **`last_legit_status`** registra el último estado alcanzado por una transición válida del rol propietario.

## Qué puede escribir cada quién

### Claude (ejecutor)
- **Puede:** `worklogs/TASK-NNNN.WORKLOG.md` (append-only), `reports/TASK-NNNN.FINAL_REPORT.md`, campos del TASK: `status ∈ {IN_PROGRESS, EVIDENCE_READY}` (y, en retracción de su propio tramo, `status=BLOCKED` o volver a `last_legit_status`), `evidence`, `files_touched`, `proposed_decision`, `blocked`, `blocked_reason`, `last_legit_status`, `next_action`. Diffs en **rama de trabajo** (`coordination/task-NNNN`), nunca en `main`.
- **No puede:** fijar `READY`; escribir `DECISION.md`; fijar `status=HUMAN_DECISION/HANDOFF_TO_MSO/CLOSED_REJECTED`; decidir `ABORTED` final; escribir `authority=human_final`/`jorge`/`approved_by_jorge`; tocar `assistant_os/mso`, `police`, `policy`, auth, `.env`, `secrets`, `.github/workflows`; mergear/pushear a `main`; aprobar PR; crear tokens.

### Codex (revisor)
- **Puede:** `reviews/TASK-NNNN.REVIEW.md`, `status ∈ {IN_REVIEW, CHANGES_REQUESTED, DECISION_PROPOSED}`, `proposed_decision ∈ {GO, NO-GO, NEEDS_CHANGES}` (authority=proposed), objeciones técnicas verificables, contrapropuestas en rama. En retracción de su propio tramo: `status=BLOCKED`.
- **No puede:** lo mismo que Claude en la columna "No puede". Además, no puede sobrescribir el WORKLOG/FINAL_REPORT del ejecutor (solo los lee y referencia), ni fijar `IN_PROGRESS`/`EVIDENCE_READY`.

### Reviewer delegate
- Si el revisor por defecto no está disponible, `reviewer_delegate` + `reviewer_delegate_reason` deben quedar **in-file (en `main`) antes** del REVIEW. El delegate tiene los mismos poderes/límites que el revisor y **también** debe ser distinto del ejecutor. Un REVIEW sin delegate registrado in-file es **inválido**.

### Jorge (autoridad humana)
- **Puede:** crear/cerrar tareas; **fijar `READY` in-file**; escribir `decisions/TASK-NNNN.DECISION.md` con `authority=human_final`; fijar `status=HUMAN_DECISION/CLOSED_REJECTED/ABORTED`; aprobar/mergear PR (esto es lo que **materializa** `human_final`).
- Jorge no necesita transportar contexto: lee la evidencia y el review ya presentes en el repo.

### MSO / Police
- Fuera de este plano. Reciben la tarea aprobada vía el flujo soberano normal (PR → revisión → ejecución gobernada). Solo MSO fija `HANDOFF_TO_MSO`. Nada en `coordination/` los invoca ni los ejecuta.

## Reglas de oro

1. **Un único estado canónico** por tarea: `TASK.md.status` en `main`. Nada lo duplica.
2. **`main` autoritativo; chat nunca autoridad.** `READY` y toda corrección solo cuentan si están commiteados.
3. **Propose / Review / Decide / Execute están separados** y los ejecutan sujetos distintos (agente / otro agente / Jorge / MSO).
4. **Ningún agente confiere autoridad.** Tokens prohibidos en escritura de agente: `authority=jorge`, `authority=human_final`, `approved_by_jorge`, `decided_by: jorge`, `mso_executable`.
5. **Un agente propone; otro revisa; Jorge decide; MSO ejecuta.** Ningún agente ordena a otro: como máximo `proposed_decision=NEEDS_CHANGES` o `CHANGES_REQUESTED`, refutable técnicamente.
6. **No auto-review:** ejecutor ≠ revisor ≠ delegate.
7. **Fail-closed:** falta de campo obligatorio, scope excedido, intento de tocar `forbidden`, o transición ilegal ⇒ `blocked=true`, sin avanzar.
8. **No se borra evidencia.** El fallo se preserva y se retracta, no se oculta.
9. **Nada de este plano ejecuta.** El plano coordina; MSO/Police ejecutan.
10. **Trabajo en rama (`coordination/task-NNNN`), nunca en main.** Los agentes proponen vía rama/PR; la aprobación/merge es acción humana de Jorge.
