# RULES_OF_ENGAGEMENT — coordination/

> Reglas de quién puede escribir qué y cuándo. **Fail-closed:** ante ambigüedad, campo faltante o transición no permitida, la tarea se **bloquea**; no se avanza ni se asume comportamiento.

## Roles

- **Iniciador** — Jorge, o un agente *proponiendo* una tarea. Crea `TASK.md`.
- **Ejecutor** — agente que produce evidencia. Por defecto: **Claude**.
- **Revisor** — agente que verifica la evidencia. Por defecto: **Codex**.
- **Autoridad humana** — **solo Jorge**. Decide.
- **Autoridad de ejecución** — **solo MSO** (fuera de este plano).

Ejecutor y revisor deben ser agentes **distintos** en una misma tarea (no auto-revisión).

## Propiedad de estado (quién puede fijar cada `status`)

| status | Lo fija | Nunca lo fija |
|---|---|---|
| `DRAFT` | iniciador | — |
| `READY` | iniciador | — |
| `IN_PROGRESS` | ejecutor (Claude) | revisor, Jorge-as-agent |
| `EVIDENCE_READY` | ejecutor (Claude) | revisor |
| `UNDER_REVIEW` | revisor (Codex) | ejecutor |
| `DECISION_PROPOSED` | cualquier agente (proposed) | — |
| `HUMAN_DECISION` | **solo Jorge** | **cualquier agente** |
| `HANDOFF_TO_MSO` | **solo Jorge** (al aprobar) | **cualquier agente** |
| `CLOSED_REJECTED` | **solo Jorge** (al rechazar) | **cualquier agente** |

**Invariante:** un rol no puede mover una tarea a un estado cuya propiedad es de otro rol. Un agente que detecta que debería avanzar a un estado ajeno **se detiene** y deja `next_action`.

## Qué puede escribir cada quién

### Claude (ejecutor)
- **Puede:** `worklogs/<id>.WORKLOG.md` (append-only), `reports/<id>.FINAL_REPORT.md`, campos del TASK: `status ∈ {IN_PROGRESS, EVIDENCE_READY}`, `evidence`, `files_touched`, `proposed_decision`, `blocked`, `blocked_reason`, `next_action`. Diffs en **rama de trabajo** (`agent/<id>`), nunca en `main`.
- **No puede:** escribir `DECISION.md`; fijar `status=HUMAN_DECISION/HANDOFF_TO_MSO/CLOSED_REJECTED`; escribir `authority=human_final`/`jorge`/`approved_by_jorge`; tocar `assistant_os/mso`, `police`, `policy`, auth, `.env`, `secrets`, `.github/workflows`; mergear/pushear a `main`; aprobar PR; crear tokens.

### Codex (revisor)
- **Puede:** `reviews/<id>.REVIEW.md`, `status=UNDER_REVIEW`, `proposed_decision ∈ {GO, NO-GO, NEEDS_CHANGES}` (authority=proposed), objeciones técnicas verificables, contrapropuestas en rama.
- **No puede:** lo mismo que Claude en la columna "No puede". Además, no puede sobrescribir el WORKLOG/FINAL_REPORT del ejecutor (solo los lee y referencia).

### Jorge (autoridad humana)
- **Puede:** crear/cerrar tareas; escribir `decisions/<id>.DECISION.md` con `authority=human_final`; fijar `status=HUMAN_DECISION/HANDOFF_TO_MSO/CLOSED_REJECTED`; aprobar/mergear PR (esto es lo que **materializa** `human_final`).
- Jorge no necesita transportar contexto: lee la evidencia y el review ya presentes en el repo.

### MSO / Police
- Fuera de este plano. Reciben la tarea aprobada vía el flujo soberano normal (PR → revisión → ejecución gobernada). Nada en `coordination/` los invoca.

## Reglas de oro

1. **Un único estado canónico** por tarea: `TASK.md.status`. Nada lo duplica.
2. **Propose / Review / Decide / Execute están separados** y los ejecutan sujetos distintos (agente / otro agente / Jorge / MSO).
3. **Ningún agente confiere autoridad.** Tokens prohibidos en escritura de agente: `authority=jorge`, `authority=human_final`, `approved_by_jorge`, `decided_by: jorge`, `mso_executable`.
4. **Un agente propone; otro revisa; Jorge decide; MSO ejecuta.** Ningún agente ordena a otro: como máximo `proposed_decision=NEEDS_CHANGES`, refutable técnicamente.
5. **Fail-closed:** falta de campo obligatorio, scope excedido, intento de tocar `forbidden`, o transición ilegal ⇒ `blocked=true`, sin avanzar.
6. **Nada de este plano ejecuta.** El plano coordina; MSO/Police ejecutan.
7. **Trabajo en rama, nunca en main.** Los agentes proponen vía rama/PR; la aprobación/merge es acción humana de Jorge.
