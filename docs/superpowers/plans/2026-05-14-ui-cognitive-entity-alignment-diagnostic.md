# UI Entity / Cognitive Chain Alignment Diagnostic + Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the alignment between every visible UI entity and its real backend/cognitive/operational contract before opening Advanced Mode.

**Architecture:** The system runs two separate shells: `AppShell` (Main Chat, `/`) and `SovereignShell` (`/sovereign`). Each surface sends to the same `/api/chat/process` proxy but declares a different `surface` field, producing completely separate backend code paths. The MSO cognitive chain is fully wired (Anthropic Haiku + Vault + Session History). The primary structural debt is the absence of a formal UI Cognitive Entity Registry that makes these contracts machine-readable and self-describing.

**Tech Stack:** Next.js 14, Zustand, Python webhook server, Anthropic SDK (Haiku), Obsidian vault, SQLite sessions, custom Police/Policy/Pipeline governance.

---

## 1. Executive Finding

**Classification: OPERABLE WITH STRUCTURAL DEBTS**

The system is architecturally honest: every UI entity that claims to be read-only is genuinely read-only. No panel invents execution authority. The MSO cognitive chain is end-to-end wired. Provenance fields (response_source, provider_used, model_used, cognitive_trace, vault_packs_consulted, history_*) are surfaced in the raw drawer and per-message badges.

**Direct answers:**

- **Is MSO Console backed by the full Economic Cognition chain?** YES. `mso_direct` surface goes through `build_mso_grounding_context()` + `_get_vault_context()` + `_get_session_history()` + `call_mso_chat_provider()` → Anthropic Haiku (claude-haiku-4-5-20251001). Fallback chain to deterministic narrative on provider failure. Full cognitive trace returned.

- **Is Main Chat distinct from MSO?** YES, at the backend level. Main Chat declares `surface: 'assistant_chat'` → `get_surface_behavior_response()` with router/orchestrator path for WORK/CODE/FIN. MSO Console declares `surface: 'mso_direct'` → cognitive generation path. Visually they live in separate shells (`/` vs `/sovereign`). They share the same backend endpoint but diverge immediately on the `surface` field.

- **Is Provider Selector only display or truly selectable?** **Display-only — explicitly and correctly.** The component is labeled `v0 · read-only`, options are `cursor-not-allowed`, with note: "Change `MSO_SEAT_PROVIDER` and restart backend." This is honest.

- **Are Mission Control / queues / prepared actions connected to real backend state?** YES. All four polling hooks (`useSeatProviderPolling`, `usePreparedActionsPolling`, `useConfirmPendingPolling`, `useAuthorityStatusPolling`) hit real backend endpoints. The data shown is live. However, there are **no action surfaces** — everything is observability only.

- **Does UI expose provenance/trace honestly?** YES for MSO Console: per-message badges show response_source, provider/model, fallback, latency, execution_status, governance. Raw drawer shows full backend response. **For Main Chat:** NO — only execution_status and governance_trace are shown; no provider_used, no response_source, no cognitive_trace.

- **Which UI entities are decorative or weakly wired?**
  - `SovereignStatusView` — Executive Authority Chain rows are **hardcoded static text**, not from backend.
  - `AgentPanel` — shows live registry data but no agent is operationally interactive; every agent beyond a list view returns "console not yet available."
  - `AuthorityMatrixPanel` — live but read-only; no interpretation layer.
  - `MSOProviderSelector` — live polling but no selector interaction. The `PROVIDER_OPTIONS` list is hardcoded in the frontend, not driven by backend.
  - Main Chat — no provider/source provenance visible to user.

---

## 2. Current Repository State

| Field | Value |
|-------|-------|
| Branch | `claude/hopeful-lehmann-7015cc` |
| HEAD | `26559e7` — Merge PR #193 (SPRINT-ALPHA-04.9 Identity Routing Refinement) |
| git status | Clean — nothing to commit, working tree clean |
| Aligned with main | Yes — `up to date with 'origin/main'` |
| Phases 1–4.9 present | Yes (verified by commit history) |
| Surprising files | None |

---

## 3. UI Entity Inventory

