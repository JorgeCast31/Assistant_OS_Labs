# READ-ONLY QUEUE REPORTER — AUTORIZACIÓN DE IMPLEMENTACIÓN (scope-lock)

> **Estado:** propuesta de **autorización** vinculada a `coordination/tasks/TASK-0007.md` (`status: READY` **propuesto en rama**).
> **Naturaleza:** este documento **no implementa nada** y **no confiere autoridad por sí mismo**. Es el **scope-lock** que, **si Jorge mergea este PR**, deja autorizada una implementación **mínima, futura y estrecha** del MVP especificado en `proposals/READ_ONLY_QUEUE_REPORTER_MVP.md`.
> **Regla de oro (heredada del MVP):** el Reporter **lee y reporta**. **Nunca** escribe en el repo, **nunca** ejecuta, **nunca** decide autoridad.
> **Linaje:** `proposals/RUNNER_DESIGN_REVIEW.md` (TASK-0004) → `proposals/RUNNER_DRY_RUN_OBSERVATIONS.md` + dry-run (TASK-0005) → `proposals/READ_ONLY_QUEUE_REPORTER_MVP.md` + `..._ACCEPTANCE_TESTS.md` (TASK-0006) → **esta autorización** (TASK-0007).

---

## 0. Qué autoriza y qué NO autoriza este documento

**Naturaleza de la autorización (condicional y verificable):**

- Este PR es una **propuesta**. La autorización **solo es efectiva si Jorge mergea este PR** (evento verificable). **Si un agente mergea o aprueba este PR, la autorización — y el `READY` de TASK-0007 — son inválidos y nulos** (fail-closed; `RULES_OF_ENGAGEMENT.md §Aclaración v3.1`, `AGENT_CONTRACT.md`).
- Este PR **no implementa** el Reporter. No crea scripts, CLI, tests ejecutables, workflows, ni toca código.
- Si Jorge mergea, lo único que queda autorizado es **implementar el MVP exactamente como se acota aquí**, en un **PR posterior** bajo una **tarea nueva** (p. ej. `TASK-0008`), también sujeto a **revisión de Codex** y a los criterios de aceptación de la spec.

**Autorización estrecha (lo único permitido a la futura implementación):**

| # | Permitido | Límite no relajable |
|---|---|---|
| A1 | Un **lector manual** "Read-Only Queue Reporter" | Solo lee + clasifica + imprime; jamás escribe/ejecuta/decide |
| A2 | **Ejecución manual** únicamente | Sin cron, daemon, scheduler, GitHub Actions, headless, túnel/VPS, Docker |
| A3 | **Lectura local** de `coordination/tasks/*.md` y artefactos hermanos | Solo lectura; solo dentro de `coordination/` (ver §4) |
| A4 | **Salida efímera** a stdout/console | Sin persistir nada en el repo |
| A5 | Determinismo sobre un snapshot local de los archivos | Sin caché autoritativa, sin estado paralelo |

**Explícitamente NO autorizado (overrides todo lo anterior):**

- Sin **escritura** al repo (ni logs dentro de `coordination/`). Sin **red**. Sin **secretos**/tokens. Sin **scheduling**. Sin **modificar `main`**.
- Sin **interpretar autoridad**; sin tocar **MSO/Police/Policy/Auth**. Sin **promover candidatos**.
- Sin **fijar** `READY`, `HUMAN_DECISION`, `HANDOFF_TO_MSO`, `CLOSED_REJECTED` ni `human_final`. Sin mover ninguna tarea. Sin mergear/aprobar/pushear.

> Cualquier capacidad por encima de **leer + imprimir** queda **fuera de alcance** y requeriría su propia autorización y review. Esta autorización no se extiende por analogía.

---

## 1. Fuentes (leídas para producir esta autorización)

