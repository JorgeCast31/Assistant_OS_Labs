# Mission Query Seam Contract

## Purpose

The Mission Query Seam exposes Mission Core state for observation. It gives local
tools a stable JSON view of missions, mission detail summaries, and mission event
history without changing Mission Core state.

## Read-only Boundary

This seam is read-only by design. The query module accepts a store object and
uses only its read methods. The HTTP adapter is a thin GET-only wrapper around
those query functions.

This is not execution. It does not decide work, schedule work, prepare work, or
advance mission state. It does not add a Mission pipeline, and it must not be
attached to the runtime dispatcher.

## No Webhook Integration

The seam is deliberately standalone. It does not integrate with the webhook
server because the webhook path is part of the assistant runtime surface, while
this contract is an observation-only Mission Core surface. Keeping it separate
prevents accidental promotion from state inspection into runtime authority.

## Domain Pipeline Boundary

`DOMAIN_PIPELINES["MISSION"]` is forbidden. Mission Query is not a pipeline
domain, not a dispatch target, and not a runtime action path. Adding a Mission
pipeline would change the authority model from observation to execution.

## Port

The adapter reads `MISSION_API_PORT` and defaults to `8200`.

## Store Strategy

`create_server` requires an explicit store object. The adapter must be handed the
store that the caller intends to observe; it does not create a default application
store on its own. This prevents an empty standalone store from looking like live
runtime Mission Core state.

## Endpoints

`GET /health`

```json
{
  "ok": true,
  "service": "mission_api"
}
```

`GET /api/missions`

```json
{
  "ok": true,
  "missions": [],
  "count": 0
}
```

`GET /api/missions/{mission_id}`

```json
{
  "ok": true,
  "mission": {
    "mission_id": "mission_...",
    "title": "Example",
    "macro_goal": "Example goal",
    "created_by": "surface",
    "source_surface": "chat",
    "status": "draft",
    "created_at": "2026-05-06T00:00:00+00:00",
    "updated_at": "2026-05-06T00:00:00+00:00",
    "blueprint_id": null
  },
  "blueprint": null,
  "event_count": 0
}
```

When a blueprint exists, the response includes only a blueprint summary:

```json
{
  "blueprint_id": "blueprint_...",
  "mission_id": "mission_...",
  "summary": "Short plan summary",
  "version": 1,
  "status": "draft",
  "created_at": "2026-05-06T00:00:00+00:00",
  "workstream_count": 2
}
```

`GET /api/missions/{mission_id}/events`

```json
{
  "ok": true,
  "mission_id": "mission_...",
  "events": [],
  "count": 0
}
```

## Error Envelopes

Unknown missions and unknown paths return JSON error envelopes:

```json
{
  "ok": false,
  "error": "not found"
}
```

Unknown mission IDs return `404`. Malformed empty mission IDs return `400`.

## Explicit NO-GO Boundaries

- No write endpoints.
- No mission state mutation.
- No arbitrary model side data in responses.
- No policy decisions.
- No confirmation or approval flow.
- No execution or dispatch.
- No Mission pipeline registration.
- No webhook server integration.
- No Machine Operator integration.
- No capability or grant flow.
- No UI surface.

## Out of Scope

- Persistence changes.
- Mission Control UI.
- Full blueprint, workstream, and activity expansion.
- Write endpoints.
- Policy.
- Confirmation.
- Execution.
- Machine Operator.
- Webhook integration.
