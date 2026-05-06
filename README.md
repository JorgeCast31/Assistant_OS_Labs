# Assistant OS

For external coding agents, read AGENTS.md first.

Multi-agent personal assistant system with a split local runtime: webhook/backend, Code API, Next.js UI, and optional/external machine-operator and local-LLM services.

## Quick Start

1. Copy `.env.example` to `.env` and fill in required values.
2. Install dependencies: `pip install -r requirements.txt`
3. Start the AssistantOS webhook/backend: `python -m assistant_os --server`
4. Start the Code API when you need CODE HTTP access: `python run_code_api.py`
5. Start the UI from `ui/`: `npm run dev`

## Canonical Local Runtime Map

| Component | Default URL | Notes |
|---|---|---|
| Next.js UI | `http://localhost:3100` | Browser UI |
| AssistantOS backend / webhook / chat | `http://localhost:8787` | Main HTTP backend and chat route family |
| Code API | `http://localhost:8000` | Separate CODE HTTP server |
| Control plane admin | `http://127.0.0.1:8788` | Operator/admin server |
| OpenClaw backend | `http://127.0.0.1:18790` | Optional Machine Operator subordinate backend |
| Local LLM (Ollama) | `http://127.0.0.1:11434` | Optional external dependency |
| Local LLM (llama.cpp) | `http://127.0.0.1:8081` | Optional external alternative |

For the full topology, launcher notes, authority-path classification, and optional/external service details, see [docs/RUNTIME_TOPOLOGY.md](docs/RUNTIME_TOPOLOGY.md).

## Configuration

### Required Environment Variables

- `NOTION_TOKEN` - Notion API token
- `NOTION_WORK_DB_ID` - Notion database ID for WORK tasks
- `WEBHOOK_TOKEN` - Authentication token for the AssistantOS webhook/backend
- `SHEETS_SPREADSHEET_ID` - Google Sheets ID for FIN expenses

### Optional Runtime Variables

- `WEBHOOK_HOST` / `WEBHOOK_PORT` - webhook/backend bind address, default `0.0.0.0:8787`
- `CODE_API_PORT` - Code API port, default `8000`
- `CONTROL_PLANE_HOST` / `CONTROL_PLANE_PORT` - control-plane admin bind address, default `127.0.0.1:8788`
- `OPENCLAW_GATEWAY_URL` - Machine Operator adapter target, canonical local default `ws://127.0.0.1:18790`
- `LOCAL_LLM_BASE_URL` - external local-LLM URL, default docs target `http://127.0.0.1:11434`

### Optional: TEST Database

To avoid polluting your production WORK database with UI/development test tasks:

1. Create a new Notion database with the same structure as your WORK database.
2. Copy the database ID from the URL.
3. Add to `.env`:
   ```env
   NOTION_WORK_TEST_DB_ID=your_test_database_id
   ```
4. Restart the server.

## Testing

```bash
python -m pytest tests/ -v
```

## Documentation

- [docs/CHAT.md](docs/CHAT.md) - UI and chat runtime notes
- [docs/RUNTIME_TOPOLOGY.md](docs/RUNTIME_TOPOLOGY.md) - canonical server/process topology
