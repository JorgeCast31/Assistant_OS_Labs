# REALITY_ALIGNMENT_ASSISTANT_OS_LABS.md

**Fecha:** 2026-05-08  
**Propósito:** Fuente de verdad corregida para Obsidian y planificación de sprints.  
**Base:** Auditoría directa del repo frente a CARTOGRAFIA_REPO_COMPLETA.md.  
**Modo de producción:** Solo lectura. Sin modificación de archivos.

---

## 1. Estado Real del Sistema

### 1.1 Implementado (código real, activo, verificable estáticamente)

| Componente | Archivos clave | Observaciones |
|---|---|---|
| **MSO Core** | `mso/` — 28 archivos `.py` | Governance engine, policy engine, contracts, candidate orchestration, delegation, audit wiring, anomaly engine, risk engine, restrictions, system state — todos con implementación real. |
| **Domain Pipelines** | `pipelines/code_pipeline.py`, `work_pipeline.py`, `fin_pipeline.py`, `host_pipeline.py`, `machine_operator_pipeline.py`, `openclaw_adapter.py` | Los 5 dominios tienen pipelines reales con código ejecutable. |
| **Runner/Sandbox** | `runners/` (13 archivos), `sandbox/` (13 archivos) | apply_engine, validation_engine, workspace_manager, authorized_plan, revocation, execution_backend, output_policy — todo real. Más rico que lo descrito en cartografía. |
| **PolicyDecision** | `contracts.py:599` (TypedDict) | Instanciado y evaluado en `core/orchestrator.py` y `core/policy.py`. Puede bloquear ejecución. |
| **AuthorizedPlan** | `sandbox/authorized_plan.py:34` | Requerida por runners para ejecutar. Single-use enforcement activo. |
| **CapabilityScope** | `mso/contracts.py:1714` | Usada en police models, runners y code_pipeline. |
| **CapabilityToken** | `capabilities/token_models.py:120` | Token de capacidad real, con issuer, verifier y gate. |
| **Fail-closed pattern** | `capabilities/capability_gate.py`, `capabilities/token_verifier.py`, `cognition/router.py`, `identity_guard.py`, `machine_operator_policy.py` | Patrón fail-closed documentado e implementado en al menos 5 módulos distintos. |
| **Audit infrastructure** | `police/audit.py`, `mso/audit_wiring.py`, `sandbox/audit.py`, `mso/machine_operator_audit.py`, `audit/sink.py`, `audit/jsonl_store.py` | JSONL store, event building, audit paths — todo real y activo. |
| **Control Plane** | `control_plane/` — 9 archivos | admin_server, admin_service, bootstrap, locks, lock_backend, maintenance, scheduler, scheduler_runner, token_service. Operabilidad parcial, pero más completo que lo documentado. |
| **UI Observability** | `ui/components/sovereign/` (30+ componentes), `ui/stores/` (8 stores), `ui/hooks/` (7 hooks) | MSOView, GovernanceRecentPanel, OutcomeStatusPanel, PoliceEvaluationPanel, AuthorityBadge, ConfirmFlowQueuePanel — todos reales. |
| **Chat System** | `chat_core.py`, `chat_db.py`, `chat_renderer.py`, `context_store.py` | Sesiones persistentes, multi-dominio, confirm flow — funcionales. |
| **Identity/Auth** | `identity.py`, `identity_guard.py` | guard enforcement real, fail-closed en identity_guard.py:197. |
| **Police Enforcer (agente-level)** | `police/enforcer.py` | Evalúa tool permissions, environment permissions, capability scope, risk signals. Implementado y testeable. |

---

### 1.2 Parcial (estructura presente, implementación incompleta o no conectada al path principal)

| Componente | Estado real | Brecha |
|---|---|---|
| **Police layer — token-bound gate** | `police/enforcement.py` levanta `NotImplementedError` | Gate token-bound explícitamente no implementado hasta `S-POLICE-CORE-03`. |
| **Police → main HTTP path** | `PoliceEnforcer` solo importado en `agents/permissions.py` → `mso/candidate_orchestration.py` | `candidate_orchestration` NO está importado en `webhook_server.py` ni en `core/orchestrator.py`. La validación police no corre en el path chat principal, solo en el path MSO de candidatos. |
| **OpenClaw Backend** | `openclaw_backend/` tiene: `server.py`, `runtime.py`, `config.py`, `audit_interim.py`, `preflight.py` | Estructura diferente a lo documentado. `models.py` y `protocol.py` no existen. Operabilidad requiere prueba dinámica. |
| **OperatorAuthToken** | `mso/contracts.py:1533` | Existe como clase, pero su ciclo de vida completo (emisión → verificación → revocación) requiere prueba dinámica. |
| **Grants system** | `grants/grant_models.py`, `grants/grant_store.py` | Existe con código real, pero separado de la `authority/` directory (la cartografía los confundía). |
| **Control Plane operability** | 9 archivos presentes | Admin server, scheduler, locks están implementados, pero la prueba dinámica de admin operations no ha sido verificada en esta auditoría. |

