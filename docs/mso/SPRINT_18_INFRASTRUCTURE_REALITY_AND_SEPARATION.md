# Sprint 18: Infrastructure Reality and Separation

## Goal

Make the control plane more operationally real without introducing distributed
complexity or weakening the canonical governance architecture.

This sprint focuses on:

- scheduler decoupling readiness
- lock backend abstraction
- maintenance action surfaces
- richer operational health
- tighter service boundaries
- internal operational signals

## Core Design

### 1. Scheduler logic is now separate from scheduler hosting

The scheduler no longer owns the maintenance logic directly.

Instead:

- `control_plane.scheduler` is responsible for hosting and timing
- `control_plane.maintenance` owns the actual maintenance actions

This means the same maintenance cycle can now be:

- run automatically by the in-process scheduler
- triggered manually by an authenticated admin action
- reused later by a different scheduler host/process with minimal changes

### 2. Lock backend abstraction is explicit

The lock manager now depends on an explicit backend interface instead of
embedding a single hard-coded implementation.

Current state:

- `LocalProcessLockBackend` is the default
- `ControlPlaneLockManager` owns lease semantics and ownership checks
- future multi-process backends can replace the backend without changing admin
  service code

This keeps locking explicit and replaceable while preserving current
process-local behavior.

### 3. Maintenance actions are now operable

The control plane exposes governed maintenance surfaces for:

- running a maintenance cycle
- forcing token cleanup
- inspecting active locks
- forcing lock-slot cleanup

These actions remain:

- authenticated
- role-checked
- traceable through `ControlPlaneRequest`
- auditable via persisted maintenance records

### 4. Operational health is richer and more actionable

`GET /health` now includes:

- service identity and mode
- scheduler status
- token hygiene summary
- lock summary
- recent maintenance records
- recent operational signals
- warnings and degraded status where appropriate

This keeps health practical and structured, without becoming a full monitoring
system.

### 5. Operational signals are persisted

The control plane now emits simple structured signals for meaningful operational
conditions.

Current examples:

- scheduler failure
- no stale locks cleaned on forced lock cleanup
- hygiene warnings surfaced from maintenance

Signals remain internal for now. They are persisted and visible, but they are
not yet external notifications.

## New / Updated Surfaces

### Admin maintenance reads

- `GET /admin/maintenance`
- `GET /admin/maintenance/locks`

### Admin maintenance writes

- `POST /admin/maintenance/run`
- `POST /admin/maintenance/tokens/cleanup`
- `POST /admin/maintenance/locks/cleanup`

### Health

- `GET /health`

Now includes recent maintenance and signals in addition to scheduler, token,
store, and lock status.

## Persistence

New persisted record kinds:

- control plane maintenance records
- control plane operational signals

Windows-safe record filename handling was added so persisted record IDs no
longer break when they contain characters like `:`.

## Known Limitations

- Scheduler hosting is still in-process.
- Lock backend is still process-local.
- Maintenance signals are internal only; no external alert transport exists.
- This sprint does not introduce multi-process coordination or deployment
  orchestration.

## Next Likely Step

Sprint 19 should focus on stronger operational realism such as:

- clearer service supervision/runtime conventions
- better maintenance retention and history querying
- stronger lock backend replacement path if needed
- more formal signal review/acknowledgement workflow
