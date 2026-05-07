# Mission Execution Candidate Contract

## Purpose

`MissionExecutionCandidate` is a mission-scoped, gate-pending snapshot created only after `PoliceEvaluationType.ALLOW`.

It is built from mission context, an `AgentPermissionProfile`, an `AgentPoliceRequest`, and a `PoliceEvaluation`. It stores only references and primitive snapshots needed by a future authority layer.

## Created Only For ALLOW

`PoliceEvaluationType.ALLOW` creates a candidate with `PENDING_GATE` status.

`PoliceEvaluationType.DENY` creates no candidate. `PoliceEvaluationType.REQUIRES_CONFIRMATION` creates no candidate. Those outcomes remain represented by the `PoliceEvaluation` itself.

The candidate is not a blocked status holder and does not replace Police evaluation records.

## Pending Gate, Not Authorization

A candidate is pending gate review. It is not runtime work, not permission to start work, and not execution authorization.

`PoliceEvaluation.ALLOW` means the candidate is eligible for a future token-bound gate. The candidate id is intended to become a future operation/execution reference for that gate, but there is no import, call, or wiring to that layer in this contract.

## Inputs

The builder combines:

- Mission context: mission id, optional activity id, optional workstream id, and operation key.
- Agent profile snapshot fields: agent id, profile id, profile version, and profile derivation time.
- Agent request snapshot fields: request id, requested tool, requested environment, and requested capabilities.
- Police evaluation snapshot fields: evaluation id, evaluation outcome, risk level, and audit event id.

The candidate does not retain live `AgentPermissionProfile`, `AgentPoliceRequest`, `PoliceEvaluation`, or Mission objects.

## Out Of Scope

PoliceDecision and token-bound gate behavior remain future work. Runner, CODE, Machine Operator, sandbox, API, UI, and mission persistence wiring are outside this contract.

## Stored Fields

The candidate stores:

- generated candidate id
- mission, activity, and workstream references
- agent id and profile references
- request id, requested tool, requested environment, and requested capabilities
- Police evaluation id, outcome string, risk level, and audit event reference
- operation key
- candidate status
- timezone-aware creation time

It never stores an agent callable, token references, binding references, authorized plan references, PoliceDecision, or a permitted boolean.
