# MSO Boundary Notes

## Boundaries To Preserve

- Chat ingress boundary:
  - `ui/*` -> `ui/app/api/chat/process/route.ts` -> `assistant_os/webhook_server.py::_handle_chat_process()`

- Chat state boundary:
  - `assistant_os/chat_core.py`
  - `assistant_os/chat_renderer.py`
  - `assistant_os/chat_db.py`

- Canonical kernel boundary:
  - `assistant_os/core/orchestrator.py`
  - `assistant_os/core/semantic.py`
  - `assistant_os/core/planner.py`
  - `assistant_os/core/policy.py`
  - `assistant_os/core/routing.py`

- Domain execution boundary:
  - `assistant_os/pipelines/*`

- CODE provider boundary:
  - `assistant_os/pipelines/code_pipeline.py`
  - `assistant_os/executors/startup.py`
  - executor registries for read/review/propose

## Boundaries To Avoid Violating

- Do not put MSO logic into the Next.js proxy routes.
- Do not put MSO logic into `chat_renderer.py`.
- Do not wire a local model directly into UI actions or session persistence.
- Do not bypass `Plan` and `DomainResult`.
- Do not call CODE executors directly from a new MSO module.

## Safe Future Seam

Safest seam:

- `assistant_os/core/orchestrator.py`

Safe extension style:

- orchestrator -> internal MSO/local adapter -> existing semantic/policy/routing pipeline

Not recommended as first seam:

- `assistant_os/chat_core.py`
- frontend route handlers
- direct mutation of domain pipelines
