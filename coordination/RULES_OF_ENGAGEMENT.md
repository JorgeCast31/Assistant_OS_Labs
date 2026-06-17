# RULES_OF_ENGAGEMENT — coordination/ — **v3**

> Reglas de quién puede escribir qué y cuándo. **Fail-closed:** ante ambigüedad, campo faltante o transición no permitida, la tarea se **bloquea**; no se avanza ni se asume comportamiento.
> **Principio rector v2 (vigente):** `main` es la única fuente autoritativa. Las ramas proponen. El chat nunca es autoridad. **"Si no está commiteado, no pasó."**
> **Principio v3 (Human Approval Model — activo):** `authorship != authority`. Un agente puede **redactar** un `DECISION_CANDIDATE`; la autoridad humana se materializa por un **evento verificable de Jorge**, no por teclear el markdown.
>
> ```text
> Agent-generated decision candidates are allowed.
> Agent-approved human_final decisions are invalid.
> Human approval is a verifiable event, not physical authorship.
> ```

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
- **Puede:** `worklogs/TASK-NNNN.WORKLOG.md` (append-only), `reports/TASK-NNNN.FINAL_REPORT.md`, **(v3)** `candidates/TASK-NNNN.DECISION_CANDIDATE.md` (solo estado `CANDIDATE`, `effective_authority: none`), campos del TASK: `status ∈ {IN_PROGRESS, EVIDENCE_READY}` (y, en retracción de su propio tramo, `status=BLOCKED` o volver a `last_legit_status`), `evidence`, `files_touched`, `proposed_decision`, `blocked`, `blocked_reason`, `last_legit_status`, `next_action`. Diffs en **rama de trabajo** (`coordination/task-NNNN`), nunca en `main`.
- **No puede:** fijar `READY`; escribir `DECISION.md` ni nada en `decisions/`; **(v3)** escribir campos de aprobación en un candidato (`approved_by`, `approval_method`, `approved_at`, `effective_authority=human_final`, `decided_by=jorge`); fijar `status=HUMAN_DECISION/HANDOFF_TO_MSO/CLOSED_REJECTED`; decidir `ABORTED` final; escribir `authority=human_final`/`jorge`/`approved_by_jorge`; tocar `assistant_os/mso`, `police`, `policy`, auth, `.env`, `secrets`, `.github/workflows`; mergear/pushear a `main`; aprobar PR; crear tokens.

### Codex (revisor)
- **Puede:** `reviews/TASK-NNNN.REVIEW.md`, `status ∈ {IN_REVIEW, CHANGES_REQUESTED, DECISION_PROPOSED}`, `proposed_decision ∈ {GO, NO-GO, NEEDS_CHANGES}` (authority=proposed), objeciones técnicas verificables, contrapropuestas en rama. **(v3)** puede redactar un `candidates/TASK-NNNN.DECISION_CANDIDATE.md` **solo** cuando actúe como generador y **no** sea el revisor de ese mismo candidato (no auto-review). En retracción de su propio tramo: `status=BLOCKED`.
- **No puede:** lo mismo que Claude en la columna "No puede" (incluidos los campos de aprobación de candidato). Además, no puede sobrescribir el WORKLOG/FINAL_REPORT del ejecutor (solo los lee y referencia), ni fijar `IN_PROGRESS`/`EVIDENCE_READY`, ni revisar/aprobar un candidato que él mismo generó.

### Reviewer delegate
- Si el revisor por defecto no está disponible, `reviewer_delegate` + `reviewer_delegate_reason` deben quedar **in-file (en `main`) antes** del REVIEW. El delegate tiene los mismos poderes/límites que el revisor y **también** debe ser distinto del ejecutor. Un REVIEW sin delegate registrado in-file es **inválido**.

### Jorge (autoridad humana)
- **Puede:** crear/cerrar tareas; **fijar `READY` in-file**; escribir `decisions/TASK-NNNN.DECISION.md` con `authority=human_final`; **(v3)** **aprobar un `DECISION_CANDIDATE` redactado por un agente** y materializarlo en `human_final` por evento verificable (merge/aprobación de PR, commit firmado, o UI auditable) — **sin necesidad de teclear el markdown**; fijar `status=HUMAN_DECISION/CLOSED_REJECTED/ABORTED`; aprobar/mergear PR (esto es lo que **materializa** `human_final`).
- Jorge no necesita transportar contexto: lee la evidencia, el review y el candidato ya presentes en el repo. Su autoridad es la **aprobación verificable**, no la autoría material.

### Candidatos de decisión (v3)
- Un `DECISION_CANDIDATE` lo **redacta un agente** (ejecutor/generador) y vive en `coordination/candidates/`. Lleva `generated_by`, `effective_authority: none`, `requires_human_approval: true`. **No tiene autoridad.**
- **No auto-aprobación / no auto-review:** el agente que genera un candidato **no** lo revisa ni lo aprueba. El revisor (Codex por defecto) verifica el candidato según `schemas/DECISION.schema.md §E`.
- **`generated_by != approved_by`.** La aprobación nunca borra `generated_by`.
- **Si un agente mergea, aprueba o escribe campos de aprobación** (`approved_by`, `effective_authority=human_final`, etc.) **sin evento verificable de Jorge**, el artefacto es **inválido y nulo** (fail-closed). El enforcement primario es control de acceso; el secundario, verificabilidad contra el historial.
- **Runner futuro:** puede *detectar y notificar* candidatos, **nunca** promoverlos a `human_final` ni mergear/aprobar.

### MSO / Police
- Fuera de este plano. Reciben la tarea aprobada vía el flujo soberano normal (PR → revisión → ejecución gobernada). Solo MSO fija `HANDOFF_TO_MSO`. Nada en `coordination/` los invoca ni los ejecuta.

## Reglas de oro

1. **Un único estado canónico** por tarea: `TASK.md.status` en `main`. Nada lo duplica.
2. **`main` autoritativo; chat nunca autoridad.** `READY` y toda corrección solo cuentan si están commiteados.
3. **Propose / Review / Decide / Execute están separados** y los ejecutan sujetos distintos (agente / otro agente / Jorge / MSO).
4. **Ningún agente confiere autoridad.** Tokens prohibidos en escritura de agente: `authority=jorge`, `authority=human_final`, `effective_authority=human_final`, `approved_by`/`approved_by_jorge`, `approval_method`, `approved_at`, `decided_by: jorge`, `mso_executable`. (v3) Un agente solo escribe candidatos con `effective_authority: none`.
5. **Un agente propone; otro revisa; Jorge decide; MSO ejecuta.** Ningún agente ordena a otro: como máximo `proposed_decision=NEEDS_CHANGES` o `CHANGES_REQUESTED`, refutable técnicamente.
6. **No auto-review:** ejecutor ≠ revisor ≠ delegate.
7. **Fail-closed:** falta de campo obligatorio, scope excedido, intento de tocar `forbidden`, o transición ilegal ⇒ `blocked=true`, sin avanzar.
8. **No se borra evidencia.** El fallo se preserva y se retracta, no se oculta.
9. **Nada de este plano ejecuta.** El plano coordina; MSO/Police ejecutan.
10. **Trabajo en rama (`coordination/task-NNNN`), nunca en main.** Los agentes proponen vía rama/PR; la aprobación/merge es acción humana de Jorge.