| UI Entity | File(s) | User-facing purpose | Backend endpoint/API | Surface | Cognitive/operational actor | Status | Notes |
|-----------|---------|--------------------|--------------------|---------|----------------------------|--------|-------|
| Main Chat | `ui/components/views/chat-view.tsx` | Conversational interface for WORK/CODE/FIN/HOST tasks | `/api/chat/process` → Python `/chat/process` | `assistant_chat` | `get_surface_behavior_response()` + router + orchestrator | real | Full session management, retry, confirm flow |
| MSO Console | `ui/components/sovereign/MSOView.tsx` + `MSOComposer.tsx` | Sovereign cognitive conversational surface | `/api/chat/process` → Python `/chat/process` | `mso_direct` | `call_mso_chat_provider()` → Anthropic Haiku | real | Full cognitive chain: grounding + vault + history + Anthropic |
| MSO Transcript | `ui/components/sovereign/MSOChatTranscript.tsx` | Renders MSO message history with provenance badges | in-memory via `mso-chat-store` | n/a | Zustand store | real | Shows response_source, provider, fallback, latency, execution_status, governance |
| MSO Raw Drawer | `ui/components/sovereign/MSOMessageRawDrawer.tsx` | Full backend provenance inspector per message | in-memory via `mso-chat-store` | n/a | Passthrough of `raw_response` | real | Exposes complete backend response JSON |
| MSO Provider Selector | `ui/components/sovereign/MSOProviderSelector.tsx` | Shows seated cognitive provider | `/api/mso/seat/provider` → Python `/mso/seat/provider` | n/a | `seat_model_provider_registry.get_seated_provider()` | read-only | Explicitly labeled v0 read-only; options hardcoded in frontend |
| System View (Sovereign) | `ui/components/sovereign/SystemChatView.tsx` | Runtime posture + system-assistant interpretation | `/api/system-assistant/state` | n/a | `build_system_assistant_interpretation()` | partial | Read-only status dashboard, NOT a chat; no composer |
| Sovereign Status | `ui/components/sovereign/SovereignStatusView.tsx` | Authority chain + queue + event log | `/api/system/runtime-state` (via `useUIStore`) + ConfirmFlowQueuePanel + OutcomeStatusPanel | n/a | Multiple polled endpoints | partial | Authority chain rows are **hardcoded static** — not from backend |
| Mission Control | `ui/components/sovereign/MissionControlView.tsx` | Read-only situation room: MSO seat + queue + authority | `/api/mso/seat/provider`, `/api/mso/prepared-actions/pending`, `/api/confirm/pending`, `/api/mso/authority/status` | n/a | Multiple backend readers | real | Correct read-only; "next safe step" is dynamically computed |
| Confirm Flow Queue | `ui/components/sovereign/ConfirmFlowQueuePanel.tsx` | Observability of confirm-pending + prepared actions | `/api/confirm/pending`, `/api/mso/prepared-actions/pending` | n/a | Polling stores | real | Observability only; no action buttons |
| Prepared Actions | embedded in `ConfirmFlowQueuePanel.tsx` + `PreparedActionDetailPanel.tsx` | Lists prepared actions for manual review | `/api/mso/prepared-actions/pending` | n/a | `prepared_action_queue.list_pending_confirmable_action_dicts()` | real | Shows authority timeline (11 stages); read-only |
| Authority Matrix | `ui/components/sovereign/AuthorityMatrixPanel.tsx` | Capability posture view (allow/deny/confirm-only counts) | `/api/mso/authority/status` | n/a | `authority_status.build_authority_status_response()` | real | Live polling; labeled "posture, not execution permission" |
| Agent Registry | `ui/components/sovereign/AgentPanel.tsx` | Shows registered agents from backend | `/api/agents/registry` | n/a | `build_agents_registry_response()` | partial | List is live; no agent has an operational console |
| System Capabilities | polled via `useReadinessSourcePolling` → `useSovereignStore` | Agent registry + capabilities status metadata | `/api/agents/registry`, `/api/system/capabilities` | n/a | `build_system_capabilities_response()` | real | Only for status metadata; no visual rendering beyond agent list |
| Outcome Status | `ui/components/sovereign/OutcomeStatusPanel.tsx` | Shows last execution outcome | `/api/mso/outcome/status` | n/a | `build_outcome_status_response()` | real | Live polling |
| Governance Status | `ui/components/sovereign/GovernanceStatusBand.tsx` + `GovernanceRecentPanel.tsx` | Governance decisions band + recent history | `/api/mso/governance/status`, `/api/mso/governance/recent` | n/a | Governance store | real | Read-only |
| MSO Invariant Strip | `ui/components/sovereign/MSOInvariantStrip.tsx` | Always-visible invariant banner in MSO Console header | n/a | n/a | Static | display-only | Correct — this should be static |
| Execution Not Open Panel | `ui/components/sovereign/ExecutionNotOpenPanel.tsx` | Confirms execution path closed | n/a | n/a | Static | display-only | Correct |
| Readiness Panel | `ui/components/sovereign/ReadinessPanel.tsx` | Source readiness status | via `useSovereignStore` | n/a | Polling metadata | real | |
| Security View | `ui/components/sovereign/SecurityView.tsx` | Security posture | unknown | n/a | unknown | unknown | Not inspected in depth |
| Police panels | `ui/components/sovereign/police/*` | Police gate status | static or polling | n/a | Police enforcement layer | partial | Not inspected in depth |

---

## 4. Cognitive Chain Map Per Entity

### 4A. Main Chat (`assistant_chat`)

```
User types in ChatComposer
→ ChatView.coreDispatch()
→ sendChatMessage({ surface: 'assistant_chat', text, session_id, session_context })  [lib/api.ts]
→ fetch('/api/chat/process', POST)  [Next.js proxy route]
→ Python /chat/process  [webhook_server.py]
→ get_surface_behavior_response(surface='assistant_chat', text, ...)  [surface_behavior.py]
   ├─ conversational patterns → deterministic response (no LLM, no vault)
   ├─ router.route_text() → intent classification
   │   ├─ executable_intent + should_pass_to_kernel → return None → orchestrator
   │   ├─ plan_request → build_plan_request_authority_data() → enqueue prepared action
   │   └─ needs_context → clarification response
   └─ MSO narrative runtime for unknown_ambiguous operational queries
→ If None → orchestrator path → domain handler (WORK/CODE/FIN/HOST)
← Response: { message, domain, intent, execution_status, governance_trace, plan, ui_actions, session }

Metadata added: execution_status, governance_trace, decision_source, confidence_score
LLM used: Yes (for CODE review, FIN planning, WORK creation — orchestrator-driven)
Vault used: No (only in mso_direct path)
Session history used: Yes (SQLite-backed chat sessions)
Execution possible: Yes (WORK/FIN/CODE via orchestrator + Police gate)
Confirmation required: Yes for RISK_MEDIUM/HIGH
UI provenance shown: execution_status badge, governance badge, decision_source — NO provider/model/response_source
```

### 4B. MSO Console (`mso_direct`)

