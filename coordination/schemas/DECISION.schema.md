# DECISION.schema — decisión humana y candidato de decisión — **v3**

> **v3 activo.** Adopta el modelo *Human Approval Model* (`authority != authorship`): un agente puede **redactar** un candidato de decisión; **solo Jorge** confiere autoridad, por un **evento verificable**. Diseño: `proposals/HUMAN_APPROVAL_MODEL_V3.md` (aprobado y mergeado en PR #246).

Este schema cubre **dos artefactos** del mismo eje de decisión:

| Artefacto | Archivo | Carpeta | Quién lo redacta | ¿Autoridad? |
|---|---|---|---|---|
| `DECISION_CANDIDATE` | `TASK-NNNN.DECISION_CANDIDATE.md` | `coordination/candidates/` | Claude o Codex (agente) | **Ninguna** (`effective_authority: none`) |
| `DECISION` | `TASK-NNNN.DECISION.md` | `coordination/decisions/` | materializada por evento verificable de **Jorge** | `human_final` |

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

### B.1 Front-matter — estado APPROVED/efectivo

```yaml
id: TASK-NNNN-...                  # required
artifact_kind: DECISION            # required
generated_by: claude               # optional; autoría material del contenido (si vino de un candidato). NO cambia con la aprobación
approved_by: jorge                 # required; SOLO 'jorge'
approval_method: github_merge      # required; el evento real de §C que materializó la autoridad
approved_at: 2026-06-17            # required; sellado por el evento humano
decided_by: jorge                  # required; debe ser 'jorge' (compat v2)
authority: human_final             # required; único lugar (junto con effective_authority) donde aparece human_final
effective_authority: human_final   # required; ahora SÍ es autoridad final
decision: APPROVED                 # required; enum: APPROVED | REJECTED
resulting_status: HANDOFF_TO_MSO    # required: HANDOFF_TO_MSO (si APPROVED) | CLOSED_REJECTED (si REJECTED)
pr_ref: <PR mergeado por Jorge>     # required; el PR/commit que materializa la decisión
decided_at: 2026-06-17             # required (compat v2)
```

### B.2 Cuerpo

```
## Decisión
## Justificación
## Condiciones / alcance autorizado
## Qué NO se autoriza
```

---

## C. Cómo se verifica la aprobación de Jorge (evento verificable)

`effective_authority: human_final` es **real** solo cuando existe un **acto humano verificable de Jorge** que un agente **no puede producir**. Métodos válidos (`approval_method`):

- `github_merge` — Jorge mergea el PR que contiene/promueve el candidato.
- `github_review_then_merge` — Jorge aprueba el PR (review) y lo mergea.
- `signed_commit` — commit firmado por Jorge del artefacto en `decisions/`.
- `assistant_os_ui` — aprobación futura vía UI auditable de Assistant OS (cuando exista), atribuible a Jorge de forma no falsificable.

**Propiedad común:** todos son actos de **control de acceso** del repositorio/sistema. La autoridad la da el **evento**, no el texto del frontmatter. El enforcement es acceso (los agentes no mergean ni aprueban PRs), **no** honor-system.

`approval_method` debe poder **cotejarse contra el historial real** (quién mergeó / quién firmó). Un `approved_by: jorge` sin evento correspondiente en el historial es fraude detectable ⇒ artefacto **inválido y nulo**.

> **Transcripción, no manufactura.** Los campos de estado APPROVED (`approved_by`, `approval_method`, `approved_at`, `authority/effective_authority: human_final`, `pr_ref`) **transcriben** un evento que ya ocurrió y es verificable. Un agente **nunca** los manufactura: si los escribe sin un evento real de Jorge que los respalde, el artefacto es nulo (fail-closed). Y aunque los transcribiera correctamente, la transcripción solo entra a `main` por otro merge de Jorge.

---

## D. Reglas (fail-closed) — críticas

1. **`generated_by != approved_by`.** Autoría material y autoridad son campos distintos. Un candidato tiene `generated_by` y **no** `approved_by`. La aprobación **no** borra ni reescribe `generated_by`.
2. **`effective_authority` manda.** `none` en CANDIDATE; `human_final` solo en `DECISION` y solo tras el evento verificable de §C.
3. **Ningún agente se auto-aprueba.** Un agente no escribe `approved_by`, `approval_method`, `approved_at`, `decided_by: jorge`, `authority: human_final` ni `effective_authority: human_final` sin evento real. Hacerlo ⇒ **inválido y nulo**.
4. **Si un agente mergea o intenta auto-aprobar.** Cualquier merge, aprobación de PR, o promoción a `human_final` ejecutada por un agente es **inválida y nula**. La defensa primaria es control de acceso (los agentes no tienen permiso de merge/aprobar/push a `main`); la secundaria es verificabilidad (§C).
5. **`decisions/` es terreno humano.** Ningún agente escribe en `coordination/decisions/`. Un agente redacta en `coordination/candidates/`.
6. **No ejecuta.** `APPROVED ⇒ resulting_status: HANDOFF_TO_MSO`, fijado por **MSO**; la decisión solo autoriza el flujo soberano. `mso_executable` sigue siendo exclusivo de MSO. `REJECTED ⇒ CLOSED_REJECTED`.
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

---

## F. Cierre de TASK-0002 bajo v3 (en un PR posterior)

Este schema **no** cierra TASK-0002. Bajo v3, el cierre futuro sería:

1. Claude prepara `candidates/TASK-0002.DECISION_CANDIDATE.md` (`generated_by: claude`, `effective_authority: none`), reusando `proposals/TASK-0002.HUMAN_DECISION_DRAFT.md`.
2. Codex lo revisa (§E).
3. Jorge lo aprueba/mergea en GitHub (evento verificable de §C).
4. Solo entonces se materializa `decisions/TASK-0002.DECISION.md` (`approved_by: jorge`, `effective_authority: human_final`) y TASK-0002 pasa a `HUMAN_DECISION`.
5. El Runner Design Review **solo** empieza después de cerrar TASK-0002.

Jorge **no teclea** el markdown final; **aprueba responsablemente** su contenido. Authorship (agente) ≠ Authority (Jorge).
