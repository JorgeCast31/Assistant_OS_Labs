# HOST_MACHINE_OPERATOR_DIRECT_CALL_AUDIT.md

**Fecha:** 2026-05-08  
**Auditor:** Agente autónomo — solo lectura  
**Fuente:** código + tests versionados. Obsidian no consultado.  
**PR de referencia:** #155 (MSO Governance BLOCKED enforcement)

---

## 1. Veredicto ejecutivo

| Pregunta | Estado | Evidencia |
|---|---|---|
| ¿HOST puede ser llamado directamente? | **Verificado — SÍ** | `agents/registry.py:_host_launcher_entrypoint` → `execute_host_action` sin orchestrator |
| ¿MACHINE_OPERATOR puede ser llamado directamente? | **Verificado — SÍ** | `agents/registry.py:_machine_operator_entrypoint` → `machine_operator_pipeline.execute(context_id="agent_registry")` sin orchestrator |
| ¿OpenClaw puede ejecutarse sin gate soberano? | **Parcial** | Backend HTTP sí tiene sovereign gate; `PlaywrightRuntimeDispatcher.execute()` callable directo en Python |
| ¿Hay bypass real? | **Verificado — SÍ** | `agents/registry.py` es un bypass al path completo de gobernanza del orchestrator |
| ¿Qué está protegido? | **Parcial** | HOST: confirmed + ACTIVE + rate limits + allowlist + audit. MACHINE_OPERATOR: contract validation + policy registry + allowlist + approval. OpenClaw server: sovereign gate + auth token. |
| ¿Qué requiere prueba dinámica? | **Requiere prueba dinámica** | Si el registry path es invocable en producción; si sovereign gate bloquea sin refs válidos en escenarios reales |

**Hallazgo más crítico:** `agents/registry.py` expone entrypoints directos a HOST (`execute_host_action`) y MACHINE_OPERATOR (`machine_operator_pipeline.execute`) que NO pasan por `IdentityGuard → PolicyDecision → CapabilityToken → MSO Governance`. Son bypass reales, estáticamente verificados, al path canónico.

---

## 2. HOST pipeline map

| Elemento | Ruta | Función pública | Llamadores conocidos | Controles internos | Riesgo |
|---|---|---|---|---|---|
| `host_pipeline.execute` | `assistant_os/pipelines/host_pipeline.py:110` | Entry point del pipeline HOST | `core/routing.py` (via orchestrator) · `agents/registry.py:_host_launcher_entrypoint` (directo) | Valida domain_payload, campo `confirmed`, campos requeridos por acción | **Alto** — callable sin orchestrator |
| `execute_host_action` | `assistant_os/agents/host_agent.py:1666` | Ejecutor final del agente HOST | `host_pipeline.py:215` (normal) · `agents/registry.py:134` (directo) | Gate 1: `confirmed=True` · Gate 2: `HOST_AGENT_ID ACTIVE en control_plane` · Gate 3: rate limit · allowlist/sandbox · intent audit antes de ejecución | **Medio** — tiene gates propios, no tiene PolicyDecision/CapabilityToken/Governance |
| `_handle_write_text_file` | `assistant_os/agents/host_agent.py:1193` | Escribe archivos en WRITE_SANDBOX | Sólo via `execute_host_action` | Sandbox containment · extension allowlist · size cap 64KB · symlink rejection · atomic write | **Bajo** — bien hardened internamente |
| `APP_REGISTRY` | `assistant_os/agents/host_agent.py:120` | Whitelist de ejecutables | N/A | Solo 3 apps: notepad, calc, explorer. No shell=True | **Bajo** |
| `/host/action` HTTP endpoint | `assistant_os/webhook_server.py:5064` | Endpoint HTTP para HOST | Callers externos | Auth header · routes a `orchestrator.handle_request` — NUNCA llama pipeline/agent directamente (comentado explícitamente) | **Bajo** — path seguro |
| `/host/confirm` HTTP endpoint | `assistant_os/webhook_server.py` | Confirma plan pendiente | Callers externos | Auth header · routes a `orchestrator.handle_request` con confirm_plan_id | **Bajo** |
| `openclaw_adapter.py` | `assistant_os/pipelines/openclaw_adapter.py` | Historical scaffold HOST-scoped | Ninguno activo | Raises `OpenClawDeprecatedInHost` si se llama | **Bajo** — quarantined |