```
User types in MSOComposer
→ sendSovereignMessage(text, 'mso_direct', sessionId)  [lib/sovereign/api.ts]
→ fetch('/api/chat/process', POST, { surface: 'mso_direct', text, session_id })  [Next.js proxy]
→ Python /chat/process  [webhook_server.py]
→ get_surface_behavior_response(surface='mso_direct', text, session_id, ...)  [surface_behavior.py]
   ├─ executive prefixes → return None → orchestrator (currently: these pass through but MSO doesn't execute)
   ├─ _MSO_DIRECT_CONVERSATIONAL → deterministic narrative response
   ├─ is_mso_narrative_intent() → narrative_runtime.build_narrative_context_message()
   └─ COGNITIVE PATH (Sprint 4):
       ├─ build_mso_grounding_context()  [mso/narrative_runtime.py]
       │   → operational_mode, agents, perception frame version, etc.
       ├─ _get_vault_context(query=text)  [mso/vault_context.py]
       │   → keyword/topk retrieval from Obsidian vault, packs_consulted, chunks_used
       ├─ _get_session_history(session_id)  [mso/session_history.py]
       │   → last 5 turns from SQLite chat_db
       └─ _call_mso_cognitive(grounding_with_vault, text, history)
           → call_mso_chat_provider()  [mso/mso_chat_provider.py]
               → anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
                   model=MSO_SEAT_MODEL or CODE_REVIEW_MODEL or "claude-haiku-4-5-20251001",
                   system=build_mso_chat_system_prompt(grounding_context),
                   messages=[...history, { role:'user', content:text }]
                 )
               ← text, provider_name='anthropic', model_name, status
           → validation: rejects execution claim phrases
← Response: { message, response_source='llm_economic', execution_status='real',
              provider_used, model_used, cognitive_generation=True,
              cognitive_trace={vault_packs_consulted, history_*, synthesis_mode='economic', ...},
              tokens_in, tokens_out, latency_ms, ... }

Fallback: if provider fails → narrative_runtime.build_narrative_context_message() with response_source='deterministic_fallback' or 'provider_unavailable'

Metadata added: ALL provenance fields (see cognitive_trace)
LLM used: Yes — Anthropic Haiku (hardcoded provider)
Vault used: Yes — all configured packs, keyword+topk retrieval
Session history used: Yes — last 5 turns from SQLite
Execution possible: No — used_execution=False enforced in provider contract
Confirmation required: No — cognitive only
UI provenance shown: response_source badge, provider/model badge, fallback badge, latency, execution_status, governance. Raw drawer: full backend JSON including cognitive_trace
```

### 4C. Mission Control (read observation)

```
MissionControlView mount
→ useSeatProviderPolling() → GET /api/mso/seat/provider → Python /mso/seat/provider
   → seat_model_provider_registry.get_seated_provider()
   → { seat_provider: { provider_name, model_name, is_available, availability, local_or_remote } }
→ usePreparedActionsPolling() → GET /api/mso/prepared-actions/pending → Python /mso/prepared-actions/pending
   → prepared_action_queue.list_pending_confirmable_action_dicts()
   → { count, items: [ConfirmablePreparedAction...] }
→ useConfirmPendingPolling() → GET /api/confirm/pending → Python /confirm/pending
   → confirm_flow.list_pending_confirmations()
   → { pending_count, pending: [...], expired_pending_count }
→ useAuthorityStatusPolling() → GET /api/mso/authority/status → Python /mso/authority/status
   → authority/artifact.build_authority_status_response()
   → { counts: { total, allow, confirm_only, deny, blocked, active_grants, active_revocations }, capabilities: [...] }
← All displayed as status tiles and posture rows. No execution buttons. No action endpoints called.

LLM used: No
Vault used: No
Execution possible: No
UI truth: Displays live counts. Next-safe-step is computed from operational_mode + preparedCount.
```

### 4D. Provider Selector (read display)

```
MSOProviderSelector renders
→ useSeatProviderStore → polled by useSeatProviderPolling → /api/mso/seat/provider
→ Displays: provider_name, model_name, availability, local_or_remote
→ Renders PROVIDER_OPTIONS=['llama','anthropic','openai/gpt','gemma'] as static badges
→ Currently seated option highlighted; others cursor-not-allowed

No interaction endpoint. Read-only display. Options list is hardcoded, not from backend.
```

### 4E. System Chat View (system-assistant state)

```
SystemChatView mount + Refresh button
→ getSystemAssistantState()  [lib/api.ts]
→ GET /api/system-assistant/state → Python /system-assistant/state
   → build_system_assistant_state_response()
   → { interpretation: { status, summary, observations, warnings, source }, snapshot: { operational_mode, ... } }
← Displays: status badge, source badge, summary, observations, warnings, assistant-reported mode

Not a chat surface. Read-only system state panel. No composer.
```

---

## 5. Main Chat vs MSO Console Distinction

**Is this distinction actually implemented?**

YES — at the backend level, clearly and correctly.

| Dimension | Main Chat (`ChatView`) | MSO Console (`MSOView`) |
|-----------|----------------------|------------------------|
| Shell | `AppShell` at `/` | `SovereignShell` at `/sovereign` |
| Surface declared | `assistant_chat` | `mso_direct` |
| Backend code path | `get_surface_behavior_response(surface='assistant_chat')` → router → orchestrator | `get_surface_behavior_response(surface='mso_direct')` → cognitive chain |
| LLM backing | Orchestrator-driven (CODE/FIN/WORK) | Anthropic Haiku via `mso_chat_provider` |
| Vault used | No | Yes |
| Session model | Full SQLite session management with sidebar | MSO chat store (in-memory, Zustand, no persistent sidebar) |
| Execution possible | Yes (governed: WORK/FIN/CODE) | No (cognitive only, invariant) |
| Confirmation flow | Yes (UIActionBar with confirm/select/form) | No (MSO proposes, cannot confirm) |
| Provenance shown | execution_status, governance trace | Full provenance: response_source, provider, fallback, latency, cognitive_trace |
| Visual language | Standard chat, domain badges only on executive responses | MSO branding ("Conversational Console"), invariant strip, collapsible system status |

**Are there backend contracts enforcing the distinction?** Yes — `get_surface_behavior_response()` has separate `if surface == "mso_direct":` vs `if surface == "assistant_chat":` branches. The mso_direct path cannot enter the orchestrator's execution path for conversational turns (executive prefixes pass through, but the MSO cognitive actor returns cognitive-only responses).

**Are tests enforcing the distinction?** Partially — `test_surface_behavior_layer.py` and `test_identity_routing.py` cover surfaces. No test explicitly asserts that `mso_direct` responses never have `execution_status='real'` from the orchestrator path.

**Gap:** MSO chat store is in-memory only (no session persistence sidebar). If the user sends 10 MSO messages and refreshes, the history is lost. Session history is wired for the cognitive prompt (last 5 turns from SQLite) but the UI does not restore prior MSO sessions.

---

## 6. Provider / Model Backing Audit

