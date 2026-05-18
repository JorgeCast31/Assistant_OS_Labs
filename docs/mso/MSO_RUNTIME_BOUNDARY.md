# MSO Runtime Boundary

## Current Runtime Truth

The executable sovereign runtime currently enters through:

```text
assistant_os.mso.kernel.handle_sovereign_request(...)
```

The current implementation body remains:

```text
assistant_os.core.orchestrator.handle_request(...)
```

The orchestrator is not an independent sovereign actor.
MSO owns the orchestrator.

## Why This Exists

The previous architecture had real authority behavior distributed across:

- webhook_server
- core/orchestrator
- policy engine
- MSO governance engine
- capability/token gates
- pipelines

This boundary makes the ownership explicit without changing behavior.

## Current Surface Reality

Current implementation truth:

- `assistant_chat` is the path that may reach executable orchestration.
- `mso_direct` is currently cognitive/read-only and may generate prepared actions.
- `mso_direct` does not execute.
- `surface` is currently descriptive metadata and observability context, not an authority boundary.

## Legacy Call Sites

Several other call sites in `webhook_server.py` (command handler, FIN_PLAN, FIN_EXPENSE, and others) still import `handle_request` directly from `core.orchestrator`. These are intentionally left unchanged in this sprint. Only the primary chat executable dispatch path routes through the MSO kernel boundary.

## Out of Scope for This Sprint

This sprint does not:

- integrate Police into the main path;
- change token semantics;
- change governance semantics;
- change FROZEN behavior;
- change Runner behavior;
- change `code_api.py`;
- rename surfaces;
- unify pending action queues;
- clean legacy files.

## Next Expected Sprint

The next architectural sprint should integrate Police into the main path:

```text
MSO Kernel
→ Policy/Governance/Token
→ Police Gate
→ Pipeline/Runner
```
