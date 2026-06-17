# READ-ONLY QUEUE REPORTER — MVP (especificación)

> **Estado:** propuesta de **especificación** (diseño). **No implementa nada.** No es contrato vigente. No es autoridad.
> **Vinculado a:** `coordination/tasks/TASK-0006.md` (status `DRAFT`).
> **Linaje:** `proposals/RUNNER_DESIGN_REVIEW.md` (TASK-0004, §13 MVP) → `proposals/RUNNER_MANUAL_PROTOCOL_DRAFT.md` + dry-run `worklogs/TASK-0005.WORKLOG.md` / `reports/TASK-0005.FINAL_REPORT.md` + `proposals/RUNNER_DRY_RUN_OBSERVATIONS.md` (TASK-0005, F1–F4) → **este MVP**.
> **Regla de oro:** el Reporter **lee y reporta**. **Nunca** escribe en el repo, **nunca** ejecuta, **nunca** decide autoridad. Es un lector que ordena y marca la cola; el juicio queda en Jorge.

---

## 1. Resumen ejecutivo

El dry-run manual (TASK-0005) demostró que la lógica del Runner es **operable sin autoridad**: con solo el front-matter de cada `TASK.md` en `main` y la presencia de artefactos, se puede construir una cola de trabajo útil. El **Read-Only Queue Reporter** es el MVP **más pequeño posible** que mecaniza **exactamente** ese paso de lectura — y nada más.

En una implementación futura (no autorizada aquí), el Reporter:

1. lee `coordination/tasks/*.md` desde `main` (solo lectura);
2. extrae front-matter (YAML);
3. detecta artefactos presentes (worklog/report/review/candidate/decision);
4. **clasifica** cada tarea (tabla §6), incorporando F1–F4;
5. imprime/reporta una **cola** ordenada por accionabilidad;
6. **marca** ambigüedades en vez de resolverlas;
7. **no escribe** en el repo, **no ejecuta**, **no decide** autoridad.

Defensa real: **control de acceso** (identidad solo-lectura, sin merge/approve/push). No honor-system. Este documento es **spec/review**; el siguiente paso es revisión de Codex y decisión humana de Jorge sobre si autorizar una implementación.

---

## 2. Alcance

- Especificar entradas, modelo de datos, clasificación, manejo F1–F4, algoritmo (pseudocódigo), output, ejemplos (TASK-0001..0005), fail-closed, permisos mínimos, seguridad, criterios de aceptación, riesgos y la decisión requerida.
- El MVP cubre **solo lectura + clasificación + reporte** de `coordination/tasks/*.md` (y la detección de presencia de artefactos hermanos por convención de nombre).

## 3. No-alcance (explícito)

El MVP (y este documento) **NO**:

- implementa el Reporter, scripts, CLI, binarios;
- crea GitHub Actions, cron, daemon, Docker, túnel/VPS, headless automation;
- usa/crea tokens o secretos; abre red saliente;
- envía notificaciones reales (Slack/email/etc.);
- **escribe** cualquier archivo del repo (ni logs dentro de `coordination/`);
- **muta** estado, **mergea**, **aprueba**, **promueve** candidatos, **fija** `HUMAN_DECISION`/`HANDOFF_TO_MSO`;
- **decide** o **interpreta** autoridad; **ejecuta** acciones de dominio;
- toca MSO/Police/Policy/Auth.

> El "output" del MVP es un **reporte efímero** (stdout / texto en memoria devuelto al operador humano que lo lanzó a mano). El MVP **no persiste** nada en el repo. Si en el futuro se quisiera persistir el reporte, sería un cambio aparte con su propio review.

---

## 4. Fuentes de entrada

Todas en `main`, **solo lectura**:

