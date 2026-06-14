# AGENT_CONTRACT — coordination/

Contrato de los colaboradores acotados (*bounded collaborators*) del plano de coordinación.

## Principio

Claude y Codex son **bounded collaborators**: pueden proponer y revisar, nunca decidir ni ejecutar. La única autoridad humana es Jorge. La única autoridad de ejecución es MSO.

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
- commit firmado por Jorge de `decisions/<id>.DECISION.md`.

El enforcement real es **control de acceso del repositorio** (D2): los agentes no tienen permiso de merge, ni de aprobar PR, ni de push directo a `main`. Por tanto, aunque un agente escribiera por error `authority=human_final`, **no podría producir el efecto** (merge/aprobación) que la hace real. La defensa no es honor-system; es acceso.

## Contrato por agente

### claude
```yaml
agent: claude
role_default: executor
may_write: [worklogs/, reports/, TASK.status(IN_PROGRESS|EVIDENCE_READY), evidence, files_touched, proposed_decision]
may_emit_authority: [proposed]
branch: agent/<task-id>        # nunca main
forbidden_write:
  - decisions/                  # decisión final es de Jorge
  - TASK.status(HUMAN_DECISION|HANDOFF_TO_MSO|CLOSED_REJECTED)
  - authority(human_final|jorge|approved_by_jorge|mso_executable)
  - assistant_os/mso, assistant_os/police, assistant_os/policy, auth, .env, secrets, .github/workflows
  - merge, push:main, approve_pr, create_token
```

### codex
```yaml
agent: codex
role_default: reviewer
may_write: [reviews/, TASK.status(UNDER_REVIEW), proposed_decision]
may_emit_authority: [proposed]
branch: agent/<task-id>
forbidden_write:
  - decisions/
  - TASK.status(HUMAN_DECISION|HANDOFF_TO_MSO|CLOSED_REJECTED)
  - authority(human_final|jorge|approved_by_jorge|mso_executable)
  - assistant_os/mso, assistant_os/police, assistant_os/policy, auth, .env, secrets, .github/workflows
  - merge, push:main, approve_pr, create_token
  - overwrite executor's WORKLOG/FINAL_REPORT
```

### jorge
```yaml
actor: jorge
role: human_authority
may_write: [tasks/, decisions/, TASK.status(any)]
may_emit_authority: [human_final]
exclusive_powers: [approve_pr, merge, close_task, set HUMAN_DECISION/HANDOFF_TO_MSO/CLOSED_REJECTED]
```

> Roles ejecutor/revisor pueden intercambiarse por tarea (campo `assigned_agent` / `reviewer` en el TASK), pero **nunca** pueden coincidir en la misma tarea (no auto-revisión).

## Cláusulas no negociables

1. Ningún agente escribe autoridad humana ni ejecutable.
2. Ningún agente ejecuta acciones de dominio; eso es MSO/Police.
3. Ningún agente declara `MSO ACTIVE`, `MSO HEALTHY`, kill-switch off, ni readiness como autoridad.
4. Ningún agente mergea, aprueba PR, ni pushea a `main`.
5. Trabajo de agente siempre en rama `agent/<task-id>`, propuesto vía PR.
6. Fail-closed ante ambigüedad: bloquear y reportar, nunca inventar.
7. El incumplimiento de cualquier cláusula invalida el artefacto producido (no se acepta evidencia fuera de contrato).
