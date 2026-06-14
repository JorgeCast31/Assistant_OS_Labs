---
id: TASK-0001-no-human-cable-contract
agent: claude
authority: proposed
status_at_report: "DRAFT (blocked=true) — RETRACTADO de EVIDENCE_READY por decisión MSO/Police; ver banner de corrección"
created_at: 2026-06-13
---

# FINAL_REPORT — TASK-0001-no-human-cable-contract (ejecutor: Claude)

> ## ⛔ CORRECCIÓN — DOGFOOD FAILED USEFULLY (no es éxito)
> **Clasificación MSO/Police: `TASK-0001 = dogfood failed usefully / needs contract correction`.**
> El ciclo **NO se considera exitoso** y **NO valida el Runner**. El dogfood falló por **F1**: la tarea seguía en `DRAFT` en el repo y el ejecutor avanzó a `EVIDENCE_READY` apoyándose en autorización por **chat** (out-of-band), lo que viola el criterio no-human-cable y la propiedad de estado del iniciador.
> **Corrección aplicada:** `status` revertido a `DRAFT` + `blocked=true` (el enum de `status` **no** tiene `BLOCKED` ni `NEEDS_CHANGES`; ver F5/§6). `proposed_decision=NEEDS_CHANGES`.
> **No hay autorización para automatizar.** Esto se preserva como **evidencia de fallo útil**: el contrato detectó una brecha real, pero el proceso aún **no es autocontenido**. Primero se corrige F1/F2 (y se decide F6), luego se repite el dogfood limpio.
> Las secciones de abajo conservan el análisis original (la evidencia del intento); su encuadre de "EVIDENCE_READY" queda **superado** por este banner.

Trabajo asignado: recorrer la parte de Claude del ciclo de dogfood y, como tarea trivial y verificable, **revisar el propio contrato `coordination/`** para detectar fricción, ambigüedad o estado duplicado, sin tocar código. Esta es evidencia para que **Codex** revise leyendo solo el repo.

## 1. Estado del sistema

- `coordination/` presente en disco con los 13 archivos del tramo B (verificado por `find`).
- Git del sandbox inconsistente tras el merge (`Failed to resolve HEAD`) — atribuible al montaje FUSE; la verificación de tracking/commit y todo `git` se hace en Windows. **No** afirmo haber confirmado estado git.
- El ciclo de coordinación es operable a nivel de artefactos: pude tomar la tarea, leer todo el contrato desde el repo, y producir WORKLOG + este FINAL_REPORT siguiendo los schemas.

## 2. Hallazgos

Cinco hallazgos, todos verificables contra archivos del repo (ruta + línea citadas en el WORKLOG):

- **F1 — `READY` no registrable por el ejecutor / autorización fuera del repo (severidad ALTA).**
  `TASK-0001.status` estaba en `DRAFT`. Por `RULES_OF_ENGAGEMENT.md`, `DRAFT→READY` la fija el **iniciador (Jorge)**, e `IN_PROGRESS` solo viene de `READY`. La autorización para ejecutar llegó por **chat**, no in-file. Resultado: leyendo **solo el repo**, Codex no ve que `READY` fue autorizado → se reintroduce transporte de contexto fuera del repo (contradice el objetivo no-human-cable y la Regla de Oro 1). Es el hallazgo central del dogfood.
- **F2 — Convención de nombre de archivo inconsistente (MEDIA).** `<task-id>.WORKLOG.md` (README/schemas) vs `TASK-0001-...WORKLOG.md` (cuerpo TASK) vs `...-WORKLOG.md` con guion (instrucción Jorge). Tres patrones. Un validador/Runner futuro necesitaría un patrón único o fallaría.
- **F3 — Convención de rama inconsistente (BAJA).** `agent/<task-id>` (AGENT_CONTRACT) vs `coordination/task-0001-claude-evidence` (instrucción Jorge).
- **F4 — `.gitignore` (BAJA, ya resuelto).** `/agent_contract.md` anclado a raíz no afecta a `coordination/AGENT_CONTRACT.md`. El fix funciona; dejo caveat por si se reintroduce un patrón no anclado.
- **F5 — Acoplamiento reporte↔estado (BAJA→confirmada).** `FINAL_REPORT.schema` exige `status_at_report: EVIDENCE_READY` y dice "marca la transición a EVIDENCE_READY", sin contemplar el caso de fallo (F1). Al revertir a `DRAFT (blocked)`, el front-matter de este reporte ya **no puede** cumplir el `EVIDENCE_READY` hardcodeado del schema → el schema necesita admitir reportes de fallo.
- **F6 — Sin estado/transición de fallo ni regla de retracción (MEDIA, detectado en la corrección).** El enum de `status` no tiene estado terminal de fallo (`BLOCKED`/`ABORTED`); el bloqueo solo se expresa con el campo `blocked`. Además, el ejecutor solo puede *fijar* `IN_PROGRESS`/`EVIDENCE_READY` (RULES), así que **revertir** un avance ilegítimo a `DRAFT` queda fuera de su set permitido. El contrato necesita: (a) una regla de aborto/retracción y quién la ejecuta, y (b) decidir si el fallo se expresa con un status terminal nuevo o solo con `blocked=true`.

