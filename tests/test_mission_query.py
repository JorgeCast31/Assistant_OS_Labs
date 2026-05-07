import json

from assistant_os.missions.models import MissionBlueprint, Workstream
from assistant_os.missions.query import get_mission, get_mission_events, list_missions
from assistant_os.missions.service import MissionRegistry


def test_list_missions_empty_registry() -> None:
    registry = MissionRegistry()

    result = list_missions(registry.store)

    assert result == {"ok": True, "missions": [], "count": 0}


def test_opened_mission_appears_in_list() -> None:
    registry = MissionRegistry()
    mission = registry.open_mission(
        macro_goal="Observe Mission Core state.",
        title="Mission observation",
        created_by="test",
        source_surface="unit",
    )

    result = list_missions(registry.store)

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["missions"][0]["mission_id"] == mission.mission_id


def test_get_mission_unknown_returns_none() -> None:
    assert get_mission(MissionRegistry().store, "missing") is None


def test_get_mission_returns_summary_without_blueprint() -> None:
    registry = MissionRegistry()
    mission = registry.open_mission(
        macro_goal="Keep details compact.",
        title="No blueprint",
        created_by="test",
        source_surface="unit",
    )

    result = get_mission(registry.store, mission.mission_id)

    assert result is not None
    assert result["mission"]["mission_id"] == mission.mission_id
    assert result["mission"]["status"] == "draft"
    assert result["blueprint"] is None
    assert result["event_count"] == 1


def test_get_mission_with_blueprint_returns_blueprint_summary() -> None:
    registry = MissionRegistry()
    mission = registry.open_mission(
        macro_goal="Summarize blueprint.",
        title="Blueprint summary",
        created_by="test",
        source_surface="unit",
    )
    blueprint = MissionBlueprint(
        mission_id=mission.mission_id,
        summary="A compact mission plan.",
        workstreams=[
            Workstream(
                mission_id=mission.mission_id,
                name="Observation",
                objective="Expose state.",
                domain="MISSION",
            )
        ],
    )
    registry.attach_blueprint(mission.mission_id, blueprint)

    result = get_mission(registry.store, mission.mission_id)

    assert result is not None
    assert result["blueprint"]["blueprint_id"] == blueprint.blueprint_id
    assert result["blueprint"]["summary"] == "A compact mission plan."
    assert result["blueprint"]["workstream_count"] == 1


def test_get_mission_events_unknown_returns_none() -> None:
    assert get_mission_events(MissionRegistry().store, "missing") is None


def test_get_mission_events_returns_event_dicts() -> None:
    registry = MissionRegistry()
    mission = registry.open_mission(
        macro_goal="Read events.",
        title="Events",
        created_by="test",
        source_surface="unit",
    )

    result = get_mission_events(registry.store, mission.mission_id)

    assert result is not None
    assert result["ok"] is True
    assert result["count"] == 1
    assert result["events"][0]["event_type"] == "mission_opened"
    assert isinstance(result["events"][0], dict)


def test_query_results_are_json_serializable() -> None:
    registry = MissionRegistry()
    mission = registry.open_mission(
        macro_goal="Serialize all envelopes.",
        title="Serialization",
        created_by="test",
        source_surface="unit",
    )

    json.dumps(list_missions(registry.store))
    json.dumps(get_mission(registry.store, mission.mission_id))
    json.dumps(get_mission_events(registry.store, mission.mission_id))


def test_datetime_values_are_iso_strings() -> None:
    registry = MissionRegistry()
    mission = registry.open_mission(
        macro_goal="Serialize time.",
        title="Datetime",
        created_by="test",
        source_surface="unit",
    )

    mission_result = get_mission(registry.store, mission.mission_id)
    events_result = get_mission_events(registry.store, mission.mission_id)

    assert mission_result is not None
    assert events_result is not None
    assert mission_result["mission"]["created_at"] == mission.created_at.isoformat()
    assert mission_result["mission"]["updated_at"] == mission.updated_at.isoformat()
    assert events_result["events"][0]["created_at"].endswith("+00:00")


def test_mission_metadata_is_not_serialized() -> None:
    registry = MissionRegistry()
    mission = registry.open_mission(
        macro_goal="Hide metadata.",
        title="Metadata",
        created_by="test",
        source_surface="unit",
    )
    mission.metadata["secret"] = "not for this seam"

    result = get_mission(registry.store, mission.mission_id)

    assert result is not None
    assert "metadata" not in result["mission"]
    assert "secret" not in json.dumps(result)


def test_event_metadata_is_not_serialized() -> None:
    registry = MissionRegistry()
    mission = registry.open_mission(
        macro_goal="Hide event details.",
        title="Event side data",
        created_by="test",
        source_surface="unit",
    )
    event = registry.store.get_events(mission.mission_id)[0]
    event.metadata["secret"] = "not for this seam"

    result = get_mission_events(registry.store, mission.mission_id)

    assert result is not None
    assert "metadata" not in result["events"][0]
    assert "secret" not in json.dumps(result)


def test_blueprint_response_excludes_full_workstreams() -> None:
    registry = MissionRegistry()
    mission = registry.open_mission(
        macro_goal="Avoid expansion.",
        title="Compact blueprint",
        created_by="test",
        source_surface="unit",
    )
    blueprint = MissionBlueprint(
        mission_id=mission.mission_id,
        summary="No full workstream expansion.",
        workstreams=[
            Workstream(
                mission_id=mission.mission_id,
                name="One",
                objective="Stay summarized.",
                domain="MISSION",
            )
        ],
    )
    registry.attach_blueprint(mission.mission_id, blueprint)

    result = get_mission(registry.store, mission.mission_id)

    assert result is not None
    assert "workstreams" not in result["blueprint"]
