import dataclasses

from assistant_os.missions.models import (
    Mission,
    MissionActivity,
    MissionBlueprint,
    MissionEvent,
    MissionStatus,
    Workstream,
)


def test_mission_can_be_created_with_stable_non_empty_id() -> None:
    mission = Mission(
        title="Mission Core Foundation",
        macro_goal="Represent mission intent without execution.",
        created_by="codex",
        source_surface="test",
    )

    assert mission.mission_id
    assert mission.mission_id == mission.mission_id
    assert mission.status is MissionStatus.DRAFT
    assert mission.blueprint_id is None


def test_blueprint_workstreams_and_activities_can_be_represented() -> None:
    mission = Mission(
        title="Blueprint representation",
        macro_goal="Capture workstreams and activities.",
        created_by="codex",
        source_surface="test",
    )
    activity = MissionActivity(
        workstream_id="workstream_existing",
        title="Draft contract",
        description="Write the mission contract.",
        dependencies=["mission-created"],
        artifacts=["docs/mission/mission-core-contract.md"],
    )
    workstream = Workstream(
        mission_id=mission.mission_id,
        workstream_id="workstream_existing",
        name="Core contract",
        objective="Define the non-executable boundary.",
        domain="mission",
        assigned_role="technical_executor",
        activities=[activity],
    )
    blueprint = MissionBlueprint(
        mission_id=mission.mission_id,
        summary="Represent mission intent only.",
        workstreams=[workstream],
    )

    assert blueprint.blueprint_id
    assert blueprint.mission_id == mission.mission_id
    assert blueprint.workstreams[0].activities[0].workstream_id == workstream.workstream_id
    assert blueprint.workstreams[0].activities[0].dependencies == ["mission-created"]


def test_mission_event_is_directly_immutable() -> None:
    event = MissionEvent(
        mission_id="mission_test",
        event_type="noted",
        message="Mission event is immutable.",
        actor="test",
    )

    try:
        event.message = "mutated"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("MissionEvent should reject direct mutation")
