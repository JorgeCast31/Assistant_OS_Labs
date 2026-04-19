# MACHINE_OPERATOR A3: Transport Hooks and Boundary Rules

This document defines the Windows-side preparation seam for the future
Windows -> Ubuntu/OpenClaw trust boundary.

It does not implement Linux-side verification, mTLS, PKI, signatures, or
secret-backed execution.

## Current repo-side transport surface

- Gateway URL is configured through `OPENCLAW_GATEWAY_URL`.
- Timeout is configured through `OPENCLAW_TIMEOUT_SECONDS`.
- The MACHINE_OPERATOR adapter translates the canonical request into one narrow
  OpenClaw execute payload and keeps transport details inside the adapter.
- Current live lane scope remains bounded browser execution only.
- `require_credentials` remains `False`.

## Supported transport auth modes

Repo-side configuration now supports:

- `OPENCLAW_GATEWAY_AUTH_MODE=disabled`
- `OPENCLAW_GATEWAY_AUTH_MODE=header_token`

Additional required fields when `header_token` is selected:

- `OPENCLAW_GATEWAY_AUTH_HEADER_NAME`
- `OPENCLAW_GATEWAY_AUTH_TOKEN_ENV_VAR`

The adapter reads the actual token value at runtime from the env var named by
`OPENCLAW_GATEWAY_AUTH_TOKEN_ENV_VAR`.

If `header_token` is configured but the header name or token is missing or
invalid, the adapter fails closed before backend dispatch.

## Outbound boundary rules

Allowed to cross the boundary:

- `intent_id`
- `correlation_id`
- `capability_name`
- request `arguments`
- bounded `budget`
- policy refs needed for bounded execution:
  - `policy_decision_ref`
  - `allowlist_refs`
  - `constraints`
  - `approval_mode`
- execution controls:
  - `mode`
  - `reuse_session`
  - `persist_profile`
  - `allow_side_effects`
  - `require_credentials`
  - `timeout_seconds`
  - adapter-private `workflow_execution_id`
  - `close_session`
- one optional transport auth header when `header_token` mode is enabled

Not transmitted:

- approval artifact contents
- `secret_refs`
- `governance_ref`
- `requested_side_effects`
- raw operator/admin auth material

## Inbound boundary rules

Canonical response material may include:

- observation
- evidence refs
- consumed budget
- side-effect declarations, which still must remain empty for this lane
- adapter-generated observability metadata

Backend-supplied free-form `metadata` does not currently cross this boundary.

Transport-private fields are stripped from backend observation data and
backend-supplied metadata, including:

- `workflow_execution_id`
- gateway URL fields
- transport auth fields
- approval fields
- `secret_refs`
- `require_credentials`

## No-log and redaction rules

The following must never be logged or surfaced raw in MACHINE_OPERATOR adapter
results:

- the transport auth token value
- approval artifact contents
- `secret_refs`
- transport-private workflow/session identifiers outside adapter-private use

If a token-like value is encountered in transport-error text or backend
observation text, the adapter redacts it before it reaches audit/result
surfaces.

## Still deferred after A3

- Linux-side auth verification
- mTLS
- PKI or signature services
- backend attestation
- secret delivery into OpenClaw
- secret-enabled MACHINE_OPERATOR capabilities
