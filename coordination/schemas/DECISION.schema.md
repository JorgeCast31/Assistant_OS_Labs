# DECISION.schema — decisión humana y candidato de decisión — **v3.1**

> **v3 activo** (PR #246/#247). **Enmienda v3.1:** aclara que un agente **puede redactar el artefacto `DECISION` como PROPUESTA en una rama/PR**, cuya autoridad se materializa por el **merge verificable de Jorge de ese mismo PR** (materialización en el mismo PR, §C.bis). No relaja la invariante de seguridad: un agente sigue **sin poder mergear** ni hacer efectivo nada; el efecto lo produce el merge de Jorge. Diseño: `proposals/HUMAN_APPROVAL_MODEL_V3.md`.

> **Principio rector (v2, vigente):** `main` es la única fuente autoritativa; **el chat nunca es autoridad**; *"si no está commiteado a `main`, no pasó"*. Por tanto, un artefacto de decisión **en rama es solo propuesta**, aunque su frontmatter contenga campos de aprobación: no es efectivo hasta el merge de Jorge.

Este schema cubre **dos artefactos** del mismo eje de decisión:

| Artefacto | Archivo | Carpeta | Quién lo redacta | ¿Autoridad? |
|---|---|---|---|---|
| `DECISION_CANDIDATE` | `TASK-NNNN.DECISION_CANDIDATE.md` | `coordination/candidates/` | Claude o Codex (agente) | **Ninguna** (`effective_authority: none`) |
| `DECISION` (propuesta en rama) | `TASK-NNNN.DECISION.md` | `coordination/decisions/` | **redactable por agente** como propuesta condicional (`requires_verifiable_human_approval: true`) | **Ninguna aún** — propuesta, no efectiva hasta el merge de Jorge |
| `DECISION` (efectiva en `main`) | `TASK-NNNN.DECISION.md` | `coordination/decisions/` | **materializada** por el merge verificable de **Jorge** | `human_final` |

> **Regla central (no negociable):**
> ```text
> Agent-generated decision candidates are allowed.
> Agent-approved human_final decisions are invalid.
> Human approval is a verifiable event, not physical authorship.
> ```

---

## A. `DECISION_CANDIDATE` (redactado por agente)

Vive en `coordination/candidates/TASK-NNNN.DECISION_CANDIDATE.md`. Un agente (≠ revisor) lo redacta. **No tiene autoridad.** Solo prepara contenido para que Jorge decida.

### A.1 Front-matter — estado CANDIDATE

```yaml
id: TASK-NNNN-...                  # required; mismo NNNN/id que la TASK
artifact_kind: DECISION_CANDIDATE  # required; fija el tipo
generated_by: claude               # required; autoría material. enum: claude | codex
prepared_for: jorge                # required; destinatario de la aprobación
artifact_status: CANDIDATE         # required; enum: CANDIDATE | APPROVED | REJECTED | SUPERSEDED
intended_authority: human_final    # required; lo que SERÍA tras aprobación humana
effective_authority: none          # required; lo que ES ahora. En CANDIDATE siempre 'none'
requires_human_approval: true      # required; siempre true en un candidato
approval_method_expected: github_merge  # required; enum: github_merge | github_review_then_merge | signed_commit | assistant_os_ui
proposed_decision: APPROVED        # required; null | APPROVED | REJECTED (propuesta del agente, NO autoridad)
created_at: 2026-06-17             # required (ISO date)
updated_at: 2026-06-17             # required
```

**Prohibido en estado CANDIDATE** (su presencia ⇒ artefacto **inválido y nulo**):
`approved_by`, `approval_method`, `approved_at`, `decided_by: jorge`, `authority: human_final`, `effective_authority: human_final`.

### A.2 Cuerpo

```
## Decisión propuesta
## Justificación / evidencia
## Condiciones / alcance que se aprobaría
## Qué NO se autorizaría
## Evento de aprobación esperado   # cuál de los métodos de §C materializaría la autoridad
```

---

## B. `DECISION` (autoridad humana materializada)

Vive en `coordination/decisions/TASK-NNNN.DECISION.md`. Es la decisión **final humana**. Su autoridad la confiere un **evento verificable de Jorge** (§C), no la redacción del texto.

### B.0 Fase de propuesta en rama (v3.1) — redactada por agente

Un agente (≠ revisor) puede **redactar** el artefacto `DECISION` en una **rama** y proponerlo vía PR, **derivándolo de un `DECISION_CANDIDATE` ya aprobado en `main`**. En esta fase el artefacto es una **propuesta condicional**, no autoridad:

- vive en la rama (no en `main`): por el principio rector, una rama solo propone;
- **debe** incluir `requires_verifiable_human_approval: true`;
- **debe** incluir, visible en el cuerpo, la nota de no-efectividad (§B.3);
- el agente **no** puede mergear el PR ni hacerlo efectivo; el efecto lo produce **solo** el merge de Jorge (§C.bis).

Los campos de aprobación (`approved_by: jorge`, `approval_method`, `effective_authority: human_final`, etc.) presentes en la propuesta **no son afirmaciones de un hecho ya ocurrido**: son la forma que tomará el artefacto **cuando** Jorge mergee. Antes del merge de Jorge **no tienen efecto**; si los mergea o aprueba un agente, el artefacto es **inválido y nulo** (§D.4). El frontmatter es idéntico al de §B.1; lo que cambia es que, en rama, **aún no es efectivo**.

### B.1 Front-matter — estado APPROVED/efectivo

```yaml
id: TASK-NNNN-...                  # required
artifact_kind: DECISION            # required
source_candidate: coordination/candidates/TASK-NNNN.DECISION_CANDIDATE.md  # required en v3.1 si deriva de un candidato; trazabilidad
generated_by: claude               # optional; autoría material del contenido (si vino de un candidato). NO cambia con la aprobación
requires_verifiable_human_approval: true  # required (v3.1); reafirma que la efectividad depende del merge de Jorge
approved_by: jorge                 # required; SOLO 'jorge'
approval_method: github_merge      # required; el evento real de §C que materializó la autoridad
approved_at: 2026-06-17            # required; sellado por el evento humano
decided_by: jorge                  # required; debe ser 'jorge' (compat v2)
authority: human_final             # required; único lugar (junto con effective_authority) donde aparece human_final
effective_authority: human_final   # required; efectivo SOLO tras el merge de Jorge (en rama es propuesta, §B.0)
decision: APPROVED                 # required; enum: APPROVED | REJECTED
resulting_status: HUMAN_DECISION    # required: HUMAN_DECISION (si APPROVED — la decisión humana materializa este estado del TASK) | CLOSED_REJECTED (si REJECTED)
pr_ref: <PR mergeado por Jorge>     # required; el PR/commit que materializa la decisión
decided_at: 2026-06-17             # required (compat v2)
```

> **Nota sobre `resulting_status` (v3.1).** Para `APPROVED`, la decisión humana materializa la transición del TASK a **`HUMAN_DECISION`** (estado propiedad de Jorge). El paso posterior a **`HANDOFF_TO_MSO`** es un acto **separado y exclusivo de MSO** por el flujo soberano; **ninguna `DECISION` ni ningún agente** lo fija. (Esto precisa el v2, que escribía `HANDOFF_TO_MSO` directamente.)

### B.2 Cuerpo

```
## Decisión
## Justificación
## Condiciones / alcance autorizado
## Qué NO se autoriza
```

### B.3 Nota de no-efectividad (obligatoria en la propuesta en rama)

Toda `DECISION` redactada por un agente y propuesta en rama (§B.0) **debe** incluir, textual y visible, una nota equivalente a:

```text
This DECISION is not effective until Jorge merges this PR.
If merged or approved by an agent, it is invalid/null.
```

La ausencia de esta nota en una propuesta redactada por agente ⇒ artefacto **inválido** (fail-closed).

---

## C. Cómo se verifica la aprobación de Jorge (evento verificable)

`effective_authority: human_final` es **real** solo cuando existe un **acto humano verificable de Jorge** que un agente **no puede producir**. Métodos válidos (`approval_method`):

- `github_merge` — Jorge mergea el PR que contiene/promueve el candidato.
- `github_review_then_merge` — Jorge aprueba el PR (review) y lo mergea.
- `signed_commit` — commit firmado por Jorge del artefacto en `decisions/`.
- `assistant_os_ui` — aprobación futura vía UI auditable de Assistant OS (cuando exista), atribuible a Jorge de forma no falsificable.

**Propiedad común:** todos son actos de **control de acceso** del repositorio/sistema. La autoridad la da el **evento**, no el texto del frontmatter. El enforcement es acceso (los agentes no mergean ni aprueban PRs), **no** honor-system.

`approval_method` debe poder **cotejarse contra el historial real** (quién mergeó / quién firmó). Un `approved_by: jorge` **efectivo en `main`** sin evento correspondiente en el historial es fraude detectable ⇒ artefacto **inválido y nulo**.

### C.bis Materialización en el mismo PR (v3.1)

El **evento verificable** puede ser el **merge, por Jorge, del propio PR que introduce el artefacto `DECISION`**. En ese caso:

- mientras el PR está abierto, el artefacto vive **en rama** y es una **propuesta condicional** (§B.0): sus campos de aprobación **no tienen efecto**;
- el **merge de Jorge** es el `approval_method: github_merge` que **materializa** la autoridad en el momento del merge;
- el `pr_ref` referencia ese mismo PR;
- un agente **no** puede producir ese merge (control de acceso). Si un agente mergea, o si el PR nunca lo mergea Jorge, el artefacto **nunca es efectivo** y es **nulo**.

> **Propuesta condicional vs. manufactura.** Que un agente **redacte** los campos de aprobación dentro de una **propuesta en rama** marcada `requires_verifiable_human_approval: true` y con la nota de §B.3 **no es manufactura de autoridad**: es preparar el artefacto que el merge de Jorge volverá efectivo. **Manufactura** (nula) es escribir esos campos **sin** marcar la propuesta como condicional, **o** hacerlos efectivos en `main` **sin** un merge de Jorge que los respalde. La distinción la garantiza el control de acceso: el agente no mergea; el efecto siempre lo da Jorge.

---

## D. Reglas (fail-closed) — críticas

1. **`generated_by != approved_by`.** Autoría material y autoridad son campos distintos. Un candidato tiene `generated_by` y **no** `approved_by`. La aprobación **no** borra ni reescribe `generated_by`.
2. **`effective_authority` manda.** `none` en CANDIDATE; `human_final` solo en `DECISION` y solo tras el evento verificable de §C.
3. **Ningún agente se auto-aprueba.** Un agente solo puede escribir `approved_by`, `approval_method`, `approved_at`, `decided_by: jorge`, `authority/effective_authority: human_final` dentro de una **propuesta en rama** (§B.0) marcada `requires_verifiable_human_approval: true` y con la nota de §B.3, cuyo único activador es el **merge de Jorge** (§C.bis). Escribirlos **sin** ese marco condicional, o hacerlos **efectivos en `main`** sin merge de Jorge, ⇒ **inválido y nulo**. El agente nunca se aprueba a sí mismo: `generated_by != approved_by`.
4. **Si un agente mergea o intenta auto-aprobar.** Cualquier merge, aprobación de PR, o promoción a `human_final` **ejecutada por un agente** es **inválida y nula**. La defensa primaria es control de acceso (los agentes no tienen permiso de merge/aprobar/push a `main`); la secundaria es verificabilidad (§C).
5. **`decisions/` es terreno humano; el agente solo propone.** Ningún agente **mergea, hace efectivo, ni escribe directamente en `main`** dentro de `coordination/decisions/`. Un agente **sí** puede **redactar en rama** (vía PR) un artefacto `DECISION` como **propuesta condicional** derivada de un candidato aprobado (§B.0); ese artefacto **no es efectivo** hasta el merge verificable de Jorge. El borrador de trabajo libre del agente sigue siendo el candidato en `coordination/candidates/`.
6. **No ejecuta.** `APPROVED` materializa la transición del TASK a **`HUMAN_DECISION`** (propiedad de Jorge); el paso a **`HANDOFF_TO_MSO`** es exclusivo de **MSO** y **ninguna `DECISION` ni agente** lo fija. La decisión solo autoriza el flujo soberano. `mso_executable` sigue siendo exclusivo de MSO. `REJECTED ⇒ CLOSED_REJECTED`.
7. **Revisor ≠ generador.** El candidato lo revisa un agente distinto del que lo generó (no auto-review).
8. **Runner no promueve.** Un Runner futuro puede *detectar y notificar* candidatos (`effective_authority: none`), pero **no** puede convertirlos a `human_final` ni mergear/aprobar. Ver `RULES_OF_ENGAGEMENT.md`.
9. **Fail-closed.** Campo `required` ausente, enum fuera de rango, candidato con campos de aprobación, o discrepancia frontmatter/evento ⇒ artefacto inválido; no se promueve.

---

## E. Cómo Codex revisa un candidato

Codex (revisor, ≠ generador) verifica sobre un `DECISION_CANDIDATE`:

1. **Archivos** — el candidato solo toca `coordination/candidates/`; nunca `decisions/`, MSO/Police/Policy/Auth, secrets ni workflows.
2. **`generated_by`** — coincide con la autoría real del diff.
3. **No auto-aprobación** — sin `approved_by`/`approval_method`/`approved_at`/`authority: human_final`; `effective_authority: none`.
4. **No Runner** — no introduce ejecución, automatización, cron, workflows ni headless.
5. **No escalamiento** — no toca autoridad/tokens ni amplía `scope`/`permissions` declarados en la TASK.
6. **Evento requerido** — declara `requires_human_approval: true` y un `approval_method_expected` válido de §C.
7. **Compatibilidad con `main`** — coherente con el estado autoritativo; no duplica ni contradice estado canónico.

Codex emite `proposed_decision ∈ {GO, NO-GO, NEEDS_CHANGES}` con `authority: proposed`. **Codex tampoco aprueba**: solo verifica que el candidato está bien formado y es seguro para que Jorge decida.

### E.bis Cómo Codex revisa una propuesta de `DECISION` en rama (v3.1)

Codex (≠ generador) verifica sobre una propuesta `DECISION` (en `decisions/`, en rama):

1. **Solo archivos permitidos** — el PR toca a lo sumo `decisions/TASK-NNNN.DECISION.md` y `tasks/TASK-NNNN.md`; nunca MSO/Police/Policy/Auth, secrets, workflows, STATE.md ni el candidato.
2. **Deriva de un candidato aprobado** — `source_candidate` apunta a un `DECISION_CANDIDATE` ya en `main`; el contenido es coherente con él.
3. **Marca condicional presente** — `requires_verifiable_human_approval: true` y la **nota de no-efectividad** (§B.3) están presentes.
4. **Autoridad depende del merge de Jorge** — el artefacto **no** es efectivo en la rama; ningún agente lo mergea ni lo aprueba.
5. **Transición correcta** — propone `TASK.status: HUMAN_DECISION` (no `HANDOFF_TO_MSO`, que es de MSO); `resulting_status: HUMAN_DECISION`.
6. **No Runner / no escalamiento** — no introduce ejecución, automatización, tokens ni cambios de permisos.

Si todo se cumple, Codex emite `GO` (con `authority: proposed`); **no aprueba** la decisión: solo verifica que es segura para que **Jorge** la mergee.

---

## F. Cierre de TASK-0002 bajo v3.1

Este schema **no** cierra TASK-0002. El cierre se materializa así:

1. Claude prepara `candidates/TASK-0002.DECISION_CANDIDATE.md` (`generated_by: claude`, `effective_authority: none`). **(Hecho — PR #248, mergeado.)**
2. Codex lo revisa (§E). **(Hecho — GO.)**
3. **(v3.1)** Claude redacta **en rama** `decisions/TASK-0002.DECISION.md` como **propuesta condicional** (derivada del candidato, `requires_verifiable_human_approval: true`, nota §B.3) y propone en el mismo PR `tasks/TASK-0002.md → status: HUMAN_DECISION`.
4. Codex revisa la propuesta (§E.bis).
5. **Jorge mergea el PR** (evento verificable, §C.bis). Solo ese merge **materializa** `decisions/TASK-0002.DECISION.md` como `human_final` y la transición a `HUMAN_DECISION`.
6. El paso posterior a `HANDOFF_TO_MSO`, si correspondiera, es exclusivo de **MSO**; ni la `DECISION` ni un agente lo fijan.
7. El Runner Design Review **solo** empieza después de cerrar TASK-0002.

Jorge **no teclea** el markdown final; **aprueba responsablemente** su contenido por el merge. Authorship (agente) ≠ Authority (Jorge).
