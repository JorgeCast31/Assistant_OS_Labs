---
id: TASK-0001-no-human-cable-contract
title: Validar manualmente el ciclo de coordinación coordination/ (TASK→WORKLOG→FINAL_REPORT→REVIEW→DECISION) antes de diseñar Runner
author: jorge
authority: proposed
assigned_agent: claude
reviewer: codex
status: DRAFT
scope:
  - coordination/
permissions:
  read:
    - coordination/
    - README.md
    - AGENTS.md
  write_proposal:
    - coordination/worklogs/
    - coordination/reports/
  forbidden:
    - assistant_os/mso
    - assistant_os/police
    - assistant_os/policy
    - auth
    - .env
    - secrets
    - .github/workflows
risks:
  - Riesgo de tratar el contrato como autonomía antes de validarlo manualmente (teatro).
  - Riesgo de estado duplicado si algún artefacto redefine status fuera de TASK.md.
evidence: []
files_touched: []
proposed_decision: null
blocked: false
blocked_reason: null
next_action: "Jorge revisa el contrato; si lo aprueba, mueve esta tarea a READY para que Claude ejecute el ciclo de prueba."
created_at: 2026-06-13
updated_at: 2026-06-13
---

## Contexto

`coordination/` se acaba de proponer como bus de coordinación versionado Claude↔Codex (tramo B aprobado por MSO/Police). Antes de diseñar o implementar cualquier Agent Runner, hay que **probar el ciclo manualmente** para confirmar que el contrato es operable y no teatro.

## Objetivo

Recorrer una vez el ciclo completo con una tarea trivial y verificable:

1. Jorge mueve esta tarea a `READY`.
2. **Claude** (ejecutor) la toma → `IN_PROGRESS`, deja `worklogs/TASK-0001-...WORKLOG.md` y `reports/TASK-0001-...FINAL_REPORT.md` → `EVIDENCE_READY`.
3. **Codex** (revisor) lee la evidencia **sin intervención de Jorge**, emite `reviews/TASK-0001-...REVIEW.md` → `UNDER_REVIEW`, deja `proposed_decision`.
4. Agentes convergen → `DECISION_PROPOSED`.
5. **Jorge** decide en `decisions/TASK-0001-...DECISION.md` (`authority=human_final`) y aprueba/mergea el PR → `HUMAN_DECISION` → `HANDOFF_TO_MSO` o `CLOSED_REJECTED`.

La "tarea trivial" sugerida: que Claude proponga (en rama, como evidencia) una corrección menor y verificable dentro de `coordination/` (p. ej. un typo o una aclaración en un schema), y que Codex la revise. **Sin tocar código del sistema.**

## Alcance y límites

- Solo `coordination/`. Cero cambios en MSO/Police/Policy/Auth.
- Trabajo en rama `agent/TASK-0001-no-human-cable-contract`, nunca `main`.
- Sin Runner, sin ejecución headless, sin automatización. Este ciclo se hace a mano.

## Criterios de aceptación

- [ ] La tarea pasa de `TASK` a `FINAL_REPORT` con evidencia real.
- [ ] Codex lee la evidencia de Claude sin que Jorge transporte contexto.
- [ ] Claude puede leer el REVIEW de Codex sin que Jorge transporte contexto.
- [ ] Jorge solo aprueba/rechaza; no transporta contexto.
- [ ] Ningún agente escribió `authority=human_final`/`jorge`/`approved_by_jorge`.
- [ ] El estado vivió siempre y solo en `TASK.md.status`.
- [ ] Ninguna ejecución ocurrió fuera de MSO/Police (de hecho, no hubo ejecución de dominio).

## Notas

Esta tarea es el **dogfood** del contrato. Si el ciclo manual funciona limpio, recién entonces tiene sentido diseñar el Agent Runner (tramo C).