---

### 1.3 Conceptual / Solo documental

| Componente | Ubicación | Estado |
|---|---|---|
| **Kill Switch** | `contracts/line-f/kill-switch-assumption.md` | El documento se autoclasifica: `[!WARNING] Historical / Frozen Contract Reference` y `<!-- agent:do-not-treat-as-source-of-truth -->`. Semántica "provisional, sujeta a finalización en Line D". No hay función Python que aplique un kill-switch. |
| **Line F contracts** | `contracts/line-f/` | 5 documentos de especificación de contrato (kill-switch, convergence assumptions, adapter contract, sovereign store interface, closure status). Todos tienen disclaimers de estado histórico/provisional. |
| **Memory system** | `assistant_os/memory/` | Solo contiene `state.py` + archivos de datos en tiempo de ejecución (`chat_sessions.db`, `context_store.json`, `log.ndjson`). No hay `memory.py`, `long_term.py`, ni `short_term.py`. No es un sistema de memoria estructurada. |

---

### 1.4 Afirmado por cartografía pero no existe

| Afirmación | Realidad |
|---|---|
| `sandbox/sandbox.py` | No existe. El directorio sandbox tiene 13 archivos con nombres completamente distintos. |
| `sandbox/docker_executor.py` | No existe. Hay `sandbox/container_backend.py`. |
| `openclaw_backend/models.py` | No existe. |
| `openclaw_backend/protocol.py` | No existe. |
| `control_plane/admin_api.py` | No existe. El archivo real es `control_plane/admin_service.py`. |
| `authority/authority_token.py` | No existe. El directorio `authority/` solo tiene `artifact.py`. |
| `authority/grants_store.py` | No existe en `authority/`. Los grants están en `grants/grant_store.py`. |
| `memory/memory.py`, `memory/long_term.py`, `memory/short_term.py` | Ninguno existe. |
| `system_assistant/assistant.py`, `system_assistant/explainer.py` | No existen. Solo `observer.py` e `interpreter.py`. |
| `agents/base_agent.py`, `agents/work_agent.py`, `agents/fin_agent.py` | No existen. Los agentes reales: `biz_agent.py`, `code_agent.py`, `doc_agent.py`, `host_agent.py`, `job_agent.py`. |
| `components/panels/`, `components/forms/` (UI) | No existen esos subdirectorios. Estructura real: `sovereign/`, `views/`, `cognition/`, `layout/`, `shared/`. |
| Clase `AuthorityToken` | No existe como clase. Ver sección 2. |
| Clase `GovernanceTrace` | No existe como clase. Ver sección 2. |

---

### 1.5 Requiere prueba dinámica

Los siguientes puntos son estructuralmente plausibles pero no verificables solo con lectura estática:

- Que el path chat activa `candidate_orchestration` y por tanto el police gate de agente.
- Que `OperatorAuthToken` ciclo completo (emisión → consume → revocación) funciona en ejecución real.
- Que el sandbox bypass risk en case-insensitive FS (`host_agent.py:230`) no se activa en producción.
- Que los endpoints del Control Plane admin son operables en tiempo de ejecución.
- Que el `governance/` directory genera traces reales en ejecución (no solo directorios vacíos).
- Que el token-bound police gate (`S-POLICE-CORE-03`) no es alcanzable desde ningún path actual.

---

## 2. Corrección de Nombres Conceptuales