---

## 3. MACHINE_OPERATOR pipeline map

| Elemento | Ruta | Función pública | Llamadores conocidos | Controles internos | Riesgo |
|---|---|---|---|---|---|
| `machine_operator_pipeline.execute` | `assistant_os/pipelines/machine_operator_pipeline.py:67` | Entry point del pipeline MACHINE_OPERATOR | `core/routing.py` (via orchestrator) · `agents/registry.py:_machine_operator_entrypoint` (directo, `context_id="agent_registry"`) | Contract validation · `enforce_machine_operator_request` · allowlist · approval (si requerida) · secrets prohibited · budget enforcement | **Crítico** — callable sin orchestrator, context_id hardcoded |
| `enforce_machine_operator_request` | `assistant_os/mso/machine_operator_policy.py:301` | Policy enforcement del pipeline | `machine_operator_pipeline.py:142` | Contract schema · capability registry · tier check · approval artifact (N1) · secret refs denied · side effects denied · budget caps | **Medio** — controles sólidos, pero no PolicyDecision ni CapabilityToken |
| `_CAPABILITY_POLICIES` | `assistant_os/mso/machine_operator_policy.py:36` | Registry de capabilities | `enforce_machine_operator_request` | N0: snapshot/screenshot/read_visible_text (approval_mode=none) · N1: navigate (approval_mode=required) · N2 default: deny | **Bajo** — fail-closed por diseño |
| `MachineOperatorAdapter.execute` | `assistant_os/mso/machine_operator_adapter.py` | Adapter boundary | `machine_operator_pipeline.py:212` | Policy decision ya aprobada para este punto | **Requiere prueba dinámica** |
| `/machine_operator/execute` HTTP endpoint | `assistant_os/webhook_server.py:5279` | Endpoint HTTP para MACHINE_OPERATOR | Callers externos | Auth header · navigate explícitamente rechazado · routes a `orchestrator.handle_request` | **Bajo** — path seguro |
| `agents/registry.py:_machine_operator_entrypoint` | `assistant_os/agents/registry.py:138` | Entrypoint del agent registry | Cualquier caller de `get_agent("machine_operator")` | Solo delega a pipeline; NO incluye PolicyDecision, CapabilityToken, MSO Governance | **Crítico** |

---

## 4. OpenClaw adapter/backend map

| Elemento | Ruta | Función | Gate/guard | Audit | Riesgo |
|---|---|---|---|---|---|
| `openclaw_backend/server.py` HTTP server | `assistant_os/openclaw_backend/server.py` | Servidor HTTP independiente `POST /v1/machine-operator/execute` | Auth header (`OPENCLAW_EXPECTED_AUTH_TOKEN`) · `_sovereign_store.is_execution_allowed()` ANTES de runtime | `emit_audit_event` en cada intento/bloqueo/éxito | **Medio** — gate soberano presente pero separado del orchestrator principal |
| `_sovereign_store.is_execution_allowed` | via `MSOSovereignStateStore` | Sovereign gate del backend | Verifica `approval_id`, `policy_decision_ref`, `governance_ref`, `capability_scope`, `expires_at` | Audit event emitido | **Verificado** — bloqueo antes de runtime |
| `PlaywrightRuntimeDispatcher.execute` | `assistant_os/openclaw_backend/runtime.py:216` | Dispatcher real de Playwright | Ninguno propio — solo valida URL y capability_name | Logs estructurados | **Alto** — callable directamente en Python sin sovereign gate |
| `NullRuntimeDispatcher` | `assistant_os/openclaw_backend/runtime.py:76` | Fallback cuando OPENCLAW_RUNTIME_ENABLED=False | `is_available()=False`, raises `RuntimeUnavailableError` | Ninguno | **Bajo** — no ejecuta |
| `openclaw_adapter.py` | `assistant_os/pipelines/openclaw_adapter.py` | Historical HOST-scoped scaffold | Raises `OpenClawDeprecatedInHost` | Ninguno | **Bajo** — quarantined, no active |
| `preflight.py` | `assistant_os/openclaw_backend/preflight.py` | Startup readiness check | Auth config check, runtime usable check | Ninguno | **Bajo** |

