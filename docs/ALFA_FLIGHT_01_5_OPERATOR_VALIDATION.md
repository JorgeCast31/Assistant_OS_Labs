# ALFA-FLIGHT-01.5 — Operator Validation Form

> Audit cannot be self-completed. The Cowork bash sandbox is unavailable in
> this session, so all backend tests, the UI typecheck, and the manual UI
> walkthrough must be executed on your workstation. Paste the literal output
> back into chat and I will produce the final GO/NO-GO verdict.
>
> **Do not edit code while running this form.** This is a NO-CODE audit.

---

## Phase 1 — PRECHECK

Run from the repo root:

```bash
git status
git branch --show-current
git fetch origin
git diff origin/main --stat
```

Fill in:

```
git status output:
[paste]

git branch --show-current:
[paste]

git diff origin/main --stat:
[paste]
```

**Expected.** Working tree clean except for the ALFA-FLIGHT-01.5 changes
on the `cowork/alfa-flight-01-5-operability-surface` branch. The diffstat
should show only the files in §3 of `docs/ALFA_FLIGHT_01_5_REPORT.md`.

---

## Phase 2 — Backend tests

```bash
python -m pytest tests/test_s01_freeze_system.py tests/test_s02_admin_token_hardening.py tests/test_codeops_endpoints.py tests/test_mso_governance.py tests/test_mo_agent_registry.py tests/test_surface_behavior_layer.py tests/test_backend_operability_endpoints.py -v
```

Paste:

```
=================== test session starts ===================
[paste full output through the final summary line]
```

**Expected.**

- `test_s01_freeze_system.py`     : all PASS
- `test_s02_admin_token_hardening`: all PASS
- `test_codeops_endpoints.py`     : all PASS
- `test_mso_governance.py`        : all PASS
- `test_mo_agent_registry.py`     : all PASS
- `test_surface_behavior_layer`   : all PASS (incl. `test_system_chat_unknown_text_returns_none`)
- `test_backend_operability_endpoints.py::test_chat_process_surface_is_preserved_in_metadata_and_audit_without_changing_execution_mode` — explicit canary; MUST pass.

---

## Phase 3 — UI typecheck

```bash
cd ui
npx tsc --noEmit
```

Paste:

```
[paste]
```

**Expected.** Zero errors. Any error is a NO-GO.

---

## Phase 4 — Manual UI walkthrough

Bring the stack up per `docs/LOCAL_RUNBOOK.md` (three terminals: webhook,
code API, UI). Then perform each test and fill the form.

### TEST A — System status (no UNKNOWN post-init)

Open `http://localhost:3000` → System view.

```
[A.1] TopHUD operational badge label after first poll: ____________
      (must be NORMAL / DEGRADED / FROZEN / OFFLINE — never the word UNKNOWN)

[A.2] CODE API service card label:        ____________  (Online / Offline)
[A.3] Webhook service card label:         ____________  (Online / Offline)
[A.4] Endpoints panel — any row showing "Unknown"?  yes / no
[A.5] Stop the webhook server (Terminal A). Wait ~25s for next poll.
      Webhook card label now:              ____________
      Operational mode badge label now:    ____________  (must read OFFLINE, not UNKNOWN)
[A.6] Restart webhook. After next poll, mode returns to NORMAL?  yes / no
```

### TEST B — Freeze, both states

#### B.1 — `ASSISTANT_ADMIN_TOKEN` UNSET

Edit `ui/.env.local`, comment out `ASSISTANT_ADMIN_TOKEN`, restart UI dev
server. Click "Freeze System" → Confirm.

```
Result panel says:
[paste verbatim — should be a multi-line Blocked: block]

Contains "Blocked:"             ?  yes / no
Contains "domain=SYSTEM"        ?  yes / no
Contains "action=governance.freeze" ?  yes / no
Contains "reason=missing_ui_admin_token" ?  yes / no
Contains "suggestion=Set ASSISTANT_ADMIN_TOKEN" ?  yes / no
Operational mode after the click: ____________ (must NOT be FROZEN)
```

