# Phase 1.0.1 - Baseline Documentation

## Overview

Assistant OS is a multi-agent command router that processes natural language commands,
classifies intent, plans actions, and executes them against various integrations
(Notion, Google Sheets, etc.).

**Version:** 1.0.1 (Stabilization Release)  
**Date:** March 2026

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              CLIENT                                      │
│  (Web UI /chat, iOS Shortcut, curl, etc.)                               │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼ HTTP POST
┌─────────────────────────────────────────────────────────────────────────┐
│                         webhook_server.py                                │
│  ┌─────────────┐  ┌─────────────────┐  ┌──────────────────────────────┐ │
│  │  /health    │  │  /command       │  │  /command/summary            │ │
│  │  /chat      │  │  /classify      │  │  /fin/expense, /work/query   │ │
│  └─────────────┘  └─────────────────┘  └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           router.py                                      │
│         parse_command_to_request() → route_request()                     │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         classifier.py                                    │
│    classify_text() → domain, operation, confidence                       │
│    Deterministic rules + keyword matching (no LLM)                       │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Plan Builder                                     │
│    contracts.py::make_plan() — PURE FUNCTION                             │
│    Creates Plan with: action, target, risk_level, requires_confirmation  │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
            requires_confirmation?         auto-executable?
                    │                             │
                    ▼                             ▼
           Return Plan (await)           Execute immediately
           Client calls /confirm               │
                    │                          │
                    └──────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Execution Layer                                  │
│    runner.py, fin_expense.py, summary.py                                 │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Integrations                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────────────┐  │
│  │  notion.py       │  │  sheets.py       │  │  schema_ops.py        │  │
│  │  (Notion API)    │  │  (Google Sheets) │  │  (DB schema changes)  │  │
│  └──────────────────┘  └──────────────────┘  └───────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           Response                                       │
│    contracts.py::Response TypedDict                                      │
│    JSON with: status, output, error, context_id                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Key Invariants

### 1. Plan Builder is Pure
`make_plan()` in `contracts.py` produces a `Plan` from inputs without side effects.
No I/O, no external calls, no state mutation.

### 2. `/command/summary` Has No Side Effects
This endpoint classifies and plans but **never executes**. Safe to call repeatedly.
Returns a mobile-friendly summary of what *would* happen.

### 3. Confirmation Flow for Risky Actions
Actions with `risk_level == "high"` or `requires_confirmation == True` return a Plan.
Client must call `/command` with `confirm: true` to execute.

### 4. Deterministic Classification
`classifier.py` uses rule-based pattern matching (no LLM).
Same input → same output, every time.

### 5. All Notion Requests Have Timeouts
Every `requests.*` call to Notion API has explicit `timeout=N` seconds.
Timeout errors return JSON error response instead of hanging.

### 6. Threaded Server During Tests
When `PYTEST_CURRENT_TEST` env var is set, server uses `ThreadingMixIn`.
Prevents one slow request from blocking other tests.

---

## Running the Server

### Start Server (Development)

```powershell
# Default: 127.0.0.1:8787
python -m assistant_os --server

# Custom host/port
python -m assistant_os --server --host 127.0.0.1 --port 8787
```