| Nombre conceptual anterior | Estado | Nombre real / forma real en repo | Acción documental |
|---|---|---|---|
| `AuthorityToken` | No usar / renombrar | `CapabilityToken` (`capabilities/token_models.py:120`) para tokens de capacidad de agente. `OperatorAuthToken` (`mso/contracts.py:1533`) para operadores externos. | Reemplazar en todos los nodos Obsidian. Nunca referenciar `AuthorityToken` en specs. |
| `GovernanceTrace` | No usar / renombrar | Campo `governance_trace_ref: str` en contratos MSO. Clases: `AdvisoryDecisionTrace`, `DeterministicDecisionTrace`, `TraceChain` en `mso/contracts.py`. | Dividir en tres nodos: TraceChain (estructura), governance_trace_ref (campo de trazabilidad), AdvisoryDecisionTrace (LLM advisory path). |
| `ExecutionMode` | Renombrar (no es clase) | Campo `execution_mode: str` en `mso/contracts.py:475` y `authority/artifact.py:44`. Valores típicos: `"stub"`, `"real"`. | En Obsidian: documentar como campo de contrato, no como tipo independiente. |
| `ApprovalID` | Renombrar (no es clase) | Campo `approval_id: str` en `mso/contracts.py:486`. Validado en `mso/contracts.py:744`. | En Obsidian: documentar como campo de autorización dentro de GovernanceDecision. |
| `RuntimeProfile` | Renombrar (no es clase) | Campo `runtime_profile: str` en `authority/artifact.py:46`. | En Obsidian: parte del AuthorityArtifact. No nodo independiente. |
| `Kill Switch` | Documental histórico | `contracts/line-f/kill-switch-assumption.md` — provisional, frozen, sin implementación Python. | Marcar nodo como "conceptual / Line F". No referenciar como feature operativo. |
| `Memory System` | No usar / renombrar | `assistant_os/memory/` contiene `state.py` + bases de datos de sesión. No es un sistema de memoria estructurada. | Renombrar nodo a "Session State Store". Eliminar referencias a long_term/short_term memory. |
| `OpenClaw Backend` | Parcial / estructura diferente | `assistant_os/openclaw_backend/server.py`, `runtime.py`, `config.py`, `audit_interim.py`, `preflight.py`. Sin `models.py` ni `protocol.py`. | Actualizar nodo con estructura real. Marcar como parcial. |
| `Police token-bound gate` | Parcial / pendiente | `police/enforcement.py` — `NotImplementedError`. Ticket: `S-POLICE-CORE-03`. | Crear nodo separado "Police Gap / S-POLICE-CORE-03" marcado como pendiente de implementación. |

---

## 3. Police Gap Central

### 3.1 Qué sí existe en Police

El módulo `assistant_os/police/` contiene 6 archivos + `__init__.py`:

| Archivo | Contenido | Estado |
|---|---|---|
| `enforcer.py` | `PoliceEnforcer.evaluate()` — chequeo declarativo de tools, environments, capability scope, risk signals. Devuelve `ALLOW`, `DENY` o `REQUIRES_CONFIRMATION`. | Implementado ✓ |
| `models.py` | `PoliceCheckRequest`, `PoliceEvaluation`, `PoliceAuditEvent`, `AgentPermission`, `PoliceViolation`, `RiskLevel`. | Implementado ✓ |
| `gate_models.py` | `PoliceDecision`, `PoliceGateRequest`, `PoliceOutcome`, `CapabilityScope` (importado). | Implementado ✓ |
| `audit.py` | `build_audit_event()` — construye eventos de auditoría para cada evaluación police. | Implementado ✓ |
| `harness.py` | Test harness para gates police. | Implementado ✓ |
| `enforcement.py` | `check(request: PoliceGateRequest) -> PoliceDecision` | **NOT IMPLEMENTED** ✗ |

El `PoliceEnforcer` (agente-level) está conectado al flow de:
```
mso/candidate_orchestration.py 
  → agents/permissions.py (evaluate_agent_permissions) 
  → police/enforcer.py (PoliceEnforcer.evaluate)
```
Este path evalúa permisos de agente antes de crear un `MissionExecutionCandidate`.

### 3.2 Qué no está implementado

```python
# assistant_os/police/enforcement.py

def check(request: PoliceGateRequest) -> PoliceDecision:
    raise NotImplementedError(
        "Token-bound Police gate is not implemented until S-POLICE-CORE-03"
    )
```

Este es el **token-bound Police gate**: el gate que vincularía un `CapabilityToken` o `OperatorAuthToken` válido al chequeo de Police antes de permitir ejecución. Sin este gate, es posible que un request con tokens incorrectos o expirados no sea bloqueado por Police incluso si el enforcer declarativo lo rechazaría.