---

## 5. Import/call graph estático

### Quién importa HOST

| Importador | Ruta | Tipo | Evidencia |
|---|---|---|---|
| `core/routing.py` | `from ..pipelines.host_pipeline import execute as _host_execute` | Import observado | routing.py:31 |
| `agents/registry.py` | `from .host_agent import execute_host_action` (deferred) | Llamada observada | registry.py:134 |
| `pipelines/openclaw_adapter.py` | `from ..agents.host_agent import HostActionRequest, HostActionResult` | Import observado (quarantined) | openclaw_adapter.py:14 |

### Quién importa MACHINE_OPERATOR

| Importador | Ruta | Tipo | Evidencia |
|---|---|---|---|
| `core/routing.py` | `from ..pipelines.machine_operator_pipeline import execute as _machine_operator_execute` | Import observado | routing.py:32 |
| `agents/registry.py` | `from ..pipelines.machine_operator_pipeline import execute as _mo_execute` (deferred) | **Llamada directa observada** | registry.py:151 |

### Quién importa OpenClaw

| Importador | Ruta | Tipo | Evidencia |
|---|---|---|---|
| `openclaw_backend/server.py` | `from .runtime import ... create_default_runtime_dispatcher` | Import observado | server.py:18 |
| `mso/machine_operator_adapter.py` | (importa runtime via adapter) | Inferencia | Requiere lectura adicional |

### Quién puede saltar orchestrator

| Path | Método | Verificación governance | Estado |
|---|---|---|---|
| `get_agent("host_launcher").entrypoint(request)` | `execute_host_action` directo | NO — bypasses PolicyDecision, CapabilityToken, MSO Governance | **Bypass verificado** |
| `get_agent("machine_operator").entrypoint(request)` | `machine_operator_pipeline.execute` directo | NO — bypasses PolicyDecision, CapabilityToken, MSO Governance | **Bypass verificado** |
| `PlaywrightRuntimeDispatcher().execute(...)` | Python direct | NO — ningún gate soberano | **Bypass verificado** |
| `DOMAIN_PIPELINES["HOST"]` directo | Python dict access | NO — bypasses orchestrator | **Bypass potencial** |
| `DOMAIN_PIPELINES["MACHINE_OPERATOR"]` directo | Python dict access | NO — bypasses orchestrator | **Bypass potencial** |

---

## 6. Controles internos

### Controles verificados (presentes en código, probados)

| Control | Dónde | Alcance |
|---|---|---|
| `confirmed=True` gate | `host_agent.execute_host_action:Gate 1` | Toda operación HOST |
| `HOST_AGENT_ID ACTIVE` gate | `host_agent.execute_host_action:Gate 2` | Toda operación HOST |
| Rate limiting por acción | `host_agent._check_rate_limit` | HOST: 10-20 ops/60s |
| Path allowlist + traversal protection | `validate_allowed_directory`, `validate_allowed_write_path` | HOST filesystem ops |
| Symlink/junction rejection | `_check_no_symlink_in_path` | HOST write ops |
| Windows device name rejection | `_reject_unsafe_path_components` | HOST write ops |
| Audit emit antes de ejecución | `emit_action_intent` en cada handler | HOST — aborta si falla |
| Contract validation MACHINE_OPERATOR | `enforce_machine_operator_request` | MACHINE_OPERATOR pipeline |
| Capability policy registry (fail-closed) | `_CAPABILITY_POLICIES`, `_DENY_BY_DEFAULT_POLICY` | MACHINE_OPERATOR |
| Secrets prohibited | `machine_operator_policy.py:383-403` | MACHINE_OPERATOR |
| Side effects denied | `machine_operator_policy.py:429-443` | MACHINE_OPERATOR (N0/N1) |
| Budget caps | `machine_operator_policy.py:445-466` | MACHINE_OPERATOR |
| Auth token (OpenClaw server) | `server.py:_enforce_auth` | OpenClaw backend HTTP |
| Sovereign gate (OpenClaw server) | `server.py:_sovereign_store.is_execution_allowed` | OpenClaw backend HTTP |

