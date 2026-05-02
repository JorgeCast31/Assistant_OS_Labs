# Sovereign Observability Checkpoint

## Purpose

This document freezes the meaning of the current observability surfaces in
AssistantOS. It records what each surface shows, what it does not show, and
the semantic boundaries that must be preserved across future work.

It is a reference, not a specification. Nothing here authorizes code changes.
Surfaces may evolve, but their semantic boundaries may not be relaxed without
an explicit architectural decision.

---

## Current Surfaces

### 1. ReadinessPanel

| Property | Value |
|---|---|
| Source | `GET /system/runtime-state` (webhook :8787) |
| Ephemeral | Yes — polled on load, not persisted |
| Read-only | Yes |
| Implies authority | No |
| Implies MSO active | No |
| Implies system healthy | No |

**What it shows:** Operational mode and recent system events from the MSO
runtime state snapshot. Rendered as a status band in the System view.

**What it does NOT show:** Whether MSO has processed any request. Whether any
agent is ready to execute. Whether the system is safe to use. Whether recent
events indicate a problem or normal operation.

---

### 2. Governance Status Band

| Property | Value |
|---|---|
| Source | `GET /mso/governance/status` (webhook :8787, proxied via Next.js `/api/mso/governance/status`) |
| Ephemeral | Yes — marked `ephemeral: true` in response |
| Read-only | Yes |
| Implies authority | No |
| Implies MSO active | No |
| Implies system healthy | No |

**What it shows:** Current operational mode (NORMAL / RESTRICTED / DEGRADED /
FROZEN), its derivation source (derived from anomaly signals, or manual
override), hardened domain count, active revocation count, and recent anomaly
count. These are runtime governance posture counts, not health indicators.

**What it does NOT show:** Whether any request succeeded. Whether MSO is
running, loaded, or reachable beyond this read. Whether the governance engine
has made any recent decisions. Whether counts of zero mean nothing happened or
that nothing needed governance attention.

**Mode color semantics:** FROZEN = error color, DEGRADED = warning color,
NORMAL = secondary text, UNKNOWN = muted text. Colors communicate operational
posture only — not health or activity.

---

### 3. Recent Governance Panel

| Property | Value |
|---|---|
| Source | `GET /mso/governance/recent?limit=20` (webhook :8787, proxied via Next.js `/api/mso/governance/recent`) |
| Ephemeral | Yes — in-memory ring buffer, cleared on backend restart |
| Read-only | Yes |
| Implies authority | No |
| Implies MSO active | No |
| Implies system healthy | No |

**What it shows:** The most recent governance decisions recorded in the
in-process ring buffer since the backend last started. Each entry includes
`governance_ref`, `action` (ALLOW / BLOCK / REQUIRE_CONFIRMATION / DEGRADE),
`target_domain`, `target_action`, `risk_level`, `operational_mode` at
decision time, `effective_execution_mode`, and the primary reason.

**What it does NOT show:** Historical decisions from before the current backend
process started. Decisions from previous sessions. A persistent audit log.
Whether displayed decisions caused a user-visible error. Whether absence of
entries means no decisions were made (it may mean the buffer was not yet
populated, or the backend restarted).

---

### 4. System Assistant State

| Property | Value |
|---|---|
| Source | `GET /system-assistant/state` (webhook :8787, proxied via Next.js `/api/system-assistant/state`) |
| Ephemeral | Yes — snapshot generated on each request |
| Read-only | Yes |
| Implies authority | No |
| Implies MSO active | No |
| Implies system healthy | No |

**What it shows:** A read-only snapshot (`snapshot`) and non-authoritative
interpretation (`interpretation`) of observable system state. The snapshot
includes: operational mode override, registered agents (count and metadata),
registered capabilities, tasks summary, governance status summary, and recent
governance decisions (up to 3). The interpretation includes a summary sentence,
a list of observation strings, and pass-through warnings.

**Summary sentence wording:**

- Manual override present: `"… manual operational override FROZEN, …"`
- No override, governance summary present: `"… effective governance mode NORMAL (source derived), …"`
- No override, no governance summary: `"… mode unknown (no override set), …"`

**What it does NOT show:** Whether any agent is healthy. Whether the system
will accept the next request. Whether governance decisions were correct.
Whether `execution_status=None` means anything about future executions —
it is always `null` because the System Assistant never executes.

**Interpreter invariants (never violated):**
- `narrative: true` in all outputs
- `execution_status: null` in all outputs
- Does not call `observe_system()` automatically
- Does not call pipelines, agents, or Kernel
- Does not import from `governance_surface`
- Pure function: identical inputs → identical outputs

---

### 5. Cognition Provider Readiness

| Property | Value |
|---|---|
| Source | `GET /cognition/providers` and `GET /cognition/providers/health` (webhook :8787) |
| Ephemeral | Yes — health checks are point-in-time |
| Read-only | Yes |
| Implies authority | No |
| Implies MSO active | No |
| Implies execution approved | No |

**What it shows:** Runtime status of registered cognitive providers (e.g.,
local Llama instance). Status values: `online`, `offline`, `degraded`,
`disabled`. Includes last health check timestamp, latency, and available tasks.
When local Llama reports `1/1 online`, it means the provider responded to a
health probe.

**What it does NOT show:** Whether the provider is authorized to handle the
next request. Whether the cognitive restriction level permits LLM use. Whether
`online` means any request will be routed to this provider — routing policy
is determined by MSO governance, not provider status alone.

---

## Semantic Boundaries

These boundaries are invariants. They must not be weakened by UI copy, log
messages, observation strings, summary sentences, or documentation.

### Operational mode is not MSO ACTIVE

`operational_mode = "NORMAL"` means the governance engine computed NORMAL from
the current anomaly signal set. It does not mean MSO is running, healthy,
processing requests, or that any agent is available.

