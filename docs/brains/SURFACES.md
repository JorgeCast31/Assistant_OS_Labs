> [!WARNING]
> **Historical / Conceptual Specification**
> This document is historical/conceptual reference material. It is not the current source of truth for runtime behavior.
> Current source of truth: code in `assistant_os/` and `ui/`, plus `README.md`, `docs/RUNTIME_TOPOLOGY.md`, and `docs/CHAT.md`.

<!-- agent:do-not-treat-as-source-of-truth -->

---

# SURFACES

## 1. Definition

Surfaces are the user-facing interaction boundaries through which operators and users communicate with the system. Each surface has a defined purpose, a specific UX contract, and explicit constraints on what it can and cannot trigger. Surfaces influence presentation and routing context. Surfaces do not hold authority and do not modify execution rules.

---

## 2. Surfaces

### Chat Surface

**Purpose:** Multi-turn conversational interface for submitting intents and receiving structured responses.

**Can trigger:**
- Intent submission to the Kernel via orchestrator
- Confirmation signals for pending execution plans
- Surface-matched informational query intercepts (via `surface_behavior.py`)

**Cannot trigger:**
- Direct pipeline invocation
- Capability grant creation
- Operator state modification
- Governance verdicts

**Entry point:** `assistant_os/webhook_server.py` (port 8787)

---

### System Chat

**Purpose:** Conversational interface for querying system state. Responses are observational only.

**Can trigger:**
- Read queries against operability endpoints
- `surface_behavior.py` pattern intercepts for status questions

**Cannot trigger:**
- Any execution pipeline
- Any state-modifying operation
- Any authority action

**Entry point:** `ui/` → `/api/system` proxy → `operability.py`

---

### MSO Direct (Sovereign Surface)

**Purpose:** Direct operator console for interacting with the Machine Sovereign Operator. Provides inspection bundles, cycle history, and operator control actions.

**Can trigger:**
- Sovereign intent submission to MSO runtime
- Operator acknowledgement and override actions (via `operator_actions.py`)
- Governance verdict inspection

**Cannot trigger:**
- Direct agent invocation
- Capability token creation outside MSO authority flow
- Policy modification

**Entry point:** `ui/components/sovereign/` → `ui/app/sovereign/` → MSO runtime

---

### Code Execution Surface

**Purpose:** Specialized view for CODE domain — proposal review, test results, and execution output inspection.

**Can trigger:**
- Review confirmation signals for pending CODE execution plans

**Cannot trigger:**
- Direct code execution outside the CODE pipeline
- Agent invocation bypassing the Kernel
- Execution without an authorized plan

**Entry point:** `ui/components/views/` → `assistant_os/api/code_api.py` (port 8000)

---

### Control Plane (Operator Admin Surface)

**Purpose:** Administrative surface for operator identity management, capability grants, temporal restrictions, and system locks.

**Can trigger:**
- Capability grant creation (via MSO authority flow)
- Temporal restriction activation
- Distributed lock management
- Bootstrap and maintenance operations

**Cannot trigger:**
- Chat or conversational execution
- Pipeline invocation outside governance flow
- Identity bypass

**Entry point:** `assistant_os/control_plane/admin_server.py` (port 8788)

---

### Operability Endpoints

**Purpose:** Read-only API for system observability. Used by System Assistant and monitoring tooling.

**Can trigger:**
- Read of MSO state, agent registry, and capability inventory

**Cannot trigger:**
- Any write, modification, or execution

**Entry point:** `assistant_os/operability.py` — `/mso/state`, `/agents/registry`, `/system/capabilities`

---

## 3. Invariants

- Surfaces must NEVER create authority
- Surfaces must NEVER invoke agents or pipelines directly
- Surface context influences UX routing but must NEVER override policy or governance decisions
- Every execution-triggering surface action must pass through the Kernel and Police before reaching a pipeline
- The Control Plane surface is the ONLY surface that can initiate capability grant flows — and only through MSO
