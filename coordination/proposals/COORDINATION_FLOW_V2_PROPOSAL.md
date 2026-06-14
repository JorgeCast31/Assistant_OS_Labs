# COORDINATION FLOW v2 — Propuesta documental

> **Tipo:** propuesta documental (no ejecuta nada, no implementa Runner).
> **Estado:** propuesta (`authority=proposed`). La autoridad final es de Jorge vía aprobación/merge del PR.
> **Alcance:** solo `coordination/`. No toca MSO/Police/Policy/Auth ni `.github/workflows`.
> **Origen:** corrige las brechas que el dogfood fallido de `TASK-0001` expuso en el contrato v1.

---

## 1. Por qué v2

El MVP v1 de `coordination/` validó la premisa (coordinar Claude↔Codex por archivos versionados, sin ejecución y sin autoridad falsa), pero el dogfood de `TASK-0001` **falló útilmente** y reveló cinco brechas estructurales:

| # | Brecha detectada en v1 | Hallazgo origen |
|---|---|---|
| B1 | `READY` podía autorizarse **por chat** (out-of-band); el repo no era autocontenido para el revisor. | F1 |
| B2 | **Naming inconsistente**: tres patrones para el mismo artefacto (`<id>.WORKLOG.md`, `TASK-0001-...WORKLOG.md`, `...-WORKLOG.md`). Bloqueante para un futuro Runner que parsee nombres. | F2 |
| B3 | **Convención de rama** inconsistente. | F3 |
| B4 | El schema de `FINAL_REPORT` exigía `status_at_report: EVIDENCE_READY` hardcodeado: **no admitía reportes de fallo**. | F5 |
| B5 | **Sin estado/transición de fallo ni regla de retracción**: el enum no tenía estado terminal de fallo; el ejecutor no tenía forma legítima de revertir un avance ilegítimo. | F6 |

A esto se suma la falta de soporte para **reviewer suplente** (`reviewer_delegate`) cuando el revisor por defecto no está disponible.

v2 es un **parche documental mínimo** que cierra B1–B5 y añade `reviewer_delegate`, dejando el canal **autocontenido y runner-ready** sin construir el Runner.

---

## 2. Principio rector reforzado: autoridad in-file / `main`

> **`main` es la única fuente autoritativa de estado. Las ramas son propuestas. El chat nunca es autoridad.**

- El estado canónico de una tarea es `TASK.md.status` **tal como existe en `main`**.
- Una rama puede *proponer* un cambio de estado, pero ese estado **no es real hasta que un humano (Jorge) lo mergea a `main`**.
- `READY` solo es válido cuando existe en `main` por **acción humana verificable** (merge/commit de Jorge). El control de acceso del repo (los agentes no mergean) es el enforcement, no el honor-system.
- **La autorización por chat NUNCA equivale a `READY`.** Si Jorge dice "adelante" en una conversación pero no hay `status: READY` commiteado en `main`, la tarea sigue en `DRAFT` y el ejecutor **no arranca**. Esto es exactamente lo que falló en `TASK-0001`.
- Los agentes **no pueden mover estados críticos** (`HUMAN_DECISION`, `HANDOFF_TO_MSO`, `CLOSED_REJECTED`, ni fijar `READY`).

---

## 3. Máquina de estados v2

### 3.1 Enum

```
DRAFT
READY
IN_PROGRESS
EVIDENCE_READY
IN_REVIEW
CHANGES_REQUESTED
DECISION_PROPOSED
HUMAN_DECISION
HANDOFF_TO_MSO
BLOCKED
ABORTED
CLOSED_REJECTED
```

**Cambios de naming respecto a v1 (justificados):**
- `UNDER_REVIEW` → **`IN_REVIEW`** (alineado al patrón `IN_PROGRESS`; un solo idioma de estados activos `IN_*`). Migración trivial: renombrar el valor en schema/README/RULES.
- **Nuevos:** `CHANGES_REQUESTED` (cierra el lazo revisor→ejecutor sin abusar de `proposed_decision`), `BLOCKED` (bloqueo recuperable), `ABORTED` (fallo terminal / retracción confirmada). Estos tres resuelven B5.

Estados **terminales**: `HANDOFF_TO_MSO`, `CLOSED_REJECTED`, `ABORTED`.
Estado **recuperable**: `BLOCKED` (vuelve al `last_legit_status` tras corregir, o escala a `ABORTED`).

### 3.2 Diagrama de transiciones