| Question | Finding |
|----------|---------|
| Who is actually behind MSO chat today? | **Anthropic Haiku** (`claude-haiku-4-5-20251001`) — hardcoded in `mso_chat_provider.py` line 24 |
| Is Provider Selector read-only? | Yes — explicitly, correctly, with `cursor-not-allowed` and clear note |
| Can user actually switch provider from UI? | No — env var restart required |
| Does the selected provider affect MSO chat? | **Partial mismatch:** UI polls `/mso/seat/provider` which reads `MSO_SEAT_PROVIDER` env var via `seat_model_provider_registry`. But `mso_chat_provider.py` calls Anthropic directly — it reads `MSO_SEAT_MODEL` for the model name but **always calls Anthropic**. If `MSO_SEAT_PROVIDER=llama`, the UI shows "llama" but MSO still calls Anthropic. |
| Is local Llama wired to MSO chat? | **No.** `mso_chat_provider.py` imports `anthropic` directly. The `seat_model_provider_registry` knows about local providers but `mso_chat_provider` ignores this. |
| Is Anthropic hardcoded in `mso_chat_provider`? | **Yes** — `provider_name = "anthropic"` line 110, `_get_anthropic_client()` always returns `anthropic.Anthropic()` |
| Are provider/model fields visible in raw/provenance? | Yes — `provider_used` and `model_used` appear in badges and raw drawer |
| What is needed to make provider selection operational? | Route `mso_chat_provider` through `seat_model_provider_registry.get_seated_provider()` dispatch table instead of direct Anthropic call |

---

## 7. Operability Contract Audit

| Entity | Observe | Converse | Prepare | Confirm | Execute | Inspect trace | Change provider | Notes |
|--------|---------|----------|---------|---------|---------|---------------|-----------------|-------|
| Main Chat | yes | yes | partial | yes (via UIActionBar) | yes (governed) | read-only (execution_status badge) | no | Full execution path for WORK/CODE/FIN |
| MSO Console | yes | yes | yes (plan_request queues prepared action) | no | no | yes (raw drawer + badges) | no | Cognitive only invariant |
| MSO Provider Selector | yes | no | no | no | no | no | read-only | Shows seated provider; no switch capability |
| MSO Transcript | yes | no | no | no | no | yes (per-message) | no | Badges + raw drawer |
| MSO Raw Drawer | yes | no | no | no | no | yes (full JSON) | no | Best truth surface in the system |
| System Chat View | yes | no | no | no | no | read-only | no | Status dashboard only |
| Sovereign Status | yes | no | no | no | no | partial (hardcoded chain) | no | Authority chain rows are static text |
| Mission Control | yes | no | no | no | no | partial (live counts) | no | Correct read-only situation room |
| Confirm Flow Queue | yes | no | no | no | no | yes (authority timeline) | no | Observability only; correct |
| Prepared Actions | yes | no | no | no | no | yes (11-stage timeline) | no | Manual review; no action buttons |
| Authority Matrix | yes | no | no | no | no | yes (per-capability) | no | Posture only; correct |
| Agent Registry | yes | no | no | no | no | no | no | List only; no operational console |
| Outcome Status | yes | no | no | no | no | no | no | Last outcome only |

---

## 8. Provenance / Truth Audit

**Fields returned by backend for `mso_direct` cognitive responses:**
- `response_source` ✓ (shown: badge in transcript)
- `execution_status` ✓ (shown: badge)
- `provider_used` ✓ (shown: badge)
- `model_used` ✓ (shown: badge combined with provider)
- `cognitive_generation` ✓ (in raw drawer)
- `fallback_used` ✓ (shown: badge if true)
- `fallback_reason` ✓ (shown: badge truncated)
- `cognitive_trace` ✓ (in raw drawer as JSON)
  - `vault_packs_consulted` ✓ (in cognitive_trace JSON)
  - `history_available`, `history_turns_used`, `history_source` ✓ (in cognitive_trace JSON)
  - `synthesis_mode` ✓ (in cognitive_trace JSON)
- `latency_ms` ✓ (shown: badge)
- `tokens_in`, `tokens_out` ✓ (in raw drawer)
- `execution_allowed` ✓ (in raw drawer — always False)
- `can_execute_now` ✓ (in raw drawer — always False)
- `trace_id` ✓ (in raw drawer)

**For `assistant_chat` (Main Chat) — only:**
- `execution_status` ✓ (shown: badge)
- `governance_trace` ✓ (shown: GovernanceBadge)
- `decision_source` ✓ (shown: badge if present)
- `confidence_score` ✓ (shown: badge if present)
- `response_source` ✗ (not passed through from backend to UI in chat-view.tsx)
- `provider_used` ✗ (not passed through)
- `model_used` ✗ (not passed through)
- `cognitive_trace` ✗ (not passed through)

**Does any UI component infer or invent state?**
- `SovereignStatusView` authority chain rows are **hardcoded static** — they do not come from backend. This is the only case of invented display state. Examples: "MSO Governance: Active", "PolicyDecision: Present", "Police Gate: Fail-closed" are always shown as OK regardless of real backend state.

**Does raw drawer expose enough?** Yes — for MSO chat, the raw drawer exposes the full response JSON including cognitive_trace, which contains vault and history metadata.

**Is cognitive_trace human-readable?** No — it's a raw JSON object. A visual cognitive trace would need a dedicated rendering component that explains: "This response was generated by Anthropic Haiku using vault packs [X, Y] and 3 history turns."

**What would be needed for a visual cognitive trace?**
- A structured `cognitive_trace_v1` schema that the backend returns with typed sections
- A `CognitiveTracePanel` component that renders each section (provider, vault, history, grounding version) as labeled rows

---

## 9. Mission Control / Operational Surfaces Audit

**Are these connected to real backend endpoints?** Yes.
- `/api/mso/prepared-actions/pending` → Python `/mso/prepared-actions/pending` → `prepared_action_queue`
- `/api/confirm/pending` → Python `/confirm/pending` → `confirm_flow`
- `/api/mso/authority/status` → Python `/mso/authority/status` → `authority` module
- `/api/mso/seat/provider` → Python `/mso/seat/provider` → `seat_model_provider_registry`

