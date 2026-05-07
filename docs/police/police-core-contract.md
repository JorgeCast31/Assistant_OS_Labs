# Police Declarative Enforcement Core v0 Contract

## Purpose

Police Declarative Enforcement Core v0 is the Assistant_OS Police permission pre-evaluation core for checking proposed actions against declared permissions, environments, capability scopes, and risk signals. It produces PoliceEvaluation records and audit events only.

This PR is intentionally bounded. It does not implement token-bound enforcement, does not validate execution instances, and is not the final gate before runtime work.

The token-bound gate is future work.

## What This Core Does Now

Police Core v0 evaluates a `PoliceCheckRequest` against a supplied `AgentPermission` declaration.

It checks:

- requested tool membership in the declared allowed tools
- requested environment membership in the declared allowed environments
- requested capability names against the declared capability scope
- critical, high, medium, and low risk signals
- whether the agent permission requires review

It returns:

- a `PoliceEvaluation`
- zero or more `PoliceViolation` records
- allowed and denied tool/environment lists
- the supplied capability scope
- a risk level
- an audit event identifier

It can also build an in-memory `PoliceAuditEvent` from a request and evaluation.

`PoliceEvaluation.ALLOW` is not authorization to execute. It means the v0 declarative permission pre-evaluation found no v0 blocking condition.

## What This Core Explicitly Does Not Do Yet

Police Core v0 does not validate capability tokens.
Police Core v0 does not consume tokens.
Police Core v0 does not validate an AuthorizedPlan.
Police Core v0 does not bind evaluations to runtime instances.
Police Core v0 does not enforce temporal token restrictions.
Police Core v0 does not cross the runner or sandbox boundary.
Police Core v0 does not provide the final action gate for runtime work.

## Enforcement, Not Sovereignty

Police is subordinate to the AssistantOS authority model. It is a contract enforcement component, not a sovereign authority. It does not define ultimate authority, replace user authority, or own the system power model.

## Relationship To MSO

Police is not MSO and does not perform MSO responsibilities. MSO may coordinate operational work elsewhere in the system, while Police evaluates whether a proposed request satisfies a declared enforcement contract.

## Relationship To PolicyDecision

Police Core v0 does not create or wrap PolicyDecision objects. PoliceEvaluation is a pre-evaluation result with Police-specific outcomes, reasons, violations, scope details, risk level, and audit identifiers.

PoliceDecision is reserved for future S-POLICE-CORE-03 token-bound execution gate work. It is intentionally not part of this v0 module.

## Relationship To Mission Layer

Police accepts mission and activity identifiers as optional request context. It does not load, mutate, advance, or own mission records. Mission state remains outside the Police core.

## Relationship To Agent Registry

Police evaluates a request against an AgentPermission contract supplied by its caller. It does not issue agent permissions, persist registry state, mint tokens, or modify registry records.

## Evaluation Outcomes

- `ALLOW`: the requested tool, environment, capabilities, and risk signals satisfy the supplied permission contract.
- `DENY`: one or more enforcement violations block the request.
- `REQUIRES_CONFIRMATION`: the supplied agent permission requires review and no deny condition was found.

## Request, Evaluation, And Audit Model

`PoliceCheckRequest` carries request identity, optional mission/activity context, requester identity, agent identity, requested tool, requested environment, requested capabilities, risk signals, and metadata.

`PoliceEvaluation` carries the evaluation identity, request identity, outcome, reason, optional blocked or confirmation reason, violations, allowed and denied tools, allowed and denied environments, capability scope, risk level, creation time, and audit event identity.

`PoliceAuditEvent` is an in-memory audit shape built from a request and evaluation. Police audit helpers do not persist, write files, talk to databases, or emit logs.

## NO-GO Boundaries

Police does not execute proposed work.
Police does not plan proposed work.
Police does not call runtime workers, coordination layers, pipelines, MSO, or mission services.
Police does not create confirmations.
Police does not issue grants or tokens.
Police does not mutate mission objects.
Police produces only pre-evaluations and audit events.

## Future Integration Points

Future integrations can supply AgentPermission records from an agent registry, attach PoliceEvaluation results to higher-level request flows, and persist PoliceAuditEvent records in a dedicated audit sink. Those integrations must remain outside the Police core and preserve the boundary that Police evaluates contracts without performing the proposed action.

Future S-POLICE-CORE-02 should address:

- CapabilityToken presence and validity
- OperationBinding
- AuthorizedPlan binding
- token consumption
- temporal restrictions
- runner and sandbox boundary