### Governance Status is runtime operational posture, not system health

The governance status band shows the current governance posture derived from
anomaly signals and operator overrides. A posture of NORMAL does not mean the
system is functioning correctly. A posture of FROZEN does not mean the system
has failed — it may mean the operator has intentionally restricted operations.

### Recent Governance is ephemeral runtime decision history, not persistent audit

The recent governance ring buffer holds decisions from the current backend
process only. It is not an audit log. It is not persistent. It does not
represent a complete record of governance activity. Consumers must not treat
it as authoritative history.

### Empty recent governance does not mean MSO is inactive

An empty recent governance list means no decisions have been recorded in the
current in-memory buffer since the backend started. This is the normal state
of a freshly started backend before any request triggers governance evaluation.
It does not mean MSO has not been initialized, is not running, or has made no
decisions.

### BLOCK decision is not a failure

A `BLOCK` governance decision means the governance engine evaluated a request
and determined it should not proceed under current policy and mode. This is the
governance engine working correctly. It is not an error, a crash, or a
malfunction. In a system with restrictive domains (e.g., ENERGY/COMMAND),
BLOCK on routine requests is expected.

### System Assistant is observer and interpreter only, not executor

The System Assistant observes existing state and interprets it as
non-authoritative narrative. It does not execute requests, approve actions,
trigger pipelines, call agents, or produce governance verdicts. The
`execution_status: null` field in every interpretation output is a structural
invariant, not a coincidence.

### Cognition online means provider reachable, not authority

A cognitive provider reporting `online` means it responded to a health probe.
It does not mean requests are authorized to use it, that the cognitive
restriction level permits LLM participation, or that the provider is integrated
into the current request path.

---

## Runtime Validation Example

The following safe trigger produces a governance decision visible across all
observability surfaces. No secrets, tokens, or operator credentials are
included in this example.

### Trigger

```
POST /chat/process
Content-Type: application/json
X-Assistant-Token: <operator token>

{"text": "hola"}
```

### Expected governance outcome

The ENERGY domain handles generic command-style text. The governance engine
evaluates the request under current policy and mode, producing:

```json
{
  "action": "BLOCK",
  "target_domain": "ENERGY",
  "target_action": "COMMAND",
  "effective_execution_mode": "blocked",
  "risk_level": "high",
  "reason": "generic command/capability denied"
}
```

### Where it appears

| Surface | What you see |
|---|---|
| `/chat/process` response | `execution_mode: "blocked"`, `mso_decided: true` |
| `/mso/governance/recent` | Entry with `action: "BLOCK"`, `target_domain: "ENERGY"` |
| Recent Governance Panel | Decision row visible with BLOCK badge |
| `/system-assistant/state` `interpretation.observations` | `"Recent governance: 1 decision(s) shown; latest BLOCK on ENERGY/COMMAND, execution mode blocked."` |
| System Assistant summary | `"effective governance mode NORMAL (source derived), all sources available."` (if no manual override is set) |

### What this does NOT prove

- That MSO is "working correctly" in a general sense
- That future requests will be blocked or allowed
- That the system is healthy
- That the BLOCK was an error

---

## Known Limitations

**1. Recent governance is in-memory and ephemeral.**
Restarting the backend clears all recorded decisions. There is no persistent
governance decision store. The panel and System Assistant observations reflect
only the current process lifetime.

**2. System Assistant frontend renders observations as generic text.**
The `interpretation.observations` list is rendered as a plain string list in
`SystemChatView.tsx`. Governance observation strings appear as text, not as
structured cards, badges, or tables. This is a deliberate first-phase choice —
no structured governance UI exists in the System Assistant panel yet.

**3. operational_mode override field may be null while effective mode is NORMAL.**
`snapshot.operational_mode` comes from `get_operational_mode_override()` and
is `null` when no manual override is set. The actual effective governance mode
(NORMAL, RESTRICTED, DEGRADED) is derived from anomaly signals and available
via `governance_status_summary.operational_mode`. The summary wording reflects
this distinction: `"mode unknown (no override set)"` vs `"effective governance
mode NORMAL (source derived)"`.

**4. No persistent audit-grade governance explorer.**
There is no UI or endpoint that provides a complete, persistent, queryable
record of governance decisions across backend restarts. The recent governance
panel and ring buffer are operational visibility tools, not audit infrastructure.

**5. No execution controls in UI.**
The UI is entirely read-only. There are no buttons, forms, or actions that
trigger execution, approve governance decisions, or modify operational mode
through the frontend. All operator actions require direct API interaction.

---

## Next Recommended Work

The following areas are candidates for future work if the operational focus
shifts. None are required to maintain current system integrity.

**System Assistant structured governance UI**
The System Assistant currently renders governance observations as plain text.
A structured card or panel inside the System Assistant view (showing governance
mode, recent decisions as a compact table, and count badges) would improve
operator comprehension. This requires frontend-only changes to
`SystemChatView.tsx` and `SystemAssistantSnapshot` type additions in
`ui/lib/api.ts`.

**Persistent audit store exploration**
A persistent, queryable governance decision store would enable audit-grade
review across sessions and backend restarts. This requires backend design work:
storage format, query API, retention policy, and indexing strategy.

**TraceChain viewer discovery**
`trace_aggregator.py` maintains `TraceChain` records linking governance
decisions to their originating requests. A viewer for this data would provide
end-to-end request traceability. Discovery needed to assess feasibility and
query surface.

**Code API readiness if operational focus shifts**
The Code execution API (`/api/code/executions`) and execution review workflow
are present but not the current operational focus. If agent-executed code
changes become a priority, readiness review of the runner/validator pipeline
and review UI would be appropriate.