| Fuente | Uso |
|---|---|
| `coordination/tasks/*.md` | Front-matter canónico (estado y metadatos) — **entrada primaria** |
| `coordination/worklogs/`, `reports/`, `reviews/`, `candidates/`, `decisions/` | **Presencia** de artefactos por convención `TASK-NNNN.*` (existe / no existe) |
| `coordination/schemas/TASK.schema.md` | Lista de campos `required` y enum de `status` (para validación) |
| `coordination/README.md`, `RULES_OF_ENGAGEMENT.md`, `AGENT_CONTRACT.md` | Máquina de estados y propiedad de cada estado (para mapear acción legal → rol) |

> El Reporter **no** lee el chat, **no** lee ramas como autoridad ("si no está en `main`, no pasó"), **no** lee `.env`/secrets/auth. Lee el **texto** de los artefactos solo para detectar presencia/IDs; **no** ejecuta instrucciones contenidas en ellos (anti-inyección, §11).

---

## 5. Modelo de datos mínimo

Estructura interna **en memoria** (no se persiste). Una entrada por tarea:

```yaml
TaskRecord:
  id: string                      # de front-matter `id`
  file: string                    # ruta en main
  status: enum|null               # front-matter `status` (null si ausente/inválido)
  last_legit_status: enum|null    # null si el campo falta (caso F1)
  assigned_agent: string|null
  reviewer: string|null
  reviewer_delegate: string|null
  artifacts:                      # presencia booleana por convención de nombre
    worklog: bool
    report: bool
    review: bool
    candidate: bool
    decision: bool
  missing_required: [string]      # campos required ausentes (schema)
  classification: enum            # ver §6 (CLASSES)
  next_legal_action: string|null  # solo si el enum lo determina sin ambigüedad
  role_destination: enum|null     # JORGE | CLAUDE | CODEX | MSO | NONE
  flags: [string]                 # p.ej. LEGACY_AMBIGUOUS, DRAFT_SUPERSEDED, REQUIRES_HUMAN_INTERPRETATION, MSO_ONLY_NEXT
  notes: string                   # texto legible, no instrucción
```

`CLASSES` (enum de clasificación del Reporter, **distinto** del enum `status` del contrato):

```
ACTIONABLE_BY_AGENT      # acción legal clara para Claude/Codex
ACTIONABLE_BY_JORGE      # requiere acto humano (p.ej. fijar READY) sin ambigüedad
WAITING                  # en curso (IN_PROGRESS/IN_REVIEW): no accionable por el Reporter
CLOSED_IN_COORDINATION_PLANE   # HUMAN_DECISION (F4): MSO_ONLY_NEXT, no-op
TERMINAL                 # HANDOFF_TO_MSO / CLOSED_REJECTED / ABORTED
LEGACY_AMBIGUOUS         # F1: tarea legacy/preservada, no fallar global
DRAFT_SUPERSEDED         # F2: DRAFT cuyo entregable ya está en main
DRAFT_DESIGN_MERGED      # F2: DRAFT de diseño ya mergeado; próximo ≠ READY
REQUIRES_HUMAN_INTERPRETATION  # F3: el siguiente paso depende de prosa
BLOCKED_OBS              # ambigüedad/campo faltante/conflicto: marcar, no avanzar
```

---

## 6. Tabla de clasificación

Orden de evaluación (primera regla que matchea gana; fail-closed por defecto):

