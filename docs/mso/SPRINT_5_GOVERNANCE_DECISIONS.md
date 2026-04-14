# Sprint 5: Active MSO Governance Decisions

Sprint 5 gives the MSO its first real authority layer.

The orchestrator still owns planning, routing, and structural execution.
The MSO now owns a narrow governance function:

- classify risk
- validate capabilities
- intervene before execution
- require confirmation
- block unsafe actions
- degrade execution scope

This remains conservative, explicit, and traceable.

## Architecture

### 1. Risk Engine

Module:

- `assistant_os/mso/risk_engine.py`

Outputs a typed `RiskEvaluation` with:

- `level`: `low` | `medium` | `high`
- explicit `reasons`
- `base_risk`
- recent failure count
- anomaly flag

Rules are deterministic and inspectable.

Current risk signals include:

- planner risk
- destructive action shape
- mutating CODE actions
- recent domain failures
- advisory-layer failure notes as non-authoritative context

Recent failures only tighten risk for auto-executed actions with possible side effects.
Read-only actions keep their safe posture unless another rule elevates them.

### 2. Capability Registry

Module:

- `assistant_os/mso/capability_registry.py`

Provides a minimal central authority over action capability.

Current modes:

- `allow`
- `confirm_only`
- `plan_only`
- `deny`

This answers:

- whether an action is allowed at all
- whether it must be confirmation-gated
- whether it should be degraded to plan-only
- whether governance should deny it

This is intentionally simple in Sprint 5 and designed to evolve later.

### 3. Governance Decision Engine

Module:

- `assistant_os/mso/governance_engine.py`

Combines deterministic policy posture, risk evaluation, and capability authority into a typed `GovernanceDecision`.

Possible actions:

- `ALLOW`
- `REQUIRE_CONFIRMATION`
- `BLOCK`
- `DEGRADE`

Each decision includes:

- `governance_ref`
- justification
- structured reasons
- optional constraints
- capability mode
- base execution mode
- effective execution mode

### 4. Canonical Interception Point

Integration point:

- `assistant_os/core/orchestrator.py`

Order of control is now:

1. semantic classification
2. structural planning
3. deterministic policy decision
4. advisory consultation
5. MSO governance review
6. final execution-mode application
7. pipeline execution or safe non-execution result

The MSO does not create a second orchestrator.
It reviews the deterministic posture and may narrow it.

## Current Governance Outcomes

### Allow

Low-risk, allowed actions preserve the deterministic execution mode.

Example:

- `WORK_QUERY` remains `auto`

### Require Confirmation

Governance can override permissive deterministic policy and require confirmation.

Example:

- medium-risk `FIN_EXPENSE` auto posture becomes `confirm`
- capability policy with `confirm_only` also forces `confirm`

### Block

Governance can stop execution safely before any domain pipeline runs.

Example:

- high-risk destructive actions
- denied capabilities such as `COMMAND`

Blocked requests return a non-executing result plus a governance trace.

### Degrade

Governance can reduce scope instead of silently allowing full execution.

Current Sprint 5 degrade behavior:

- `auto` -> `confirm` when anomaly signals indicate recent failures
- `plan_only` capability mode maps to non-executing behavior for future use

## Trace Integration

Sprint 5 extends the unified trace chain to include governance.

Each chain can now reconstruct:

- original request
- advisory trace
- deterministic decision trace
- governance trace
- execution metadata
- final result

Supporting modules:

- `assistant_os/mso/trace_aggregator.py`
- `assistant_os/mso/system_state.py`
- `assistant_os/mso/governance_surface.py`

The governance layer is now queryable through recent governance decisions and linked task records.

## Current Limitations

- capability grants are static and in-memory
- governance state is still in-memory
- there are no temporary grants or operator overrides yet
- governance does not use the local model as an authority source
- the MSO still does not execute actions directly
- no autonomous scheduling or self-directed loops exist

## Sprint 6 Direction

Likely next steps:

- persistent governance/task/trace state
- richer capability policy scopes
- explicit operator override flows
- clearer blocked/degraded surfaces for downstream transports
- tighter linkage with execution audit/reporting layers
