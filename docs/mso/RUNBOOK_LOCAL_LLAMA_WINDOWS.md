# Runbook: Local Llama on Windows

## Intended Runtime

- Windows host
- Ollama local server
- Llama-family instruct model such as `llama3.2:3b-instruct`

## Basic Setup

1. Install Ollama for Windows.
2. Start Ollama so it serves on `http://127.0.0.1:11434`.
3. Pull a model, for example:

```powershell
ollama pull llama3.2:3b-instruct
```

4. Set AssistantOS env values in `.env`:

```env
MSO_ENABLED=true
LOCAL_LLM_PROVIDER=ollama
LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
LOCAL_LLM_MODEL=llama3.2:3b-instruct
LOCAL_LLM_TIMEOUT_SECONDS=4.0
```

## Probe

Run:

```powershell
python scripts/probe_local_llm.py
```

Expected outcomes:
- `reachable=true`
- `model_available=true`
- `roundtrip_ok=true`

## Failure Modes

### Ollama not running

Symptoms:
- probe returns request/connection failure
- AssistantOS still works deterministically

### Model not pulled

Symptoms:
- probe reachability may succeed
- `model_available=false`
- roundtrip may fail depending on Ollama behavior

### Timeout too low

Symptoms:
- advisory call returns timeout error
- AssistantOS still falls back safely

## Operational Notes

- this sprint’s integration is advisory only
- the local model is not mandatory
- current chat flow and domain execution remain the source of truth
