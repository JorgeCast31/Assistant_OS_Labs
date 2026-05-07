"""Read-only Mission Core query helpers."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from assistant_os.missions.models import Mission, MissionBlueprint, MissionEvent
from assistant_os.missions.store import InMemoryMissionStore


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _mission_summary(mission: Mission) -> dict[str, Any]:
    return {
        "mission_id": mission.mission_id,
        "title": mission.title,
        "macro_goal": mission.macro_goal,
        "created_by": mission.created_by,
        "source_surface": mission.source_surface,
        "status": _json_value(mission.status),
        "created_at": _json_value(mission.created_at),
        "updated_at": _json_value(mission.updated_at),
        "blueprint_id": mission.blueprint_id,
    }


def _blueprint_summary(blueprint: MissionBlueprint) -> dict[str, Any]:
    return {
        "blueprint_id": blueprint.blueprint_id,
        "mission_id": blueprint.mission_id,
        "summary": blueprint.summary,
        "version": blueprint.version,
        "status": _json_value(blueprint.status),
        "created_at": _json_value(blueprint.created_at),
        "workstream_count": len(blueprint.workstreams),
    }


def _event_summary(event: MissionEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "mission_id": event.mission_id,
        "event_type": event.event_type,
        "message": event.message,
        "actor": event.actor,
        "created_at": _json_value(event.created_at),
    }


def list_missions(store: InMemoryMissionStore) -> dict[str, Any]:
    missions = [_mission_summary(mission) for mission in store.list_missions()]
    return {
        "ok": True,
        "missions": missions,
        "count": len(missions),
    }


def get_mission(store: InMemoryMissionStore, mission_id: str) -> dict[str, Any] | None:
    mission = store.get_mission(mission_id)
    if mission is None:
        return None

    blueprint = store.get_blueprint(mission.blueprint_id) if mission.blueprint_id else None
    events = store.get_events(mission_id)
    return {
        "ok": True,
        "mission": _mission_summary(mission),
        "blueprint": _blueprint_summary(blueprint) if blueprint else None,
        "event_count": len(events),
    }


def get_mission_events(store: InMemoryMissionStore, mission_id: str) -> dict[str, Any] | None:
    mission = store.get_mission(mission_id)
    if mission is None:
        return None

    events = [_event_summary(event) for event in store.get_events(mission_id)]
    return {
        "ok": True,
        "mission_id": mission_id,
        "events": events,
        "count": len(events),
    }
