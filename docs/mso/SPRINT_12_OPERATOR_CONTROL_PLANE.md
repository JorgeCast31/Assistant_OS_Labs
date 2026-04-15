# Sprint 12: Operator Control Plane

## Objective

Sprint 12 adds a structured operator-facing control plane over dynamic restrictions without weakening canonical governance.

The goal is not to bypass the system. The goal is to make restrictions:

- visible
- explainable
- queryable
- manually controllable through audited actions

## What Was Added

### 1. Active Restriction Model

Restrictions are now explicit records instead of being implied only by temporary capability changes.

Each restriction includes:

- `restriction_id`
- `type`
- `target`
- `scope`
- `source_events`
- `created_at`
- `expires_at`
- `status`
- `reason`
- `trace_id`

Additional linkage fields connect the restriction to:

- originating security response
- enforcement kind (`grant` or `revocation`)
- enforcement reference
- last lifecycle transition

### 2. Restriction Lifecycle

The restriction lifecycle is now explicit:

- `ACTIVE`
- `EXPIRED`
- `CLEARED`
- `EXTENDED`
- `OVERRIDDEN`

Supported transitions:

- `ACTIVE -> EXPIRED` automatically
- `ACTIVE/EXTENDED -> CLEARED` manually
- `ACTIVE/EXTENDED -> EXTENDED` manually
- `ACTIVE/EXTENDED -> OVERRIDDEN` manually

### 3. Operator Actions

Operator actions are now structured and ledgered:

- `acknowledge_restriction`
- `clear_restriction`
- `extend_restriction`
- `override_restriction`

Each action requires:

- `operator_id`
- `reason`
- `target_restriction_id`

Each action produces an `OperatorActionRecord`.

### 4. Governance Integration

Operator actions do not bypass governance.

They operate only through:

- validated restriction state
- existing capability registry primitives
- explicit persisted transitions

This means:

- clears remove the underlying temporary grant/revocation
- overrides replace the underlying restriction with a controlled temporary grant when requested
- extensions refresh the underlying temporary grant window when applicable

### 5. Query Layer

The system now supports:

- active restrictions
- expired restrictions
- restrictions by type
- restrictions by source event
- recent operator actions
- restriction history

### 6. Diagnostics Extension

Diagnostics now exposes:

- active restrictions
- recent expired restrictions
- recent restrictions
- recent operator actions
- recent security responses
- event -> restriction -> response -> operator-action linkage surfaces

## Design Notes

- restrictions remain descriptive and auditable
- capability policy remains authoritative for actual execution behavior
- operator actions remain explicit mutations with reasons and trace IDs
- no hidden state mutation was introduced

## Residual Limits

- there is not yet a dedicated operator authentication/role model beyond explicit `operator_id`
- there is not yet a separate admin transport/API surface
- override policy is intentionally conservative and narrow

## Suggested Sprint 13 Focus

- operator identity/role validation
- durable admin-facing APIs
- richer restriction history views
- notification or inbox surfacing for newly created restrictions