```
DRAFT ──(Jorge, in-file/main)──▶ READY
  │                                 │
  │                                 ▼
  │                          IN_PROGRESS ◀──────────────┐
  │                                 │                    │
  │                                 ▼                    │
  │                          EVIDENCE_READY              │
  │                                 │                    │
  │                                 ▼                    │
  │                            IN_REVIEW                 │
  │                            │        │                │
  │              CHANGES_REQUESTED   DECISION_PROPOSED    │
  │                    │                  │              │
  │                    └──(executor)──────┘              │
  │                       retoma ─────────────────────────┘
  │                                       │
  │                                       ▼
  │                                HUMAN_DECISION ──(Jorge)──┐
  │                                       │                  │
  │                                       ▼                  ▼
  │                                HANDOFF_TO_MSO     CLOSED_REJECTED
  │                                   (MSO)               (Jorge)
  │
  ├───────────── BLOCKED (cualquier agente, su propio tramo; recuperable)
  └───────────── ABORTED (iniciador/Jorge; fallo terminal / retracción)
```

- Desde **cualquier estado activo** (`READY`, `IN_PROGRESS`, `EVIDENCE_READY`, `IN_REVIEW`, `CHANGES_REQUESTED`) un agente puede proponer `BLOCKED` **para su propio tramo**.
- `BLOCKED` → vuelve a `last_legit_status` (tras corrección) **o** escala a `ABORTED` (decisión del iniciador/Jorge).
- `ABORTED` es terminal; lo fija el iniciador/Jorge (o MSO/Police por clasificación). Un agente **no** decide el aborto final; solo lo propone vía `blocked=true` + `next_action`.

### 3.3 Propiedad de transiciones

| Transición | La ejecuta | Nunca |
|---|---|---|
| `DRAFT → READY` | **Jorge / iniciador** (in-file en `main`) | cualquier agente |
| `READY → IN_PROGRESS` | **Executor** | revisor |
| `IN_PROGRESS → EVIDENCE_READY` | **Executor** | revisor |
| `EVIDENCE_READY → IN_REVIEW` | **Reviewer** (≠ executor) | executor |
| `IN_REVIEW → CHANGES_REQUESTED` | **Reviewer** | executor |
| `IN_REVIEW → DECISION_PROPOSED` | **Reviewer** (convergencia) | — |
| `CHANGES_REQUESTED → IN_PROGRESS` | **Executor** (retoma) | revisor |
| `DECISION_PROPOSED → HUMAN_DECISION` | **Solo Jorge** | cualquier agente |
| `DECISION_PROPOSED → CLOSED_REJECTED` | **Solo Jorge** | cualquier agente |
| `HUMAN_DECISION → HANDOFF_TO_MSO` | **Solo MSO** (tras aprobación de Jorge) | cualquier agente |
| `* → BLOCKED` | **Cualquier agente** (su propio tramo) | — (no decide final) |
| `BLOCKED → last_legit_status` | el agente del tramo, tras corregir | — |
| `* → ABORTED` | **Iniciador / Jorge** (o MSO/Police por clasificación) | agente (solo propone) |

**Invariante:** un rol no mueve una tarea a un estado cuya propiedad es de otro rol. Si detecta que *debería* avanzar a un estado ajeno, **se detiene** y deja `next_action`.

---

## 4. Reviewer independiente y `reviewer_delegate`

**No hay auto-review:** `reviewer` (o `reviewer_delegate` si existe) **nunca** puede ser el mismo agente que `assigned_agent`.

Nuevos campos opcionales en el front-matter de `TASK`:

```yaml
reviewer: codex
reviewer_delegate: opus
reviewer_delegate_reason: "codex no disponible esta jornada; opus revisa como suplente"
```

Reglas:
1. Si existe `reviewer_delegate`, **debe ser explícito in-file** (no por chat) y traer `reviewer_delegate_reason` no vacío.
2. `reviewer_delegate` también debe ser **distinto** de `assigned_agent` (no auto-review por la puerta de atrás).
3. Si el revisor no está disponible, la **reasignación debe quedar en el repo (en `main`) antes** de que comience el `REVIEW`. Un `REVIEW` emitido sin delegate registrado in-file es inválido.
4. El `REVIEW.md` declara qué identidad revisó (`agent`) y, si aplica, que actuó como `reviewer_delegate`.

---

## 5. Naming único (preferencia MSO)

Un solo patrón, **sin slug en el nombre de archivo**. El slug/título vive en el front-matter (`id`, `title`).

```
coordination/tasks/TASK-NNNN.md
coordination/worklogs/TASK-NNNN.WORKLOG.md
coordination/reports/TASK-NNNN.FINAL_REPORT.md
coordination/reviews/TASK-NNNN.REVIEW.md
coordination/decisions/TASK-NNNN.DECISION.md
```