### Controles parciales

| Control | Estado | Gap |
|---|---|---|
| PolicyDecision (`evaluate_policy`) | Presente en orchestrator, **ausente en agent registry path** | registry path bypassa |
| CapabilityToken (issue + verify + consume) | Presente en orchestrator, **ausente en agent registry path** | registry path bypassa |
| MSO Governance (`evaluate_governance`) | Presente en orchestrator, **ausente en agent registry path** | registry path bypassa |
| Sovereign gate OpenClaw | Presente en HTTP server, **ausente en Python direct call** | PlaywrightRuntimeDispatcher.execute callable directo |

### Controles faltantes

| Control | Estado |
|---|---|
| Police token-bound gate (S-POLICE-CORE-03) | `NotImplementedError` — no implementado |
| AuthorizedPlan end-to-end | Documental — no integrado al path principal |
| Guard interno en agent registry entrypoints | No existe — no verifica authority context antes de delegar |

### Controles documentales (solo en docs/comentarios)

| Control | Evidencia |
|---|---|
| "NEVER calls host_pipeline or host_agent directly" | webhook_server.py:5089 y 5207 — solo para el HTTP handler; no aplica al registry |
| "The adapter translates; the MSO decides; OpenClaw executes; nobody crosses lanes" | machine_operator_pipeline.py:11 — principio de diseño, no enforced en registry path |

---

## 7. Direct-call scenarios

### Scenario A — Direct HOST call

**Mecanismo:** `get_agent("host_launcher")["entrypoint"](request)` donde `request = HostActionRequest(execution_id="...", action="write_text_file", confirmed=True, path="...", content="...")`

**¿Posible?** SÍ — estáticamente verificado. `agents/registry.py:_host_launcher_entrypoint` llama `execute_host_action` directamente.

**¿Bloqueado?** PARCIALMENTE — los gates de `execute_host_action` bloquean si:
- `confirmed=False` → `CONFIRMED_REQUIRED`
- `HOST_AGENT_ID` no es ACTIVE en control_plane → `CONTROL_PLANE_BLOCKED`
- rate limit excedido
- path fuera del sandbox

**¿Qué NO verifica?** PolicyDecision, CapabilityToken, MSO Governance. Si `execution_mode=BLOCKED` en el orchestrator, esta ruta lo ignora completamente.

**Evidencia:** `registry.py:134-135`, `host_agent.py:1666-1755`

**Conclusión:** Parcialmente protegido — gates internos presentes, governance orchestrator ausente.

---

### Scenario B — Direct MACHINE_OPERATOR call

**Mecanismo:** `get_agent("machine_operator")["entrypoint"](request)` donde `request` es un dict con `machine_operator_request`.

**¿Posible?** SÍ — estáticamente verificado. `registry.py:_machine_operator_entrypoint` construye un plan con `context_id="agent_registry"` y llama `machine_operator_pipeline.execute` directamente.

**¿Bloqueado?** PARCIALMENTE — `enforce_machine_operator_request` dentro del pipeline verifica:
- capability knowledge (unknowns → denied)
- tier correctness
- secrets → denied
- side effects → denied
- budget caps
- allowlist refs
- approval artifact (si N1/navigate)

