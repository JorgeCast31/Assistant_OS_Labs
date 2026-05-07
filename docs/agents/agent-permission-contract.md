# Agent Permission Contract

## Purpose

The agent permission bridge describes an agent as a governable entity before any operational work is considered. It records identity, declared capability scope, Police-owned tool and environment permissions, review requirement, current operational status, and derivation time.

This contract is declarative. It returns a `PoliceEvaluation` for a proposed agent request. A `PoliceEvaluation.ALLOW` means the pre-operation permission check passed; it is not execution authorization, not a launch instruction, and not a grant.

## AgentPermissionProfile

`AgentPermissionProfile` is frozen and keyword-only. Once derived, it is auditable and cannot be mutated in place.

Fields:

- `profile_id`: generated UUID for the derived profile.
- `agent_id`: stable agent identifier.
- `display_name`: human-readable name.
- `role`: role or responsibility label.
- `domain`: optional domain declared by the registry.
- `version`: optional registry version.
- `declared_capabilities`: immutable set of capabilities declared by the agent source data.
- `permitted_tools`: immutable set of tools allowed by Police-owned bridge configuration.
- `permitted_environments`: immutable set of environments allowed by Police-owned bridge configuration.
- `requires_review`: whether otherwise allowed requests require confirmation.
- `status`: one of `ACTIVE`, `INACTIVE`, `DEGRADED`, or `DISABLED`.
- `derived_at`: timezone-aware derivation timestamp.

The profile does not include callables, runtime bindings, token references, activity state, arbitrary metadata passthrough, or later-stage authority objects.

## Police-Owned Permission Config

Agents declare capabilities through registry/profile data. The bridge does not convert declared capabilities into tool or environment permission.

Permitted tools and permitted environments come from `AGENT_POLICE_PERMISSION_CONFIG` inside the bridge module. This keeps agent declarations separate from Police-owned permission scope and prevents an agent from becoming self-authorizing by merely declaring a capability.

## Registry Use

`build_agent_permission_profile(agent_name)` reads the registry as source data only. The registry is not mutated in this sprint.

The builder may read only non-callable fields:

- `name`
- `domain`
- `version`
- `description`
- `input_contract`
- `output_contract`
- `requires_review`
- `capability_scope`

It never accesses `entrypoint`, does not read the registry callable boundary, and does not call any agent.

## AgentPoliceRequest

`AgentPoliceRequest` is operation-scoped and immutable.

Fields:

- `request_id`: stable request identifier.
- `agent_id`: agent making the request.
- `requested_by`: actor that initiated the request.
- `requested_tool`: optional requested tool.
- `requested_environment`: optional requested environment.
- `requested_capabilities`: requested capability names.
- `risk_signals`: declarative risk labels for Police evaluation.
- `mission_id`: optional mission trace identifier.
- `activity_id`: optional activity trace identifier.

It does not carry callables, token references, binding references, authorized plan references, or embedded Police result objects.

## Bridge Into PoliceEvaluation

The bridge maps `AgentPermissionProfile` into `AgentPermission` and maps `AgentPoliceRequest` into `PoliceCheckRequest`, then calls `PoliceEnforcer.evaluate()`.

Status handling is explicit:

- `ACTIVE`: evaluated normally.
- `DEGRADED`: evaluated normally, but the derived Police permission requires review. If the request is otherwise allowed, the result is `REQUIRES_CONFIRMATION`; if it violates tool, environment, capability, or risk rules, the result remains `DENY`.
- `INACTIVE`: denied before `PoliceEnforcer.evaluate()`.
- `DISABLED`: denied before `PoliceEnforcer.evaluate()`.

The bridge does not mutate the profile or request objects.

## Why This Is Not Execution

The bridge only constructs declarative permission objects and returns a `PoliceEvaluation`. It does not call agent implementations, start services, reach runtime launch paths, or perform any side effect beyond allocating normal dataclass return objects.

`PoliceEvaluation.ALLOW` is pre-evaluation success, not permission to run an implementation. Later authority layers must still decide whether any actual operation may proceed.

## Why PoliceDecision And Token Gate Are Out Of Scope

`PoliceDecision` and token-gate objects represent a later authority layer. This sprint only establishes whether an agent request is permitted, denied, or requires confirmation under Police Core v0. Producing or consuming token-gate types here would collapse the permission check into a later enforcement stage, so those objects are intentionally excluded.

## Future MissionExecutionCandidate Use

A future `MissionExecutionCandidate` can include an agent id, proposed tool, target environment, required capabilities, mission id, and activity id. That data can be converted into `AgentPoliceRequest`, checked against the agent's frozen `AgentPermissionProfile`, and then used as an input to later mission authority stages only after the returned `PoliceEvaluation` is acceptable.
