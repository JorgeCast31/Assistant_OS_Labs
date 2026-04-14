# Sprint 3: Advisory Layer

Sprint 3 makes the local Llama seam useful without changing system authority.

## What was added

- A structured advisory engine at `assistant_os/mso/advisory_engine.py`
- A richer internal advisory schema in `assistant_os/mso/contracts.py`
- A combined orchestrator advisory prompt in `assistant_os/mso/prompts.py`
- Advisory trace metadata in `assistant_os/core/orchestrator.py`
- Optional CODE packaging enrichment in `assistant_os/pipelines/code_pipeline.py`

## Advisory roles now implemented

1. Reasoning summary
   - Produces a compact assistant-side interpretation of the request.
   - Stored as advisory metadata only.

2. Routing hint
   - Suggests a likely domain/action/posture.
   - Never overrides deterministic planning or policy.

3. CODE delegation packaging
   - When the final deterministic action is in `CODE_*`, the advisory layer can
     produce a cleaner package with:
     - task summary
     - repo context
     - constraints
     - expected artifact
     - risk notes
   - This package is appended to executor context as a non-authoritative note.

## Deterministic control remains canonical

- Classifier output still drives planning input.
- Planner still chooses the authoritative action.
- Policy still decides execution mode.
- Routing still chooses the domain pipeline.
- CODE execution still flows through the existing CODE pipeline.

## Advisory trace behavior

The orchestrator now records a small advisory trace showing:

- whether advisory was consulted
- which advisory roles produced usable output
- advisory status/provider/model/latency
- suggested route/action
- final deterministic action/domain/execution mode
- whether CODE packaging was attached

This trace is:

- attached privately to execution plans as `_mso_trace`
- exposed in `plan_confirmation_required` and `plan_generated` data as `advisory_trace`
- logged by the orchestrator for inspection

## Failure behavior

All local-model failures remain non-fatal:

- disabled configuration -> ignored safely
- timeouts -> ignored safely
- unreachable Ollama -> ignored safely
- invalid JSON -> adapter error -> deterministic fallback
- valid JSON with unusable fields -> advisory status becomes `ignored`

## Notes for Sprint 4

- Consider persisting advisory trace into execution metadata for post-run audit.
- Consider surfacing limited advisory trace in backend diagnostics endpoints.
- Keep advisory suggestions non-authoritative until an explicit governance change is designed.
