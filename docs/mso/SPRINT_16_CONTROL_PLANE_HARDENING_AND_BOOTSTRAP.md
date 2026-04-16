# Sprint 16: Control Plane Hardening and Bootstrap

## Goal

Make the standalone control plane operationally durable without weakening the
existing governance or canonical execution boundaries.

This sprint adds:

- formal control-plane bootstrap
- stronger token lifecycle hygiene
- explicit credential policy
- cleaner standalone readiness
- safer coordination semantics
- better operator/token audit visibility

## Key Decisions

### 1. Bootstrap is explicit and guarded

Bootstrap is now a first-class control-plane action.

The bootstrap path:

1. validates that the requested operator exists
2. requires the operator role to be `admin`
3. refuses to run if bootstrap was already completed
4. refuses to run if active admin credentials already exist
5. issues a bounded initial token with TTL
6. records a persistent bootstrap event

This keeps initial trust establishment explicit and auditable.

### 2. Token lifecycle is now operationally governed

Operator tokens now support:

- issue
- list/audit
- revoke
- rotate
- expiration cleanup

Stored token metadata now includes:

- `revoked_at`
- `revoked_by`
- `rotated_from`
- `rotation_reason`
- `issued_reason`

Raw bearer secrets remain one-time visible only. Persisted records store only a
token hash.

### 3. Credential policy is explicit

The control plane now enforces a minimal credential policy from config:

- default token TTL
- maximum token TTL
- maximum active tokens per operator

The policy is intentionally small and deterministic. Requests that exceed the
policy are clamped or rejected through the governed token lifecycle.

### 4. Control plane is more deployment-ready

The control plane keeps its own host/port config and can now be started cleanly
in standalone mode through its own CLI entrypoint.

Operational additions:

- explicit health endpoint
- distinct control-plane service identity
- standalone token issuance mode
- standalone bootstrap mode

This prepares the service for stronger deployment separation without requiring a
distributed redesign.

### 5. Locking semantics are explicit

Restriction actions now use a named lock abstraction instead of ad hoc local
locks. The abstraction provides:

- clear conflict semantics
- safe release behavior
- a future replacement point for multi-process or distributed locking

Current behavior remains process-local and fail-closed on conflicts.

## New Surfaces

### Standalone bootstrap

Example:

```powershell
python -m assistant_os.control_plane.admin_server `
  --bootstrap `
  --operator-id ops-admin `
  --ttl-minutes 60 `
  --reason "Initial control-plane bootstrap"
```

### Standalone token issuance

```powershell
python -m assistant_os.control_plane.admin_server `
  --issue-token `
  --operator-id ops-admin `
  --ttl-minutes 60
```

### Health endpoint

`GET /health`

Returns control-plane identity and listen configuration for readiness checks.

### Admin audit endpoints

- `GET /admin/tokens`
- `GET /admin/operators`
- `GET /admin/bootstrap`
- `POST /admin/tokens/revoke`
- `POST /admin/tokens/rotate`
- `POST /admin/tokens/cleanup`

## Security Properties Preserved

- Operator actions still require bearer authentication.
- Operator actions still require role-based authorization.
- Operator actions still require explicit reason where applicable.
- Kernel/governance authority is unchanged.
- Core never receives raw bearer tokens; it only sees `OperatorContext` and
  `ControlPlaneRequest`.

## Known Limitations

- Locking is still process-local, not distributed.
- Token bootstrap is local/admin-operated, not externally integrated.
- The control plane is standalone-runnable, but not yet fully isolated by
  deployment topology.
- Token cleanup is explicit/triggered, not a background scheduler.

## Next Likely Step

Sprint 17 should focus on stronger operational separation, such as:

- more formal bootstrap and rotation procedures
- stronger deployment isolation
- richer audit review flows
- eventual replacement of process-local locks with a stronger coordination
  backend when needed