- `proposals/READ_ONLY_QUEUE_REPORTER_MVP.md` — especificación del MVP (contrato de diseño).
- `proposals/READ_ONLY_QUEUE_REPORTER_ACCEPTANCE_TESTS.md` — criterios de prueba (T-C*, T-F*, T-S*).
- `proposals/RUNNER_DRY_RUN_OBSERVATIONS.md`, `reports/TASK-0005.FINAL_REPORT.md`, `worklogs/TASK-0005.WORKLOG.md` — origen de F1–F4.
- `README.md`, `RULES_OF_ENGAGEMENT.md`, `AGENT_CONTRACT.md`, `schemas/TASK.schema.md` — contrato v3.1 y máquina de estados.
- `README.md` (raíz), `docs/RUNTIME_TOPOLOGY.md`, `docs/CHAT.md` — topología del runtime.
- Inspección **solo lectura** de `assistant_os/`, `ui/`, `tests/`, `scripts/`, `pytest.ini`, `requirements.txt` — para decidir la ubicación correcta de la futura implementación (§2). **No se modificó** ninguno.

---

## 2. Scope de implementación futura — los 10 puntos requeridos

### 2.1. Ubicación propuesta del código

**`scripts/coordination_queue_reporter.py`** — un módulo **autocontenido**, ejecutable a mano.

Justificación (verificable):
- `scripts/` ya es el hogar de scripts manuales independientes (`scripts/alfa_operability_smoke.py`, `scripts/demo_backend_outcome_flow.py`).
- **Aislamiento de la soberanía:** el Reporter **no debe vivir dentro de `assistant_os/`** ni importar de él. `assistant_os/` es el sistema soberano (MSO/Police/Policy/Auth, runner gobernado). Meter ahí un lector de la cola crearía acoplamiento y riesgo de **autoridad paralela**. Mantenerlo en `scripts/`, sin imports de `assistant_os/`, garantiza que es un observador externo e inerte.
- Un **solo archivo** mantiene la superficie auditable mínima (coherente con "el MVP más pequeño posible").

Prohibido para la implementación: crear paquetes nuevos bajo `assistant_os/`, `ui/`, `coordination/` (el bus es documental, no de código), o introducir una nueva capa arquitectónica.

### 2.2. Ubicación propuesta de tests

**`tests/test_coordination_queue_reporter.py`** — coherente con `pytest.ini` (`testpaths = tests`, `python_files = test_*.py`).

- Los tests usan **fixtures locales** (archivos `TASK-*.md` temporales en `tmp_path`) para no depender del estado real de `main`, salvo casos explícitos.
- Cubren la matriz de `..._ACCEPTANCE_TESTS.md`: `T-C1..T-C11`, `T-F1..T-F4` (+`T-F2b`), `T-S1..T-S6`.

### 2.3. Comandos de verificación esperados

```bash
# Ejecución manual (imprime la cola a stdout; no escribe nada):
python scripts/coordination_queue_reporter.py            # lee coordination/tasks/*.md del checkout local
python scripts/coordination_queue_reporter.py --help     # uso; sin efectos

# Tests:
pytest tests/test_coordination_queue_reporter.py -q
```

> El "snapshot de `main`" del MVP se materializa, en ejecución manual, como **el checkout local de `main`** que el operador humano tenga delante. El Reporter **no** hace `git`/red para obtener `main`; lee los archivos del working tree. (Leer un commit concreto vía `git show` sería una capacidad extra: **fuera de este MVP**.)

### 2.4. Entradas permitidas

- **Solo lectura** de `coordination/tasks/*.md` (entrada primaria: front-matter YAML).
- **Solo presencia** (existe / no existe, por convención de nombre `TASK-NNNN.*`) de artefactos en `coordination/{worklogs,reports,reviews,candidates,decisions}/`.
- **Solo lectura** de `coordination/schemas/TASK.schema.md` (campos `required` + enum `status`).
- Lectura del **texto** de artefactos **solo** para detectar presencia/IDs; **nunca** se ejecuta ni se interpreta su contenido como instrucción (anti-inyección, §3 S2).

