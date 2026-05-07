"""Mission Core registry facade."""

from __future__ import annotations

from typing import Any

from assistant_os.missions.models import Mission, MissionBlueprint, MissionEvent
from assistant_os.missions.store import InMemoryMissionStore


class MissionRegistry:
    def __init__(self, store: InMemoryMissionStore | None = None) -> None:
        self.store = store or InMemoryMissionStore()

    def open_mission(
        self,
        macro_goal: str,
        title: str,
        created_by: str,
        source_surface: str,
    ) -> Mission:
        mission = Mission(
            title=title,
            macro_goal=macro_goal,
            created_by=created_by,
            source_surface=source_surface,
        )
        self.store.create_mission(mission)
        self.record_event(
            mission.mission_id,
            event_type="mission_opened",
            message="Mission opened in draft state.",
            actor=created_by,
            metadata={"source_surface": source_surface},
        )
        return mission

    def attach_blueprint(self, mission_id: str, blueprint: MissionBlueprint) -> MissionBlueprint:
        if blueprint.mission_id != mission_id:
            raise ValueError("blueprint mission_id must match target mission_id")
        saved_blueprint = self.store.save_blueprint(blueprint)
        self.record_event(
            mission_id,
            event_type="blueprint_attached",
            message=f"Mission blueprint {blueprint.blueprint_id} attached.",
            actor="mission_registry",
            metadata={"blueprint_id": blueprint.blueprint_id, "version": blueprint.version},
        )
        return saved_blueprint

    def record_event(
        self,
        mission_id: str,
        event_type: str,
        message: str,
        actor: str,
        metadata: dict[str, Any] | None = None,
    ) -> MissionEvent:
        event = MissionEvent(
            mission_id=mission_id,
            event_type=event_type,
            message=message,
            actor=actor,
            metadata=dict(metadata or {}),
        )
        return self.store.append_event(event)

    def summarize_mission(self, mission_id: str) -> dict[str, Any]:
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise KeyError(f"unknown mission: {mission_id}")
        blueprint = self.store.get_blueprint(mission.blueprint_id) if mission.blueprint_id else None
        events = self.store.get_events(mission_id)
        return {
            "mission_id": mission.mission_id,
            "title": mission.title,
            "macro_goal": mission.macro_goal,
            "status": mission.status.value,
            "blueprint_id": mission.blueprint_id,
            "blueprint_status": blueprint.status.value if blueprint else None,
            "workstream_count": len(blueprint.workstreams) if blueprint else 0,
            "event_count": len(events),
            "updated_at": mission.updated_at,
        }