### Health Check

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8787/health" -Method GET
```

Expected response:
```json
{
  "status": "ok",
  "service": "assistant_os",
  "notion_db_id_loaded": "...",
  "notion_token_set": true
}
```

---

## Running Tests

### Unit Tests (No External Services)

```powershell
python -m pytest -q
```

### Integration Tests (Requires Notion API)

```powershell
$env:RUN_INTEGRATION="1"; python -m pytest -q
```

### Integration Tests Only

```powershell
$env:RUN_INTEGRATION="1"; python -m pytest -m integration -q
```

---

## Configuration

### Required Environment Variables

| Variable            | Description                                      |
|---------------------|--------------------------------------------------|
| `NOTION_TOKEN`      | Notion integration secret (starts with `ntn_`)  |
| `NOTION_WORK_DB_ID` | Notion database ID for WORK tasks               |

### Optional Environment Variables

| Variable                 | Description                              |
|--------------------------|------------------------------------------|
| `NOTION_WORK_TEST_DB_ID` | Test database ID (for integration tests) |
| `NOTION_WORK_TRASH_DB_ID`| Trash database ID (for delete flow)      |
| `ASSISTANT_API_TOKEN`    | Token for API authentication             |
| `RUN_INTEGRATION`        | Set to `1` to enable integration tests   |

### Configuration via `.env`

Create a `.env` file in the project root:

```env
NOTION_TOKEN=ntn_your_secret_here
NOTION_WORK_DB_ID=your_database_id_here
ASSISTANT_API_TOKEN=your_api_token
```

---

## Troubleshooting

### Notion Not Available

**Symptom:** Tests skip or fail with "Notion not available"

**Check:**
```powershell
# Verify environment variables
$env:NOTION_TOKEN
$env:NOTION_WORK_DB_ID
```

**Fix:**
1. Set environment variables or add to `.env`
2. Ensure Notion integration is shared with the database
3. Verify token hasn't expired

### Request Timeout Errors

**Symptom:** `"error": "Request timed out"` or `"type": "timeout"`

**Cause:** Notion API took longer than timeout (10-30 seconds)

**Response format:**
```json
{
  "ok": false,
  "error": {
    "type": "timeout",
    "message": "Notion API request timed out"
  }
}
```

**Fix:**
1. Check Notion API status: https://status.notion.so/
2. Retry the request
3. If persistent, check network connectivity

### Network Errors

**Symptom:** `"type": "network_error"`

**Response format:**
```json
{
  "ok": false,
  "error": {
    "type": "network_error",
    "message": "Network error: ..."
  }
}
```

**Fix:**
1. Check internet connectivity
2. Verify firewall allows outbound HTTPS to api.notion.com
3. Check if behind proxy (may need `HTTPS_PROXY` env var)

### Server Won't Start (Port in Use)

**Symptom:** `OSError: [Errno 98] Address already in use`

**Fix:**
```powershell
# Find and kill process using port
Get-NetTCPConnection -LocalPort 8787 | Select-Object OwningProcess
Stop-Process -Id <PID> -Force

# Or use different port
python -m assistant_os --server --port 8788
```

---

## Phase 1.0.1 Stabilization Summary

This release focused on fixing flaky tests in CI when running with `RUN_INTEGRATION=1`.

### Changes

#### 1. Threaded Server in Tests
- `WebhookHTTPServer` now uses `ThreadingMixIn` when `PYTEST_CURRENT_TEST` is set
- Prevents single-threaded blocking that caused timeouts
- Production mode remains single-threaded (simpler, sufficient)

#### 2. Explicit Timeout Handling
- All Notion HTTP requests have `timeout=` parameter (10-30s range)
- Added explicit `requests.exceptions.Timeout` catch blocks
- Timeout errors return structured JSON, never hang

**Affected files:**
- `assistant_os/integrations/notion.py` - All request calls
- `assistant_os/integrations/schema_ops.py` - Schema update calls

#### 3. Integration Test Markers
- All tests hitting Notion API marked with `@pytest.mark.integration`
- Skipped by default unless `RUN_INTEGRATION=1`
- Added markers to `tests/test_work_query.py`

### Test Results

```
# Without integration tests
python -m pytest -q
→ 833 passed, 8 skipped

# With integration tests  
$env:RUN_INTEGRATION="1"; python -m pytest -q
→ 841 passed (0 flaky across multiple runs)

# Integration tests only
$env:RUN_INTEGRATION="1"; python -m pytest -m integration -q
→ 8 passed, 833 deselected
```

---

## File Structure (Key Files)

```
assistant_os/
├── __main__.py          # Entry point: python -m assistant_os
├── main.py              # CLI argument parsing, server startup
├── webhook_server.py    # HTTP server, all endpoints
├── router.py            # Command routing logic
├── classifier.py        # Intent classification (deterministic)
├── contracts.py         # TypedDicts, Plan/Response, make_plan()
├── summary.py           # Summary generation
├── fin_expense.py       # Financial expense parsing
├── config.py            # Configuration, env vars
└── integrations/
    ├── notion.py        # Notion API client (with timeouts)
    ├── sheets.py        # Google Sheets client
    └── schema_ops.py    # Notion schema operations

tests/
├── test_webhook.py      # Webhook endpoint tests
├── test_work_query.py   # Notion integration tests (marked)
└── ...

scripts/
├── smoke.ps1            # PowerShell smoke test
└── smoke.py             # Python smoke test (cross-platform)
```

---

## Quick Reference

| Task                       | Command                                              |
|----------------------------|------------------------------------------------------|
| Start server               | `python -m assistant_os --server`                    |
| Run all tests              | `python -m pytest -q`                                |
| Run integration tests      | `$env:RUN_INTEGRATION="1"; python -m pytest -q`     |
| Health check               | `curl http://127.0.0.1:8787/health`                  |
| Smoke test (PowerShell)    | `.\scripts\smoke.ps1`                                |
| Smoke test (Python)        | `python scripts/smoke.py`                            |
