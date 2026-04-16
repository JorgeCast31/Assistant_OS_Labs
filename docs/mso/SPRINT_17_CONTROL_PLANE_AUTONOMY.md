# Sprint 17: Control Plane Autonomy

## Goal

Make the control plane operationally autonomous without changing the canonical
execution architecture or duplicating governance logic.

This sprint adds:

- autonomous control-plane maintenance behavior
- a lightweight internal scheduler
- automatic token expiration enforcement
- a stronger, replaceable lock abstraction
- extended health/status visibility
- clearer operational logging

## Architecture Outcome

The control plane remains a separate operator-facing service. It still performs
authentication, authorization, and governed operator actions through explicit
contracts, but it can now maintain part of its own operational hygiene without
relying on external schedulers or ad hoc manual cleanup.

The orchestrator remains the only execution entrypoint.
The kernel remains the sole authority for execution validation and capability
issuance.

## Scheduler Design

The new `ControlPlaneScheduler` is a lightweight daemon thread created by the
standalone admin server.

Responsibilities:

- clean up expired operator tokens
- clean up expired MSO store records
- prune unused local lock slots
- report run metadata and warnings

The scheduler:

- has a configurable interval
- records `started_at`, `last_started_at`, `last_finished_at`, and `run_count`
- keeps the last run summary in memory for health/status surfaces
- does not execute domain actions
- does not modify governance rules outside existing token/store lifecycle paths

## Token Auto-Management

Automatic maintenance now includes:

- token expiration cleanup
- token cleanup logging
- token counts in health/status

Token management remains explicit and auditable:

- issue
- rotate
- revoke
- cleanup

Expired-token cleanup now has two modes:

1. explicit operator-triggered cleanup via admin API
2. automatic scheduler-driven cleanup

Both preserve hashed storage only. Raw bearer tokens remain one-time visible.

## Lock Model

The control plane lock abstraction now provides:

- explicit acquire
- explicit release
- ownership tracking
- timeout-ready signature
- active lease inspection
- cleanup of unused lock slots

Current locking is still process-local by design, but the abstraction is now a
clean replacement point for future multi-process or distributed implementations.

## Health / Status

`GET /health` now exposes:

- service status
- uptime
- process id
- scheduler status
- token counts
- active locks
- MSO store status
- warnings

Warnings are intentionally simple and deterministic, for example:

- scheduler disabled
- scheduler not running
- expired active tokens present
- expired store records present

## Observability

Structured logging was added for:

- control-plane server startup/shutdown
- scheduler start/stop/run
- token issue/revoke/rotate/cleanup
- bootstrap completion
- HTTP access
- lock conflicts

This remains lightweight and local, without introducing new external logging
infrastructure.

## Known Limitations

- Scheduler state is in-memory and resets on restart.
- Locking remains process-local.
- The control plane is standalone-runnable, but not yet isolated by deployment
  topology or IPC boundary stronger than the current service split.
- Automatic maintenance is intentionally limited to credential/store hygiene,
  not broader policy automation.

## Next Likely Step

Sprint 18 should focus on stronger operational separation, such as:

- clearer service bootstrap/deploy conventions
- stronger persistence-backed lock replacement if needed
- richer operational diagnostics and alert surfaces
- more formal maintenance policy controls without adding uncontrolled behavior