Restore `ASSISTANT_ADMIN_TOKEN` in `ui/.env.local`. Restart UI.

#### B.2 — Tokens configured + matching

Click "Freeze System" → Confirm.

```
Result panel says:
[paste verbatim — should say "System is now FROZEN" or similar]

Operational mode after the click: ____________ (must be FROZEN)
```

Send any chat message. Backend must reject (HTTP 503 from /chat/process).

```
Chat reply (or error):
[paste]
```

Unfreeze the system via the backend admin path (curl /admin/governance/mode
with mode=NORMAL) so the next tests can run.

#### B.3 — Tokens configured but mismatched

Set `ASSISTANT_ADMIN_TOKEN` to a value that does NOT match the backend
`WEBHOOK_ADMIN_TOKEN`. Restart UI. Click Freeze.

```
Result panel says:
[paste]

Contains "Admin token rejected" or "403"? yes / no
Operational mode unchanged?              yes / no
```

Restore matching tokens; restart UI.

### TEST C — System Chat does NOT leak action artefacts

System view → switch to System Chat. Send each input, paste the assistant
reply.

```
[C.1] Input: "hola"
Reply:
[paste]

[C.2] Input: "quiero usar machine operator"
Reply:
[paste]
Contains the literal text "ENERGY"  ?  yes / no   ← MUST be no
Contains the literal text "COMMAND" ?  yes / no   ← MUST be no
Contains "Blocked:" or redirects to MSO/Machine Operator?  yes / no

[C.3] Input: "crea una tarea"
Reply:
[paste]
Plan rendered visibly in the System Chat bubble?  yes / no   ← MUST be no
Reply contains either curated text OR a Blocked: block?  yes / no
```

### TEST D — MSO Direct does not fake execution

```
[D.1] Input: "hola"
Reply:
[paste]

[D.2] Input: "quiero buscar imagen en chrome"
Reply:
[paste]
Reply claims a real action was performed without execution_status: real?  yes / no   ← MUST be no
Reply contains executionStatus badge?  yes / no
Badge value: ____________ (real / stub / unavailable / partial)
If badge is "real", does the backend `governance_trace.decision` confirm ALLOW?
[paste decision if visible]
```

### TEST E — Machine Operator honesty

Switch to Machine Operator console.

```
[E.1] Input: help
Output:
[paste]
Contains "browser.snapshot, browser.screenshot, browser.read_visible_text, browser.navigate"?  yes / no

[E.2] Input: snapshot
Output:
[paste]
First line begins with "[execution_status: ..."?  yes / no
Status reported: ____________
If gateway is not running, status MUST be "unavailable" — fake "real" is a NO-GO.

[E.3] Input: bogus_capability
Output:
[paste]
Says "Unknown capability" or similar honest error?  yes / no
```

---

## Phase 5 — Coherence questions for the auditor (you)

Please answer yes/no/observation to each. These cannot be answered without
having actually used the system.

```
[Q1] Did any UI surface show "UNKNOWN" as a final state (not a transient
     init)?                                                       yes / no
[Q2] Did Freeze ever return ok=true while the operational_mode did not
     transition to FROZEN?                                        yes / no
[Q3] Did System Chat ever render a plan or a confirmation prompt?  yes / no
[Q4] Did MSO Direct ever claim "completed" without a backend execution
     trace?                                                        yes / no
[Q5] Did Machine Operator ever show "[execution_status: real]" while
     the OpenClaw gateway was not actually reachable?             yes / no
[Q6] Were there any "ENERGY / COMMAND" artefacts anywhere in the
     conversation history?                                         yes / no

If ANY answer is "yes" except where the form explicitly allows it, the
verdict is NO-GO regardless of test results.
```

---

## Submitting the validation

Paste the entire filled form back into chat. I will then produce
`docs/ALFA_FLIGHT_01_5_AUDIT.md` with:

- PASS/FAIL per phase
- consolidated findings
- final GO / NO-GO (no conditionals — strict per the brief).