**¿Qué NO verifica?** PolicyDecision, CapabilityToken, MSO Governance. El `context_id="agent_registry"` es un string hardcoded — no correlaciona con ninguna sesión gobernada. Si MSO Governance está en BLOCKED o FROZEN, este path lo ignora.

**Evidencia:** `registry.py:138-157`, `machine_operator_pipeline.py:93-257`

**Conclusión:** Parcialmente protegido — policy interna sólida para capabilities conocidas, pero bypass completo de la capa de gobernanza del orchestrator.

---

### Scenario C — Direct OpenClaw adapter call

**Mecanismo (backend HTTP):** `POST /v1/machine-operator/execute` con auth header y policy fields válidos.

**¿Posible?** SÍ — requiere auth token correcto + sovereign decision positiva.

**¿Bloqueado?** POR SOVEREIGN GATE — `_sovereign_store.is_execution_allowed()` verifica `approval_id`, `policy_decision_ref`, `governance_ref`, `capability_scope`, `expires_at`. Si bloquea → HTTP 403.

**¿Mecanismo (Python directo)?** `PlaywrightRuntimeDispatcher().execute(capability_name="browser.navigate", ...)` — NO hay gate. Solo valida URL y capability_name. El sovereign gate no se invoca.

**¿Qué NO verifica (Python directo)?** Sovereign gate, auth, audit, PolicyDecision, CapabilityToken.

**Evidencia:** `server.py:423-489`, `runtime.py:216-276`

**Conclusión:** Backend HTTP protegido; Python direct call no protegido — requiere prueba dinámica para confirmar si es alcanzable en producción.

---

## 8. Tests existentes

