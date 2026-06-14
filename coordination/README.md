# coordination/ — Plano de coordinación multiagente (Claude ↔ Codex)

> **Estado:** propuesta documental (tramo B). **No ejecuta nada.** No automatizado. No hay Runner.
> Este directorio es el **bus de coordinación versionado** entre agentes acotados (Claude, Codex) bajo autoridad final humana (Jorge) y autoridad de ejecución soberana (MSO).

## Qué es y qué NO es

`coordination/` es un **plano de coordinación**: tareas, evidencia, revisión y decisión, todo en archivos versionados y auditables.

`coordination/` **NO** es:
- un plano de **ejecución** — nada aquí ejecuta acciones; la ejecución solo ocurre vía **MSO → Police → Pipeline → Runner**;
- una fuente de **autoridad** — ningún archivo aquí confiere permiso ejecutable;
- un canal en tiempo real — el handoff es por archivos commiteados, no por mensajería;
- `agent_context/` — ese path está excluido por `.agentignore` y queda como contexto interno/histórico, **no** como bus operativo (decisión D1).

## Estructura

```
coordination/
  README.md                 # este archivo: reglas del bus y modelo de autoridad
  RULES_OF_ENGAGEMENT.md     # qué puede/no puede escribir cada rol
  AGENT_CONTRACT.md          # contrato por agente (claude, codex) y por Jorge
  schemas/                   # esquemas de cada artefacto (campos obligatorios, fail-closed)
    TASK.schema.md
    WORKLOG.schema.md
    FINAL_REPORT.schema.md
    REVIEW.schema.md
    DECISION.schema.md
  tasks/        <task-id>.md           # TASK canónica (front-matter = estado único)
  worklogs/     <task-id>.WORKLOG.md    # bitácora append-only del ejecutor
  reports/      <task-id>.FINAL_REPORT.md
  reviews/      <task-id>.REVIEW.md     # veredicto del revisor
  decisions/    <task-id>.DECISION.md   # decisión final humana (solo Jorge)
```

Una tarea se identifica por un `id` inmutable (`TASK-NNNN-...`). Todos sus artefactos comparten ese `id`.

## Estado único y auditable

El **único estado canónico** de una tarea vive en el front-matter YAML de su `TASK.md`, campo `status`. Ningún otro archivo redefine el estado; los demás artefactos solo aportan evidencia. Esto previene estado duplicado / autoridad paralela.

## Máquina de estados

```
DRAFT
  → READY              (iniciador: tarea bien formada, lista para ejecutor)
  → IN_PROGRESS        (ejecutor toma la tarea)
  → EVIDENCE_READY     (ejecutor: WORKLOG + FINAL_REPORT completos)
  → UNDER_REVIEW       (revisor: REVIEW emitido)
  → DECISION_PROPOSED  (cualquier agente: proposed_decision, authority=proposed)
  → HUMAN_DECISION     (SOLO Jorge: DECISION.md + authority=human_final)
        ├─ APPROVED → HANDOFF_TO_MSO   (entra al flujo soberano normal; ningún agente ejecuta)
        └─ REJECTED → CLOSED_REJECTED
```

Reglas de transición → ver `RULES_OF_ENGAGEMENT.md`. Cualquier ambigüedad o campo faltante ⇒ la tarea se considera **bloqueada** (fail-closed), no se avanza.

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

## Flujo Claude ↔ Codex sin cable humano

```
TASK(READY) → [Claude] ejecuta en rama, deja WORKLOG+FINAL_REPORT → EVIDENCE_READY
            → [Codex] lee evidencia SIN Jorge, emite REVIEW         → UNDER_REVIEW
            → agentes convergen                                      → DECISION_PROPOSED
            → [Jorge] aprueba/rechaza (merge/PR)                     → HUMAN_DECISION
            → si APPROVED: PR entra a MSO/Police                     → HANDOFF_TO_MSO
```

Jorge solo participa en `HUMAN_DECISION`. El contexto vive en el repo; cada agente lo lee directo. Jorge no transporta contexto.

## Límites de este tramo (Police)

Este tramo es **contrato verificable**, no autonomía. No incluye: Runner, ejecución headless, cron, servicios permanentes, GitHub Actions, túneles, VPS, Docker, tokens, ni cambios en MSO/Police/Policy/Auth. La autonomía posterior debe apoyarse en este contrato para no ser teatro ni depender de Jorge como cable.
