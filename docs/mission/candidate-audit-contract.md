# Candidate Audit Contract

## Purpose

`CandidateAuditRecord` is the contract-level event for alpha flow step 7: a `MissionExecutionCandidate` has been created after `PoliceEvaluation.ALLOW`.

The record exists so later layers can reconstruct that candidate creation moment from scalar snapshots. It is not a durable audit store.

## Alpha Flow Position

Candidate audit happens after candidate creation and before the future token-bound gate.

1. MSO receives intent.
2. MSO creates or updates a Mission.
3. MSO selects a candidate agent.
4. `AgentPermissionProfile` is derived.
5. Police evaluates.
6. `MissionExecutionCandidate` is created only for `PoliceEvaluation.ALLOW`.
7. `CandidateAuditRecord` snapshots the candidate creation event.

## What It Stores

The record stores scalar snapshots only:

- audit id
- event type
- candidate id
- mission, activity, and workstream ids
- agent and agent profile ids
- request id
- Police evaluation id and outcome string
- operation key
- timezone-aware creation time
- immutable details tuple

It does not store the `MissionExecutionCandidate` object.

## Boundaries

Candidate audit is not persistence. Persistence comes later in `S-PERSISTENCE-01`.

Candidate audit is not execution. It does not call runtime workers, pipelines, CODE, Machine Operator, sandbox, APIs, or UI.

Candidate audit is not `PoliceDecision`. The token-bound gate comes later in `S-POLICE-CORE-03`.

Candidate audit does not verify or consume tokens and does not carry token, binding, or plan refs.

MSO wiring comes later. UI surface comes later.

## Relationship To Police Audit

The current `PoliceAuditEvent` shape is an in-memory Police evaluation event with mutable metadata. `CandidateAuditRecord` is an immutable mission-side candidate creation event.

No adapter is added in this sprint because mapping between the two would weaken the event semantics. A future audit sink can define a shared durable envelope without changing this contract.
