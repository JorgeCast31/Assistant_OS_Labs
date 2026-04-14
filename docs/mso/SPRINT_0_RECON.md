# MSO Sprint 0 Recon

## Scope

This document records the current AssistantOS architecture as-is for Sprint 0 reconnaissance.

This sprint does not introduce MSO behavior, does not replace the kernel, and does not add a second chat path. The goal is to identify where a future local Llama-backed layer can attach with the least risk and the smallest blast radius.

## Canonical Working Path

- Canonical repo path: `C:\Users\Jorge\Assistant_OS_Labs`
- Canonical backend package: `assistant_os/`
- Canonical frontend app: `ui/`
- Duplicate/non-canonical path observed: `assistant_os/.claude/worktrees/stoic-lichterman/...`

Recommendation:
- Treat `C:\Users\Jorge\Assistant_OS_Labs` as the only working source of truth for Sprint 1 changes.
- Do not modify mirrored `.claude/worktrees/...` copies unless there is an explicit workflow reason.

## A. Current Chat Flow

### User entrypoint

The live browser chat path is:

1. `ui/components/views/chat-view.tsx`
2. `ui/lib/api.ts::sendChatMessage()`
3. `ui/app/api/chat/process/route.ts`
4. `assistant_os/webhook_server.py::_handle_chat_process()`
5. `assistant_os/chat_core.py::process_chat_input()`
6. `assistant_os/chat_renderer.py::render_chat_response()`
7. response returned to UI and persisted to session DB when `session_id` is present

### Frontend ingress

- `ui/components/views/chat-view.tsx`
  - sends `text`, optional structured `action`, `session_context`, and `session_id`
  - stores returned session state locally for the next turn
- `ui/lib/api.ts`
  - browser calls internal Next.js route `/api/chat/process`
- `ui/app/api/chat/process/route.ts`
  - server-side proxy
  - injects `ASSISTANT_TOKEN`
  - forwards to backend webhook `/chat/process`

### Backend chat ingestion

Primary ingestion endpoint:

- `assistant_os/webhook_server.py::_handle_chat_process()`

Responsibilities:
- auth and JSON validation
- loads authoritative `context_id` from `chat_db` when `session_id` exists
- rebuilds `ChatSession` from `session_context`
- calls `process_chat_input(text, session, action=action_raw)`
- calls `render_chat_response(response)`
- persists user/assistant messages to SQLite when `session_id` is present
- updates session `context_id`

### Highest-level chat routing decision

For the chat UX path, the highest-level routing decision currently lives in:

- `assistant_os/chat_core.py::process_chat_input()`

Priority order inside chat_core:

1. structured action routing
2. pending flow resolver routing
3. classifier-based domain routing

This means the current chat experience is governed primarily by `chat_core`, not by `core/orchestrator.py`.

### Confirm / cancel / select / form_submit flows

These are handled in `assistant_os/chat_core.py`.

Key elements:
- `STRUCTURED_ACTION_TYPES`
- `parse_action()`
- `_process_structured_action(...)`
- `PENDING_FLOW_RESOLVERS`

Observed pending flows:
- `fin_confirm`
- `clarification`
- `work_confirm`
- `code_context`
- `code_review_context`
- `code_preview`

Implication:
- The chat UX is already a stateful deterministic flow engine.
- A future governor layer must not bypass this by inventing a parallel confirm/cancel mechanism.

### Session persistence and reload

Persistent chat session store:

- `assistant_os/chat_db.py`

Storage:
- SQLite DB at `assistant_os/memory/chat_sessions.db`

What is persisted:
- sessions metadata
- ordered message history
- current `context_id`

Reload path:
- `_handle_chat_process()` reads `session_id`
- loads `context_id` from `chat_db.get_session(session_id)`
- UI also sends `session_context` holding `pending_flow`, `pending_data`, `last_domain`

Important nuance:
- persistent session metadata lives in SQLite (`chat_db.py`)
- pending confirmation plans for non-chat canonical plan execution live separately in `assistant_os/context_store.py`

This is already a split state model:
- chat conversation state -> `chat_db.py`
- pending plan confirmation state -> `context_store.py`

## B. Kernel / Orchestration Boundaries

### What currently acts as the top-level coordinator

For canonical request execution, the top-level coordinator is:

- `assistant_os/core/orchestrator.py::handle_request()`

Pipeline:

1. `normalize_request()` -> `CanonicalRequest`
2. `core.semantic.classify()`
3. `core.planning.build_plan()`
4. `core.policy.build_policy()`
5. `core.routing.get_pipeline()`
6. domain pipeline execution
7. `DomainResult`

