# Runtime Topology

Canonical local runtime map for `Assistant_OS_Labs`.

## Canonical Ports

| Component | Default address | Type | Started by current launcher | Required | Authority path |
|---|---|---|---|---|---|
| Next.js UI | `http://localhost:3100` | HTTP | Yes | Optional | Auxiliary |
| AssistantOS backend / webhook / chat | `http://localhost:8787` | HTTP | Yes | Required | Yes |
| Code API | `http://localhost:8000` | HTTP | Yes | Optional | Auxiliary for external CODE HTTP access |
| Control plane admin | `http://127.0.0.1:8788` | HTTP | No | Optional | Safety-critical auxiliary |
| OpenClaw backend | `http://127.0.0.1:18790` | HTTP | No | Optional | No, subordinate execution only |
| Local LLM (Ollama) | `http://127.0.0.1:11434` | External HTTP | No | Optional | No, advisory only |
| Local LLM (llama.cpp) | `http://127.0.0.1:8081` | External HTTP | Yes, in current local launcher config | Optional | No, advisory only |
| MSO | no port | In-process module | n/a | Required | Yes |
| Runner / Police boundary | no port | In-process + subprocess boundary | n/a | Required for governed execution | Yes |
| Chat | no separate port | Route family inside webhook | n/a | Required | Yes |

## Component Notes

### UI

- Lives in `ui/`
- Canonical port is `3100` via `ui/package.json`
- Talks to:
  - Code API directly for CODE health/execution data
  - webhook `/health` directly
  - Next.js proxy routes for token-protected webhook calls such as chat and system state

### AssistantOS backend / webhook / chat

- Entry point: `python -m assistant_os --server`
- Canonical bind defaults from `assistant_os/config.py` are `0.0.0.0:8787`
- Hosts the chat route family (`/chat/process`, `/chat/sessions`, `/chat/search`)
- Also exposes operability surfaces:
  - `GET /health`
  - `GET /mso/state`
  - `GET /system/capabilities`
  - `GET /agents/registry`

### Code API

- Entry point: `python run_code_api.py`
- Canonical local default is `http://localhost:8000`
- Separate from the webhook server
- Does not own system-governance endpoints like `/api/system/runtime-state` or `/api/system/freeze`

### Control plane admin

- Entry point: `python -m assistant_os.control_plane.admin_server`
- Canonical default is `127.0.0.1:8788`
- Separate operator/admin surface

### OpenClaw backend / gateway

- Tracked backend lives under `assistant_os/openclaw_backend/`
- Canonical local backend default is `127.0.0.1:18790`
- `OPENCLAW_GATEWAY_URL` should align to the same local default when using the tracked backend:
  - `ws://127.0.0.1:18790`
- This service is optional and subordinate to the sovereign Machine Operator pipeline

### Local LLM

- Optional external dependency
- Ollama default/docs target: `http://127.0.0.1:11434`
- Optional llama.cpp alternative: `http://127.0.0.1:8081`
- Advisory only; not part of the authority path

### MSO

- In-process orchestration layer
- No standalone port or launcher entry
- Runs inside the AssistantOS backend path

### Runner / Police boundary

- In-process governance + subprocess/container execution boundary
- No standalone HTTP server in the tracked repo
- Includes runner/sandbox/container enforcement, but this document does not redefine authority semantics

## Current Launcher Scope

The current local launcher configuration observed in this workspace starts:

- AssistantOS backend / webhook on `8787`
- Code API on `8000`
- Next.js UI on `3100`
- optional llama.cpp server on `8081`

It does not currently start:

- control plane admin on `8788`
- OpenClaw backend on `18790`
- Ollama on `11434`

## External vs Optional

- External dependencies:
  - Ollama (`11434`)
  - llama.cpp (`8081`)
- Optional local servers:
  - Code API (`8000`)
  - control plane admin (`8788`)
  - OpenClaw backend (`18790`)
- Required local server:
  - AssistantOS backend / webhook / chat (`8787`)

## Proxy Rules

- Browser -> Next.js proxy:
  - `/api/chat/*`
  - `/api/system/runtime-state`
- Browser direct:
  - Code API endpoints on `NEXT_PUBLIC_API_BASE_URL`
  - webhook `/health` on `NEXT_PUBLIC_WEBHOOK_BASE_URL`
- Backend internal:
  - MSO, runner, and police/enforcement logic are in-process
  - Machine Operator reaches OpenClaw through the adapter boundary
