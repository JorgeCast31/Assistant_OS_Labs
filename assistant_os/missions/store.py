"""In-memory Mission Core store."""

from __future__ import annotations

from collections import defaultdict

from assistant_os.missions.models import Mission, MissionBlueprint, MissionEvent, MissionStatus, utc_now


class InMemoryMissionStore:
    def __init__(self) -> None:
        self._missions: dict[str, Mission] = {}
        self._events: dict[str, list[MissionEvent]] = defaultdict(list)
        self._blueprints: dict[str, MissionBlueprint] = {}

    def create_mission(self, mission: Mission) -> Mission:
        if mission.mission_id in self._missions:
            raise ValueError(f"mission already exists: {mission.mission_id}")
        self._missions[mission.mission_id] = mission
        return mission

    def get_mission(self, mission_id: str) -> Mission | None:
        return self._missions.get(mission_id)

    def list_missions(self) -> list[Mission]:
        return list(self._missions.values())

    def update_mission_status(self, mission_id: str, status: MissionStatus | str) -> Mission:
        mission = self._require_mission(mission_id)
        mission.status = MissionStatus(status)
        mission.updated_at = utc_now()
        return mission

    def append_event(self, event: MissionEvent) -> MissionEvent:
        self._require_mission(event.mission_id)
        self._events[event.mission_id].append(event)
        return event

    def get_events(self, mission_id: str) -> tuple[MissionEvent, ...]:
        self._require_mission(mission_id)
        return tuple(self._events.get(mission_id, ()))

    def save_blueprint(self, blueprint: MissionBlueprint) -> MissionBlueprint:
        mission = self._require_mission(blueprint.mission_id)
        self._blueprints[blueprint.blueprint_id] = blueprint
        mission.blueprint_id = blueprint.blueprint_id
        mission.updated_at = utc_now()
        return blueprint

    def get_blueprint(self, blueprint_id: str) -> MissionBlueprint | None:
        return self._blueprints.get(blueprint_id)

    def _require_mission(self, mission_id: str) -> Mission:
        mission = self.get_mission(mission_id)
        if mission is None:
            raise KeyError(f"unknown mission: {mission_id}")
        return mission