### Is the kernel explicit or distributed?

Both.

There is now an explicit kernel module:
- `assistant_os/core/orchestrator.py`

But the system still has distributed coordination in practice:
- chat UX routing is concentrated in `chat_core.py`
- webhook transport adapts and sometimes directly invokes canonical orchestration
- domain pipelines contain execution logic

Conclusion:
- the kernel exists explicitly for canonical request execution
- the end-to-end product behavior is still split across `webhook_server.py`, `chat_core.py`, and `core/*`

### Safest future interception points

There are two plausible insertion points, but only one is recommended for first Llama integration.

#### Recommended future interception point

- `assistant_os/core/orchestrator.py::handle_request()`

Why:
- already transport-independent
- already normalizes all canonical requests into a single pipeline
- already separates semantic classification, planning, policy, routing, and execution
- smallest risk of UI contamination
- easiest place to insert a governor decision without duplicating ingress

#### Secondary possible boundary

- `assistant_os/core/semantic.py::classify()`

Why:
- narrow scope if the first Llama role is only semantic interpretation

Why it is less ideal as the first insertion:
- too low-level if MSO is intended to govern routing/orchestration rather than just classification
- would not naturally own policy-level or delegation-level decisions

#### Chat-path-only insertion that should be avoided initially

- `assistant_os/chat_core.py::process_chat_input()`

Why not first:
- this would couple MSO to current UI flow mechanics
- higher risk of interfering with confirm/select/form lifecycles
- could create a second orchestration locus instead of clarifying one

### Contracts that should remain untouched

Preserve these unless Sprint 1 proves a strict need:

- `assistant_os/contracts.py::CanonicalRequest`
- `assistant_os/contracts.py::PolicyDecision`
- `assistant_os/contracts.py::Plan`
- `assistant_os/contracts.py::DomainResult`
- `assistant_os/contracts.py::ChatCoreResponse`
- current `ui_actions` contract between `chat_core` and `chat_renderer`
- current `chat/session_context` request shape used by UI
- `chat_db.py` session storage schema
- `context_store.py` pending-plan persistence semantics

Reason:
- these are the system’s current boundary objects
- changing them early would contaminate multiple layers at once

## C. CODE Delegation Boundary

### Where CODE tasks are recognized

CODE detection begins in:

- `assistant_os/classifier.py`
- `assistant_os/core/semantic.py`
- `assistant_os/core/planner.py`

Routing chain:

1. classifier emits `OP_CODE_EXPLAIN`, `OP_CODE_REVIEW`, `OP_CODE_FIX`, `OP_CODE_CREATE`
2. planner maps them to `ACTION_CODE_*`
3. `core.routing.action_domain()` maps `CODE_*` to `CODE`
4. `core.routing.get_pipeline()` dispatches to `assistant_os/pipelines/code_pipeline.py`

### How CODE is currently invoked

There are two active CODE surfaces:

#### Chat-oriented CODE surface

- `assistant_os/chat_core.py`

This path handles:
- interactive CODE requests from chat
- repo/file context gathering
- preview / confirm flow
- direct use of registered CODE executors for read/review/proposal generation

#### Canonical CODE execution pipeline

- `assistant_os/pipelines/code_pipeline.py`

This path handles:
- read-only CODE explain/review
- mutating CODE preview/apply
- proposal single-use enforcement
- runner-backed audited apply path

### Clean contract boundary for future governor delegation to CODE

Recommended boundary:

- delegate into canonical `Plan` with `ACTION_CODE_*`
- let `core.routing` dispatch to `pipelines/code_pipeline.py`

Do not delegate by:
- calling Claude executors directly
- calling chat-only helpers directly
- inventing a new CODE endpoint

Reason:
- `code_pipeline.py` is already the clean execution boundary
- executor registries already isolate provider-specific implementation
- runner/audit logic already hangs off this path

## D. Local Llama Integration Feasibility

### Best insertion point

Best initial insertion point:

- `assistant_os/core/orchestrator.py::handle_request()`

Best shape:
- an internal adapter module consulted by orchestrator before or during semantic/policy stages
- not a public-facing second service path
- not a second chat entrypoint

### Placement options assessed

#### 1. Inside current backend flow

Feasible: yes

Pros:
- simplest request path
- no duplicate ingress
- easiest to keep contracts unchanged

Cons:
- must keep failure isolation strong
- should not block or destabilize current deterministic path

#### 2. As a sidecar service

