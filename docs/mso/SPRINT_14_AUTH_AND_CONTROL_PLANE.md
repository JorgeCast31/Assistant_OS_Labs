# Sprint 14: Auth and Control Plane Separation

## Goal

Replace static admin-token trust with structured operator auth tokens and move restriction-control endpoints into a dedicated control plane.

## What Changed

- Added `OperatorAuthToken` and `OperatorContext`.
- Added opaque operator tokens with:
  - issuance
  - expiration
  - revocation
  - persistence
- Added token validation that fails closed when a token is:
  - missing
  - invalid
  - inactive
  - expired
- Added a dedicated control plane server:
  - `assistant_os/control_plane/admin_server.py`
- Added a service layer:
  - `assistant_os/control_plane/admin_service.py`
- Removed admin route exposure from the user-facing webhook server.
- Added basic concurrency protection for conflicting actions over the same restriction.

## Auth Model

### OperatorIdentity

Roles remain:

- `viewer`
- `reviewer`
- `admin`

Bootstrap identities still live in `assistant_os/mso/operator_identity.py`.

### OperatorAuthToken

Each token records:

- `token_id`
- `operator_id`
- `issued_at`
- `expires_at`
- `is_active`

Additional implementation metadata:

- `token_hash`
- `last_used_at`
- `revoked_at`

Raw token values are returned only at creation time. Persisted records keep the hash, not the clear token.

### OperatorContext

Every authenticated request creates a request-scoped context:

- `operator_id`
- `role`
- `token_id`
- `request_id`
- `authenticated_at`

This context is propagated into operator action records for traceability.

## Control Plane Separation

Admin routes no longer live on `assistant_os/webhook_server.py`.

They now live on the dedicated control plane server:

- `GET /admin/restrictions`
- `GET /admin/restrictions/{restriction_id}`
- `GET /admin/restrictions/{restriction_id}/history`
- `GET /admin/operator-actions`
- `POST /admin/restrictions/{restriction_id}/acknowledge`
- `POST /admin/restrictions/{restriction_id}/clear`
- `POST /admin/restrictions/{restriction_id}/extend`
- `POST /admin/restrictions/{restriction_id}/override`

Authentication transport:

- `Authorization: Bearer <operator_token>`

The user-facing webhook server no longer serves these routes.

## Admin Service Layer

`assistant_os/control_plane/admin_service.py` is now the single control-plane service boundary.

Responsibilities:

- authenticate bearer tokens
- validate operator role
- build `OperatorContext`
- apply restriction actions through governed modules
- expose read models for restrictions and action history
- enforce conflict protection on the same restriction

The admin HTTP handler does not call MSO modules directly for business logic.

## Token Lifecycle

Implemented:

- `create_operator_token()`
- `revoke_token()`
- `list_operator_auth_tokens()`

Service-level wrappers:

- `mint_operator_token()`
- `revoke_operator_token()`
- `list_operator_tokens_view()`

## Concurrency Protection

Restriction-changing actions now use a per-restriction lock.

Behavior:

- if no conflicting action is running, the action proceeds
- if another action is in-flight for the same restriction, the control plane returns `409 Conflict`

This is intentionally basic and fail-closed.

## Traceability

Operator action ledger records now include:

- `operator_id`
- `operator_role`
- `token_id`
- `request_id`
- `trace_id`

This preserves linkage between:

- authenticated request
- restriction action
- restriction lifecycle state

## Residual Limits

- Token issuance is still internal/module-level, not exposed through a dedicated operator bootstrap flow.
- There is no external IAM provider or signed token scheme in this sprint.
- Concurrency protection is per-process only.
- Control plane and user API are separated by server/module boundary, not by deployment topology yet.

## Likely Next Step

Sprint 15 should likely focus on:

- control-plane deployment separation
- operator bootstrap / token issuance workflow
- signed tokens or stronger credential model
- per-process or distributed lock evolution if needed