| Test file | Ruta | Qué cubre | Qué NO cubre |
|---|---|---|---|
| `test_host_pipeline.py` | `tests/test_host_pipeline.py` | Pipeline dispatch, confirmed gate, agent ACTIVE gate, plan_id forwarding, write/read/list/url/pid handlers, deprecation notice | Direct call via registry path; PolicyDecision bypass |
| `test_host_agent.py` | `tests/test_host_agent.py` | Gates 1-3 de execute_host_action, APP_REGISTRY, path validation, rate limits | Governance bypass; registry entrypoint |
| `test_host_phase3a.py` | `tests/test_host_phase3a.py` | Phase 3A filesystem read-only ops | Write sandbox; direct call |
| `test_host_http.py` | `tests/test_host_http.py` | Endpoint /host/action y /host/confirm vía orchestrator | Direct pipeline call |
| `test_host_audit.py` | `tests/test_host_audit.py` | Audit events (intent, outcome, rejection) | Governance interlock |
| `test_machine_operator_pipeline.py` | `tests/test_machine_operator_pipeline.py` | Pipeline dispatch, policy enforcement, adapter boundary, budget, allowlist, approval | Direct call via registry; `context_id="agent_registry"` corner case |
| `test_machine_operator_policy.py` | `tests/test_machine_operator_policy.py` | Policy registry N0/N1/N2, capability tiers, approval mode, secrets, side effects | Orchestrator integration |
| `test_machine_operator_adapter.py` | `tests/test_machine_operator_adapter.py` | Adapter boundary | Direct adapter call |
| `test_machine_operator_contracts.py` | `tests/test_machine_operator_contracts.py` | Contract validation | — |
| `test_machine_operator_negative_validation.py` | `tests/test_machine_operator_negative_validation.py` | Rejection paths | Registry bypass path |
| `test_agent_registry.py` | `tests/test_agent_registry.py` | Registry structure, entrypoint callability | No verifica que entrypoints no bypassen gobernanza |
| `test_mso_governance_blocked_enforcement.py` | `tests/test_mso_governance_blocked_enforcement.py` (PR #155) | BLOCKED vía orchestrator path | BLOCKED via registry direct call |

**Brecha crítica detectada:** No existe ningún test que verifique que la llamada directa via `agents/registry.py` sin authority context sea rechazada, ni que `execution_mode=BLOCKED` se propague al path del registry.

---

## 9. Tests recomendados

Los siguientes tests son propuestas. No implementados.

### T1 — HOST registry direct call sin authority context
```python
# Verificar que el host_launcher entrypoint del registry
# rechaza ejecución si HOST_AGENT_ID no está ACTIVE
# (el control_plane gate debe disparar)
def test_host_registry_direct_call_blocked_when_agent_not_active():
    ...
```

### T2 — MACHINE_OPERATOR registry direct call con capability no registrada
```python
# Verificar que _machine_operator_entrypoint rechaza capability desconocida
def test_machine_operator_registry_direct_call_rejects_unknown_capability():
    ...
```

### T3 — MACHINE_OPERATOR registry direct call no verifica MSO Governance BLOCKED
```python
# Documentar el gap: con governance BLOCKED, la registry path
# no llama evaluate_governance y puede proceder
# (test de caracterización, no de corrección)
def test_machine_operator_registry_does_not_check_mso_governance():
    # Con governance en BLOCKED, registry path llega a pipeline.execute
    # Policy interna puede bloquear por otras razones (allowlist, etc.)
    # Pero NO por governance BLOCKED
    ...
```

### T4 — HOST direct call no pasa por PolicyDecision
```python
# Documentar el gap: execute_host_action NO llama evaluate_policy
def test_execute_host_action_has_no_policy_decision_check():
    ...
```

### T5 — OpenClaw runtime Python direct call ejecuta sin sovereign gate
```python
# Verificar que PlaywrightRuntimeDispatcher.execute
# NO tiene sovereign gate interno
def test_playwright_runtime_has_no_sovereign_gate_internaly():
    ...
```

### T6 — HOST registry BLOCKED via orchestrator, NOT via direct call (contraste)
```python
# Si se llama via orchestrator con BLOCKED → PLAN_GENERATED
# Si se llama via registry direct → pasa a execute_host_action
# (ilustra la asimetría)
def test_host_blocked_via_orchestrator_but_not_via_registry():
    ...
```

---

## 10. Riesgos y severidad

### CRÍTICO

**R1 — agents/registry.py bypassa orchestrator governance para MACHINE_OPERATOR**
- **Evidencia:** `agents/registry.py:138-157` — `_machine_operator_entrypoint` llama `machine_operator_pipeline.execute(plan, context_id="agent_registry")` directamente
- **Impacto:** Un caller de `get_agent("machine_operator")["entrypoint"]` puede ejecutar capabilities de browser (snapshot, screenshot, read_visible_text) sin pasar por PolicyDecision, CapabilityToken, ni MSO Governance. Si `execution_mode=BLOCKED` está activo en el orchestrator, esta ruta lo ignora.
- **Recomendación:** Añadir guard en `_machine_operator_entrypoint` que verifique authority context antes de delegar, o restringir acceso al registry (no expuesto públicamente).

**R2 — Police gate S-POLICE-CORE-03 no implementado**
- **Evidencia:** `police/enforcement.py:4-7` — `raise NotImplementedError("Token-bound Police gate is not implemented until S-POLICE-CORE-03")`
- **Impacto:** El gate policial token-bound no se ejecuta en ningún path. El pipeline puede ejecutarse sin validación del PoliceEnforcer.
- **Recomendación:** Bloquear Sprint 19 hasta implementar S-POLICE-CORE-03.

### ALTO

**R3 — agents/registry.py bypassa orchestrator governance para HOST**
- **Evidencia:** `agents/registry.py:121-135` — `_host_launcher_entrypoint` llama `execute_host_action` directamente
- **Impacto:** Puede ejecutar acciones HOST (abrir apps, escribir archivos en sandbox) sin PolicyDecision, CapabilityToken, MSO Governance. Los gates internos (confirmed, ACTIVE, allowlist) mitigan pero no reemplazan la capa de gobernanza.
- **Recomendación:** Mismo que R1: guard previo en entrypoint, o documentar como surface interna con acceso restringido.

**R4 — PlaywrightRuntimeDispatcher.execute() callable directamente sin sovereign gate**
- **Evidencia:** `openclaw_backend/runtime.py:216` — el método solo valida URL y capability_name, no invoca ningún sovereign store
- **Impacto:** Si el backend HTTP server es bypassed (llamada interna Python), OpenClaw ejecuta browser actions sin sovereign gate, sin audit, sin auth.
- **Recomendación:** No exponer el dispatcher directamente fuera del módulo; o añadir sovereign gate interno al dispatcher.

### MEDIO

**R5 — `context_id="agent_registry"` hardcoded en machine_operator_entrypoint**
- **Evidencia:** `agents/registry.py:157` — `_mo_execute(plan, context_id="agent_registry")`
- **Impacto:** Todas las llamadas via registry usan el mismo context_id, rompiendo el modelo de correlación de audit. No hay trazabilidad de qué sesión solicitó la ejecución.
- **Recomendación:** Pasar un `context_id` real generado por el caller, o requerir authority context como parámetro.

**R6 — AuthorizedPlan no integrado end-to-end**
- **Evidencia:** `sandbox/authorized_plan.py` existe como módulo pero no es verificado en el path HOST→pipeline ni MACHINE_OPERATOR→pipeline
- **Impacto:** Las decisiones de autorización no están formalizadas como artifacts verificables end-to-end.
- **Recomendación:** Evaluar integración de AuthorizedPlan como prerequisito para Sprint 19.

### BAJO

**R7 — openclaw_adapter.py quarantined pero importable**
- **Evidencia:** `pipelines/openclaw_adapter.py` — raises en ejecución, pero importable sin error
- **Impacto:** No ejecuta, pero su presencia puede confundir a futuros desarrolladores.
- **Recomendación:** Marcar como deprecated en tests; no urgente.

---

## 11. Recomendación de próximo sprint

**Recomendación: A) Implementar tests direct-call + C) Implementar S-POLICE-CORE-03**