### 3.3 Qué significa S-POLICE-CORE-03

Es una tarea de sprint explícitamente documentada en el código fuente como prerequisito para completar el Police layer. El número sugiere que es el tercer sprint del Police Core track. Su implementación requeriría:

1. Conectar `PoliceGateRequest` con el token emitido por `capabilities/token_issuer.py`.
2. Verificar el token via `capabilities/token_verifier.py` dentro del gate.
3. Hacer que `enforcement.check()` devuelva `PoliceDecision.DENY` si el token no es válido, en lugar de un error.
4. Conectar este gate al path de ejecución real (actualmente ausente en `webhook_server.py` y `core/orchestrator.py`).

### 3.4 Por qué no se debe afirmar "Police full enforced"

Cuatro razones verificables:

1. **`enforcement.py` levanta `NotImplementedError`** — el gate token-bound no corre.
2. **`PoliceEnforcer` no está en el path HTTP principal** — `webhook_server.py` y `core/orchestrator.py` no importan ni invocan `PoliceEnforcer` directamente.
3. **El path que usa Police** (`mso/candidate_orchestration.py`) no está confirmado como alcanzable desde el chat flow. Si el chat no genera un `MissionExecutionCandidate`, el police gate de agente no se activa.
4. **No hay tests de integración end-to-end** que confirmen que un request rechazable (tool no permitido + context válido) llega a Police y es bloqueado antes de tocar un pipeline.

Lo correcto es afirmar: **"Police declarativo de agente implementado; Police token-bound pendiente (S-POLICE-CORE-03); conexión al path principal requiere verificación dinámica."**

### 3.5 Pruebas dinámicas que hacen falta

Antes de afirmar Police como "enforced", se necesita verificar en ejecución real:

1. **Test de bloqueo end-to-end:** enviar un request de chat que solicite un tool no permitido → confirmar que el response es DENY (no ejecución parcial ni error 500).
2. **Test de alcanzabilidad de candidate_orchestration:** loggear si `mso/candidate_orchestration.py` se invoca durante un request chat normal.
3. **Test de `enforcement.check()` no alcanzable:** confirmar que ningún path productivo llama a `police/enforcement.py` actualmente (para verificar que el `NotImplementedError` no mata requests en silencio).
4. **Test de token expirado:** emitir un token expirado y confirmar que el sistema bloquea antes de ejecutar, sin depender del gate no implementado.

---

## 4. Mapa Corregido para Obsidian