**Are they polling real state?** Yes — all four hooks poll on an interval.

**Are they stale display panels?** No — the data is live. However, the **authority chain section in `SovereignStatusView`** is hardcoded.

**Do they align with MSO perception frame?** Partially — Mission Control shows prepared actions and confirm-pending counts which ARE what the MSO grounding context reads. But the UI does not show the grounding context itself (operational_mode, agents_registered, vault_state) in a machine-readable form.

**Does MSO perception actually read the same prepared actions / confirm pending data shown in UI?** YES — `build_mso_grounding_context()` (in `narrative_runtime.py`) reads the same queue state that the UI polls.

**Can a user operate through these surfaces?** No — no action buttons exist anywhere in Mission Control, Confirm Queue, or Prepared Actions. Operation must go through MSO Console or Main Chat.

**Where does the chain stop?** The chain stops at human confirmation, which has no UI surface. A human must signal confirmation by sending a message to the MSO Console or Main Chat. There is no dedicated "Approve prepared action" button.

---

## 10. Gaps and Debts

### BLOCKERS before Advanced Mode

| Gap | Description |
|-----|-------------|
| **G-01** | **Provider selector / MSO chat mismatch.** `mso_chat_provider.py` always calls Anthropic regardless of `MSO_SEAT_PROVIDER`. If env var says "llama", UI shows "llama" but Anthropic is called. This is a truth contract violation. |
| **G-02** | **No UI Cognitive Entity Registry.** No formal machine-readable mapping of UI entity → backend actor → allowed operations. This makes it impossible to reason about system operability from the UI alone. |
| **G-03** | **SovereignStatusView authority chain is hardcoded.** Rows claim "PolicyDecision: Present", "Police Gate: Fail-closed" regardless of real backend state. This is invented UI truth. |

### Important before Advanced Mode

| Gap | Description |
|-----|-------------|
| **G-04** | **Main Chat provenance not surfaced.** User cannot see which provider/model responded, response_source, or cognitive_trace in Main Chat. |
| **G-05** | **No confirmation action surface.** A user who sees a prepared action in the queue has no UI button to approve it — must send text. This is architecturally correct but operationally opaque. |
| **G-06** | **cognitive_trace is raw JSON only.** No visual layer. Hard to inspect without opening raw drawer and parsing JSON mentally. |
| **G-07** | **MSO chat session not persisted in UI.** Cognitive context (history) IS wired to SQLite. But the MSO chat UI does not show a session sidebar or restore prior MSO conversations on reload. |
| **G-08** | **AgentPanel has no operational console.** Every agent registered in backend shows "console not yet available." The panel is display-only. |
| **G-09** | **PROVIDER_OPTIONS in MSOProviderSelector is hardcoded in frontend.** Not driven by backend `/system/capabilities` or `/mso/seat/provider`. Should come from backend. |

### Post-Advanced Mode

| Gap | Description |
|-----|-------------|
| **G-10** | Local Llama not wired to MSO chat |
| **G-11** | Execution approval surface (Confirm button for prepared actions) |
| **G-12** | Advanced Mode invocation surface not defined |
| **G-13** | MSO cannot initiate plan_request from chat proactively — only responds |
| **G-14** | Police panels (`/police/*`) not audited in depth |

### Test Debt

| Gap | Description |
|-----|-------------|
| **T-01** | No test asserting `mso_direct` responses never have `execution_status='real'` via orchestrator path |
| **T-02** | No test asserting that `provider_used` in MSO response matches what `seat_model_provider_registry` reports |
| **T-03** | No UI-level tests for provenance badge rendering in MSO transcript |

### Documentation Debt

| Gap | Description |
|-----|-------------|
| **D-01** | No canonical mapping document: UI entity → backend actor → allowed operations |
| **D-02** | No ADR for the two-shell architecture (AppShell vs SovereignShell) |

---

## 11. Recommended Hardening Architecture

### A. UI Cognitive Entity Registry (v0 — static config first)

**Where it should live:** Frontend-only static config (`ui/lib/sovereign/entity-registry.ts`) in v0. Backend-driven in v1 (via a `/system/entity-registry` endpoint that returns the same shape).

**v0 shape:**

```typescript
// ui/lib/sovereign/entity-registry.ts

export interface CognitiveEntityDefinition {
  id: string
  label: string
  description: string
  surface: string | null
  backend_endpoint: string | null
  status_endpoint: string | null
  cognitive_actor: string
  provider_binding: 'seat_provider' | 'orchestrator' | 'static' | 'none'
  capabilities: CognitiveCapability[]
  boundaries: CognitiveBoundary[]
  provenance_required: boolean
  raw_trace_required: boolean
  execution_policy: 'cognitive_only' | 'governed_execution' | 'read_only' | 'display_only'
}

export type CognitiveCapability =
  | 'observe_state'
  | 'converse'
  | 'prepare_action'
  | 'confirm_action'
  | 'execute_action'
  | 'inspect_trace'
  | 'inspect_raw'
  | 'change_provider'

export type CognitiveBoundary =
  | 'no_direct_execution'
  | 'no_token_issuance'
  | 'no_policy_override'
  | 'read_only_surface'
  | 'display_only'
```

**Initial entity definitions:**

