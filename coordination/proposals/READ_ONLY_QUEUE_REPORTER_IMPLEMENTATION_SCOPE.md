# READ-ONLY QUEUE REPORTER — SCOPE DE IMPLEMENTACIÓN (ficha compacta)

> **Estado:** apoyo a `READ_ONLY_QUEUE_REPORTER_IMPLEMENTATION_AUTHORIZATION.md` (TASK-0007). **No implementa nada. No confiere autoridad.**
> Resume, en una sola ficha, el **contorno exacto** que debería respetar el PR de implementación futura **si Jorge autoriza** (merge de TASK-0007). Ante cualquier conflicto, mandan el `..._AUTHORIZATION.md` y el `..._MVP.md`.

---

## Frontera en una línea

> **Leer `coordination/tasks/*.md` + detectar presencia de artefactos + clasificar + imprimir a stdout. Nada más.**

## Permitido / Prohibido (techo no relajable)

| Permitido (techo) | Prohibido (sin excepción) |
|---|---|
| Ejecución **manual** (`python scripts/coordination_queue_reporter.py`) | cron, daemon, scheduler, GitHub Actions, headless, Docker, túnel/VPS |
| **Lectura** de `coordination/tasks/*.md`, schema, y **presencia** de artefactos | leer `.env`/secrets/auth, red, chat, ramas-como-autoridad |
| Salida **efímera** a stdout | escribir/crear/modificar archivos del repo (incl. logs en `coordination/`) |
| Clasificar y **marcar** (flags) | decidir/interpretar autoridad; mover estados; promover candidatos |
| Determinismo sobre archivos locales | tocar `assistant_os/`, `ui/`, `auth`, MSO/Police/Policy; `import assistant_os` |

## Ubicaciones (propuestas)

| Artefacto | Ruta propuesta | Razón |
|---|---|---|
| Código | `scripts/coordination_queue_reporter.py` | hogar de scripts manuales; aislado de la soberanía; superficie mínima |
| Tests | `tests/test_coordination_queue_reporter.py` | coherente con `pytest.ini` (`testpaths = tests`) |

## Verificación esperada

```bash
python scripts/coordination_queue_reporter.py     # imprime cola; no escribe nada
pytest tests/test_coordination_queue_reporter.py -q
```

## Entradas / Salidas

- **Entrada:** front-matter de `coordination/tasks/*.md` (read-only); presencia (existe/no) de `TASK-NNNN.*` en `worklogs/reports/reviews/candidates/decisions`; `schemas/TASK.schema.md` (required + enum).
- **Salida:** un reporte efímero a stdout (forma en `MVP §9`), descriptivo, sin órdenes aplicadas. `exit code` no codifica autoridad.

## Invariantes de seguridad (build-breaking)

`S1` read-only · `S2` anti-inyección (parser puro; nunca `eval`/`yaml.load` inseguro) · `S3` sin secretos/red · `S4` sin persistencia · `S5` determinismo · `S6` fail-closed · `S7` sin autoridad paralela (sin `import assistant_os`).

## F1–F4 (obligatorio)

- **F1** legacy sin `last_legit_status` ⇒ `LEGACY_AMBIGUOUS`, sin fallo global (C2).
- **F2** DRAFT con entregables en `main` ⇒ `DRAFT_SUPERSEDED`/`DRAFT_DESIGN_MERGED` + `REQUIRES_HUMAN_INTERPRETATION`, nunca `READY` ciego (C9); DRAFT sin entregables ⇒ candidato `DRAFT→READY` (C10).
- **F3** siguiente paso no deducible del enum ⇒ `REQUIRES_HUMAN_INTERPRETATION`; no inventar estado.
- **F4** `HUMAN_DECISION` ⇒ `CLOSED_IN_COORDINATION_PLANE` + `MSO_ONLY_NEXT`; no empujar `HANDOFF_TO_MSO`.

## Fail-closed

Campo `required` ausente / `status` fuera de enum / conflicto ⇒ `BLOCKED_OBS` o `LEGACY_AMBIGUOUS` (marcar, no avanzar). Fila inválida no aborta el barrido. Duda ⇒ no sugerir acción.

## Aceptación

Pasan todos los casos `T-C*`, `T-F*`, `T-S*` (`..._ACCEPTANCE_TESTS.md`) y los criterios `MVP §13`; Codex los revisa como suficientes; read-only sin autoridad confirmado.

## Fuera del MVP

Persistencia, `git`/red para leer commits, notificaciones, scheduling, transiciones de estado, acoplamiento con `assistant_os/`, y la distinción cierta `DRAFT_SUPERSEDED` vs `DRAFT_DESIGN_MERGED` (queda en `REQUIRES_HUMAN_INTERPRETATION`).

---

> Esta ficha es **descriptiva**. La autorización efectiva depende **solo** del merge verificable de Jorge de `TASK-0007`. Hasta entonces, el Reporter/Runner sigue **bloqueado**.