- `NNNN` es el número correlativo cero-rellenado (`0001`, `0002`, …).
- El `id` en front-matter puede seguir llevando slug descriptivo (`TASK-0002-clean-dogfood-v2`), pero **el nombre de archivo es solo `TASK-NNNN.<TIPO>.md`**.
- Esto da a un futuro Runner un patrón único parseable (cierra B2/B3).

**Convención de rama (cierra B3):** `coordination/task-NNNN` para el trabajo de una tarea. (Antes había `agent/<task-id>` vs `coordination/task-...`; v2 fija `coordination/task-NNNN`.)

---

## 6. Fallo y retractación

Esto es el corazón de lo que `TASK-0001` expuso (B5).

### 6.1 Qué pasa si un agente avanza mal
Si un agente fija un `status` que no le corresponde o sin la precondición in-file (p. ej. avanzar a `EVIDENCE_READY` cuando la tarea seguía `DRAFT` en `main`):
- el avance es **inválido** desde el momento en que ocurre;
- el agente debe **retractarlo** él mismo en cuanto lo detecta (o cuando MSO/Police lo señala).

### 6.2 Cómo se bloquea sin borrar evidencia
- **Nunca se borra** el `WORKLOG` ni el `FINAL_REPORT`. El `WORKLOG` es append-only: la corrección es una **entrada nueva**, no una reescritura.
- Se fija `blocked=true` + `blocked_reason` (texto verificable).
- El `status` se devuelve al **último estado legítimo** (`last_legit_status`) o a `BLOCKED`. La evidencia del intento fallido queda preservada como registro.

### 6.3 Quién puede retractar
- **Un agente puede retractar su propio avance ilegítimo** devolviendo el `status` al `last_legit_status` y marcando `blocked=true`. Esto es corrección hacia la verdad, no usurpación.
- **El iniciador/Jorge** (o MSO/Police por clasificación) puede llevar la tarea a `ABORTED` (terminal).
- Un agente **no** decide `ABORTED` final; lo propone.

### 6.4 Cómo se registra el último estado legítimo
Nuevo campo en el front-matter de `TASK`:

```yaml
last_legit_status: DRAFT   # último status alcanzado por una transición válida del rol propietario
```

- Se actualiza **solo** cuando una transición legítima se completa.
- Si hay que retractar, `status` vuelve a `last_legit_status` y el `WORKLOG` narra el porqué.

### 6.5 Cómo se evita que correcciones por chat sustituyan al repo
- **Toda corrección debe quedar in-file y, para ser real, en `main`.** Una corrección que solo existe en el chat **no cuenta**.
- El repo es la única fuente de verdad; el chat es contexto out-of-band.
- Regla operativa: *"si no está commiteado, no pasó"*. Aplica tanto a `READY` como a cualquier retracción.

---

## 7. Migración de `TASK-0001` (sugerida, NO aplicada en este PR)

`TASK-0001` **no se reactiva** y **se preserva intacto** como evidencia de dogfood fallido útil (ya está commiteado en `main` con su naming v1). Este PR **no** muta esos archivos para no alterar la evidencia.

Migración **sugerida** (a aplicar más adelante mediante una retracción legítima del iniciador, fuera de este PR):

```
TASK-0001:
  archivos → renombrar a naming v2:
    coordination/tasks/TASK-0001.md
    coordination/worklogs/TASK-0001.WORKLOG.md
    coordination/reports/TASK-0001.FINAL_REPORT.md
  status            → ABORTED        (fallo terminal del dogfood)
  proposed_decision → NEEDS_CHANGES  (sin cambios)
  last_legit_status → DRAFT
  blocked           → true (motivo: chat-authorized READY, no in-file)
```

> ⚠️ **No** se declara `human_final`, **no** se crea `DECISION`, **no** lo decide un agente. La transición a `ABORTED` la confirma Jorge/iniciador cuando proceda.

---

## 8. `TASK-0002` — dogfood limpio bajo v2 (DRAFT)

Se crea `coordination/tasks/TASK-0002.md` en **`DRAFT`** (no `READY`) para repetir el dogfood limpio una vez v2 esté mergeado. Sigue el naming v2 y exige `READY` in-file antes de cualquier ejecución. Ver el archivo para criterios de aceptación.

---

## 9. Lo que v2 explícitamente NO hace

- No implementa Runner, headless, GitHub Actions, cron, servicios, bridge, Docker, túnel ni VPS.
- No toca `assistant_os/mso`, `assistant_os/police`, `assistant_os/policy`, `auth/`, `.env`, secrets ni `.github/workflows`.
- No declara `human_final`, `approved_by_jorge`, `mso_executable` ni crea `DECISION`.
- No reactiva `TASK-0001`.

v2 es contrato verificable, no autonomía. La autonomía posterior (tramo C / Runner) debe apoyarse en este contrato.