## 3. Cambios realizados (en working tree, a versionar en rama del dogfood)

- `coordination/worklogs/TASK-0001-no-human-cable-contract-WORKLOG.md` — NUEVO. Bitácora append-only de la ejecución.
- `coordination/reports/TASK-0001-no-human-cable-contract-FINAL_REPORT.md` — NUEVO. Este reporte.
- `coordination/tasks/TASK-0001-no-human-cable-contract.md` — MODIFICADO solo en campos que el contrato asigna al ejecutor: `status` → `EVIDENCE_READY`, `evidence`, `files_touched`, `proposed_decision`, `next_action`, `updated_at`. **No** se tocó `author`, `authority`, `assigned_agent`, `reviewer`, `scope`, `permissions`, `id`.

Ningún cambio fuera de `coordination/`. Sin tocar MSO/Police/Policy/Auth, código del sistema, workflows, `.env`, secretos, tokens ni permisos. Sin operaciones git desde el sandbox.

## 4. Validaciones

- **Pertenencia de archivos:** `find coordination -type f` ⇒ los 3 artefactos creados/modificados caen bajo `coordination/`. ✔ (verificable por Codex)
- **Estado único:** `status` vive solo en `TASK.md`; WORKLOG/FINAL_REPORT describen evidencia, no redefinen estado. ✔
- **Sin autoridad humana escrita por agente:** ninguno de los 3 archivos contiene `authority=human_final`/`jorge`/`approved_by_jorge`/`decided_by: jorge`/`mso_executable`. ✔ (Codex puede `grep` para confirmarlo)
- **Roles:** no se creó `REVIEW` (reservado a Codex) ni `DECISION` (reservado a Jorge). ✔
- **Git/tracking:** NO validado (sandbox FUSE inconsistente). Pendiente en Windows. ✗ (declarado honestamente)

## 5. Riesgos residuales

- F1 sin resolver: hasta que el iniciador registre `READY` in-file (o el contrato lo permita explícitamente al ejecutor citando la referencia autorizante), el repo no es 100% autocontenido para el revisor.
- F2/F3 (convenciones) no resueltos: bajos para el ciclo manual, pero **bloqueantes para un Runner** que parsee nombres/ramas.
- Estado git del dogfood depende de materialización en Windows (rama/PR), no hecha aquí.

## 6. Decisión propuesta

**`NEEDS_CHANGES`** (authority=proposed).

Justificación: el ciclo manual de artefactos **funciona** (se pudo coordinar por archivos reales, sin ejecución, sin autoridad falsa), lo que valida la premisa del contrato. PERO F1 es una fricción real que reintroduce transporte de contexto fuera del repo, y F2 es un riesgo concreto para automatización futura. Propuesta: **corregir F1 y F2 (y fijar convenciones F3) antes de diseñar el Agent Runner**, tal como pide el Police note ("si el contrato genera fricción… se corrige antes de diseñar Runner").

No es decisión final. Codex revisa; Jorge decide.

---

## Qué debe revisar Codex (handoff)

Codex, leyendo **solo el repo** (rama del dogfood), por favor verifica y emite `coordination/reviews/TASK-0001-no-human-cable-contract-REVIEW.md`:

1. **F1:** ¿coincides en que `DRAFT→READY` por el ejecutor viola RULES, y que la autorización por chat rompe "estado único en TASK.md"? Propón el fix mínimo: (a) Jorge commitea `READY` in-file, o (b) el contrato añade una regla para que el ejecutor registre `READY` citando referencia autorizante verificable.
2. **F2/F3:** ¿qué patrón único de nombre de archivo y de rama fijamos en README/schemas/AGENT_CONTRACT?
3. **Estado:** confirma que `status` solo aparece en `TASK.md` (sin duplicación).
4. **Sin autoridad falsa:** `grep -ri "human_final\|approved_by_jorge\|authority=jorge"` sobre los 3 artefactos ⇒ debe dar vacío.
5. **Alcance:** confirma que no se tocó nada fuera de `coordination/`.
6. Emite `proposed_decision` (GO / NO-GO / NEEDS_CHANGES) con objeciones verificables. No escribas `DECISION` (es de Jorge) ni `authority=human_final`.

**Criterio de éxito de este tramo:** que puedas hacer lo anterior sin que Jorge te transporte contexto — todo está en el repo.
