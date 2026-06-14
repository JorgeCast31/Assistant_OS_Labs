# AGENT_CONTRACT — coordination/ — **v2**

Contrato de los colaboradores acotados (*bounded collaborators*) del plano de coordinación.

## Principio

Claude y Codex son **bounded collaborators**: pueden proponer y revisar, nunca decidir ni ejecutar. La única autoridad humana es Jorge. La única autoridad de ejecución es MSO.

**Principio rector v2:** `main` es la única fuente autoritativa de estado. Las ramas proponen. El chat nunca es autoridad. **"Si no está commiteado, no pasó."**

## Modelo de autoridad (normativo)

`authority` es un enum cerrado. Valores permitidos en este plano:

| Valor | Quién lo emite | Semántica | ¿Ejecuta? |
|---|---|---|---|
| `proposed` | Claude, Codex | Propuesta / evidencia / veredicto de revisión | No |
| `human_final` | **Solo Jorge** | Voluntad humana validada | No directamente; **autoriza** entrada al flujo soberano |

`mso_executable` existe en el sistema real pero **nunca** se escribe como valor otorgable en `coordination/`. Pertenece solo al MSO.

### Cómo se materializa `human_final`
`human_final` no es texto que un agente pueda escribir. Se **realiza** por una acción humana verificable de Jorge:
- aprobación y/o **merge del PR** por Jorge, y/o
- commit firmado por Jorge de `decisions/TASK-NNNN.DECISION.md`.

El enforcement real es **control de acceso del repositorio** (D2): los agentes no tienen permiso de merge, ni de aprobar PR, ni de push directo a `main`. Por tanto, aunque un agente escribiera por error `authority=human_final`, **no podría producir el efecto** (merge/aprobación) que la hace real. La defensa no es honor-system; es acceso.

### Por qué `READY` también depende del acceso (v2)
Igual que `human_final`, `READY` **solo es real cuando existe en `main`**, y a `main` solo llega por acción humana de Jorge. Un agente que escriba `READY` en una rama **no** lo hace real. La autorización por chat no equivale a `READY`. (Esto cierra el fallo de `TASK-0001`.)

## Naming y rama (v2)

- Artefactos: `TASK-NNNN.md`, `TASK-NNNN.WORKLOG.md`, `TASK-NNNN.FINAL_REPORT.md`, `TASK-NNNN.REVIEW.md`, `TASK-NNNN.DECISION.md`. El slug vive en el `id` del front-matter, no en el nombre de archivo.
- Rama de trabajo: `coordination/task-NNNN`. Nunca `main`.

## Contrato por agente

### claude
```yaml
agent: claude
role_default: executor
may_write:
  - worklogs/TASK-NNNN.WORKLOG.md
  - reports/TASK-NNNN.FINAL_REPORT.md
  - TASK.status(IN_PROGRESS|EVIDENCE_READY)
  - TASK.status(BLOCKED)            # solo su propio tramo; recuperable
  - evidence, files_touched, proposed_decision
  - blocked, blocked_reason, last_legit_status, next_action
may_emit_authority: [proposed]
branch: coordination/task-NNNN     # nunca main
forbidden_write:
  - TASK.status(READY)              # READY es de Jorge, in-file en main
  - decisions/                      # decisión final es de Jorge
  - TASK.status(HUMAN_DECISION|HANDOFF_TO_MSO|CLOSED_REJECTED|ABORTED)
  - authority(human_final|jorge|approved_by_jorge|mso_executable)
  - assistant_os/mso, assistant_os/police, assistant_os/policy, auth, .env, secrets, .github/workflows
  - merge, push:main, approve_pr, create_token
```

### codex
```yaml
agent: codex
role_default: reviewer
may_write:
  - reviews/TASK-NNNN.REVIEW.md
  - TASK.status(IN_REVIEW|CHANGES_REQUESTED|DECISION_PROPOSED)
  - TASK.status(BLOCKED)            # solo su propio tramo; recuperable
  - proposed_decision
may_emit_authority: [proposed]
branch: coordination/task-NNNN
forbidden_write:
  - TASK.status(READY)
  - decisions/
  - TASK.status(IN_PROGRESS|EVIDENCE_READY)   # son del ejecutor
  - TASK.status(HUMAN_DECISION|HANDOFF_TO_MSO|CLOSED_REJECTED|ABORTED)
  - authority(human_final|jorge|approved_by_jorge|mso_executable)
  - assistant_os/mso, assistant_os/police, assistant_os/policy, auth, .env, secrets, .github/workflows
  - merge, push:main, approve_pr, create_token
  - overwrite executor's WORKLOG/FINAL_REPORT
```

### reviewer_delegate (v2)
```yaml
# Opcional. Solo válido si está registrado in-file (en main) ANTES del REVIEW.
reviewer_delegate: <agent>
reviewer_delegate_reason: "<por qué el revisor por defecto no está disponible>"
constraints:
  - debe ser distinto de assigned_agent (no auto-review)
  - hereda los poderes/límites del revisor
  - un REVIEW sin delegate registrado in-file es inválido
```

### jorge
```yaml
actor: jorge
role: human_authority
may_write: [tasks/, decisions/, TASK.status(any)]
may_emit_authority: [human_final]
exclusive_powers:
  - set READY (in-file en main)
  - approve_pr, merge, close_task
  - set HUMAN_DECISION / CLOSED_REJECTED / ABORTED
```

### mso
```yaml
actor: mso
role: execution_authority   # fuera de este plano
exclusive_powers: [set HANDOFF_TO_MSO]   # solo tras aprobación humana de Jorge
note: nada en coordination/ invoca ni ejecuta MSO; recibe la tarea por el flujo soberano normal.
```

> Roles ejecutor/revisor pueden intercambiarse por tarea (campos `assigned_agent` / `reviewer` / `reviewer_delegate` en el TASK), pero **nunca** pueden coincidir en la misma tarea (no auto-revisión).

## Cláusulas no negociables

1. Ningún agente escribe autoridad humana ni ejecutable.
2. Ningún agente fija `READY`; `READY` solo es real en `main` por acción de Jorge.
3. Ningún agente ejecuta acciones de dominio; eso es MSO/Police.
4. Ningún agente declara `MSO ACTIVE`, `MSO HEALTHY`, kill-switch off, ni readiness como autoridad.
5. Ningún agente mergea, aprueba PR, ni pushea a `main`.
6. Ningún agente decide `ABORTED` final; solo lo propone (`blocked=true` + `next_action`).
7. Trabajo de agente siempre en rama `coordination/task-NNNN`, propuesto vía PR.
8. No se borra evidencia: el fallo se retracta y se preserva (WORKLOG append-only).
9. Fail-closed ante ambigüedad: bloquear y reportar, nunca inventar.
10. El incumplimiento de cualquier cláusula invalida el artefacto producido (no se acepta evidencia fuera de contrato).
