# Mission Core Contract

## Purpose

Mission Core is the non-executable mission layer foundation for Assistant OS. It records mission intent, high-level goals, blueprints, workstreams, activities, and audit events as domain state.

It is a representation layer only. A mission can describe what should be considered or coordinated in the future, but it does not perform work.

## Non-Executable Nature

Mission Core does not execute actions. Mission Core is not a planner. Mission Core is not an executor. Mission Core is not policy. Mission Core is not Police. It does not call runners, planners, policy systems, LLMs, external services, Machine Operator, OpenClaw, or capability registries. It does not create confirmations or mutate execution authority.

The current store is process-local and in-memory. It performs no file writes, database writes, network calls, or durable persistence.

## Invariants

- Mission Core records intent, state, and audit history only.
- Mission Core does not create policy decisions.
- Mission Core does not mutate execution mode.
- Mission Core does not inspect or modify capability registries.
- Mission Core does not create confirmations.
- Mission Core does not dispatch, run, execute, or schedule work.
- Mission Core does not call an existing planner.
- Mission Core does not call an LLM.
- Mission events are appended through the store API and returned as immutable tuples.

## Object Model

### Mission

Top-level mission intent. A mission has a stable ID, title, macro goal, status, creation and update timestamps, creator, source surface, optional attached blueprint ID, and metadata.

### MissionBlueprint

Versioned descriptive representation for a mission. A blueprint contains a summary, status, creation timestamp, and workstreams.

MissionBlueprint is not ExecutionPlan. It is not a runnable plan, not a scheduler input, and not a substitute for a policy-reviewed execution design.

### Workstream

Mission-scoped area of described work. A workstream records a name, objective, domain, optional assigned role, status, and activities.

### MissionActivity

Descriptive unit inside a workstream. An activity records title, description, status, dependencies, and artifacts.

MissionActivity is not a runnable step. It does not carry execution authority, approval state, confirmation state, capability requirements, or dispatch instructions.

### MissionEvent

Append-only audit event for a mission. Events record event type, message, actor, timestamp, and metadata.

## Future Integration Points

Future layers may read Mission Core state to propose planning, approval, execution, UI display, observability, or persistence integrations. Those integrations must live outside Mission Core and preserve the authority boundary.

Potential future integrations:

- Persistent mission repository.
- UI display of mission timelines.
- Policy review that reads mission blueprints without Mission Core importing policy.
- Planner integration that emits MissionBlueprint objects without Mission Core calling the planner.
- Runner integration that reads approved steps outside Mission Core after separate authorization.
- MissionRegistry adapters that expose mission lifecycle state to UI surfaces.

MissionRegistry does not call orchestrator, runner, policy, or capability registry. It is a lifecycle registry only.

## Explicit NO-GO Boundaries

Mission Core must not:

- Import or instantiate PolicyDecision.
- Read or write execution_mode.
- Import orchestrator, runner, runners, policy, pipeline, MSO, OpenClaw, or capability registry modules.
- Create confirmation requests.
- Run, dispatch, execute, schedule, or start work.
- Call local or remote LLM services.
- Write mission state to disk.
- Use databases or external services.