| # | Condición (sobre `main`) | `classification` | `role_destination` | `next_legal_action` |
|---|---|---|---|---|
| C1 | `status` ausente o fuera de enum | `BLOCKED_OBS` | JORGE | — (marcar) |
| C2 | Tarea **legacy** (naming v1) **o** `blocked=true` con `status=DRAFT` **o** falta `last_legit_status` | `LEGACY_AMBIGUOUS` | NONE (observar) | — (marcar, no fallar) |
| C3 | `status ∈ {HANDOFF_TO_MSO, CLOSED_REJECTED, ABORTED}` | `TERMINAL` | NONE | — |
| C4 | `status == HUMAN_DECISION` | `CLOSED_IN_COORDINATION_PLANE` | MSO (out-of-plane) | flag `MSO_ONLY_NEXT` |
| C5 | `status ∈ {IN_PROGRESS, IN_REVIEW}` | `WAITING` | NONE | — (esperar) |
| C6 | `status == EVIDENCE_READY` y `report`+`worklog` presentes y `reviewer ≠ assigned_agent` | `ACTIONABLE_BY_AGENT` | CODEX | `EVIDENCE_READY → IN_REVIEW` |
| C7 | `status == CHANGES_REQUESTED` | `ACTIONABLE_BY_AGENT` | CLAUDE | `CHANGES_REQUESTED → IN_PROGRESS` |
| C8 | `status == READY` | `ACTIONABLE_BY_AGENT` | CLAUDE | `READY → IN_PROGRESS` |
| C9 | `status == DRAFT` **y** entregables declarados en `evidence`/`files_touched` ya **presentes** en `main` | `DRAFT_SUPERSEDED` **o** `DRAFT_DESIGN_MERGED` | JORGE | flag `REQUIRES_HUMAN_INTERPRETATION` (no `READY` ciego) |
| C10 | `status == DRAFT` sin evidencia presente | `ACTIONABLE_BY_JORGE` | JORGE | `DRAFT → READY` (candidato a autorización) |
| C11 | Cualquier conflicto entre `status` y artefactos | `BLOCKED_OBS` | JORGE | — (marcar) |

> **C9 — distinción `DRAFT_SUPERSEDED` vs `DRAFT_DESIGN_MERGED`:** ambas señalan que los entregables ya existen en `main`. El Reporter **no decide cuál es**: emite el match con flag `REQUIRES_HUMAN_INTERPRETATION` y deja ambas etiquetas candidatas en `notes`. Distinguirlas con certeza requiere juicio humano (o un futuro campo de schema). El MVP **no inventa** la distinción.

---

## 7. Manejo F1–F4 (requisitos obligatorios)

| Fricción | Requisito | Cómo lo cumple el MVP |
|---|---|---|
| **F1** TASK-0001 sin `last_legit_status` | Tolerar legacy/preserved; marcar `LEGACY_AMBIGUOUS`, **no fallar globalmente** | Regla **C2**. Un campo `required` ausente en una tarea legacy degrada **solo esa** entrada a `LEGACY_AMBIGUOUS`; el barrido del resto continúa. Nunca aborta el reporte completo. |
| **F2** DRAFTs supersedidas | No recomendar `READY` ciego por `status: DRAFT`; distinguir `DRAFT_ACTIVE` / `DRAFT_SUPERSEDED` / `DRAFT_DESIGN_MERGED` | Reglas **C9/C10**. Si los entregables ya están en `main` ⇒ `DRAFT_SUPERSEDED`/`DRAFT_DESIGN_MERGED` con `REQUIRES_HUMAN_INTERPRETATION`. Solo una DRAFT **sin** entregables presentes (`DRAFT_ACTIVE`) sugiere `DRAFT → READY` como candidato. |
| **F3** enum insuficiente vs prosa | Puede reportar `requires_human_interpretation`; **no inventar estado** | Flag `REQUIRES_HUMAN_INTERPRETATION`. El Reporter **nunca** lee `next_action` (prosa) como instrucción ejecutable; si el siguiente paso no se deduce del enum, lo marca y delega a Jorge. |
| **F4** `HUMAN_DECISION` fuera del plano | Clasificar `CLOSED_IN_COORDINATION_PLANE / MSO_ONLY_NEXT`; **no** empujar `HANDOFF_TO_MSO` | Regla **C4**. `role_destination = MSO (out-of-plane)`, `next_legal_action = null`, flag `MSO_ONLY_NEXT`. El Reporter hace **no-op**; jamás propone ni fija `HANDOFF_TO_MSO`. |