```typescript
export const COGNITIVE_ENTITY_REGISTRY: CognitiveEntityDefinition[] = [
  {
    id: 'main_chat',
    label: 'Main Chat',
    description: 'Conversational interface for WORK/CODE/FIN/HOST tasks. Routes through orchestrator with full governance.',
    surface: 'assistant_chat',
    backend_endpoint: '/chat/process',
    status_endpoint: '/system/runtime-state',
    cognitive_actor: 'AssistantOS Orchestrator',
    provider_binding: 'orchestrator',
    capabilities: ['observe_state', 'converse', 'prepare_action', 'confirm_action', 'execute_action'],
    boundaries: ['no_token_issuance', 'no_policy_override'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'governed_execution',
  },
  {
    id: 'mso_console',
    label: 'MSO Console',
    description: 'Sovereign cognitive conversational surface. Uses full Economic Cognition chain. Cannot execute directly.',
    surface: 'mso_direct',
    backend_endpoint: '/chat/process',
    status_endpoint: '/mso/state',
    cognitive_actor: 'MSO Economic Cognition (Anthropic Haiku + Vault + Session History)',
    provider_binding: 'seat_provider',
    capabilities: ['observe_state', 'converse', 'prepare_action', 'inspect_trace', 'inspect_raw'],
    boundaries: ['no_direct_execution', 'no_token_issuance', 'no_policy_override'],
    provenance_required: true,
    raw_trace_required: true,
    execution_policy: 'cognitive_only',
  },
  {
    id: 'mso_provider_selector',
    label: 'MSO Provider Selector',
    description: 'Displays the currently seated cognitive provider. Read-only in v0.',
    surface: null,
    backend_endpoint: '/mso/seat/provider',
    status_endpoint: '/mso/seat/provider',
    cognitive_actor: 'seat_model_provider_registry',
    provider_binding: 'seat_provider',
    capabilities: ['observe_state'],
    boundaries: ['read_only_surface', 'no_direct_execution'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
  {
    id: 'mso_raw_trace',
    label: 'MSO Raw Trace Drawer',
    description: 'Per-message full backend provenance inspector. Shows exact backend response JSON.',
    surface: null,
    backend_endpoint: null,
    status_endpoint: null,
    cognitive_actor: 'Passthrough — no backend call',
    provider_binding: 'none',
    capabilities: ['inspect_trace', 'inspect_raw'],
    boundaries: ['read_only_surface', 'display_only'],
    provenance_required: true,
    raw_trace_required: true,
    execution_policy: 'display_only',
  },
  {
    id: 'mission_control',
    label: 'Mission Control',
    description: 'Read-only situation room. Polls MSO seat, queues, authority. No execution surface.',
    surface: null,
    backend_endpoint: null,
    status_endpoint: '/mso/state',
    cognitive_actor: 'Multiple polling readers: prepared_action_queue, confirm_flow, authority, seat_provider',
    provider_binding: 'none',
    capabilities: ['observe_state'],
    boundaries: ['read_only_surface', 'no_direct_execution', 'display_only'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
  {
    id: 'confirm_queue',
    label: 'Confirm Queue',
    description: 'Observability view of confirm-pending entries. Observability only.',
    surface: null,
    backend_endpoint: '/confirm/pending',
    status_endpoint: '/confirm/pending',
    cognitive_actor: 'confirm_flow module',
    provider_binding: 'none',
    capabilities: ['observe_state', 'inspect_trace'],
    boundaries: ['read_only_surface', 'no_direct_execution'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
  {
    id: 'prepared_actions',
    label: 'Prepared Actions',
    description: 'Manual review queue of prepared actions with full authority timeline.',
    surface: null,
    backend_endpoint: '/mso/prepared-actions/pending',
    status_endpoint: '/mso/prepared-actions/pending',
    cognitive_actor: 'prepared_action_queue module',
    provider_binding: 'none',
    capabilities: ['observe_state', 'inspect_trace'],
    boundaries: ['read_only_surface', 'no_direct_execution'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
  {
    id: 'authority_matrix',
    label: 'Authority Matrix',
    description: 'Capability posture view. Shows allow/deny/confirm-only counts per domain/action.',
    surface: null,
    backend_endpoint: '/mso/authority/status',
    status_endpoint: '/mso/authority/status',
    cognitive_actor: 'authority module',
    provider_binding: 'none',
    capabilities: ['observe_state'],
    boundaries: ['read_only_surface', 'display_only'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
  {
    id: 'agent_registry',
    label: 'Agent Registry',
    description: 'Live list of registered agents. No operational console available in v0.',
    surface: null,
    backend_endpoint: '/agents/registry',
    status_endpoint: '/agents/registry',
    cognitive_actor: 'build_agents_registry_response()',
    provider_binding: 'none',
    capabilities: ['observe_state'],
    boundaries: ['read_only_surface', 'no_direct_execution'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
  {
    id: 'system_capabilities',
    label: 'System Capabilities',
    description: 'System capability and feature flag metadata.',
    surface: null,
    backend_endpoint: '/system/capabilities',
    status_endpoint: '/system/capabilities',
    cognitive_actor: 'build_system_capabilities_response()',
    provider_binding: 'none',
    capabilities: ['observe_state'],
    boundaries: ['read_only_surface', 'display_only'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
]
```

### B. Operability Contract

Allowed operations per entity — same as the table in Section 7. This becomes the source of truth for: what buttons to render, what tooltips to show, and what audit log to write.

### C. UI Truth Contract

Required fields per entity for honest rendering:

| Entity | Required fields | Optional fields |
|--------|----------------|----------------|
| MSO Console messages | `execution_status`, `response_source` | `provider_used`, `model_used`, `fallback_used`, `latency_ms` |
| MSO Raw Drawer | `cognitive_trace` (full), `raw_response` | All provenance fields |
| Main Chat messages | `execution_status`, `governance_trace` | `decision_source`, `confidence_score` |
| Mission Control | `prepared_count`, `confirm_count`, `operational_mode` | `authority_counts`, `provider_status` |
| Authority Matrix | `capabilities[]`, `counts` | `note` |

### D. Cognitive Chain Registry

The Cognitive Entity Registry (Section A) IS the Cognitive Chain Registry at v0. For each entity, the fields `cognitive_actor`, `provider_binding`, `surface`, and `backend_endpoint` define the chain. A future `/system/entity-registry` endpoint would make this backend-driven.

---

## 12. Recommended Next Sprint

**Recommendation: A — SPRINT-ALPHA-04.10 — UI Cognitive Entity Registry + Operability Contract**

