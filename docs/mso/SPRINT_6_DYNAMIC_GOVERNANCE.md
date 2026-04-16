# Sprint 6: Dynamic MSO Governance

Sprint 6 moves MSO governance from per-request control into system-aware control.

The orchestrator still owns structural execution.
The MSO now adapts governance using:

- operational mode
- dynamic capability state
- explicit anomaly signals
- current system snapshot

This is still conservative and deterministic.

## What changed

### 1. Operational Mode

System-wide operational posture is now modeled explicitly:

- `NORMAL`
- `RESTRICTED`
- `DEGRADED`

Current source options:

- manual override
- derived from anomaly severity

Current behavior:

- `NORMAL`: base Sprint 5 governance
- `RESTRICTED`: auto execution is tightened toward confirmation
- `DEGRADED`: stronger hardening, especially against permissive auto execution

The operational mode is now part of `SystemStateSnapshot`.

### 2. Dynamic Capability Lifecycle

Capability control now supports:

- static capability policy
- temporary grants
- explicit revocations

Current capabilities can now answer:

- whether an action is statically allowed
- whether it was temporarily granted
- whether it is actively revoked
- what source produced the current capability verdict

This is intentionally simple and in-memory for Sprint 6.

### 3. Anomaly Engine

Module:

- `assistant_os/mso/anomaly_engine.py`

Produces deterministic `AnomalySignal` values from observable state.

Current input signals include:

- recent failures by domain
- blocked task spikes
- repeated governance blocks
- repeated governance degradations
- repeated sensitive action attempts

Current outputs include:

- severity
- affected domain
- recommended mode
- recommended intervention

### 4. Dynamic Governance Adaptation

The governance decision engine now considers:

- risk evaluation
- capability verdict and source
- operational mode
- anomaly signals
- domain hardening state

Current adaptive behaviors include:

- revoked capability -> `BLOCK`
- temporary grant -> can override static deny
- `RESTRICTED` mode -> auto execution escalates to confirmation
- `DEGRADED` mode -> auto execution hardens to degraded confirmation
- hardened domain -> soft quarantine behavior (`auto -> confirm`)

### 5. Initial Interventions

Sprint 6 introduces explicit interventions such as:

- `revoke_capability`
- `confirmation_escalation`
- `soft_quarantine`
- `domain_hardening`
- `degrade_scope`

These are included in the governance decision trace.

## Integration Point

The canonical interception point remains:

- `assistant_os/core/orchestrator.py`

Flow now is:

1. semantic classification
2. planning
3. deterministic policy
4. advisory consultation
5. system snapshot build
6. risk evaluation with system state
7. dynamic governance decision
8. execution or safe non-executing result

No second orchestrator was introduced.

## State Surface

`SystemStateSnapshot` now includes:

- operational mode
- operational mode reason/source
- recent anomaly signals
- active temporary grants
- active revocations
- domain operational states

`governance_surface` now exposes:

- current operational mode
- active revocations
- temporary grants
- recent anomaly signals
- hardened domains

## Limits

- state remains in-memory
- grants/revocations are not persisted
- no background automation or autonomous remediation loop exists
- no final user-facing MSO conversational surface exists yet
- local LLM remains non-authoritative

## Sprint 7 candidates

- persistent governance state
- operator override / approval flows
- richer scoped capability rules
- retention policy for anomaly and governance history
- admin/diagnostic surface over dynamic governance
