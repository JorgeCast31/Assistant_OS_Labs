# HUMAN APPROVAL MODEL v3 — Propuesta documental

> **Tipo:** propuesta documental (no ejecuta nada, no implementa Runner, no cambia schemas vigentes).
> **Estado:** propuesta (`authority=proposed`). La autoridad final es de Jorge vía aprobación/merge del PR.
> **Alcance:** solo `coordination/`. No toca MSO/Police/Policy/Auth ni `.github/workflows`.
> **Origen:** corrige la limitación que `TASK-0002` expuso en v2 — la autoridad humana quedó atada a la **autoría material** del markdown final.
> **Relación con v2:** v2 sigue **vigente y autoritativo**. v3 no entra en vigor hasta que Jorge lo apruebe por acto humano verificable.

---

## 1. Problema

v2 hizo bien lo esencial: **protegió la autoridad humana**. Ningún agente puede fijar `READY`, escribir `decisions/TASK-NNNN.DECISION.md`, ni emitir `authority: human_final`. El enforcement real es el **control de acceso del repo** (los agentes no mergean ni aprueban PRs), no el honor-system.

Pero v2 protegió esa autoridad **confundiéndola con la autoría material del archivo**:

- La única forma de tener una `DECISION.md` válida es que **Jorge la escriba** (`decided_by: jorge`, `author: jorge`).
- Cuando un agente intentó **preparar** la decisión de `TASK-0002`, el contrato **bloqueó correctamente** la escritura. El resultado fue `proposals/TASK-0002.HUMAN_DECISION_DRAFT.md`: un draft explícitamente no autoritativo.
- Para cerrar `TASK-0002`, Jorge tiene que **teclear** físicamente el markdown final.

Esto reintroduce a Jorge como **cable operativo**: el sistema no puede preparar el acto humano, solo esperar a que Jorge lo redacte desde cero. Es exactamente la dependencia que el bus `coordination/` quería evitar (ver el origen de `TASK-0001`: "no human cable"). El bloqueo de v2 fue correcto, pero reveló que **falta un modelo `agent-generated, human-approved`**.

---

## 2. Principio

```text
Human authority is accountable approval, not physical authorship.
```

En español:

```text
La autoridad humana no está en teclear el markdown.
La autoridad humana está en aprobar responsablemente el contenido.
```

Corolario operativo:

```text
Authorship != Authority
```

- **Authorship** (`generated_by`): quién **redactó** el contenido. Puede ser un agente (Claude, Codex).
- **Authority** (`approved_by` + `approval_method`): quién **se hace responsable** del contenido mediante un acto verificable. Solo Jorge.

Un agente puede redactar un candidato completo y bien fundado. Eso **no** lo vuelve autoridad. La autoridad nace cuando Jorge **aprueba responsablemente** ese contenido por un medio verificable e imposible de falsificar por un agente.

---

## 3. Modelo propuesto

v3 introduce un artefacto intermedio: el **candidato de decisión**. Es redactado por un agente y vive en `proposals/` (o en `candidates/` si Jorge prefiere una carpeta dedicada — ver §9). **No** vive en `decisions/`, que sigue reservada al acto humano.

### 3.1 Estado del artefacto antes de la aprobación

```yaml
artifact_kind: DECISION_CANDIDATE
generated_by: claude            # autoría material (agente)
prepared_for: jorge             # destinatario de la aprobación
artifact_status: CANDIDATE
intended_authority: human_final # lo que SERÍA si Jorge aprueba
effective_authority: none       # lo que ES ahora: ninguna autoridad
requires_human_approval: true
```

Lectura: *"Un agente preparó este contenido pensado para que Jorge decida. Hoy no tiene ninguna autoridad efectiva. Solo será `human_final` si Jorge lo aprueba por un acto verificable."*

### 3.2 Estado del artefacto después de la aprobación humana verificable

```yaml
artifact_kind: DECISION
generated_by: claude            # la autoría NO cambia: el agente lo redactó
approved_by: jorge              # autoridad: solo Jorge
approval_method: github_merge   # acto verificable (ver §4)
approved_at: <timestamp>        # lo sella el evento humano, no el agente
effective_authority: human_final
```

Puntos clave del modelo:

1. **`generated_by` y `approved_by` son campos distintos.** Un candidato tiene `generated_by` pero **no** `approved_by`. El segundo solo aparece tras el acto humano.
2. **`effective_authority` es el campo que manda.** `none` mientras es candidato; `human_final` solo tras aprobación. Ningún agente puede ponerlo en `human_final` y que **surta efecto**, porque el efecto depende del acto de §4, que el agente no puede ejecutar.
3. **El agente no auto-promueve.** Un agente nunca escribe `approved_by: jorge`, `approval_method`, `approved_at` ni `effective_authority: human_final`. Si lo escribiera, el artefacto es **inválido/nulo** (§5).
4. **`decisions/` sigue siendo terreno humano.** El candidato vive fuera de `decisions/`. La `DECISION` efectiva existe cuando Jorge la materializa (§4 / §8).

---

## 4. Regla de activación

Un documento candidato **no es autoridad final** hasta que exista un **evento verificable de Jorge**. Eventos válidos (al menos uno):

- **Merge por Jorge** del PR que contiene/promueve el candidato.
- **GitHub review approval por Jorge + merge** del PR.
- **Commit firmado por Jorge** del artefacto en `decisions/`.
- **Aprobación futura vía UI de Assistant OS** (cuando exista un mecanismo de aprobación humana auditable e identificado).
- **Otro mecanismo definido explícitamente** y registrado en el contrato, siempre que sea (a) atribuible a Jorge de forma no falsificable y (b) verificable después del hecho.

Propiedad común a todos: el evento es **un acto de control de acceso** que un agente **no puede producir**. Eso es lo que hace que el modelo no sea honor-system. La autoridad la da el evento, no el texto del frontmatter.

> **Nota:** `approval_method` documenta **cuál** de estos eventos materializó la autoridad. Debe corresponder a un evento real verificable (p. ej. el merge commit de Jorge), no a una afirmación de un agente.

---

## 5. Regla anti-fraude

Si un agente **mergea, aprueba, o marca `approved_by: jorge`** (o `effective_authority: human_final`, `approval_method`, `approved_at`) **sin un acto verificable de Jorge**, el artefacto es **inválido y nulo**.

- La defensa primaria sigue siendo **control de acceso** (D2 de v2): los agentes no tienen permiso de merge, aprobación de PR, ni push directo a `main`. Por tanto no pueden producir el **evento** de §4 aunque escriban el texto.
- La defensa secundaria es **verificabilidad**: `approval_method` debe poder cotejarse contra el historial real (quién mergeó, quién firmó). Un `approved_by: jorge` sin evento correspondiente en el historial es fraude detectable y anula el artefacto.
- **Fail-closed:** ante cualquier discrepancia entre lo que dice el frontmatter y el evento real, el artefacto se trata como **candidato sin aprobar** (o nulo), nunca como `human_final`.
- Esto **no relaja** ninguna cláusula de v2: ningún agente confiere autoridad; ningún agente se auto-aprueba.

---

## 6. Codex review

Codex (revisor, ≠ generador del candidato) verifica sobre un `DECISION_CANDIDATE`:

1. **Archivos cambiados** — el candidato solo toca rutas permitidas (`proposals/`/`candidates/`), nunca `decisions/`, MSO/Police/Policy/Auth, secrets ni workflows.
2. **`generated_by`** — declara correctamente al agente que lo redactó; coincide con la autoría real del diff.
3. **No auto-aprobación** — el candidato **no** contiene `approved_by: jorge`, `approval_method`, `approved_at`, ni `effective_authority: human_final`. `effective_authority` debe ser `none`.
4. **No Runner** — no introduce ejecución, automatización, cron, workflows ni headless.
5. **No escalamiento de permisos** — no toca autoridad, tokens, ni amplía `scope`/`permissions` más allá de lo declarado en la TASK.
6. **Evento de aprobación requerido** — el candidato declara explícitamente que requiere acto humano verificable (`requires_human_approval: true`) y cuál sería el `approval_method` esperado.
7. **Compatibilidad con `main`** — el candidato es coherente con el estado autoritativo en `main` y no duplica ni contradice estado canónico.

Codex emite su veredicto como `proposed_decision ∈ {GO, NO-GO, NEEDS_CHANGES}` con `authority: proposed`. **Codex tampoco aprueba**: solo verifica que el candidato está bien formado y es seguro para que Jorge decida.