**Why this, why now:**
- The system is architecturally sound. The gaps are not in backend logic but in self-description.
- G-01 (provider mismatch) is the only truth contract violation — it is a backend fix (route mso_chat_provider through the seat registry) that must happen before Advanced Mode.
- G-02 (no registry) and G-03 (hardcoded authority chain) are the primary hardening targets.
- Without a registry, Advanced Mode would add more entities with no formal contract, compounding the debt.
- The registry can be implemented as a static frontend config in one sprint, enabling future backend-driving without breaking anything.

**Goal:** Produce a formal `CognitiveEntityRegistry` (static v0) that makes every UI entity's backend actor, capabilities, and boundaries machine-readable; fix the provider mismatch (G-01); fix the hardcoded authority chain (G-03); add a lightweight visual contract badge on each entity.

**Why not Advanced Mode first:** Advanced Mode adds a new surface and new operational expectations. Without the entity registry and provider mismatch fix, Advanced Mode would add more display-only or inconsistent entities. The registry costs one sprint and makes Advanced Mode significantly safer.

**Files likely touched:**

Frontend:
- `ui/lib/sovereign/entity-registry.ts` (NEW)
- `ui/components/sovereign/MSOView.tsx` (add entity registry badge)
- `ui/components/sovereign/SovereignStatusView.tsx` (fix hardcoded chain — pull from backend)
- `ui/components/sovereign/MSOProviderSelector.tsx` (add "v0 · read-only · entity:mso_provider_selector" label driven by registry)
- `ui/components/sovereign/MissionControlView.tsx` (add entity badge)
- `ui/app/api/system/runtime-state/route.ts` (may need authority chain data)

Backend:
- `assistant_os/mso/mso_chat_provider.py` (G-01: route through seat_model_provider_registry dispatch)
- `assistant_os/mso/seat_model_provider_registry.py` (G-01: ensure dispatch table routes to correct provider)
- `assistant_os/operability.py` (G-03: add authority chain actual state to `/mso/state` or new endpoint)

Tests:
- `tests/test_ui_runtime_truth_contracts.py` (add: assert provider_used matches seat_model_provider_registry)
- `tests/test_surface_behavior_layer.py` (add: assert mso_direct never returns execution_status via orchestrator)
- NEW: `tests/test_cognitive_entity_registry.py` (validate registry shape, each entity has required fields)

**Expected new contracts/types:**
- `CognitiveEntityDefinition` type (TypeScript)
- `COGNITIVE_ENTITY_REGISTRY` static config
- Python: `get_mso_chat_provider_dispatch()` — routes mso_chat_provider through seat registry

**Acceptance criteria:**
- [ ] `CognitiveEntityRegistry` exists at `ui/lib/sovereign/entity-registry.ts` with all 10 entities
- [ ] `MSOView` header shows: `entity:mso_console | actor:MSO Economic Cognition | provider:anthropic | cognitive_only`
- [ ] `SovereignStatusView` authority chain rows are fetched from a real endpoint, not hardcoded
- [ ] `mso_chat_provider.py` routes through `seat_model_provider_registry` dispatch — if `MSO_SEAT_PROVIDER=llama`, Llama is called
- [ ] `provider_used` in MSO response always matches `seat_model_provider_registry.get_seated_provider().provider_name`
- [ ] New test: `test_cognitive_entity_registry.py` asserts each entity has required fields and no entity claims execution without `execution_policy: 'governed_execution'`
- [ ] `test_ui_runtime_truth_contracts.py` extended with provider match assertion

**Out of scope:**
- Actually implementing Llama provider call (separate sprint)
- Confirmation action buttons (post-Advanced)
- MSO session sidebar (post-Advanced)
- Visual cognitive trace component (post-Advanced)
- Advanced Mode invocation surface

**Risks:**
- Routing `mso_chat_provider` through seat registry requires the registry to have a working dispatch for Anthropic without breaking current behavior — test coverage is the guard
- Pulling authority chain from backend requires a backend endpoint that exposes actual Police gate state — this must be carefully read-only (no authority inference)

---

## 13. UI Cognitive Entity Registry v0 Design (Full)

**Location:** `ui/lib/sovereign/entity-registry.ts`

**Rationale for static frontend v0:** The registry values reflect architectural invariants that change only with sprint-level decisions. A static file is auditable, version-controlled, and requires no backend plumbing. When the system matures, a `/system/entity-registry` GET endpoint can replace it, and the frontend simply fetches it.

**Frontend rendering impact:**
- Each sovereign panel can import its entity definition by ID: `getEntity('mso_console')`
- The entity label and boundaries can be rendered as a small "contract badge" in the panel header:
  `entity:mso_console | cognitive_only | provider:seat`
- The `execution_policy` field drives whether an "Execute" button is rendered (only `governed_execution` entities show it)
- The `provenance_required` field drives whether the raw drawer link is mandatory vs optional

**Backend/source-of-truth considerations:**
- v0: static TypeScript config. No backend call.
- v1: `/system/entity-registry` GET returns same shape. Frontend fetches on mount and caches.
- The backend source of truth for `cognitive_actor` is `surface_behavior.py` + `mso_chat_provider.py`
- The backend source of truth for `capabilities` is the governance policy layer

**Tests for the registry:**
```python
# tests/test_cognitive_entity_registry.py
# (TypeScript test in ui/lib/sovereign/__tests__/entity-registry.test.ts)

def test_all_entities_have_required_fields():
    required = ['id', 'label', 'surface', 'backend_endpoint', 'cognitive_actor',
                'capabilities', 'boundaries', 'execution_policy']
    for entity in COGNITIVE_ENTITY_REGISTRY:
        for field in required:
            assert field in entity, f"Entity {entity['id']} missing {field}"

def test_no_cognitive_only_entity_has_execute_capability():
    for entity in COGNITIVE_ENTITY_REGISTRY:
        if entity['execution_policy'] == 'cognitive_only':
            assert 'execute_action' not in entity['capabilities'], \
                f"Entity {entity['id']} is cognitive_only but claims execute_action"

def test_provenance_required_entities_have_trace_endpoint():
    for entity in COGNITIVE_ENTITY_REGISTRY:
        if entity['provenance_required']:
            assert entity['backend_endpoint'] is not None or entity['id'] == 'mso_raw_trace', \
                f"Entity {entity['id']} requires provenance but has no backend_endpoint"
```

