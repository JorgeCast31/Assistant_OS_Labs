# Sprint 15: Control Plane Operationalization

## Goal

Turn the control plane from a logical module split into an independently runnable service with formal token issuance, strict token validation, and a cleaner trust boundary between control and execution layers.

## What Changed

- The control plane is now independently runnable through:
  - `assistant_os/control_plane/admin_server.py`
- Added a dedicated token service:
  - `assistant_os/control_plane/token_service.py`
- Added a typed `ControlPlaneRequest` boundary.
- Added control-plane token audit visibility:
  - active tokens
  - revoked tokens
  - expiration
  - last-used timestamps
- Tightened token comparison using constant-time hash comparison.
- Kept raw tokens out of core-facing paths; only `OperatorContext` crosses the service boundary.

## Independent Control Plane

The control plane server now has:

- dedicated host/port config
- standalone startup path
- CLI entry behavior

Config:

- `CONTROL_PLANE_HOST`
- `CONTROL_PLANE_PORT`

CLI behaviors:

- run the service:
  - `python -m assistant_os.control_plane.admin_server`
- issue a one-time token and exit:
  - `python -m assistant_os.control_plane.admin_server --issue-token --operator-id ops-admin`

## Token System

### Storage

Tokens are never persisted in plain text.

Persisted token metadata includes:

- `token_id`
- `operator_id`
- `issued_at`
- `expires_at`
- `is_active`
- `token_hash`
- `last_used_at`
- `revoked_at`

### Issuance

Issuance is now formalized through `token_service.py`.

Properties:

- secure random token
- one-time raw token visibility
- hashed persistence
- issuance metadata

### Validation

Validation remains strict and fail-closed:

- token must exist
- token must be active
- token must not be expired
- hash must match

### Audit

Audit view now returns:

- `tokens`
- `active_tokens`
- `revoked_tokens`
- expiration times
- last used timestamps

Sanitization:

- `token_hash` is blanked in outward-facing audit payloads
- raw token is never returned by audit endpoints

## Separation Boundary

Raw bearer token:

- only enters `admin_server`
- is validated there / in control-plane auth helpers
- is converted into `OperatorContext`

Core/admin business logic only receives:

- `OperatorContext`
- `ControlPlaneRequest`

This preserves a clean trust boundary:

- control plane owns token handling
- core never sees raw token material

## ControlPlaneRequest

`ControlPlaneRequest` now captures:

- `request_id`
- `operator_context`
- `action`
- `payload`
- `created_at`

This gives an explicit interface between:

- HTTP control plane transport
- governed admin service logic

## Concurrency

Per-restriction locking remains in place.

Behavior:

- conflicting restriction actions fail closed with `409 Conflict`

This is still process-local by design.

## Residual Limits

- Token issuance is still CLI/internal-service mediated, not yet tied to a richer operator bootstrap workflow.
- The control plane is independently runnable, but not yet a separately deployed trust domain by default.
- Locking is still per-process, not distributed.
- There is still no signed token scheme or external identity provider.

## Likely Next Step

Sprint 16 should likely address:

- deployment/runtime isolation of control plane
- richer operator bootstrap/rotation workflows
- stronger credential formats or signed tokens
- distributed locking if the control plane becomes multi-instance
