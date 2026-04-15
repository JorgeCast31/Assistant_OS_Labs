# Sprint 13: Operator Identity and Admin API

## Goal

Introduce a formal, governed, operator-facing access layer for restriction control without bypassing kernel/governance authority.

## What Changed

- Added a typed `OperatorIdentity` model with explicit roles:
  - `viewer`
  - `reviewer`
  - `admin`
- Added explicit operator authorization checks:
  - operator must exist
  - operator must be active
  - role must allow the requested action
- Added a dedicated localhost-only admin API protected by `X-Assistant-Admin-Token`.
- Added restriction review state markers:
  - `unreviewed`
  - `acknowledged`
  - `actioned`
- Hardened override so it is:
  - admin-only
  - reason-required
  - state-validated
  - traceable through the operator action ledger

## Operator Model

Bootstrap identities live in `assistant_os/mso/operator_identity.py`:

- `ops-viewer`
- `ops-reviewer`
- `ops-admin`

This is intentionally minimal for Sprint 13. It provides a real identity and role model without introducing enterprise IAM.

## Authorization Rules

- `viewer`
  - read admin surfaces only
- `reviewer`
  - read admin surfaces
  - `acknowledge_restriction`
- `admin`
  - all read access
  - `acknowledge_restriction`
  - `clear_restriction`
  - `extend_restriction`
  - `override_restriction`

Failures are fail-closed.

## Admin API

All admin routes require:

- `X-Assistant-Admin-Token`
- localhost caller
- valid operator identity

Reads:

- `GET /admin/restrictions`
- `GET /admin/restrictions/{restriction_id}`
- `GET /admin/restrictions/{restriction_id}/history`
- `GET /admin/operator-actions`

Writes:

- `POST /admin/restrictions/{restriction_id}/acknowledge`
- `POST /admin/restrictions/{restriction_id}/clear`
- `POST /admin/restrictions/{restriction_id}/extend`
- `POST /admin/restrictions/{restriction_id}/override`

Write body requirements:

- `operator_id`
- `reason`

Additional write fields:

- `extend`
  - `expires_at`
- `override`
  - optional `override_mode`
  - optional `expires_at`

## Restriction Review Workflow

Restrictions now carry explicit review state:

- `unreviewed`
  - default when created from a security response
- `acknowledged`
  - human reviewer has seen it
- `actioned`
  - human operator performed a lifecycle action

Review state is separate from restriction lifecycle state. This preserves:

- restriction status
- review visibility
- operator traceability

## History / Trace Linkage

Restriction history now reconstructs:

- restriction record
- originating security response
- source worker security events
- operator action ledger entries

## Query / Visibility

Operator action queries support:

- filter by operator
- filter by restriction
- filter by action type

Diagnostics now also expose bootstrap operator identities so operators can see who is recognized by the current runtime.

## Residual Limits

- Operator identities are bootstrap/local, not externally managed.
- There is no dedicated admin UI yet.
- There is no operator authentication transport beyond admin token + operator identity.
- Multi-operator coordination is still intentionally minimal.

## Next Likely Step

Sprint 14 should add:

- operator authentication/authorization transport hardening
- richer admin read models
- optional API transport separation/module extraction
- durable operator directory management
