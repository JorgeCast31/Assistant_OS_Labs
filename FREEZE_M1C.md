# FREEZE_M1C — Real Docker Execution Validation & Hardening

**Fecha:** 2026-03-31
**Branch:** `reconcile/baseline-freeze`
**Commit:** → `feat(execution): M1C — enable real Docker execution and harden runtime path`
**Estado:** IMPLEMENTADO Y VALIDADO CON DOCKER REAL — path Docker completo ejercido sin mocks

---

## DIAGNÓSTICO (estado post-M1B)

M1B entregó la conexión arquitectónica entre `RunnerService` y `RunnerAPI` (Docker),
pero toda la validación fue con `RunnerAPI` mockeado. Tres deficiencias concretas quedaron
sin validar o sin corregir:

| Deficiencia | Origen | Severidad |
|---|---|---|
| Docker real nunca ejercido en CI | M1B limitación explícita | MEDIA |
| Self-copy recursivo cuando `repo_path` contiene `_RUNNER_BASE` | Bug latente en `workspace_manager.py` | ALTA — cuelgue garantizado |
| `ValidationEngine` ciega a `sandbox_metadata` | Gap arquitectónico | MEDIA — `success` real reportado como `needs_review` |

---

## CAMBIOS REALIZADOS EN M1C

### Fix 1 — `workspace_manager.py`: Prevención de self-copy recursivo

**Problema:** `shutil.copytree` con `repo_path = <project_root>` recursaba en
`var/runner/executions/<id>/workspace/` → dentro de sí misma → cuelgue garantizado
(o `path-too-long` en Windows).

**Causa raíz:** El patrón estático `_WORKSPACE_IGNORE` solo excluía `.git`.
No existía mecanismo para ignorar el directorio de destino cuando cae dentro del origen.

**Solución:** Reemplazar el ignore estático por `_make_copy_ignore(repo_path, execution_dir)`:

```python
# ANTES
_WORKSPACE_IGNORE = shutil.ignore_patterns(".git", ".git/*")
shutil.copytree(request.repo_path, str(workspace_dir), ignore=_WORKSPACE_IGNORE)

# DESPUÉS
_WORKSPACE_IGNORE_BASE = shutil.ignore_patterns(".git", ".git/*")

def _make_copy_ignore(repo_path: Path, execution_dir: Path):
    try:
        rel = execution_dir.resolve().relative_to(repo_path.resolve())
        top = rel.parts[0]   # e.g. "var"
    except ValueError:
        return _WORKSPACE_IGNORE_BASE   # execution_dir outside repo_path — no extra ignore

    repo_resolved_str = str(repo_path.resolve())

    def _ignore(src: str, names: list) -> set:
        ignored = set(_WORKSPACE_IGNORE_BASE(src, names))
        if Path(src).resolve() == Path(repo_resolved_str).resolve():
            if top in names:
                ignored.add(top)
        return ignored

    return _ignore

# In prepare_workspace:
copy_ignore = _make_copy_ignore(Path(request.repo_path), execution_dir)
shutil.copytree(request.repo_path, str(workspace_dir), ignore=copy_ignore)
```

**Garantía:** El directorio `var/` (o cualquier primer componente relativo)
es ignorado exclusivamente cuando `copytree` visita el directorio raíz del repo.
Los demás niveles de la copia no son afectados.

---

### Fix 2 — `validation_engine.py`: Conciencia de sandbox_metadata

**Problema:** `ValidationEngine.validate()` nunca inspeccionaba `result.sandbox_metadata`.
Una ejecución sandbox exitosa (exit_code=0, status="completed") caía al caso 7
("Nothing meaningful happened") → `needs_review`. El pipeline reportaba un run
Docker real y exitoso como ambiguo.

**Solución:** Insertar check 2.5 entre la verificación de error runner y los
spec requirements:

```python
# Check 2.5 — inserted after check 2, before check 3
if (
    result.sandbox_metadata is not None
    and result.sandbox_metadata.get("status") == "completed"
    and result.sandbox_metadata.get("exit_code") == 0
):
    reasons.append("Sandbox code execution completed successfully.")
    if result.modified_files:
        reasons.append(f"{len(result.modified_files)} file(s) modified.")
    return self._result("success", reasons)
```

**Árbol de decisión actualizado:**
```
1. Test timed out or explicitly failed          → failed
2. Runner error or FAILED status                → failed
2.5 Sandbox completed (exit_code=0)             → success   ← NUEVO
3. Spec requirement unmet + strict              → failed
4. Spec requirement unmet + review allowed      → needs_review
5. Tests passed                                 → success
6. Changes applied, no tests run                → needs_review / failed
7. Nothing meaningful                           → needs_review / failed
```

---

## VALIDACIÓN CON DOCKER REAL

### FASE 3 — Casos base (pre-fix, Docker real ejercido)

Antes de los fixes, Docker fue confirmado funcional con 3 casos reales:

| Caso | Code | Status Docker | `final_status` (pre-fix) |
|---|---|---|---|
| Case 1: aritmética básica | `result = 2+2; print(result)` | completed, exit=0 | needs_review (bug) |
| Case 2: stdout + stderr | `import sys; print("ok"); print("warn", file=sys.stderr)` | completed, exit=0 | needs_review (bug) |
| Case 3: exit non-zero | `import sys; sys.exit(1)` | completed, exit=1 | failed (correcto) |

