# coordination/ — Plano de coordinación multiagente (Claude ↔ Codex) — **v2**

> **Estado:** propuesta documental (v2). **No ejecuta nada.** No automatizado. No hay Runner.
> Este directorio es el **bus de coordinación versionado** entre agentes acotados (Claude, Codex) bajo autoridad final humana (Jorge) y autoridad de ejecución soberana (MSO).
> **Diseño completo de v2:** ver [`proposals/COORDINATION_FLOW_V2_PROPOSAL.md`](proposals/COORDINATION_FLOW_V2_PROPOSAL.md).

## Qué es y qué NO es

`coordination/` es un **plano de coordinación**: tareas, evidencia, revisión y decisión, todo en archivos versionados y auditables.

`coordination/` **NO** es:
- un plano de **ejecución** — nada aquí ejecuta acciones; la ejecución solo ocurre vía **MSO → Police → Pipeline → Runner**;
- una fuente de **autoridad** — ningún archivo aquí confiere permiso ejecutable;
- un canal en tiempo real — el handoff es por archivos commiteados, no por mensajería;
- `agent_context/` — ese path está excluido por `.agentignore` y queda como contexto interno/histórico, **no** como bus operativo (decisión D1).

## Estructura y naming (v2 — patrón único)

Un solo patrón de nombre por artefacto. **El slug/título vive en el front-matter, no en el nombre de archivo.**

```
coordination/
  README.md                  # este archivo: reglas del bus y modelo de autoridad
  RULES_OF_ENGAGEMENT.md      # qué puede/no puede escribir cada rol
  AGENT_CONTRACT.md           # contrato por agente (claude, codex) y por Jorge
  proposals/                  # propuestas de diseño del propio plano
    COORDINATION_FLOW_V2_PROPOSAL.md
  schemas/                    # esquemas de cada artefacto (campos obligatorios, fail-closed)
    TASK.schema.md
    WORKLOG.schema.md
    FINAL_REPORT.schema.md
    REVIEW.schema.md
    DECISION.schema.md
  tasks/        TASK-NNNN.md               # TASK canónica (front-matter = estado único)
  worklogs/     TASK-NNNN.WORKLOG.md        # bitácora append-only del ejecutor
  reports/      TASK-NNNN.FINAL_REPORT.md
  reviews/      TASK-NNNN.REVIEW.md         # veredicto del revisor
  decisions/    TASK-NNNN.DECISION.md       # decisión final humana (solo Jorge)
```

- `NNNN` = correlativo cero-rellenado (`0001`, `0002`, …).
- El `id` en front-matter puede llevar slug (`TASK-0002-clean-dogfood-v2`); el **archivo** es solo `TASK-NNNN.<TIPO>.md`.
- **Rama de trabajo:** `coordination/task-NNNN`.
- Todos los artefactos de una tarea comparten el mismo `NNNN`/`id`.

> **Nota de migración:** los archivos de `TASK-0001` conservan el naming v1 (`TASK-0001-no-human-cable-contract*`) **a propósito**: son evidencia de un dogfood fallido y no se reescriben. La migración a naming v2 se documenta en la propuesta v2 §7 y se aplicaría más adelante por una retracción legítima del iniciador.

## Estado único y auditable

El **único estado canónico** de una tarea vive en el front-matter YAML de su `TASK.md`, campo `status`, **tal como existe en `main`**. Ningún otro archivo redefine el estado; los demás artefactos solo aportan evidencia. Esto previene estado duplicado / autoridad paralela.

## Autoridad in-file / `main` (principio rector v2)

> **`main` es la única fuente autoritativa. Las ramas son propuestas. El chat nunca es autoridad.**

- El estado real de una tarea es su `status` **en `main`**. Una rama solo *propone*.
- `READY` solo es válido cuando existe en `main` por **acción humana verificable** (merge/commit de Jorge).
- **La autorización por chat NUNCA equivale a `READY`.** Sin `status: READY` commiteado en `main`, la tarea sigue en `DRAFT` y el ejecutor **no arranca**.
- Los agentes **no pueden mover estados críticos** (`HUMAN_DECISION`, `HANDOFF_TO_MSO`, `CLOSED_REJECTED`) ni fijar `READY`.
- Regla operativa: **"si no está commiteado, no pasó"**.

## Máquina de estados (v2)