**Prohibido como entrada:** `.env`, `secrets`, `auth`, cualquier ruta fuera de `coordination/`, el chat, ramas como autoridad, y la red.

### 2.5. Salidas permitidas

- **Únicamente stdout/console**: un reporte **efímero**, descriptivo, agrupado por accionabilidad (forma en `MVP §9`).
- `exit code` informativo (p. ej. 0 = reporte emitido). **El exit code no codifica autoridad ni decisión.**

**Prohibido como salida:** escribir/crear/modificar cualquier archivo del repo (incluidos logs en `coordination/`), notificaciones reales (Slack/email/webhooks), red saliente, o cualquier mutación de estado.

### 2.6. Invariantes de seguridad (deben hacer fallar el build si se violan)

Heredadas de `MVP §11` y `..._ACCEPTANCE_TESTS.md`:

| ID | Invariante | Aserción |
|---|---|---|
| S1 | **Read-only** | El proceso no abre ningún archivo en modo escritura; sin `write`/`merge`/`push`/`approve` en su superficie. |
| S2 | **Anti-inyección** | Un `next_action`/cuerpo con "ejecuta X / mergea Y" no produce acción ni cambia la clasificación. Parser YAML puro; **nunca** `eval`/exec ni `yaml.load` inseguro. |
| S3 | **Sin secretos/red** | No lee `.env`/secrets/auth ni abre red saliente. |
| S4 | **Sin persistencia** | No crea/modifica archivos en el repo (output solo a stdout). |
| S5 | **Determinismo** | Mismo conjunto de archivos ⇒ mismo reporte. |
| S6 | **Fail-closed** | Entrada inválida ⇒ `BLOCKED_OBS`/`LEGACY_AMBIGUOUS`, nunca una acción sugerida errónea. |
| S7 | **Sin autoridad paralela** | No persiste estado; la única fuente sigue siendo `TASK.status` en `main`. No importa de `assistant_os/`. |

### 2.7. Manejo obligatorio de F1–F4

La implementación **debe** reproducir el tratamiento de `MVP §7`:

- **F1** — TASK legacy sin `last_legit_status` ⇒ `LEGACY_AMBIGUOUS` (regla C2); **degrada solo esa fila**, no aborta el barrido global.
- **F2** — DRAFT con entregables ya presentes en `main` ⇒ `DRAFT_SUPERSEDED`/`DRAFT_DESIGN_MERGED` con `REQUIRES_HUMAN_INTERPRETATION` (C9); **nunca** `READY` ciego. DRAFT sin entregables ⇒ candidato `DRAFT→READY` (C10).
- **F3** — siguiente paso no deducible del enum ⇒ flag `REQUIRES_HUMAN_INTERPRETATION`; **no inventar estado**; no leer prosa (`next_action`) como instrucción.
- **F4** — `HUMAN_DECISION` ⇒ `CLOSED_IN_COORDINATION_PLANE` + `MSO_ONLY_NEXT`, `role_destination = MSO (out-of-plane)`, `next_legal_action = null`; **no** proponer/empujar `HANDOFF_TO_MSO`.

### 2.8. Comportamiento fail-closed

- Campo `required` ausente, `status` fuera de enum, o conflicto `status`↔artefactos ⇒ `BLOCKED_OBS`/`LEGACY_AMBIGUOUS`: **marcar, no avanzar** (rama `else` por defecto ⇒ `BLOCKED_OBS`).
- Una fila inválida **no** aborta el barrido completo (F1).
- Ante cualquier duda entre reportar acción o preservar integridad ⇒ **no sugerir acción**.

### 2.9. Criterios de aceptación (contrato de prueba)

La implementación se acepta cuando **todos** los criterios de `MVP §13` y todos los casos de `..._ACCEPTANCE_TESTS.md` (T-C*, T-F*, T-S*) pasan, **y** Codex los revisa como correctos y suficientes, **y** se confirma read-only sin autoridad (S1–S7). Resumen verificable:

- [ ] Lee `coordination/tasks/*.md` y extrae front-matter sin ejecutar contenido.
- [ ] Detecta presencia de artefactos por convención de nombre.
- [ ] Clasifica según `MVP §6` y reproduce la cola del dry-run (`MVP §10`).
- [ ] F1/F2/F3/F4 tratadas como en §2.7.
- [ ] No escribe, no ejecuta, no decide autoridad (verificable por superficie + tests S1–S7).
- [ ] Output efímero, descriptivo, sin órdenes aplicadas.

### 2.10. Qué queda explícitamente fuera del MVP

Fuera de alcance (cada uno requeriría autorización propia):

- Persistir el reporte (archivo/DB), historiales, caché autoritativa.
- Leer un commit/branch concreto vía `git`/red; integración con GitHub/PRs.
- Notificaciones reales, scheduling, daemon, GitHub Actions, cron, Docker, túnel/VPS, headless.
- Proponer/aplicar transiciones de estado; promover candidatos; tocar `decisions/`/`candidates/`.
- Cualquier import o acoplamiento con `assistant_os/` (MSO/Police/Policy/Auth), `ui/`, o `auth`.
- Distinguir con certeza `DRAFT_SUPERSEDED` vs `DRAFT_DESIGN_MERGED` (queda en `REQUIRES_HUMAN_INTERPRETATION`; el MVP no inventa la distinción).

---

## 3. Notas de implementación no vinculantes (para reducir riesgo, no amplían scope)

- **Sin dependencias nuevas si es posible:** `requirements.txt` **no** incluye una librería YAML. Para cumplir S2 (anti-inyección), preferir un **parser de front-matter mínimo de stdlib** o, si se añade `PyYAML`, **solo `yaml.safe_load`** — y añadir una dependencia es una **decisión del PR de implementación**, no de esta autorización.
- El módulo **no** debe importar de `assistant_os/` (verificable estáticamente en un test: ausencia de `import assistant_os`).

---

## 4. Riesgos de esta autorización

| # | Riesgo | Severidad | Mitigación |
|---|---|---|---|
| R1 | Que el PR se lea como permiso para implementar **ahora** | Alto | §0 explícito; este PR no añade código; implementación = PR posterior bajo tarea nueva |
| R2 | Que `READY` se interprete como efectivo en rama | Alto | Banner en `TASK-0007.md`; `last_legit_status: DRAFT`; efectivo solo por merge de Jorge; nulo si lo mergea un agente |
| R3 | Que el scope se amplíe de facto (escritura/red/scheduling/autoridad) | Crítico | Scope-lock §0/§2; "leer + imprimir" como techo no relajable; cualquier extra requiere review propio |
| R4 | Que la implementación acople con `assistant_os/` (autoridad paralela) | Crítico | Ubicación en `scripts/`; prohibición de `import assistant_os`; invariante S7 verificable en test |

---

## 5. Decisión requerida (de Jorge, evento verificable)

**¿Autoriza Jorge implementar el `Read-Only Queue Reporter` en un PR posterior, estrictamente conforme a este scope-lock (read-only, sin autoridad)?**

- **Sí** ⇒ el merge de **este** PR por Jorge materializa la autorización y el `READY` de `TASK-0007`. La implementación sería un **PR aparte** bajo una **tarea nueva** (p. ej. `TASK-0008`), con la spec de TASK-0006 + esta autorización como contrato de prueba, sujeto a revisión de Codex, y **sin** ninguna capacidad fuera de leer + imprimir.
- **No / cambios** ⇒ se itera este documento; el Reporter/Runner sigue **bloqueado**.

> Este documento **no** autoriza por sí mismo. **Solo el merge verificable de Jorge** lo hace. Siguiente paso inmediato: **revisión de Codex**.