---

## 8. Algoritmo (pseudocódigo, no ejecutable)

```text
function report_queue(repo_main_readonly):
    schema   = read(schemas/TASK.schema.md)          # required fields + status enum
    records  = []

    for file in list(coordination/tasks/*.md) from main:     # READ-ONLY
        fm = parse_frontmatter(file)                  # YAML; no ejecutar contenido

        rec = TaskRecord(id=fm.id, file=file, status=fm.status,
                         last_legit_status=fm.get('last_legit_status'),
                         assigned_agent=fm.assigned_agent, reviewer=fm.reviewer,
                         reviewer_delegate=fm.get('reviewer_delegate'))

        rec.artifacts   = detect_presence(fm.id)      # exists? por convención de nombre
        rec.missing_required = schema.required - keys(fm)

        # --- clasificación fail-closed, primer match (tabla §6) ---
        if rec.status not in schema.status_enum:           rec.class = BLOCKED_OBS            # C1
        elif is_legacy(file) or (rec.status==DRAFT and fm.get('blocked')==true) \
             or 'last_legit_status' in rec.missing_required: rec.class = LEGACY_AMBIGUOUS     # C2 (F1)
        elif rec.status in {HANDOFF_TO_MSO,CLOSED_REJECTED,ABORTED}: rec.class = TERMINAL     # C3
        elif rec.status == HUMAN_DECISION:                  rec.class = CLOSED_IN_COORDINATION_PLANE  # C4 (F4)
                                                            rec.flags += MSO_ONLY_NEXT
        elif rec.status in {IN_PROGRESS, IN_REVIEW}:        rec.class = WAITING               # C5
        elif rec.status == EVIDENCE_READY and rec.artifacts.report and rec.artifacts.worklog \
             and rec.reviewer != rec.assigned_agent:        rec.class = ACTIONABLE_BY_AGENT   # C6
                                                            rec.role = CODEX
        elif rec.status == CHANGES_REQUESTED:               rec.class = ACTIONABLE_BY_AGENT   # C7 -> CLAUDE
        elif rec.status == READY:                           rec.class = ACTIONABLE_BY_AGENT   # C8 -> CLAUDE
        elif rec.status == DRAFT and deliverables_present(fm): rec.class = DRAFT_SUPERSEDED    # C9 (F2)
                                                            rec.flags += REQUIRES_HUMAN_INTERPRETATION
        elif rec.status == DRAFT:                           rec.class = ACTIONABLE_BY_JORGE   # C10 -> DRAFT->READY (candidato)
        else:                                               rec.class = BLOCKED_OBS           # C11 fail-closed

        records.append(rec)

    return render(sort_by_actionability(records))      # solo stdout; NO escribe repo

# Helpers (todos read-only, sin efectos):
#   detect_presence(id)      -> existencia de TASK-id.* en worklogs/reports/reviews/candidates/decisions
#   deliverables_present(fm) -> ¿todos los paths de fm.evidence/files_touched (no-tasks) existen ya en main?
#   is_legacy(file)          -> naming v1 (slug en nombre de archivo) u marcador legacy explícito
#   parse_frontmatter        -> parser YAML puro; nunca evalúa/ejecuta valores
```

**Propiedades garantizadas:** sin `write`, sin `exec`, sin red, sin merge/approve. Determinista sobre un snapshot de `main`. Fail-closed por defecto (rama `else` ⇒ `BLOCKED_OBS`).

---

## 9. Formato de output esperado

Reporte **efímero** (stdout), legible, agrupado por accionabilidad. Ejemplo de forma:

```text
READ-ONLY QUEUE REPORTER — snapshot main @ <commit>
(read-only; no muta nada; clasificación, no autoridad)

ACTIONABLE
  (ninguna)                                  # depende del snapshot

NEEDS HUMAN (Jorge)
  TASK-0003  DRAFT   DRAFT_SUPERSEDED            [REQUIRES_HUMAN_INTERPRETATION]
  TASK-0004  DRAFT   DRAFT_DESIGN_MERGED         [REQUIRES_HUMAN_INTERPRETATION]
  TASK-0006  DRAFT   ACTIONABLE_BY_JORGE         next: DRAFT->READY (candidato)

CLOSED / NO-OP
  TASK-0002  HUMAN_DECISION  CLOSED_IN_COORDINATION_PLANE  [MSO_ONLY_NEXT]

OBSERVATIONS
  TASK-0001  DRAFT   LEGACY_AMBIGUOUS   missing: last_legit_status (legacy v1, preserved)

summary: 5 tasks | 0 actionable-by-agent | 3 needs-human | 1 closed | 1 legacy
```

> El output es **descriptivo**. No contiene órdenes; las filas "NEEDS HUMAN" son sugerencias de atención para Jorge, no transiciones aplicadas.

---

## 10. Ejemplos con TASK-0001..0005 (snapshot conceptual de `main` tras #253)

| Task | status (main) | artefactos | clasificación MVP | role | flags |
|---|---|---|---|---|---|
| TASK-0001 | DRAFT (legacy v1, `blocked=true`, sin `last_legit_status`) | worklog, report | `LEGACY_AMBIGUOUS` | NONE | `missing:last_legit_status` |
| TASK-0002 | HUMAN_DECISION | worklog, report, review, candidate, decision | `CLOSED_IN_COORDINATION_PLANE` | MSO (out-of-plane) | `MSO_ONLY_NEXT` |
| TASK-0003 | DRAFT | proposals presentes en main | `DRAFT_SUPERSEDED` | JORGE | `REQUIRES_HUMAN_INTERPRETATION` |
| TASK-0004 | DRAFT | proposals presentes en main | `DRAFT_DESIGN_MERGED` | JORGE | `REQUIRES_HUMAN_INTERPRETATION` |
| TASK-0005 | DRAFT | worklog, report, observations presentes en main | `DRAFT_SUPERSEDED`/`DRAFT_DESIGN_MERGED` | JORGE | `REQUIRES_HUMAN_INTERPRETATION` |

> Coincide con la cola del dry-run manual (TASK-0005), confirmando que el MVP **mecaniza** lo ya validado a mano y resuelve F1–F4 por construcción. (TASK-0006 vive en rama hasta su merge; un Reporter sobre `main` no la vería todavía.)

---

## 11. Reglas fail-closed y seguridad

**Fail-closed:**
1. Campo `required` ausente, `status` fuera de enum, o conflicto ⇒ `BLOCKED_OBS`/`LEGACY_AMBIGUOUS`: **marcar, no avanzar**.
2. Si no se puede deducir el siguiente paso del enum ⇒ `REQUIRES_HUMAN_INTERPRETATION`; **no inventar estado**.
3. Una entrada inválida **no** aborta el barrido completo (F1): se degrada solo esa fila.
4. Ante cualquier duda entre reportar acción o preservar integridad ⇒ no sugerir acción.

**Seguridad:**
| # | Riesgo | Mitigación de diseño |
|---|---|---|
| S1 | Escalada a escritura/autoridad | Identidad **solo lectura**; sin write/merge/approve/push; enforcement por acceso |
| S2 | Inyección vía contenido de artefactos | Parser YAML puro; **nunca** evalúa/ejecuta valores ni `next_action` como instrucción |
| S3 | Filtración de secretos | No lee `.env`/secrets/auth; sin red saliente; output efímero sin credenciales |
| S4 | Estado obsoleto/caché | Lee siempre el `main` vigente; reporte ligado a un commit; sin caché autoritativa |
| S5 | Output tratado como orden | Reporte descriptivo; sin verbos imperativos aplicados; decide Jorge |
| S6 | Autoridad paralela | El MVP no persiste estado; única fuente sigue siendo `TASK.status` en `main` |