Feasible later: yes

Pros:
- good operational isolation
- model runtime can evolve independently

Cons:
- adds deployment/runtime complexity immediately
- introduces network/process dependency before governance contract is fully defined

Verdict for Sprint 1:
- possible backend detail later, but not the first integration shape to expose to the rest of the app

#### 3. As an adapter module

Feasible: yes

Pros:
- lowest code blast radius
- fits existing executor/adapter style already used in CODE
- keeps provider swap isolated

Verdict:
- best immediate coding shape

#### 4. Behind an internal bridge

Feasible: yes

Pros:
- useful if the local model later runs as HTTP on localhost
- keeps orchestrator talking to one internal abstraction

Verdict:
- best operational shape if local Llama eventually runs as a separate local server

### Recommended first integration

Minimum viable first integration for next sprint:

1. Add inert config surface for local LLM selection.
2. Add an internal adapter module, e.g. `assistant_os/mso/local_llm_adapter.py`.
3. Add a no-op governor seam in `core/orchestrator.py` that:
   - reads config
   - remains disabled by default
   - does not change current behavior when disabled
4. In the first enabled version, use local Llama only for bounded advisory routing/governor analysis, not direct execution.
5. Keep final execution delegated to existing `Plan` + pipeline boundaries.

This preserves the kernel while creating a clean place for MSO growth.

## E. Windows / Local Runtime Implications

### Windows-specific assumptions observed

- repo uses PowerShell-oriented docs and commands
- paths are Windows absolute paths in several places
- `context_store.py` has explicit Windows rename handling:
  - removes target file before rename on `os.name == "nt"`
- workspace and path validation rely on `os.path` / `Path` behavior
- default local URLs assume localhost ports (`8787`, `8000`)

### Path assumptions that may affect local model integration

- mutating CODE path requires absolute workspace path
- path safety depends on normalized local filesystem paths
- some UI and backend logic assume repo-local working directories
- duplicated worktree copies exist under `.claude/worktrees`

Implications for local Llama:
- any local model path/config should avoid hardcoding non-portable separators in core logic
- if a local server is used, prefer base URL config instead of executable-path assumptions

### Likely future issues when running a local model server

- large model startup latency could affect synchronous request paths
- localhost server availability failures need graceful fallback to current deterministic behavior
- Windows firewall / port binding may block local HTTP model runtimes
- path quoting and environment inheritance can differ across PowerShell/process launch paths
- if GPU acceleration is later introduced, machine-specific assumptions will need isolation outside the kernel

## Recommended Insertion Strategy

### Recommendation

For Sprint 1, connect local Llama through an internal adapter/bridge that is called from the canonical orchestrator path, not from the UI and not from a second backend entrypoint.

### Why this is the safest fit

- preserves current chat ingress
- preserves current kernel
- preserves current domain pipelines
- preserves current contracts
- aligns with existing executor/adapter pattern in CODE
- keeps MSO development behind one small internal seam

## Files Most Relevant To Sprint 1

### Current live flow and boundaries

- `ui/app/api/chat/process/route.ts`
- `ui/lib/api.ts`
- `ui/components/views/chat-view.tsx`
- `assistant_os/webhook_server.py`
- `assistant_os/chat_core.py`
- `assistant_os/chat_renderer.py`
- `assistant_os/chat_db.py`
- `assistant_os/context_store.py`
- `assistant_os/contracts.py`
- `assistant_os/core/orchestrator.py`
- `assistant_os/core/semantic.py`
- `assistant_os/core/planner.py`
- `assistant_os/core/policy.py`
- `assistant_os/core/routing.py`
- `assistant_os/pipelines/code_pipeline.py`
- `assistant_os/executors/startup.py`
- `assistant_os/executors/code_review_executor.py`
- `assistant_os/executors/code_propose_executor.py`
- `assistant_os/agents/registry.py`
- `assistant_os/config.py`
- `.env.example`

## Sprint 0 Conclusions

- The live user chat path is already unified at `/chat/process`; do not create another chat ingress.
- The clearest kernel boundary already exists at `core/orchestrator.py`.
- The safest future Llama insertion is not inside UI chat state handling, but behind the canonical orchestrator as an internal adapter/bridge.
- CODE already has a provider-injection pattern via executor registries; this is a strong precedent for local model integration style.
- The system has two state stores with different responsibilities; MSO should not collapse them prematurely.
- Sprint 1 should focus on creating a disabled-by-default local LLM seam, not on replacing classification, rendering, or domain pipelines wholesale.