| Nodo | Estado | Ruta(s) reales | Nota |
|---|---|---|---|
| MSO Core | Implementado | `assistant_os/mso/` (28 archivos) | Governance engine, policy engine, candidate orchestration, delegation — todos con código real. |
| Governance Engine | Implementado | `mso/governance_engine.py` | Produce GovernanceDecision con approval_id, execution_mode, governance_ref. |
| Policy Engine (MSO) | Implementado | `mso/policy_engine.py`, `policy/policy_engine.py`, `core/policy.py` | Tres implementaciones de policy en el repo. Relación entre ellas requiere clarificación. |
| PolicyDecision | Implementado | `contracts.py:599` (TypedDict) | Activo en flujo de orquestación. Puede bloquear ejecución. |
| Candidate Orchestration | Implementado | `mso/candidate_orchestration.py` | Orquesta Police check → MissionExecutionCandidate. |
| MissionExecutionCandidate | Implementado | `missions/execution_candidate.py` | Candidato de ejecución con police evaluation embebida. |
| Domain Pipelines (×5) | Implementado | `pipelines/code_pipeline.py`, `work_pipeline.py`, `fin_pipeline.py`, `host_pipeline.py`, `machine_operator_pipeline.py` | Todos reales. |
| Runner System | Implementado | `runners/runner_service.py` + 12 archivos | apply_engine, validation_engine, workspace_manager, authority_consumption — reales. |
| Sandbox / AuthorizedPlan | Implementado | `sandbox/` (13 archivos), `sandbox/authorized_plan.py` | authorized_plan, revocation, execution_backend, output_policy — todos reales. |
| CapabilityToken | Implementado | `capabilities/token_models.py:120`, `token_issuer.py`, `token_verifier.py`, `capability_gate.py` | Token lifecycle completo (issuer + verifier + gate). Fail-closed. |
| CapabilityScope | Implementado | `mso/contracts.py:1714` | Usada en police models, runners, pipelines. |
| OperatorAuthToken | Implementado | `mso/contracts.py:1533` | Token de autenticación de operadores externos (MACHINE_OPERATOR). |
| Police Enforcer (agente-level) | Implementado | `police/enforcer.py`, `police/models.py` | Evaluación declarativa de tool/environment/capability. ALLOW / DENY / REQUIRES_CONFIRMATION. |
| Police Gate (token-bound) | Parcial — pendiente S-POLICE-CORE-03 | `police/enforcement.py` | Levanta NotImplementedError. No conectado a ningún path productivo. |
| Police Audit | Implementado | `police/audit.py`, `mso/audit_wiring.py` | build_audit_event() real. |
| Fail-Closed Pattern | Implementado | `capabilities/capability_gate.py`, `token_verifier.py`, `cognition/router.py`, `identity_guard.py`, `machine_operator_policy.py` | Patrón documentado e implementado en ≥5 módulos. |
| AuthorizedPlan | Implementado | `sandbox/authorized_plan.py:34` | Contrato real. Requerido por runner. |
| TraceChain / decision traces | Implementado | `mso/contracts.py` (TraceChain, AdvisoryDecisionTrace, DeterministicDecisionTrace) | Clases reales. El campo `governance_trace_ref: str` las conecta. |
| Audit Infrastructure | Implementado | `audit/sink.py`, `audit/jsonl_store.py`, `audit/stores.py`, `police/audit.py`, `sandbox/audit.py` | JSONL store, sink, event building — todo real. |
| Grants System | Implementado | `grants/grant_models.py`, `grants/grant_store.py` | Separado de `authority/`. Completamente diferente a lo descrito en cartografía. |
| Authority Artifact | Implementado | `authority/artifact.py` | Contiene campos: execution_mode, runtime_profile, approval_id, governance_ref. No confundir con "AuthorityToken". |
| Cognition / LLM routing | Implementado | `cognition/providers.py`, `cognition/router.py`, `cognition/classifier.py` | Router fail-closed real. Detecta intentos de bypass de policy en NL. |
| Identity / Auth | Implementado | `identity.py`, `identity_guard.py` | Fail-closed en identity_guard.py. |
| Control Plane | Parcial | `control_plane/` (9 archivos) | admin_server, scheduler, locks, maintenance — estructuralmente presente. Operabilidad requiere prueba dinámica. |
| OpenClaw Backend | Parcial | `openclaw_backend/server.py`, `runtime.py`, `config.py`, `audit_interim.py`, `preflight.py` | Estructura diferente a cartografía. models.py y protocol.py no existen. |
| UI Observability | Implementado | `ui/components/sovereign/` (30+ componentes), `ui/stores/` (8), `ui/hooks/` (7) | Governance panels, police eval panel, authority badge, confirm flow queue — reales. |
| Kill Switch | Documental histórico | `contracts/line-f/kill-switch-assumption.md` | Self-classified as frozen/provisional. Sin implementación Python. |
| Session State Store | Implementado | `memory/state.py`, `memory/context_store.json`, `memory/chat_sessions.db` | No es "Memory System". Es un store de estado de sesión. |
| AuthorityToken | No usar / renombrar | — | Clase no existente. Usar CapabilityToken o OperatorAuthToken según contexto. |
| GovernanceTrace | No usar / renombrar | — | Clase no existente. Usar governance_trace_ref (campo) + TraceChain/AdvisoryDecisionTrace (clases). |
| Memory System (long/short term) | No usar / renombrar | — | Los archivos memory.py, long_term.py, short_term.py no existen. |

---

## 5. Próximo Sprint Recomendado

### Sprint 18.5 — Reality Alignment & Police Gap Mapping

---

#### Objetivo

Eliminar la deuda documental acumulada entre la cartografía y el repo real, y trazar con precisión el alcance y riesgos del Police gap antes de que Sprint 19 asuma un modelo de enforcement que no está completo.

Este sprint **no implementa**. Solo alinea, verifica dinámicamente y documenta.

---

#### Tareas

**T1 — Validación dinámica del path Police**
- Instrumentar o loggear si `mso/candidate_orchestration.py` se invoca durante un request de chat normal.
- Confirmar que `police/enforcement.py` (`NotImplementedError`) no es alcanzable desde ningún path productivo actual.
- Documentar el resultado: ¿el Police enforcer de agente está en el path crítico del chat flow?

