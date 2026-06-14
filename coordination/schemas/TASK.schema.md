# TASK.schema — coordination/tasks/<task-id>.md

La `TASK` es el **único portador del estado canónico**. Vive en `coordination/tasks/<task-id>.md`.
Formato: front-matter YAML (campos normativos) + cuerpo Markdown (contexto legible).

**Fail-closed:** si falta cualquier campo `required`, o `status`/`authority` toman un valor fuera de enum, la tarea es **inválida** y se trata como `blocked`.

## Front-matter (YAML)

```yaml
id: TASK-0001-no-human-cable-contract   # required, único, inmutable, kebab-case con prefijo TASK-NNNN
title: ...                               # required
author: jorge | claude | codex           # required (quién creó la tarea)
authority: proposed                       # required, enum: proposed | human_final
                                          #   agentes SOLO pueden poner 'proposed'
assigned_agent: claude | codex            # required (ejecutor)
reviewer: codex | claude                  # required, distinto de assigned_agent
status: DRAFT                             # required, enum (ver máquina de estados)
scope:                                    # required, whitelist de áreas/archivos permitidos
  - coordination/
permissions:                              # required
  read: [...]
  write_proposal: [...]                   # nunca incluye mso/police/policy/auth
  forbidden: [assistant_os/mso, assistant_os/police, assistant_os/policy, auth, .env, secrets, .github/workflows]
risks: [...]                              # required (puede ser lista vacía explícita: [])
evidence: []                              # required; rutas a worklog/report/diffs/tests
files_touched: []                         # required; solo archivos en rama agent/<id>, nunca main
proposed_decision: null                   # null | GO | NO-GO | NEEDS_CHANGES  (lo ponen agentes)
blocked: false                            # required
blocked_reason: null                      # required si blocked=true
next_action: ...                          # required (qué falta y quién lo hace)
created_at: 2026-06-13                     # required (ISO date)
updated_at: 2026-06-13                     # required
```

## Enum `status`

`DRAFT → READY → IN_PROGRESS → EVIDENCE_READY → UNDER_REVIEW → DECISION_PROPOSED → HUMAN_DECISION → {HANDOFF_TO_MSO | CLOSED_REJECTED}`

Propiedad de cada estado: ver `RULES_OF_ENGAGEMENT.md`.

## Reglas de validación (fail-closed)

1. `id` único e inmutable; todos los artefactos de la tarea comparten `id`.
2. `authority=human_final` **solo** válido si `author: jorge`. Un agente que lo escriba ⇒ artefacto inválido.
3. `assigned_agent ≠ reviewer`.
4. `forbidden` debe incluir, como mínimo, mso/police/policy/auth/.env/secrets/workflows.
5. `status` solo avanza por transiciones permitidas y por el rol propietario del estado destino.
6. `blocked=true` ⇒ `blocked_reason` no nulo y la tarea no avanza.
7. `files_touched` no puede listar archivos en `main`; solo rama `agent/<id>`.
8. Campo desconocido en front-matter ⇒ se ignora pero se registra como observación; campo `required` ausente ⇒ inválido.

## Cuerpo (Markdown, libre pero recomendado)

```
## Contexto
## Objetivo
## Alcance y límites
## Criterios de aceptación
## Notas
```
