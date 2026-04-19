# MACHINE_OPERATOR A2: Secret Stance and Approval Artifact

## Scope

This note defines the current authoritative security posture for the
`MACHINE_OPERATOR` lane after Sprint A2.

## Secret Stance

Current stance: secrets are structurally represented but operationally
prohibited for `MACHINE_OPERATOR`.

That means:

- Current live capabilities remain `requires_secrets=False`.
- Non-empty `policy_context.secret_refs` are rejected fail closed.
- Any future policy path that would require secrets is rejected fail closed.
- Gateway payloads must continue to state `require_credentials=False`.

This sprint does not remove `secret_refs` from the contract. The field remains
present so the contract can evolve later without widening the current lane.

## Approval Artifact

Approval is no longer a loose non-empty token. The canonical request field is
`approval`, which contains a deterministic local approval artifact.

Required fields:

- `approval_id`
- `approved_for`
- `capability_scope`
- `expires_at`
- `issued_by`

Optional field:

- `reason`

Validation rules:

- `approved_for` must be `single_step` or `workflow`.
- `capability_scope` must be a non-empty ordered `list[str]`.
- `expires_at` must be an ISO-8601 timestamp with a timezone offset.
- Approval is required only when policy says `approval_mode="required"`.
- Required approval is rejected fail closed if missing, malformed, expired, or
  scoped to a different request kind or capability sequence.

Workflow rule:

- Workflow approval is validated at the workflow boundary against the full
  ordered capability sequence.
- Internal adapter step revalidation derives a narrowed single-step approval
  view from the already validated workflow artifact. This does not widen
  backend authority and is not sent to OpenClaw.

## Not Solved In A2

This sprint does not implement:

- backend transport authentication
- Linux trust-boundary enforcement
- cryptographic signatures
- external approval services
- secret delivery into OpenClaw
- new MACHINE_OPERATOR capabilities