**T2 — Validación dinámica de token lifecycle**
- Ejecutar el flujo: emitir `CapabilityToken` → verificar → consumir → verificar post-consume.
- Confirmar que el token verifier (`token_verifier.py`) devuelve `False` en token expirado/consumido, sin excepción.
- Documentar si hay path productivo que llame `token_issuer` → `token_verifier` en secuencia real.

**T3 — Clarificación de tres policy engines**
- El repo tiene tres implementaciones de policy: `assistant_os/policy_engine.py`, `policy/policy_engine.py`, `core/policy.py`.
- Mapear: ¿cuál está en el path activo? ¿cuáles son legacy o duplicadas?
- Documentar la autoridad única.

**T4 — Corrección documental en CARTOGRAFIA_REPO_COMPLETA.md**
- Reemplazar nombres inexistentes (`AuthorityToken`, `GovernanceTrace`, etc.) con los correctos.
- Corregir rutas de archivo que no existen (sandbox, openclaw_backend, authority/, memory/).
- Marcar Kill Switch como documental histórico.
- Actualizar conteo de archivos (mso: 28, no 31; police: 6+1, no 7).

**T5 — Actualizar Obsidian con nodos corregidos**
- Renombrar nodos según tabla de la Sección 4.
- Agregar nodo: `Police Gap / S-POLICE-CORE-03` con estado pendiente.
- Agregar nodo: `Authority Artifact` (separado de AuthorityToken).
- Separar `TraceChain` de `GovernanceTrace`.
- Marcar `Kill Switch` como documental histórico.

**T6 — Inventario de dead code en webhook_server.py**
- Confirmar que `_execute_work_query_from_plan` y `_execute_work_update_preview` son efectivamente unreachable (no importados, no testeados).
- Documentar si deben eliminarse o mantenerse como guardrails activos.

---

#### Qué no debe tocar Sprint 18.5

- No implementar `S-POLICE-CORE-03`.
- No refactorizar ningún módulo.
- No modificar MSO ni Policy.
- No agregar nuevos endpoints.
- No tocar pipelines.
- No proponer rediseño de contratos.

Si durante T1-T6 se detecta un bypass estructural nuevo: **documentar como hallazgo crítico, no parchear**.

---

#### Criterios de Cierre

| Criterio | Verificación |
|---|---|
| Se sabe si el police enforcer de agente está en el path chat activo | Resultado documentado (sí/no + evidencia) |
| Se sabe si `police/enforcement.py` es alcanzable | Resultado documentado (alcanzable/unreachable) |
| Los tres policy engines están clarificados | Un único documento indica cuál está activo |
| CARTOGRAFIA_REPO_COMPLETA.md tiene rutas y nombres corregidos | Diff revisado y aprobado |
| Obsidian refleja nodos de la Sección 4 con estados correctos | Vault auditado |
| No se introdujo ningún cambio funcional en el repo | `git diff` limpio o solo archivos de documentación |

---

#### Riesgos

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| Descubrir que el Police enforcer no está en ningún path productivo | Media | Alto | Documentar como hallazgo crítico. No parchear en este sprint. |
| Encontrar un cuarto policy engine no mapeado | Baja | Medio | Agregar a la lista de T3 y documentar. |
| Confundir worktree con main repo en validaciones dinámicas | Media | Bajo | Siempre ejecutar contra `C:/Users/Jorge/Assistant_OS_Labs/` directamente, no contra el worktree. |
| Descubrir que kill-switch requiere diseño antes de Sprint 19 | Baja | Alto | Si se confirma, elevar como bloqueante de Sprint 19. |

---

#### Herramientas Recomendadas

- `grep -rn` / `Grep` — para rastrear importaciones y referencias cruzadas.
- `wc -l` — para contar líneas y verificar claims de tamaño.
- Logs en ejecución real del webhook — para T1 y T2 (requiere entorno activo).
- `pytest tests/test_police_enforcer.py tests/test_police_gate_contract.py -v` — para verificar el comportamiento declarado de Police en tests existentes.
- `pytest tests/test_sprint12_token.py tests/test_token_lifecycle.py -v` — para verificar token lifecycle.

---

*Documento generado como fuente de verdad corregida. No reemplaza el código.*  
*Fuente primaria siempre es el código en `assistant_os/`.*