Audit trail real verificado: 8 eventos JSONL con sequence numbers, container IDs,
SHA-256 hashes, timestamps UTC.

### FASE 5 — Validación post-fix

Caso de regresión ejecutado con Docker real después de ambos fixes:

```
execution_id:  m1c-fix2-<hex>
code:          result = 2 + 2; print(f"result={result}")
repo_path:     C:/Users/Jorge/Assistant_OS_Labs/assistant_os
```

**Resultado:**
```
status:             RunnerExecutionStatus.WORKSPACE_READY
final_status:       success
error:              None
sandbox.status:     completed
sandbox.exit_code:  0
validation:         success
reasons:            ['Sandbox code execution completed successfully.']
```

### Suite de tests

| Suite | Resultado |
|---|---|
| `tests/runners/` | 152 passed, 0 failed |

---

## CONTRATOS REALES POST-M1C

### `workspace_manager._make_copy_ignore`
**Antes:** Bug latente — cuelgue garantizado con project root como repo_path.
**Ahora:** Detecta cuando `execution_dir` ⊂ `repo_path`, ignora el primer
componente relativo al visitar el directorio raíz. Backward-compatible — no cambia
comportamiento cuando `execution_dir` está fuera de `repo_path`.

### `ValidationEngine.validate` con sandbox_metadata
**Antes:** Sandbox exitoso → `needs_review` (falso negativo).
**Ahora:** `sandbox_metadata.status == "completed" AND exit_code == 0` → `success`.
El contrato de governance se refleja en el resultado final — runs Docker reales
exitosos producen `final_status: success`.

### Docker execution path completo (sin mocks)
**Antes (M1B):** RunnerAPI mockeado, nunca ejercido con Docker real.
**Ahora (M1C):** Validado end-to-end:
- Container spin-up (~350-400ms)
- stdout/stderr capture
- exit code propagation
- artifact collection (SHA-256 en audit)
- lifecycle transitions reales (`PENDING → RUNNING → COMPLETED`)
- audit.jsonl con 8 eventos por run, sequence numbers, container IDs

---

## ALERTAS RESIDUALES

### Alerta 1 — `TestEngine` no aislado
**Severidad: BAJA para M1C**
Phase 3 ejecuta `pytest` como subprocess local. Deliberado en este sprint.
El foco fue el sandbox path, no el test runner.

### Alerta 2 — `code` field opcional implica Phase 2.5 no universal
**Severidad: MEDIA**
Requests sin `code` no activan Phase 2.5. Para enforcement obligatorio,
`code` debería ser required o Phase 2.5 activarse solo con `authorized_plan`.

### Alerta 3 — CODE domain ausente del orchestrator
**Severidad: ALTA para M2**
`code_api.py` opera como servidor HTTP independiente. El flujo
`CanonicalRequest → PolicyDecision → CODE pipeline` no existe todavía.

### Alerta 4 — ValidationEngine: spec requirements no interactúan con sandbox
**Severidad: BAJA**
El check 2.5 retorna `success` antes de evaluar `require_tests` / `require_changes`.
Si un caller setea `require_changes=True` pero solo ejecuta código sandbox (sin
modificar archivos), obtendrá `success` ignorando el spec. Comportamiento
probablemente correcto para el dominio CODE, pero no explícito.

---

## FORMULACIÓN HONESTA DEL ESTADO POST-M1C

**Lo que quedó real y validado con Docker real:**
- Docker execution path completo: spin-up, code run, capture, cleanup
- Fix 1: self-copy recursivo prevenido — repo_path = project root ya no cuelga
- Fix 2: ValidationEngine sandbox-aware — `success` real en lugar de `needs_review`
- Audit trail real: eventos JSONL con metadata completa por run
- ExecutionRegistry: lifecycle transitions reales en cada run

**Lo que sigue pendiente:**
- Docker path no integrado con `TestEngine` (Phase 3 sigue siendo subprocess local)
- CODE domain sin routing desde el orchestrator principal
- `code` field no obligatorio — Phase 2.5 condicional
- `require_changes` + sandbox-only = gap semántico menor

---

## SIGUIENTE SPRINT RECOMENDADO: M2 — CODE Domain en el Orchestrator

**Objetivo:** Conectar el CODE domain al orchestrator principal.

**Slices:**
1. Routing `CanonicalRequest → CODE pipeline → RunnerService` en `core/orchestrator.py`
2. Hacer `code` field requerido cuando `authorized_plan` está presente (o viceversa)
3. Resolver gap semántico entre `require_changes` y sandbox-only execution
4. Evaluar si `TestEngine` debe ejecutar dentro del mismo container Docker o mantener separación de fases

---

## ARCHIVOS MODIFICADOS EN M1C

```
assistant_os/runners/workspace_manager.py   — Fix 1: _make_copy_ignore() previene self-copy recursivo
assistant_os/runners/validation_engine.py   — Fix 2: check 2.5 sandbox_metadata → success
FREEZE_M1C.md                               — este documento
```
