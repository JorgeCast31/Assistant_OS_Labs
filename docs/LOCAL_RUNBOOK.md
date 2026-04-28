# LOCAL_RUNBOOK — AssistantOS

Operational runbook for bringing up the local development stack on Windows.
Authoritative source for ports, environment variables, and recovery steps.

> **Principle.** The system is fail-closed. Missing config does not silently
> degrade — it blocks. Treat every "is not configured" message as an explicit
> instruction, not a warning.

---

## 1. Stack overview

| Component       | Default port | Purpose                                                   | Code path                                |
| --------------- | ------------ | --------------------------------------------------------- | ---------------------------------------- |
| Webhook server  | 8787         | Authoritative chat / governance / MSO / agents API        | `assistant_os/webhook_server.py`         |
| Code API server | 8000         | CodeOps executions surface (read-only orchestrator)        | `assistant_os/codeops/`                  |
| UI (Next.js)    | 3000         | Operator surface (Chat, MSO, Machine Operator, System)    | `ui/`                                    |

The UI never talks to the user's browser with secrets. All admin/auth tokens
are injected server-side via Next.js proxy routes (`ui/app/api/...`).

---

## 2. Required environment variables

### Backend (`.env` at repo root, loaded by `assistant_os/config.py`)

| Variable                        | Required | Purpose                                                                 |
| ------------------------------- | -------- | ----------------------------------------------------------------------- |
| `WEBHOOK_TOKEN`                 | yes      | Auth for non-admin webhook endpoints. **Fail-closed without it.**       |
| `WEBHOOK_ADMIN_TOKEN`           | yes      | Auth for admin endpoints (governance/freeze, schema plan/commit).       |
| `NOTION_TOKEN`                  | yes      | WORK domain integration.                                                |
| `NOTION_WORK_DB_ID`             | yes      | Notion database id used by the WORK pipeline.                           |
| `ANTHROPIC_API_KEY`             | for CODE | Required for CODE_EXPLAIN / CODE_REVIEW / CODE_PROPOSE flows.           |
| `SHEETS_SPREADSHEET_ID`         | for FIN  | Google Sheets target for expense logging.                               |
| `GITHUB_TOKEN`                  | for PRs  | CodeOps PR creation.                                                    |
| `OPENCLAW_GATEWAY_URL`          | optional | Future Machine Operator transport. Leave default for local sim mode.    |

`validate_startup_config()` raises `RuntimeError` if `WEBHOOK_TOKEN` is missing.
Admin endpoints reject all requests if `WEBHOOK_ADMIN_TOKEN` is missing — no
presence-only bypass.

### UI (`ui/.env.local`, loaded by Next.js)

| Variable                          | Required | Purpose                                                              |
| --------------------------------- | -------- | -------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_BASE_URL`        | yes      | Base URL of the Code API (default `http://localhost:8000`).          |
| `NEXT_PUBLIC_WEBHOOK_BASE_URL`    | yes      | Browser-visible webhook URL for health checks only.                  |
| `WEBHOOK_BASE_URL`                | yes      | Server-side webhook URL used by Next.js proxy routes.                |
| `ASSISTANT_TOKEN`                 | yes      | Server-side; matched to backend `WEBHOOK_TOKEN`.                     |
| `ASSISTANT_ADMIN_TOKEN`           | yes      | Server-side; matched to backend `WEBHOOK_ADMIN_TOKEN`. Required to   |
|                                   |          | enable the Freeze kill-switch from the System view.                  |

> **Token pairing rule.** `ASSISTANT_TOKEN` ↔ `WEBHOOK_TOKEN` and
> `ASSISTANT_ADMIN_TOKEN` ↔ `WEBHOOK_ADMIN_TOKEN`. The UI sends them as
> `X-Assistant-Token` and `X-Assistant-Admin-Token` respectively. If either
> pair is mismatched, the backend returns 401/403 and the UI surfaces a
> `Blocked:` block with a `suggestion=` line.

Copy `.env.example` → `.env` and `ui/.env.local.example` → `ui/.env.local`,
then fill in all required values. Generate tokens with:

```powershell
# PowerShell — 48 random bytes, base64-encoded
[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
```

---

## 3. Bring-up sequence (Windows)

Use three terminals; do not attempt to interleave services in a single shell.

### Terminal A — webhook server (port 8787)

```powershell
cd C:\Users\<you>\Assistant_OS_Labs
python -m assistant_os
```

Watch for these lines on stdout:

```
[CONFIG] WEBHOOK_TOKEN: configured.
[CONFIG] WEBHOOK_ADMIN_TOKEN: configured.
```