---

## 7. Runner futuro

Un Runner futuro (fuera de alcance de esta propuesta) podría **detectar** candidatos y **notificar**, pero **nunca** convertirlos a `human_final`:

```text
escanear coordination/ → encontrar artifact_kind: DECISION_CANDIDATE con effective_authority: none
                        → notificar a Jorge / esperar aprobación
                        → (FIN del rol del Runner)
```

Límite duro:

- El Runner **no** mergea, **no** aprueba PRs, **no** escribe `approved_by`/`effective_authority: human_final`.
- El Runner **no** puede producir el evento de §4. Su rol máximo es *notify & wait*.
- Cualquier diseño de Runner que pretenda promover candidatos a `human_final` viola este modelo y v2; se bloquea y se reporta.

---

## 8. Aplicación a TASK-0002

Bajo v3, el cierre de `TASK-0002` se vería así (ilustrativo; **este PR no lo ejecuta**):

1. **Claude prepara** un candidato `DECISION_CANDIDATE` para `TASK-0002` (`generated_by: claude`, `effective_authority: none`, `requires_human_approval: true`), reusando el contenido ya redactado en `proposals/TASK-0002.HUMAN_DECISION_DRAFT.md`.
2. **Codex revisa** el candidato según §6 (archivos, no auto-aprobación, compatibilidad con `main`).
3. **Jorge lo lee en GitHub** y, si está de acuerdo, **lo aprueba/mergea**. Ese merge es el evento verificable de §4.
4. El merge **materializa** la decisión: el artefacto pasa a `artifact_kind: DECISION`, `approved_by: jorge`, `approval_method: github_merge`, `effective_authority: human_final`, y `TASK-0002` puede pasar a `HUMAN_DECISION`.

Jorge **no escribe el markdown**, pero **aprueba responsablemente** su contenido. Authorship (Claude) ≠ Authority (Jorge). La autonomía sube; la autoridad humana se preserva intacta.

> **Importante:** lo anterior es una **descripción del flujo v3**, no una acción. Este PR **no** crea la `DECISION` de TASK-0002, **no** mueve TASK-0002 a `HUMAN_DECISION`, y **no** toca sus artefactos.

---

## 9. Invariantes preservadas (no negociable)

v3 es un **superconjunto disciplinado** de v2; no relaja nada:

| Invariante v2 | ¿Se mantiene en v3? |
|---|---|
| `main` es la única fuente autoritativa; el chat nunca es autoridad | Sí |
| Ningún agente fija `READY` | Sí |
| Ningún agente escribe `authority: human_final` con efecto | Sí — `effective_authority: human_final` solo tras evento de §4 |
| Ningún agente se auto-aprueba | Sí — `generated_by ≠ approved_by`, y `approved_by` solo lo realiza el evento humano |
| Enforcement por control de acceso, no honor-system | Sí — el agente no puede producir el evento de §4 |
| Ejecutor ≠ revisor (no auto-review) | Sí — el generador del candidato ≠ revisor |
| MSO es la única autoridad de ejecución | Sí — la aprobación no ejecuta; solo autoriza el flujo soberano |
| Fail-closed ante ambigüedad | Sí — discrepancia frontmatter/evento ⇒ tratado como no aprobado |

### Nota sobre carpetas y schemas

- El esquema concreto del candidato es un **draft no vinculante**: ver `DECISION_CANDIDATE_SCHEMA_DRAFT.md`.
- Si Jorge aprueba v3, queda por decidir (en un PR posterior) si los candidatos viven en `proposals/` o en una carpeta dedicada `candidates/`, y cómo se actualizan `README.md`, `AGENT_CONTRACT.md`, `RULES_OF_ENGAGEMENT.md` y los schemas vigentes. **Esta propuesta no modifica esos archivos vigentes.**

---

## 10. Qué NO autoriza esta propuesta

- No autoriza Runner, automatización, cron, GitHub Actions, Docker, túnel/VPS ni ejecución headless.
- No cierra TASK-0002 ni crea su `DECISION` real.
- No mueve TASK-0002 a `HUMAN_DECISION`.
- No modifica MSO/Police/Policy/Auth.
- No cambia los schemas/contratos vigentes (v2 sigue rigiendo hasta aprobación humana de v3).
- No confiere ninguna autoridad a ningún agente.
