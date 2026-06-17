# TASK.schema — coordination/tasks/TASK-NNNN.md — **v3**

La `TASK` es el **único portador del estado canónico**. Vive en `coordination/tasks/TASK-NNNN.md`.
Formato: front-matter YAML (campos normativos) + cuerpo Markdown (contexto legible).
El **nombre de archivo** es solo `TASK-NNNN.md`; el slug descriptivo vive en `id`.

> **Nota v3 (Human Approval Model).** El estado de la `TASK` y su máquina de estados **no cambian** respecto a v2. v3 solo añade un artefacto separado para la fase de decisión: el `DECISION_CANDIDATE` (redactado por un agente, sin autoridad), definido en `schemas/DECISION.schema.md`. La `TASK` sigue rigiéndose por `authority ∈ {proposed, human_final}`, donde un agente **solo** puede emitir `proposed`. Principio: `authorship != authority` — un agente puede redactar candidatos; la autoridad humana se materializa por un **evento verificable de Jorge**, nunca por la autoría material del archivo.

**Estado autoritativo = `status` en `main`.** Una rama solo *propone* un cambio de estado.

**Fail-closed:** si falta cualquier campo `required`, o `status`/`authority` toman un valor fuera de enum, la tarea es **inválida** y se trata como `blocked`.

## Front-matter (YAML)

```yaml
id: TASK-0002-clean-dogfood-v2            # required, único, inmutable, kebab-case con prefijo TASK-NNNN
title: ...                                # required
author: jorge | claude | codex            # required (quién creó la tarea)
authority: proposed                        # required, enum: proposed | human_final
                                           #   agentes SOLO pueden poner 'proposed'
assigned_agent: claude | codex             # required (ejecutor)
reviewer: codex | claude                   # required, distinto de assigned_agent
reviewer_delegate: null                    # optional; agente suplente si el revisor no está disponible
reviewer_delegate_reason: null             # required si reviewer_delegate != null
status: DRAFT                              # required, enum (ver máquina de estados)
last_legit_status: DRAFT                   # required; último status alcanzado por transición válida
scope:                                     # required, whitelist de áreas/archivos permitidos
  - coordination/
permissions:                               # required
  read: [...]
  write_proposal: [...]                    # nunca incluye mso/police/policy/auth
  forbidden: [assistant_os/mso, assistant_os/police, assistant_os/policy, auth, .env, secrets, .github/workflows]
risks: [...]                               # required (puede ser lista vacía explícita: [])
evidence: []                               # required; rutas a worklog/report/diffs/tests
files_touched: []                          # required; solo archivos en rama coordination/task-NNNN, nunca main
proposed_decision: null                    # null | GO | NO-GO | NEEDS_CHANGES  (lo ponen agentes)
blocked: false                             # required
blocked_reason: null                       # required si blocked=true
next_action: ...                           # required (qué falta y quién lo hace)
created_at: 2026-06-14                      # required (ISO date)
updated_at: 2026-06-14                      # required
```

## Enum `status`

```
DRAFT → READY → IN_PROGRESS → EVIDENCE_READY → IN_REVIEW
      → {CHANGES_REQUESTED → IN_PROGRESS | DECISION_PROPOSED}
      → HUMAN_DECISION → {HANDOFF_TO_MSO | CLOSED_REJECTED}

Transversales: BLOCKED (recuperable), ABORTED (terminal)
```

Lista completa del enum:
`DRAFT, READY, IN_PROGRESS, EVIDENCE_READY, IN_REVIEW, CHANGES_REQUESTED, DECISION_PROPOSED, HUMAN_DECISION, HANDOFF_TO_MSO, BLOCKED, ABORTED, CLOSED_REJECTED`

Terminales: `HANDOFF_TO_MSO`, `CLOSED_REJECTED`, `ABORTED`.
Propiedad de cada estado y transiciones permitidas: ver `RULES_OF_ENGAGEMENT.md`.

> **Nota v2:** `BLOCKED` y `ABORTED` ahora son estados del enum (en v1 el bloqueo solo se expresaba con el campo booleano `blocked`). El campo `blocked` sigue existiendo como flag transversal (puede acompañar a `BLOCKED` o a una retracción a `last_legit_status`). `IN_REVIEW` reemplaza al `UNDER_REVIEW` de v1.

## Reglas de validación (fail-closed)

1. `id` único e inmutable; todos los artefactos de la tarea comparten el mismo `NNNN`/`id`.
2. **`status` autoritativo solo en `main`.** En rama es propuesta. `READY` solo válido cuando existe en `main` por acción de Jorge.
3. `authority=human_final` **solo** válido si `author: jorge`. Un agente que lo escriba ⇒ artefacto inválido.
4. `assigned_agent ≠ reviewer`. Si hay `reviewer_delegate`, también `reviewer_delegate ≠ assigned_agent` y `reviewer_delegate_reason` no nulo.
5. `forbidden` debe incluir, como mínimo, mso/police/policy/auth/.env/secrets/workflows.
6. `status` solo avanza por transiciones permitidas y por el rol propietario del estado destino.
7. `blocked=true` ⇒ `blocked_reason` no nulo y la tarea no avanza.
8. `files_touched` no puede listar archivos en `main`; solo rama `coordination/task-NNNN`.
9. `last_legit_status` se actualiza solo al completar una transición válida; en retracción, `status` vuelve a `last_legit_status`.
10. `ABORTED` solo lo fija el iniciador/Jorge (o MSO/Police por clasificación); un agente solo lo propone vía `blocked=true` + `next_action`.
11. Campo desconocido en front-matter ⇒ se ignora pero se registra como observación; campo `required` ausente ⇒ inválido.

## Cuerpo (Markdown, libre pero recomendado)

```
## Contexto
## Objetivo
## Alcance y límites
## Criterios de aceptación
## Notas
```
