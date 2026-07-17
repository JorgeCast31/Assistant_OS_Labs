# External Worker Capability Probe v0

Status: v0 (passive local observation only). Reports whether the allow-listed Claude Code and
Codex command names are present on PATH.

> command present ≠ authenticated · installed ≠ model reachable · installed ≠ assignable ·
> observation ≠ authorization · observation ≠ dispatch · observation ≠ execution.

## Module

`assistant_os/mso/external_worker_capability_probe.py` — stdlib only. It performs executable
lookup for the fixed command names `claude` and `codex`. It does not run either command, accept
arbitrary commands, inspect auth, serialize environment values or executable paths, call a
model/SDK/API, access the network, read or write file contents, create worktrees, register workers,
route, dispatch, execute, mint tokens or grant authority. The default resolver consults PATH/PATHEXT
and local filesystem metadata solely to determine whether each fixed command is present.

The optional CLI is observational and prints one JSON snapshot:

```text
python -m assistant_os.mso.external_worker_capability_probe
```

`can_dispatch`, `can_execute`, `authority_granted`, `model_call_performed`, `process_spawned`,
`network_used` and `workspace_mutated` are always `false`.

## States

- `INSTALLED_UNVERIFIED`: an executable lookup returned a path; that path is never serialized.
- `NOT_FOUND`: no PATH entry was found.
- `ERROR`: executable lookup raised; the raw error is suppressed.

Every observation reports `auth_status=NOT_CHECKED` and `round_trip_status=NOT_RUN`.

## Safety invariants

1. Fixed lookup list only. 2. No subprocess. 3. No model, SDK, HTTP or network call. 4. No auth
inspection. 5. PATH/PATHEXT may be consulted, but no environment value is serialized. 6. No
executable path serialized. 7. Lookup errors and deserialized observations are fail-closed and
sanitized. 8. No fallback worker. 9. No file-content reads/writes or input mutation. 10.
Deterministic worker ordering. 11. Fixed lookup/time inputs produce stable JSON. 12. Authority,
dispatch and execution flags remain false after forged deserialization, which is downgraded to
`ERROR/NONE`. 13. Observations never modify `WorkerProfile` or its status.

## Relationship to orchestration preview

This snapshot may be shown beside an `OrchestrationPreview` as separate evidence. It must not be
used to auto-promote a worker to `AVAILABLE`, prove model reachability or authorize handoff. The
preview remains simulation-only and keeps `can_dispatch=false` and `can_execute=false`.

## Out of scope

Version checks, authentication checks, model round-trips, provider/account status, cost data,
worker registration, routing mutation, subprocess hardening, handoff, Runner, Police, capability
tokens, endpoints, UI and background scheduling.