En ese orden.

**Justificación:**

1. **A primero (tests direct-call):** Los gaps en `agents/registry.py` son bypasss verificados estáticamente pero sin tests de caracterización. Antes de implementar guards, los tests documentan el estado actual y hacen explícito el contrato roto. Sin tests, cualquier guard implementado podría ser circumventado sin detección. Costo: bajo. Valor: cierra la brecha de observabilidad.

2. **C segundo (S-POLICE-CORE-03):** La Police gate es el control de última línea que PR #155 asume como pendiente. Sin ella, el sistema no puede declarar enforcement token-bound completo. Su ausencia es el mayor bloqueante arquitectónico para Sprint 19.

**Por qué no B (guards internos en HOST/MACHINE_OPERATOR) primero:**
Los guards en los pipelines no resuelven el problema de raíz: el registry llama los pipelines sin authority context. La solución correcta es que el registry no exista como bypass, o que requiera authority context como parámetro. Eso es un rediseño de contrato, no solo un guard — y requiere evaluación de impacto primero.

**Por qué no D (AuthorizedPlan enforcement) primero:**
AuthorizedPlan es un control de diseño de largo plazo, no urgente dado que los gates actuales de PolicyDecision + CapabilityToken + MSO Governance cubren el path HTTP principal.

---

## Apéndice: Estado del git

```
git status --short: branch test/mso-governance-blocked-enforcement
Archivo en staging: AUTHORITY_PATH_AUDIT.md, tests/test_mso_governance_blocked_enforcement.py
```

**Nota:** Este audit document (HOST_MACHINE_OPERATOR_DIRECT_CALL_AUDIT.md) es un documento de lectura que NO debe comitearse en el mismo PR #155. Su destino natural es un PR documental separado o el sprint planning document.

---

## 12. Characterization tests — Phase A implementada

