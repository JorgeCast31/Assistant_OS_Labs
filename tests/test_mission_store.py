from pathlib import Path

import pytest

from assistant_os.missions.models import (
    Mission,
    MissionActivity,
    MissionBlueprint,
    MissionEvent,
    MissionStatus,
    Workstream,
)
from assistant_os.missions.store import InMemoryMissionStore


def make_mission() -> Mission:
    return Mission(
        title="Store mission",
        macro_goal="Keep process-local mission state.",
        created_by="codex",
        source_surface="test",
    )


def test_store_creates_lists_and_updates_mission_status() -> None:
    store = InMemoryMissionStore()
    mission = store.create_mission(make_mission())

    assert store.get_mission(mission.mission_id) == mission
    assert store.list_missions() == [mission]

    updated = store.update_mission_status(mission.mission_id, "planned")

    assert updated.status is MissionStatus.PLANNED
    assert store.get_mission(mission.mission_id).status is MissionStatus.PLANNED  # type: ignore[union-attr]


def test_blueprint_can_attach_to_mission() -> None:
    store = InMemoryMissionStore()
    mission = store.create_mission(make_mission())
    workstream = Workstream(
        mission_id=mission.mission_id,
        name="Representation",
        objective="Model planned work.",
        domain="mission",
        activities=[
            MissionActivity(
                title="Represent activity",
                description="A described activity with no action behavior.",
            )
        ],
    )
    blueprint = MissionBlueprint(
        mission_id=mission.mission_id,
        summary="Mission blueprint only.",
        workstreams=[workstream],
    )

    saved = store.save_blueprint(blueprint)

    assert saved == blueprint
    assert store.get_blueprint(blueprint.blueprint_id) == blueprint
    assert store.get_mission(mission.mission_id).blueprint_id == blueprint.blueprint_id  # type: ignore[union-attr]


def test_events_are_append_only_from_store_api() -> None:
    store = InMemoryMissionStore()
    mission = store.create_mission(make_mission())
    first = store.append_event(
        MissionEvent(
            mission_id=mission.mission_id,
            event_type="created",
            message="Mission created.",
            actor="test",
        )
    )
    second = store.append_event(
        MissionEvent(
            mission_id=mission.mission_id,
            event_type="noted",
            message="Mission note.",
            actor="test",
        )
    )

    events = store.get_events(mission.mission_id)

    assert events == (first, second)
    with pytest.raises(AttributeError):
        events.append(first)  # type: ignore[attr-defined]
    assert store.get_events(mission.mission_id) == (first, second)


def test_store_does_not_write_to_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    writes: list[str] = []

    def tracking_write_text(self: Path, *args: object, **kwargs: object) -> int:
        writes.append(str(self))
        return 0

    monkeypatch.setattr(Path, "write_text", tracking_write_text)

    store = InMemoryMissionStore()
    mission = store.create_mission(make_mission())
    store.append_event(
        MissionEvent(
            mission_id=mission.mission_id,
            event_type="checked",
            message="No persistence.",
            actor="test",
        )
    )
    store.save_blueprint(MissionBlueprint(mission_id=mission.mission_id, summary="No file writes."))

    assert writes == []
    assert list(tmp_path.iterdir()) == []
