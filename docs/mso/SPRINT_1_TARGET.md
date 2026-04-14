# MSO Sprint 1 Target

## Objective

Introduce the smallest safe preparation layer for future local Llama-backed governance without changing the current user-facing architecture.

Sprint 1 is not full MSO and not full local LLM integration. It should only create a disabled-by-default seam that can later host MSO logic.

## Target Outcome

At the end of Sprint 1, the codebase should have:

- one clearly named internal MSO/local-LLM adapter boundary
- no second chat entrypoint
- no kernel replacement
- no behavior change when disabled
- explicit config for future local model wiring

## Recommended Architecture Move

### Create a disabled adapter seam

Add an internal module such as:

- `assistant_os/mso/local_llm_adapter.py`

Initial responsibility:
- read local LLM config
- expose a tiny interface such as `is_enabled()` and a stubbed `analyze_request(...)`
- return a no-op / disabled result unless explicitly enabled

### Call it from the canonical orchestration path

Primary candidate:

- `assistant_os/core/orchestrator.py`

Initial behavior:
- if disabled: no-op, current flow unchanged
- if enabled later: allow bounded advisory analysis before semantic/policy routing

Do not:
- call it from UI
- add a new HTTP endpoint for chat
- bypass `CanonicalRequest`, `Plan`, or `DomainResult`

## Minimal File Changes Expected

### Likely Sprint 1 edits

- `assistant_os/core/orchestrator.py`
  - add one guarded hook point for MSO/local-LLM advisory use

- `assistant_os/config.py`
  - expose inert config values:
    - `MSO_ENABLED`
    - `LOCAL_LLM_PROVIDER`
    - `LOCAL_LLM_BASE_URL`
    - `LOCAL_LLM_MODEL`

- `.env.example`
  - document the new variables only

- `assistant_os/mso/__init__.py`
  - package marker if the new folder is created

- `assistant_os/mso/local_llm_adapter.py`
  - disabled-by-default adapter stub

- optional: `assistant_os/mso/contracts.py`
  - only if a tiny internal typed result object improves clarity

### Files that should probably not change in Sprint 1

- `assistant_os/chat_core.py`
- `assistant_os/chat_renderer.py`
- `assistant_os/chat_db.py`
- `assistant_os/context_store.py`
- `ui/app/api/chat/process/route.ts`
- `ui/lib/api.ts`
- `ui/components/views/chat-view.tsx`
- `assistant_os/pipelines/code_pipeline.py`
- any existing domain pipeline behavior

## First Implementation Shape

### Preferred shape

Internal adapter + internal bridge

Meaning:
- orchestrator owns the decision to consult the adapter
- adapter owns provider details
- future localhost model server can sit behind `LOCAL_LLM_BASE_URL`

### Why this shape wins

- low risk
- no duplicate ingress
- no transport contamination
- easy rollback
- keeps provider logic isolated from domain pipelines

## Proposed Sprint 1 Steps

1. Add `docs/mso/` package notes if needed.
2. Add disabled config surface in `assistant_os/config.py` and `.env.example`.
3. Create `assistant_os/mso/local_llm_adapter.py` as a no-op adapter.
4. Add one guarded orchestrator call site that does nothing when disabled.
5. Add focused tests proving:
   - disabled mode is behavior-preserving
   - enabling config does not bypass existing contracts
   - orchestrator still returns the same shapes

## Definition Of Done

- current chat flow still enters through `/chat/process`
- current kernel still flows through `core/orchestrator.py`
- current contracts remain valid
- current domain pipelines remain the execution owners
- local LLM path is disabled by default
- no external paid API is introduced
- no user-visible behavior changes unless explicitly enabled later

## Open Decisions Before Or During Sprint 1

### Decision 1

Should the future local model be consulted:

- before semantic classification
- after semantic classification but before policy
- or only as an advisory governor after plan creation

Current recommendation:
- after `CanonicalRequest` creation and within orchestrator, but before final routing decision

### Decision 2

Should the future local runtime be:

- in-process adapter only
- or adapter + localhost HTTP bridge

Current recommendation:
- code to an adapter interface now
- allow the adapter to speak to a local HTTP bridge later

### Decision 3

What is the exact first MSO responsibility?

Current recommendation:
- bounded advisory routing/governor analysis
- not direct execution
- not renderer output generation
- not replacing confirm/select/form logic

## Anti-Goals For Sprint 1

- no Ollama bootstrap unless isolated and optional
- no second assistant server
- no UI-driven orchestration
- no contract redesign
- no chat flow replacement
- no attempt to merge chat_core and orchestrator in the same sprint
