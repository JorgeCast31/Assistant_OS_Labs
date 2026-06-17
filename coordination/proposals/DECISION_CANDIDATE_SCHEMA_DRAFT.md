# DECISION_CANDIDATE.schema — **DRAFT no vinculante** (v3)

> **Tipo:** draft de esquema, **no vinculante**. Acompaña a `HUMAN_APPROVAL_MODEL_V3.md`.
> **Estado:** propuesta (`authority=proposed`). No es un schema vigente.
> **No** reemplaza `DECISION.schema.md` ni ningún schema de v2. v2 sigue rigiendo.
> **Alcance:** solo describe el artefacto candidato propuesto por v3. No implementa nada.

---

## 1. Propósito

Describir, como borrador, el artefacto **`DECISION_CANDIDATE`**: un documento de decisión **redactado por un agente** y **pendiente de aprobación humana verificable** de Jorge. Materializa el principio `authorship != authority`:

- un agente puede **redactar** (`generated_by`),
- solo Jorge **aprueba** por acto verificable (`approved_by` + `approval_method`),
- el candidato **no tiene autoridad efectiva** hasta ese acto (`effective_authority: none`).

Este draft es la base de discusión para un eventual `DECISION_CANDIDATE.schema.md` vigente, que **solo** se adoptaría tras aprobación humana de v3.

---

## 2. Ubicación propuesta

- Candidatos: `coordination/proposals/` (o una carpeta dedicada `coordination/candidates/`, a decidir si v3 se aprueba).
- Decisiones efectivas: siguen en `coordination/decisions/` y **solo** existen tras el acto humano de §4 del modelo v3. Un agente **nunca** escribe en `decisions/`.
- Nombre de archivo sugerido del candidato: `TASK-NNNN.DECISION_CANDIDATE.md` (el slug vive en `id`, consistente con el naming único de v2).

---

## 3. Front-matter — estado CANDIDATE (antes de aprobación)

```yaml
# EJEMPLO ILUSTRATIVO — DRAFT, no es un artefacto real
id: TASK-NNNN-...                  # required; mismo NNNN/id que la TASK
artifact_kind: DECISION_CANDIDATE  # required; fija el tipo de artefacto
generated_by: claude               # required; autoría material (agente). enum: claude | codex
prepared_for: jorge                # required; destinatario de la aprobación
artifact_status: CANDIDATE         # required; enum: CANDIDATE | APPROVED | REJECTED | SUPERSEDED
intended_authority: human_final    # required; lo que SERÍA tras aprobación humana
effective_authority: none          # required; lo que ES ahora. En candidato SIEMPRE 'none'
requires_human_approval: true      # required; siempre true en un candidato
approval_method_expected: github_merge   # required; cuál evento de §4 se espera
proposed_decision: APPROVED        # null | APPROVED | REJECTED  (propuesta del agente, no autoridad)
created_at: 2026-06-17             # required (ISO date)
updated_at: 2026-06-17             # required
```

Prohibido en estado CANDIDATE (su presencia ⇒ artefacto inválido/nulo):
`approved_by`, `approval_method`, `approved_at`, `effective_authority: human_final`, `decided_by: jorge`, `authority: human_final`.

---

## 4. Front-matter — estado APPROVED (tras acto humano verificable)

```yaml
# EJEMPLO ILUSTRATIVO — DRAFT. Estos campos NO los escribe un agente:
# los materializa el evento humano verificable de Jorge (§4 del modelo v3).
id: TASK-NNNN-...
artifact_kind: DECISION            # promovido desde DECISION_CANDIDATE
generated_by: claude               # la autoría NO cambia: el agente lo redactó
approved_by: jorge                 # autoridad: SOLO Jorge
approval_method: github_merge      # acto verificable real (merge/commit firmado/UI auditable)
approved_at: <timestamp>           # sellado por el evento humano, no por el agente
effective_authority: human_final   # ahora SÍ es autoridad final
decision: APPROVED                 # enum: APPROVED | REJECTED
resulting_status: HANDOFF_TO_MSO   # APPROVED ⇒ HANDOFF_TO_MSO (lo fija MSO) | REJECTED ⇒ CLOSED_REJECTED
pr_ref: <PR mergeado por Jorge>    # el PR que materializa la decisión
```

> El bloque anterior es un **ejemplo** dentro de un draft. **Ningún agente** escribe estos campos. Su escritura por un agente, sin el evento verificable correspondiente, hace el artefacto **inválido y nulo** (regla anti-fraude §5 del modelo v3).

---

## 5. Reglas de validación (draft, fail-closed)

1. **`generated_by ≠ approved_by`.** Autoría y autoridad son campos distintos. Un candidato tiene `generated_by` y **no** `approved_by`.
2. **`effective_authority` manda.** `none` en CANDIDATE; `human_final` solo en APPROVED y solo tras el evento verificable de §4 del modelo v3.
3. **No auto-aprobación.** Un agente no escribe `approved_by`, `approval_method`, `approved_at` ni `effective_authority: human_final`. Hacerlo ⇒ nulo.
4. **Enforcement por acceso, no honor-system.** La promoción a `DECISION`/`human_final` requiere un acto de Jorge que el agente no puede producir (merge, commit firmado, UI auditable).
5. **Verificabilidad.** `approval_method` debe cotejarse contra el historial real (quién mergeó/firmó). Sin evento correspondiente ⇒ se trata como CANDIDATE/nulo.
6. **No ejecuta.** `APPROVED` autoriza solo el flujo soberano normal (`resulting_status: HANDOFF_TO_MSO`, fijado por MSO). `mso_executable` sigue siendo exclusivo de MSO.
7. **Revisor ≠ generador.** El candidato lo revisa un agente distinto del que lo generó (no auto-review), consistente con v2.
8. **Fail-closed.** Campo `required` ausente, enum fuera de rango, o discrepancia frontmatter/evento ⇒ artefacto inválido; no se promueve.

---

## 6. Compatibilidad con v2

- **v2 sigue válido y vigente** hasta que v3 sea **aprobado por acto humano verificable de Jorge.** Mientras tanto, `DECISION.schema.md` v2 es el único schema de decisión en vigor.
- Este draft **no** modifica `DECISION.schema.md`, `TASK.schema.md`, `README.md`, `AGENT_CONTRACT.md` ni `RULES_OF_ENGAGEMENT.md`.
- v3 es un **superconjunto disciplinado** de v2: añade el artefacto candidato sin relajar ninguna invariante (ver tabla §9 de `HUMAN_APPROVAL_MODEL_V3.md`).
- Si v3 se aprueba, un PR posterior definiría el schema vigente y los ajustes de carpeta/contrato. Eso queda **fuera** de este PR.

### Qué NO hace este PR

- **No** cierra TASK-0002.
- **No** crea ninguna decisión real (ni candidato real de TASK-0002).
- **No** autoriza Runner ni ninguna automatización.
- **No** confiere autoridad a ningún agente.