If either says `[CRITICAL] WEBHOOK_TOKEN not set` or
`[WARNING] WEBHOOK_ADMIN_TOKEN not set`, stop. Fix `.env`. Restart.

### Terminal B — code API (port 8000)

```powershell
cd C:\Users\<you>\Assistant_OS_Labs
python -m assistant_os.codeops_server
```

Healthcheck:

```powershell
curl http://localhost:8000/health
```

Expect `{"status":"ok"}`.

### Terminal C — UI (port 3000)

```powershell
cd C:\Users\<you>\Assistant_OS_Labs\ui
npm install   # only first time, or after package.json changes
npm run dev
```

Open `http://localhost:3000`. The System view should show:

- **Operational Mode:** `NORMAL` (or `FROZEN` if you've previously frozen).
- **CODE API:** Online.
- **Assistant / Webhook:** Online.

If any service shows `Offline`, the corresponding terminal is the one to
inspect.

---

## 4. Port cleanup (Windows)

If you see `EADDRINUSE` or a server fails to bind, a previous run is still
holding the port.

```powershell
# Find the PID holding a port (replace 8787 with whichever port).
netstat -ano | findstr :8787

# Kill the process by PID (last column from the line above).
taskkill /PID <pid> /F
```

Check all three at once:

```powershell
netstat -ano | findstr "LISTENING" | findstr ":8000 :8787 :3000"
```

If nothing is listening but the bring-up still fails, check for a stale
`var/runner/executions/*` directory blocking the runner.

---

## 5. Recovery from operational states

| Symptom (UI surface)                                  | Cause                                       | Fix                                                                                    |
| ----------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------------------------- |
| `Freeze Control Unavailable` in System view           | `FREEZE_CONTROL.available === false`        | Should not happen by default. Verify `ui/lib/api.ts` was not edited.                   |
| `ASSISTANT_ADMIN_TOKEN is not configured` (status 503)| Missing UI env var                          | Add `ASSISTANT_ADMIN_TOKEN` to `ui/.env.local`, restart UI. Must match backend.        |
| `Admin token rejected by backend` (status 403)        | `ASSISTANT_ADMIN_TOKEN ≠ WEBHOOK_ADMIN_TOKEN` | Align both env vars. Restart both processes.                                           |
| `Webhook token rejected by backend` (status 401)      | `ASSISTANT_TOKEN ≠ WEBHOOK_TOKEN`            | Same pattern as above.                                                                 |
| `Operational Mode: FROZEN`                            | Kill-switch was activated                   | Use the backend admin API to flip mode back to `NORMAL` once the underlying issue is resolved. Freezing is intentional fail-closed; do not bypass. |
| `Operational Mode: UNKNOWN` + Webhook Offline         | Webhook server is down                      | Restart Terminal A. Check stdout for the config lines.                                 |
| Code API shows `Offline`, others Online               | Code API server is down                     | Restart Terminal B.                                                                    |

---

## 6. Verification checklist

After bring-up, run these to confirm the surfaces are honest:

```powershell
# Backend tests (governance + auth + capabilities + agents)
python -m pytest tests/test_s01_freeze_system.py -v
python -m pytest tests/test_s02_admin_token_hardening.py -v
python -m pytest tests/test_codeops_endpoints.py -v
python -m pytest tests/test_mso_governance.py -v
python -m pytest tests/test_mo_agent_registry.py -v

# UI typecheck
cd ui
npx tsc --noEmit
```

Manual:

- Open System view. Click `Freeze System` (test environment only). Confirm.
  Expect either `System is now FROZEN` or a `Blocked:` block with a clear
  `suggestion=` line.
- Open System Chat. Type "hola". Expect an informational response, no plan,
  no `domain=ENERGY action=COMMAND` artefact.
- Open MSO Direct. Type "ejecuta nada". Expect the orchestrator to evaluate
  governance and respond honestly — never a fake success.
- Open Machine Operator. Type `help`. Expect the capability list with
  `[execution_status: real|unavailable]` annotations on each subsequent run.

If any surface lies (success without execution, missing `execution_status`,
inferred state instead of verified), stop and document it as a finding.

---

## 7. What this runbook does NOT do

- Does not start Docker for the runner. CODE apply path runs in `stub` mode by
  default; flip `APPLY_EXECUTION_MODE=real` in `.env` only after Docker is up
  and verified.
- Does not configure the OpenClaw gateway. `OPENCLAW_GATEWAY_URL` defaults to
  a local stub. Real Tier-A wiring is out of scope for the local runbook.
- Does not initialize Notion / Sheets schemas. Use the dedicated schema-ops
  endpoints (admin-token gated) only after the surfaces are confirmed honest.
