# Sprint 2 Local Llama

## What This Sprint Adds

- first real local LLM adapter module
- feature-flagged advisory consultation from `assistant_os/core/orchestrator.py`
- Ollama-compatible HTTP client
- timeout/failure isolation
- deterministic fallback when disabled or failing
- local probe utility

## Seam Added

The new seam is:

- `assistant_os/core/orchestrator.py`
  - calls `assistant_os.mso.local_llm_adapter.consult_advisory(...)`

Current role:

- advisory only
- non-authoritative
- does not replace classification
- does not replace planning
- does not replace policy
- does not replace routing

## Current Behavior

### When disabled

- no local model is consulted
- existing deterministic behavior remains unchanged

### When enabled and healthy

- orchestrator performs one advisory local-model consultation
- successful advisory data is attached privately to the execution plan as `_mso_advisory`
- deterministic execution remains source of truth

### When enabled but failing

- timeout, connection, JSON, or provider errors are swallowed non-fatally
- orchestrator continues with deterministic execution

## Supported Provider

- `ollama`

Configured through:

- `MSO_ENABLED`
- `LOCAL_LLM_PROVIDER`
- `LOCAL_LLM_BASE_URL`
- `LOCAL_LLM_MODEL`
- `LOCAL_LLM_TIMEOUT_SECONDS`

## Validation Path

Use:

```powershell
python scripts/probe_local_llm.py
```

This checks:
- feature/config readiness
- provider reachability
- model availability via `/api/tags`
- one advisory roundtrip via `/api/generate`

## Explicit Non-Goals

- no chat_core integration
- no UI chat flow changes
- no sovereign model routing
- no mandatory local model dependency
- no CODE dependency on local LLM