---

## 14. Manual Validation Plan

Exact steps to validate alignment after sprint:

```
1. Open Main Chat (/)
   - Confirm: ChatView renders with session sidebar
   - Send: "Hola"
   - Confirm: response has no domain/intent badge (conversational = ALLOW + no plan)
   - Send: "Crea una tarea: revisar presupuesto"
   - Confirm: response has WORK domain badge + confirm/execute UIAction
   - Inspect: execution_status badge present

2. Open Sovereign (/sovereign) → System view
   - Confirm: NO composer visible (read-only status view)
   - Click "Refresh assistant" → system-assistant state loads
   - Confirm: status, source, summary, observations render

3. Open Sovereign → MSO Console (sidebar: "mso")
   - Confirm: header shows "MSO · Conversational Console"
   - Confirm: MSOInvariantStrip visible
   - Confirm: "System status" collapsible shows seated provider
   - Send: "Quién eres?"
   - Confirm: response appears with response_source badge (llm_economic or deterministic_conversational)
   - Confirm: provider/model badge appears
   - Hover response → click "{ raw }" button
   - Confirm: raw drawer opens showing: response_source, execution_status, provider_used, model_used, cognitive_trace JSON
   - Confirm: cognitive_trace contains vault_packs_consulted, history_available, synthesis_mode

4. Open Sovereign → MSO Console
   - Send: "Qué ves del sistema?"
   - Confirm: response references operational_mode or system state
   - Confirm: cognitive_trace.history_turns_used is 0 (first message in session)
   - Send: "Y qué más sabes sobre el estado?"
   - Confirm: cognitive_trace.history_turns_used is 1 (second message references history)

5. Open MSO Console → collapse "System status" → expand
   - Confirm: Provider Selector shows: provider_name, model_name, availability, deployment
   - Confirm: provider options labeled cursor-not-allowed
   - Confirm: "v0 · read-only" badge present

6. Open Sovereign → Mission Control
   - Confirm: "Read-only composite situation room" header text
   - Confirm: Prepared Actions and Confirm Pending counts show (may be 0)
   - Confirm: Next Safe Step renders appropriately
   - Confirm: NO approve/execute buttons anywhere in view

7. Open Sovereign → Sovereign Status → ConfirmFlowQueuePanel
   - Confirm: "Confirm queue is observability only" note visible
   - Confirm: PreparedActions section shows "Manual Review Only" note
   - If queue empty: "No prepared actions waiting for manual review."

8. Open Sovereign → Agents
   - Confirm: list of registered agents loads from backend (or "Registry unavailable" if backend down)
   - Confirm: no agent has an active operational console

9. Compare: send "Cuéntame sobre el sistema" to Main Chat vs to MSO Console
   - Main Chat: should go through assistant_chat surface → system_state_summary or clarification
   - MSO Console: should go through mso_direct → cognitive generation → Anthropic response

10. PROVIDER TRUTH CHECK:
    - In MSO Console, send any message
    - Open raw drawer
    - Confirm: provider_used == value of MSO_SEAT_PROVIDER env var (or 'anthropic' if unset)
    - (This will FAIL before G-01 fix — mso_chat_provider is hardcoded to Anthropic)

11. VAULT CHECK (if vault configured):
    - Send a message to MSO Console relevant to vault content
    - Open raw drawer → cognitive_trace → vault_packs_consulted
    - Confirm: packs appear in list when vault is configured

12. NO EXECUTION CHECK:
    - In MSO Console, inspect raw drawer for any message
    - Confirm: execution_allowed === false
    - Confirm: can_execute_now === false
    - Confirm: used_execution is absent or false
```

---

## 15. Go / No-Go for Advanced Mode

**NO-GO for Advanced Mode now.**

Three specific reasons:

1. **G-01 (provider mismatch)** is a truth contract violation. The UI shows the seated provider but the backend always calls Anthropic. This must be resolved before adding more complexity.

2. **G-02 (no entity registry)** means Advanced Mode would add another entity with no formal contract. Without a registry, there is no systematic way to verify that Advanced Mode entities follow the same operability rules.

3. **G-03 (hardcoded authority chain)** in SovereignStatusView means the most prominent authority view in the system shows invented state. This undermines the doctrine that "UI must not invent truth."

The hardening cost is one sprint (SPRINT-ALPHA-04.10). After that sprint, the system will have:
- A formal entity registry (G-02 resolved)
- An honest provider chain (G-01 resolved)
- A live authority chain view (G-03 resolved)

At that point, Advanced Mode can be defined on top of a fully auditable entity foundation.

---

## 16. Final Recommendation

**What to do next:**
SPRINT-ALPHA-04.10 — UI Cognitive Entity Registry + Operability Contract.

Priority order within that sprint:
1. Fix G-01 (provider mismatch in `mso_chat_provider.py`) — smallest change, highest truth impact
2. Implement `ui/lib/sovereign/entity-registry.ts` with all 10 entities
3. Fix G-03 (SovereignStatusView authority chain — pull from backend, stop hardcoding)
4. Add entity contract badge to MSO Console and Mission Control headers
5. Add tests T-01 and T-02

**What NOT to do yet:**
- Do not open Advanced Mode
- Do not implement Llama provider (separate sprint after provider dispatch table exists)
- Do not add confirmation action buttons (requires governance work not in scope)
- Do not build visual cognitive trace component (good idea, but not blocking)
- Do not add MSO session sidebar (nice but not blocking)

**What would make the system feel more operable immediately (smallest improvements):**
1. Add `provider_used` and `response_source` badges to Main Chat messages (5 lines in `chat-view.tsx`) — makes the system feel consistent across both shells
2. Add the entity contract label to MSO Console header: `"entity: mso_console | actor: MSO Economic Cognition | provider: anthropic | cognitive only"` — costs 2 lines, makes the surface self-describing
3. Fix the hardcoded authority chain in SovereignStatusView (pull from a real endpoint) — this one actually matters for truth

These three changes alone would make the system significantly more honest and inspectable before the full sprint closes.
