# 🧹 Mapa de Limpieza — Assistant_OS_Labs

> **Fecha:** 2026-05-05 | **Modo:** Diagnóstico (read-only) | **Archivos analizados:** ~700+ (excluyendo .git, node_modules, .venv)

---

## 1. Resumen Ejecutivo

| Métrica | Valor |
|---|---|
| **Basura segura identificada (Cat. A)** | ~530 archivos, ~70 MB |
| **Basura dudosa (Cat. B)** | ~25 archivos |
| **Archivos core (Cat. C — No tocar)** | ~200+ archivos |
| **Mayor fuente de basura** | `src/` (236 módulos generados idénticos) + `tests_generated/` (236 tests espejo) + `var/runner/executions/` (463 dirs) |
| **Archivo más grande innecesario** | `var/runner/preflight_failures.log` — **57.9 MB** |
| **Directorios de mayor riesgo** | `.claude/worktrees/` (42 worktrees abandonados) |

> [!CAUTION]
> El repo tiene **~472 archivos de módulos generados automáticamente** entre `src/` y `tests_generated/` que son duplicados con contenido boilerplate idéntico. Esto es la fuente #1 de ruido.

---

## 2. Tabla por Carpeta

### Raíz del proyecto

| Path | Cat. | Razón | Evidencia | Imports/Refs | Riesgo | Acción |
|---|---|---|---|---|---|---|
| `Clawtest.txt` | A | Archivo de prueba trivial | Contenido: "CLAW WAS HERE" | Ninguna | Bajo | **delete** |
| `.codex` | A | Archivo vacío (0 bytes útiles) | Solo newline | Ninguna, en .gitignore | Bajo | **delete** |
| `.assistant_os_state.json` | A | Estado runtime null | `{"operational_mode": null, "reason": ""}`, en .gitignore | Leído por runtime, pero regenerable | Bajo | **delete** |
| `manual_runner_background_test.py` | B | Script manual de prueba con paths hardcoded a `C:\Dev\` | Referencia paths que no existen en este repo | Importa sandbox internals | Medio | **archive** |
| `DIAG_M08_FASE1.md` | B | Doc diagnóstica de fase | Puede tener valor histórico | Ninguna | Bajo | **review** |
| `FREEZE_M05.md` — `FREEZE_M1C.md` | C | Docs de freeze/milestone | Documentación contractual de gobernanza | Ninguna directa | Alto | **keep** |
| `conftest.py` | C | Fixtures de pytest | Usado por todo el test suite | Importado por pytest | Alto | **keep** |
| `pytest.ini` | C | Configuración pytest | Define testpaths, markers | Usado por pytest runner | Alto | **keep** |
| `run_code_api.py` | C | Launcher del CODE API | Entry point operativo | Importa `assistant_os.api.code_api` | Alto | **keep** |
| `requirements.txt` | C | Dependencias Python | Necesario para install | Usado por pip | Alto | **keep** |
| `.env` / `.env.example` | C | Configuración de entorno | En .gitignore (`.env`); `.env.example` es template | Runtime | Alto | **keep** |
| `README.md` / `CLAUDE.md` | C | Documentación principal | Necesarios | Referencia | Alto | **keep** |

### `src/` — **236 archivos generados** ⚠️ ZONA CRÍTICA

| Path Pattern | Cat. | Razón | Evidencia | Imports/Refs | Riesgo | Acción |
|---|---|---|---|---|---|---|
| `src/crear_modulo_test.py` | A | Módulo boilerplate generado por CodeAgent | Idéntico contenido en 100 variantes `_v2` a `_v100` | Ningún import externo lo consume | Bajo | **delete** |
| `src/crear_modulo_test_v*.py` (×99) | A | Duplicados idénticos del anterior | Mismo hash, solo difiere el nombre | Ninguno | Bajo | **delete** |
| `src/crear_modulo_test_xyz123*.py` (×100) | A | Duplicados idénticos con sufijo xyz123 | Mismo template, 2341 bytes cada uno | Ninguno | Bajo | **delete** |
| `src/crear_modulo_agentcreate_*.py` (×12) | A | Generados por CodeAgent con hash IDs | Template boilerplate con nombre parametrizado | Ninguno | Bajo | **delete** |
| `src/crear_modulo_validrun_*.py` (×13) | A | Generados por validación de runner | Template idéntico, hashes distintos | Ninguno | Bajo | **delete** |
| `src/crea_modulo_*.py` (×5) | A | Variantes tempranas del generador | Mismo patrón de template | Ninguno | Bajo | **delete** |
| `src/modelo_de_tensores_vs_tti.py` | A | Generado experimental | Template boilerplate | Ninguno | Bajo | **delete** |
| `src/nuevo_chat_del_asistente_personal.py` | A | Generado experimental | Template boilerplate | Ninguno | Bajo | **delete** |
| `src/nuevo_modulo_movil.py` | A | Generado experimental | Template boilerplate | Ninguno | Bajo | **delete** |
| `src/__init__.py` | B | Init del paquete src | Puede ser necesario si algo importa src | Verificar | Bajo | **investigate** |

> **Total src/:** 236 archivos × ~2.4 KB = **~550 KB de basura pura**. Ya están en `.gitignore`.

### `tests_generated/` — **236 archivos generados** ⚠️ ZONA CRÍTICA

| Path Pattern | Cat. | Razón | Evidencia | Imports/Refs | Riesgo | Acción |
|---|---|---|---|---|---|---|
| `tests_generated/test_crear_modulo_test*.py` (×100) | A | Tests espejo de los módulos generados en src/ | Cada uno es ~2868 bytes, test boilerplate | Importan los módulos de src/ que también son basura | Bajo | **delete** |
| `tests_generated/test_crear_modulo_test_xyz123*.py` (×100) | A | Tests espejo con sufijo xyz123 | Patrón idéntico | Mismo caso | Bajo | **delete** |
| `tests_generated/test_crear_modulo_agentcreate_*.py` (×12) | A | Tests generados para agentcreate | Boilerplate | Ninguno operativo | Bajo | **delete** |
| `tests_generated/test_crear_modulo_validrun_*.py` (×13) | A | Tests generados para validrun | Boilerplate | Ninguno operativo | Bajo | **delete** |
| `tests_generated/test_crea_modulo_*.py` (×5+) | A | Tests de variantes tempranas | Boilerplate | Ninguno | Bajo | **delete** |
| `tests_generated/__init__.py` | A | Init del paquete generado | Solo si se borran todos los tests | Ninguno | Bajo | **delete** |

> **Total tests_generated/:** 236 archivos × ~2.9 KB = **~670 KB de basura pura**. Ya en `.gitignore`.

### `var/` — **Runtime artifacts** ⚠️ 58+ MB

| Path | Cat. | Razón | Evidencia | Riesgo | Acción |
|---|---|---|---|---|---|
| `var/runner/preflight_failures.log` | A | Log de fallos de preflight — **57.9 MB** | Log acumulativo, regenerable | Bajo | **delete** |
| `var/runner/audit.jsonl` | A | Audit log de runner, 4 KB | Regenerable | Bajo | **delete** |
| `var/runner/executions/` (463 subdirs) | A | Workspaces de ejecuciones pasadas | Cada uno contiene artefactos de ejecución transitoria (n8n_*, s2-*, s3-*, etc.) | Bajo | **delete** |
| `var/audit/background_test.jsonl` | A | Audit de test manual | <1 KB, regenerable | Bajo | **delete** |
| `var/audit/host_actions.jsonl` | B | Log de acciones del host — 75 KB | Podría tener valor diagnóstico | Medio | **archive** |
| `var/audit/runner_probe.jsonl` | A | Probe audit | <1 KB | Bajo | **delete** |

> **Total var/:** ~58 MB, mayormente un solo log file. Todo en `.gitignore`.

### `logs/` — **Runtime logs**

| Path | Cat. | Razón | Evidencia | Riesgo | Acción |
|---|---|---|---|---|---|
| `logs/code_api.log` | A | Log de CODE API — **1.2 MB** | Regenerable en cada ejecución | Bajo | **delete** |
| `logs/openclaw_audit.ndjson` | B | Audit trail de OpenClaw — 67 KB | Puede tener valor forense | Medio | **archive** |

### `assistant_os/memory/` — **Runtime state** ⚠️

| Path | Cat. | Razón | Evidencia | Riesgo | Acción |
|---|---|---|---|---|---|
| `memory/log.ndjson` | A | Log de runtime — **15.1 MB** | Regenerable, en .gitignore | Bajo | **delete** |
| `memory/chat_sessions.db` + shm + wal | A | SQLite DB de sesiones — **1.7 MB total** | Regenerable, en .gitignore (*.db) | Bajo | **delete** |
| `memory/context_store.json` | A | Store vacío (2 bytes: `[]`) | En .gitignore | Bajo | **delete** |
| `memory/taxonomy_cache.json` | A | Cache de taxonomía — 2 KB | Regenerable, en .gitignore | Bajo | **delete** |
| `memory/schema_ops.ndjson` | A | Log de schema ops — 5 KB | Regenerable | Bajo | **delete** |
| `memory/state.json` | A | Estado de memoria — 596 bytes | En .gitignore | Bajo | **delete** |
| `memory/mso_store/` | A | MSO store directory | En .gitignore | Bajo | **delete** |
| `memory/worker_runtime/` | A | Runtime state de workers | En .gitignore | Bajo | **delete** |
| `memory/state.py` | C | Código de gestión de estado | Módulo Python activo, no data | Alto | **keep** |
| `memory/__init__.py` | C | Init del paquete | Importado por otros módulos | Alto | **keep** |

### `.claude/` — **Claude Code worktrees** ⚠️

| Path | Cat. | Razón | Evidencia | Riesgo | Acción |
|---|---|---|---|---|---|
| `.claude/settings.json` | C | Config de Claude Code | Puede ser necesario | Medio | **keep** |
| `.claude/settings.local.json` | B | Config local de Claude | Puede contener preferencias | Bajo | **review** |
| `.claude/worktrees/` (42 subdirs) | A | Worktrees abandonados de Claude Code | Cada uno contiene copia completa del repo incluyendo node_modules | Bajo | **delete** |
| `assistant_os/.claude/worktrees/` | A | Nested worktrees | Dentro del módulo core, no debería existir | Bajo | **delete** |

> [!WARNING]
> Los 42 worktrees en `.claude/worktrees/` pueden ocupar **varios GB** de disco por los `node_modules` anidados. Son la causa de los errores de path demasiado largo en Windows.

### `scratch/` — **Archivos experimentales**

| Path | Cat. | Razón | Evidencia | Riesgo | Acción |
|---|---|---|---|---|---|
| `scratch/audit_work_update.py` | B | Script de auditoría | Puede tener valor de referencia | Medio | **review** |
| `scratch/debug_command_flow.py` | B | Script de debug | Experimental | Bajo | **archive** |
| `scratch/test_e2e_*.py` (×2) | B | Tests e2e experimentales | No en pytest testpaths | Medio | **review** |
| `scratch/test_full_flow.py` | B | Test de flujo completo | Experimental | Medio | **review** |
| `scratch/test_op_intent.py` | B | Test de intent | Experimental | Bajo | **archive** |
| `scratch/test_operational_intent.py` | B | Posible duplicado del anterior | Similar nombre | Bajo | **investigate** |
| `scratch/test_parser_phase2.py` | B | Test de parser | Experimental | Bajo | **archive** |
| `scratch/test_routing_verify.py` | B | Test de routing | Experimental | Bajo | **archive** |
| `scratch/test_t1.py` | A | Test trivial (544 bytes) | Probablemente throwaway | Bajo | **delete** |

> Todo `scratch/` está en `.gitignore`. pytest.ini lo ignora con `--ignore=scratch`.

### `tools/launcher/` — **Build artifacts**

| Path | Cat. | Razón | Evidencia | Riesgo | Acción |
|---|---|---|---|---|---|
| `tools/launcher/build/` | A | Build intermedios de launcher | Artefactos de compilación | Bajo | **delete** |
| `tools/launcher/dist/AssistantOS Launcher.exe` | B | Binario compilado — **10 MB** | Puede ser útil para distribución, pero regenerable | Medio | **archive** |
| `tools/launcher/logs/backend.log` | A | Log de backend — <1 KB | Regenerable | Bajo | **delete** |
| `tools/launcher/logs/llama.log` | A | Log de llama — 11 KB | Regenerable | Bajo | **delete** |
| `tools/launcher/launcher_config.json` | A | Config generada | En .gitignore | Bajo | **delete** |

> Todo `tools/` está en `.gitignore`.

### `ui/.next/` — **Next.js build cache**

| Path | Cat. | Razón | Evidencia | Riesgo | Acción |
|---|---|---|---|---|---|
| `ui/.next/` (completo) | A | Build cache de Next.js | Regenerable con `npm run build`, ~600KB trace + server/static | Bajo | **delete** |
| `ui/tsconfig.tsbuildinfo` | A | TS build info — 115 KB | Regenerable, en .gitignore | Bajo | **delete** |

### `state/`

| Path | Cat. | Razón | Evidencia | Riesgo | Acción |
|---|---|---|---|---|---|
| `state/run_state.json` | A | Estado de ejecución — 166 bytes | En .gitignore, regenerable | Bajo | **delete** |

### `secrets/`

| Path | Cat. | Razón | Evidencia | Riesgo | Acción |
|---|---|---|---|---|---|
| `secrets/service-account.json` | C | Credenciales de GCP | En .gitignore (`*service-account*.json`). **NO BORRAR sin backup seguro** | Alto | **keep** |

> [!CAUTION]
> Si este archivo no tiene backup, eliminarlo causaría pérdida de acceso a servicios de Google Cloud.

### `governance/` — **Keep/Do Not Touch**

| Path | Cat. | Razón | Riesgo | Acción |
|---|---|---|---|---|
| `governance/line-f/` | C | Gobernanza de línea F — estructura vacía por ahora | Alto | **keep** |

> Contenido mínimo pero forma parte de la estructura de gobernanza.

### `contracts/` — **Keep/Do Not Touch**

Todos los 5 archivos (`FINAL_REPORT.md`, `TASK_00.md`, `TASK_01.md`, `WORKLOG.md`, `agent_contract.md`) son documentación contractual. **Cat. C — keep**.

### `agent_context/` — **Keep/Do Not Touch**

Los 7 archivos son contexto de agente y documentación de arquitectura. **Cat. C — keep**.

### `docs/` — **Keep/Do Not Touch**

Toda la estructura de docs (brains, mso, observability, operability, security, testing + archivos raíz) es documentación operativa activa. **Cat. C — keep**.

### `assistant_os/` — **Core (Cat. C)**

Todos los módulos en `assistant_os/` son código operativo: mso, policy, sandbox, runners, agents, api, authority, codeops, cognition, control_plane, core, executors, grants, handlers, integrations, memory, parsers, pipelines, policy, secrets, storage, system_assistant, tools, capabilities, confirm_flow, openclaw_backend. **No tocar.**

### `tests/` — **Active test suite (Cat. C)**

Los 142 archivos de test en `tests/` y 10 en `tests/runners/` son tests activos referenciados por `pytest.ini`. **No tocar.**

### `.github/workflows/tests.yml` — **Cat. C — keep**

### `seeds/` — **Cat. C — keep** (templates en .gitignore correctamente)

---

## 3. Top 20 Candidatos de Eliminación Segura

| # | Path | Tamaño | Razón |
|---|---|---|---|
| 1 | `var/runner/preflight_failures.log` | **57.9 MB** | Log acumulado, regenerable |
| 2 | `assistant_os/memory/log.ndjson` | **15.1 MB** | Runtime log, en .gitignore |
| 3 | `assistant_os/memory/chat_sessions.db*` (3 archivos) | **1.7 MB** | SQLite regenerable |
| 4 | `logs/code_api.log` | **1.2 MB** | Log de API |
| 5 | `ui/.next/` (directorio completo) | **~1 MB+** | Build cache de Next.js |
| 6 | `ui/tsconfig.tsbuildinfo` | **115 KB** | TS build cache |
| 7 | `src/crear_modulo_test_v*.py` (99 archivos) | **231 KB** | Duplicados idénticos |
| 8 | `src/crear_modulo_test_xyz123*.py` (100 archivos) | **234 KB** | Duplicados idénticos |
| 9 | `tests_generated/test_crear_modulo_test_v*.py` (99) | **284 KB** | Tests de módulos basura |
| 10 | `tests_generated/test_crear_modulo_test_xyz123*.py` (100) | **290 KB** | Tests de módulos basura |
| 11 | `src/crear_modulo_agentcreate_*.py` (12) | **29 KB** | Generados con hash ID |
| 12 | `tests_generated/test_crear_modulo_agentcreate_*.py` (12) | **36 KB** | Tests espejo |
| 13 | `src/crear_modulo_validrun_*.py` (13) | **31 KB** | Generados por validación |
| 14 | `tests_generated/test_crear_modulo_validrun_*.py` (13) | **38 KB** | Tests espejo |
| 15 | `var/runner/executions/` (463 subdirs) | **Variable** | Workspaces transitorios |
| 16 | `Clawtest.txt` | **14 bytes** | "CLAW WAS HERE" |
| 17 | `.codex` | **0 bytes** | Archivo vacío |
| 18 | `scratch/test_t1.py` | **544 bytes** | Test trivial |
| 19 | `state/run_state.json` | **166 bytes** | Estado regenerable |
| 20 | `.assistant_os_state.json` | **40 bytes** | Estado null, regenerable |

---

## 4. Top 20 Candidatos Dudosos

| # | Path | Razón de duda | Acción recomendada |
|---|---|---|---|
| 1 | `.claude/worktrees/` (42 worktrees) | Pueden contener cambios no mergeados | **investigate** luego **delete** |
| 2 | `assistant_os/.claude/worktrees/` | Nested worktrees dentro de core | **investigate** luego **delete** |
| 3 | `manual_runner_background_test.py` | Script manual con paths hardcoded | **archive** |
| 4 | `logs/openclaw_audit.ndjson` | Audit trail con posible valor forense | **archive** |
| 5 | `var/audit/host_actions.jsonl` | 75 KB de acciones del host | **archive** |
| 6 | `tools/launcher/dist/*.exe` | Binario compilado de 10 MB | **archive** si hay build pipeline |
| 7 | `DIAG_M08_FASE1.md` | Diagnóstico de milestone 8 | **review** — puede ser historial útil |
| 8 | `scratch/test_e2e_simple.py` | Test e2e experimental | **review** — podría promoverse a tests/ |
| 9 | `scratch/test_e2e_work_update_phase2.py` | Test e2e de actualización | **review** — podría promoverse |
| 10 | `scratch/test_full_flow.py` | Test de flujo completo | **review** |
| 11 | `scratch/audit_work_update.py` | Script de auditoría | **review** |
| 12 | `scratch/debug_command_flow.py` | Script de debug | **archive** |
| 13 | `scratch/test_op_intent.py` | Test de intent operacional | **review** |
| 14 | `scratch/test_operational_intent.py` | Posible duplicado del anterior | **investigate** |
| 15 | `scratch/test_parser_phase2.py` | Test de parser | **review** |
| 16 | `scratch/test_routing_verify.py` | Test de routing | **review** |
| 17 | `src/__init__.py` | Init del paquete src | **investigate** si algo lo importa |
| 18 | `.claude/settings.local.json` | Config local de Claude Code | **review** |
| 19 | `src/crear_modulo_test.py` (original) | El "original" de todos los clones | **review** — ¿se necesita como template? |
| 20 | `assistant_os/memory/schema_ops.ndjson` | Log de schema ops | **archive** |

---

## 5. Carpetas que Requieren Auditoría Manual

| Carpeta | Razón | Complejidad |
|---|---|---|
| **`.claude/worktrees/`** | 42 worktrees pueden tener branches con cambios no mergeados. Verificar `git worktree list` antes de eliminar | Alta |
| **`scratch/`** | 10 archivos experimentales que podrían tener lógica útil para promover a `tests/` | Media |
| **`var/runner/executions/`** | 463 subdirectorios de ejecuciones. Verificar si alguna contiene datos que se necesiten para audit trail | Media |
| **`tools/launcher/`** | Contiene build artifacts + un .exe de 10 MB. Verificar si existe pipeline de rebuild | Baja |
| **`assistant_os/memory/`** | Mezcla de código Python (keep) con datos runtime (delete). Requiere separación cuidadosa | Media |

---

## 6. Propuesta de Lotes de Limpieza (Orden Seguro)

### Lote 1 — "Quick Wins" (Riesgo: BAJO, ~75 MB)
Sin dependencias, todo en `.gitignore`, cero impacto operativo.

```
# Logs y runtime data
rm var/runner/preflight_failures.log
rm var/runner/audit.jsonl
rm var/audit/background_test.jsonl
rm var/audit/runner_probe.jsonl
rm logs/code_api.log
rm assistant_os/memory/log.ndjson
rm assistant_os/memory/chat_sessions.db*
rm assistant_os/memory/context_store.json
rm assistant_os/memory/taxonomy_cache.json
rm assistant_os/memory/schema_ops.ndjson
rm assistant_os/memory/state.json
rm state/run_state.json
rm .assistant_os_state.json
rm ui/tsconfig.tsbuildinfo
rm tools/launcher/launcher_config.json
rm tools/launcher/logs/*
rm Clawtest.txt
rm .codex
```

### Lote 2 — "Módulos Generados" (Riesgo: BAJO, ~1.2 MB)
472 archivos de boilerplate sin referencias externas.

```
# Módulos generados en src/
rm src/crear_modulo_test_v*.py
rm src/crear_modulo_test_xyz123*.py
rm src/crear_modulo_agentcreate_*.py
rm src/crear_modulo_validrun_*.py
rm src/crea_modulo_*.py
rm src/modelo_de_tensores_vs_tti.py
rm src/nuevo_chat_del_asistente_personal.py
rm src/nuevo_modulo_movil.py
rm src/crear_modulo_test.py

# Tests generados espejo
rm -r tests_generated/
```

### Lote 3 — "Build Caches" (Riesgo: BAJO)
Regenerables con rebuild.

```
rm -r ui/.next/
rm -r tools/launcher/build/
```

### Lote 4 — "Execution Workspaces" (Riesgo: BAJO-MEDIO)
Requiere verificación de que no hay audit pendiente.

```
rm -r var/runner/executions/
```

### Lote 5 — "Claude Worktrees" (Riesgo: MEDIO)
**Ejecutar primero:** `git worktree list` para verificar estado.

```
# Solo después de verificar que no hay cambios sin merge
rm -r .claude/worktrees/
rm -r assistant_os/.claude/
```

### Lote 6 — "Review & Archive" (Riesgo: MEDIO)
Mover a un directorio `_archive/` antes de eliminar.

```
mkdir _archive
mv manual_runner_background_test.py _archive/
mv logs/openclaw_audit.ndjson _archive/
mv var/audit/host_actions.jsonl _archive/
mv tools/launcher/dist/ _archive/
mv scratch/ _archive/scratch/
mv DIAG_M08_FASE1.md _archive/
```

---

## 7. Hallazgos Adicionales

### Corrupción en `.gitignore`
La línea 131 contiene caracteres null (UTF-16 leak):
```
.\x00c\x00o\x00d\x00e\x00x\x00
```
Esto debería limpiarse.

### Archivos que NO están en `.gitignore` pero deberían estarlo
- `DIAG_M08_FASE1.md` — documento diagnóstico, no contractual
- `manual_runner_background_test.py` — script ad-hoc

### Estimación de espacio recuperable

| Lote | Espacio estimado |
|---|---|
| Lote 1 (logs/runtime) | ~75 MB |
| Lote 2 (módulos generados) | ~1.2 MB |
| Lote 3 (build caches) | ~2 MB |
| Lote 4 (executions) | Variable (potencialmente 100+ MB) |
| Lote 5 (worktrees) | **Potencialmente varios GB** |
| Lote 6 (archive) | ~10 MB (se mueve, no se elimina) |
| **Total estimado** | **80+ MB inmediato, potencialmente GB con worktrees** |