---

## 12. Permisos mínimos (de una implementación futura — no se solicitan aquí)

| Permiso | Por qué | NO incluye |
|---|---|---|
| Lectura de `coordination/` en `main` | Leer front-matter y presencia de artefactos | Sin lectura de `.env`/secrets/auth |
| Salida a stdout (efímera) | Imprimir la cola al operador humano que lo lanza | Sin escritura en repo, sin notificaciones reales, sin red |

**Explícitamente NO necesita:** write a repo, merge/approve/push, tokens, secretos, red saliente, cron, contenedores, workflows. Cualquier capacidad por encima de **leer + imprimir** es fuera de alcance y requiere su propio review.

---

## 13. Criterios de aceptación del MVP (para una implementación futura)

- [ ] Lee `coordination/tasks/*.md` de `main` y extrae front-matter sin ejecutar contenido.
- [ ] Detecta presencia de artefactos por convención de nombre.
- [ ] Clasifica cada tarea según §6 y reproduce la cola del dry-run (§10).
- [ ] **F1:** tarea legacy sin `last_legit_status` ⇒ `LEGACY_AMBIGUOUS`, sin fallo global.
- [ ] **F2:** DRAFT con entregables presentes ⇒ `DRAFT_SUPERSEDED`/`DRAFT_DESIGN_MERGED`, nunca `READY` ciego.
- [ ] **F3:** siguiente paso no deducible del enum ⇒ `REQUIRES_HUMAN_INTERPRETATION`.
- [ ] **F4:** `HUMAN_DECISION` ⇒ `CLOSED_IN_COORDINATION_PLANE / MSO_ONLY_NEXT`, sin empujar `HANDOFF_TO_MSO`.
- [ ] **No escribe** en el repo, **no ejecuta**, **no decide** autoridad (verificable: identidad read-only).
- [ ] Fail-closed por defecto; entrada inválida no aborta el barrido.
- [ ] Output efímero, descriptivo, sin órdenes aplicadas.

> Criterios detallados de prueba (sin código): `proposals/READ_ONLY_QUEUE_REPORTER_ACCEPTANCE_TESTS.md`.

---

## 14. Riesgos

| # | Riesgo | Severidad | Mitigación |
|---|---|---|---|
| R1 | Que la spec se lea como autorización de implementar | Alto | No-alcance explícito; TASK-0006 en `DRAFT`; decisión §15 reservada a Jorge |
| R2 | Que el MVP, implementado, adquiera escritura/autoridad | Crítico | Read-only por diseño + enforcement de acceso; §11 S1/S6 |
| R3 | Que `DRAFT_SUPERSEDED` se trate como decisión del MVP | Medio | El MVP **marca** (`REQUIRES_HUMAN_INTERPRETATION`); no cierra/aborta; decide Jorge |
| R4 | Falsos positivos en `deliverables_present` (F2) | Medio | Solo compara presencia de paths declarados; ante duda ⇒ flag, no acción |
| R5 | Drift de contrato/schema | Medio | Lee `schemas/`+contrato de `main` como fuente de enum/required |

---

## 15. Decisión requerida para pasar a implementación futura

**Decisión de Jorge (evento verificable), en un ciclo separado:** ¿se autoriza implementar el Read-Only Queue Reporter conforme a esta spec (read-only, sin autoridad), o se requieren cambios previos?

- Si **sí**: la implementación sería un **PR aparte** (`TASK-0007`?), también sujeto a review de Codex, con los criterios de aceptación §13 como contrato de prueba, y **sin** ninguna capacidad fuera de leer+imprimir.
- Si **no / cambios**: se itera esta spec.

> Este documento **no** autoriza nada. El Runner/Reporter sigue **bloqueado** hasta que Jorge decida por evento verificable. Siguiente paso inmediato: **revisión de Codex** de esta spec → decisión humana de Jorge.