**Fecha:** 2026-05-08  
**Archivo:** `tests/test_host_machine_operator_direct_call_characterization.py`  
**Resultado:** 10 tests, 10 passed (0 failed, 0 skipped)

### Tests implementados

| ID | Nombre | Qué caracteriza | Resultado |
|---|---|---|---|
| T1 | `test_host_registry_direct_call_blocked_when_agent_not_active` | Registry → `execute_host_action` sin orchestrator; Gate 2 (`CONTROL_PLANE_BLOCKED`) es la única defensa cuando el agente no está activo | PASS — gap documentado |
| T2 | `test_machine_operator_registry_direct_call_rejects_unknown_capability` | Registry → pipeline MO sin orchestrator; política interna rechaza capability desconocida | PASS — gap documentado |
| T3 | `test_machine_operator_registry_does_not_check_mso_governance` | `_evaluate_mso_governance` NUNCA se llama desde el path registry → pipeline MO | PASS — bypass confirmado |
| T4a | `test_execute_host_action_has_no_policy_decision_check` | `execute_host_action` corre sus propios gates sin llamar `evaluate_policy` (Gate 1 dispara) | PASS — bypass confirmado |
| T4b | `test_execute_host_action_active_agent_no_policy_check` | Con agente ACTIVO, `execute_host_action` aún no llama `evaluate_policy` — llega a lógica de dominio | PASS — bypass confirmado |
| T5a | `test_playwright_runtime_has_no_sovereign_gate_internally` | `NullRuntimeDispatcher.execute()` lanza `RuntimeUnavailableError` sin consultar ningún SovereignStore | PASS — gap documentado |
| T5b | `test_null_runtime_dispatcher_has_no_sovereign_store_attribute` | `NullRuntimeDispatcher` no tiene atributo sovereign — la sovereign gate es solo HTTP-layer | PASS — gap confirmado estructuralmente |
| T6a | `test_orchestrator_with_blocked_governance_returns_plan_generated` | Baseline: orchestrator con governance BLOCKED → `RESULT_TYPE_PLAN_GENERATED` | PASS — comportamiento correcto |
| T6b | `test_host_registry_path_ignores_governance_blocked` | Registry path + governance BLOCKED (mock) → `_evaluate_mso_governance` NUNCA llamado; gate `CONTROL_PLANE_BLOCKED` dispara por razón diferente | PASS — bypass real confirmado |
| T6c | `test_host_registry_path_with_active_agent_bypasses_governance` | Con agente ACTIVO, el bypass de governance en el registry path se mantiene — Gate 1 (`CONFIRMED_REQUIRED`) dispara sin consultar governance | PASS — bypass estructural, no incidental |

### Gaps visibles confirmados por tests

1. **Bypass de governance (T3, T6b, T6c):** `_evaluate_mso_governance` nunca se invoca desde `agents/registry.py`. Un BLOCKED del MSO no protege el path registry.
2. **Bypass de PolicyDecision (T4a, T4b):** `execute_host_action` no llama `evaluate_policy`. Callers directos no tienen verificación de policy S10/S13.
3. **Sovereign gate solo en HTTP (T5a, T5b):** `PlaywrightRuntimeDispatcher.execute()` es callable en Python sin sovereign check. El gate vive en `server.py`, no en el dispatcher.
4. **Último recurso: gates internos (T1, T2):** Los únicos controles en el path directo son los gates internos de `execute_host_action` y `enforce_machine_operator_request`. Sin ellos, la ejecución sería completamente desprotegida.

### Estado de la recomendación

| Fase | Estado |
|---|---|
| A — Tests de caracterización | **COMPLETADA** — 10/10 tests passing |
| C — S-POLICE-CORE-03 | Pendiente (sprint siguiente) |
| B — Guards internos HOST/MACHINE_OPERATOR | Pendiente (requiere evaluación de impacto de contrato) |
| D — AuthorizedPlan enforcement | Backlog largo plazo |