```
DRAFT
  → READY              (SOLO Jorge/iniciador, in-file en main)
  → IN_PROGRESS        (executor toma la tarea)
  → EVIDENCE_READY     (executor: WORKLOG + FINAL_REPORT completos)
  → IN_REVIEW          (reviewer ≠ executor: REVIEW emitido)
        ├─ CHANGES_REQUESTED  (reviewer: vuelve al executor → IN_PROGRESS)
        └─ DECISION_PROPOSED  (reviewer: convergencia, authority=proposed)
  → HUMAN_DECISION     (SOLO Jorge)
        ├─ APPROVED → HANDOFF_TO_MSO   (SOLO MSO; entra al flujo soberano; ningún agente ejecuta)
        └─ REJECTED → CLOSED_REJECTED  (SOLO Jorge)

Transversales:
  BLOCKED   (cualquier agente, su propio tramo; recuperable → last_legit_status o ABORTED)
  ABORTED   (iniciador/Jorge; fallo terminal / retracción confirmada)
```

Estados **terminales**: `HANDOFF_TO_MSO`, `CLOSED_REJECTED`, `ABORTED`.
Reglas de transición y propiedad → ver `RULES_OF_ENGAGEMENT.md`. Cualquier ambigüedad o campo faltante ⇒ la tarea se considera **bloqueada** (fail-closed), no se avanza.

## Fallo y retractación (v2)

- **No se borra evidencia.** El `WORKLOG` es append-only: una corrección es una entrada nueva.
- Un avance ilegítimo se **retracta** devolviendo `status` a `last_legit_status` + `blocked=true` + `blocked_reason`.
- Un agente puede retractar **su propio** avance ilegítimo; el **aborto terminal** (`ABORTED`) lo confirma Jorge/iniciador.
- `last_legit_status` (front-matter) guarda el último estado alcanzado por una transición válida.
- Las correcciones por chat **no sustituyen** al repo: solo cuenta lo commiteado en `main`.

Detalle: propuesta v2 §6.

## Modelo de autoridad (resumen; detalle en AGENT_CONTRACT.md)

| Nivel | Quién | Ejecuta |
|---|---|---|
| `authority=proposed` | Claude, Codex | No |
| `authority=human_final` | **Solo Jorge** | No directamente; **autoriza** entrada al flujo soberano vía aprobación/merge de PR |
| `mso_executable` (implícito) | **Solo MSO** | Sí, vía Police→Pipeline |

- **MSO is the only source of executable authority.**
- Ningún agente puede escribir `authority=jorge`, `authority=human_final`, `approved_by_jorge`, `decided_by: jorge` ni equivalente.
- `human_final` se **materializa** por una acción humana verificable: la aprobación/merge del PR por Jorge (control de acceso del repo, no honor-system).
- `mso_executable` **nunca** aparece como valor otorgable en este plano.

## Reviewer independiente (v2)

- `reviewer` (o `reviewer_delegate` si existe) **nunca** coincide con `assigned_agent` (no auto-review).
- Si el revisor no está disponible, se registra **in-file** un `reviewer_delegate` con `reviewer_delegate_reason`, **antes** del REVIEW. Sin ese registro en repo, el REVIEW es inválido.

## Flujo Claude ↔ Codex sin cable humano

```
TASK(READY en main) → [Claude] ejecuta en rama, deja WORKLOG+FINAL_REPORT → EVIDENCE_READY
                     → [Codex] lee evidencia SIN Jorge, emite REVIEW         → IN_REVIEW
                     → reviewer converge                                      → DECISION_PROPOSED
                     → [Jorge] aprueba/rechaza (merge/PR)                     → HUMAN_DECISION
                     → si APPROVED: PR entra a MSO/Police                     → HANDOFF_TO_MSO
```

Jorge solo participa en `DRAFT→READY` (autorización in-file) y en `HUMAN_DECISION`. El contexto vive en el repo; cada agente lo lee directo. Jorge no transporta contexto.

## Límites de este tramo (Police)

Este tramo es **contrato verificable**, no autonomía. No incluye: Runner, ejecución headless, cron, servicios permanentes, GitHub Actions, túneles, VPS, Docker, tokens, ni cambios en MSO/Police/Policy/Auth. La autonomía posterior debe apoyarse en este contrato para no ser teatro ni depender de Jorge como cable.
