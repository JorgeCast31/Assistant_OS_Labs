import ast
import dataclasses
import inspect

import assistant_os.missions as mission_package
from assistant_os.missions import models, service, store
from assistant_os.missions.models import Mission, MissionActivity, MissionBlueprint, MissionEvent, MissionStatus, Workstream
from assistant_os.missions.service import MissionRegistry


FORBIDDEN_IMPORT_FRAGMENTS = (
    "assistant_os.policy",
    "assistant_os.policy_engine",
    "assistant_os.core.orchestrator",
    "assistant_os.executors",
    "assistant_os.grants",
    "assistant_os.runner",
    "assistant_os.runners",
    "assistant_os.mso",
    "assistant_os.pipelines",
    "assistant_os.capability_registry",
    "assistant_os.capabilities",
)

FORBIDDEN_MODEL_FIELD_NAMES = {
    "execution_mode",
    "policy_decision_ref",
    "governance_ref",
    "approval_id",
    "approval_mode",
    "requires_confirmation",
    "capability",
    "capabilities",
    "required_capabilities",
}

FORBIDDEN_SOURCE_STRINGS = (
    "build_plan",
    "build_policy",
    "confirm_plan_id",
    "get_pipeline",
    "evaluate_policy",
    "evaluate_governance",
    "evaluate_risk",
    "capability_registry",
    "context_store",
    "task_registry",
    "trace_aggregator",
    "runner",
    "orchestrator",
    "plan_confirmation_required",
    "store_pending_plan",
    "execute_mission",
    "WAITING_FOR_CONFIRMATION",
    "waiting_for_confirmation",
)

FORBIDDEN_STATUS_VOCABULARY = (
    "confirmation",
    "execute",
    "dispatch",
    "trigger",
    "run_",
    "approval",
    "policy",
    "governance",
    "capability",
)

FORBIDDEN_REGISTRY_ATTRIBUTES = (
    "orchestrator",
    "pipeline",
    "runner",
    "policy",
    "executor",
    "grant",
    "capability",
)


def mission_source() -> str:
    return "\n".join(
        [
            inspect.getsource(mission_package),
            inspect.getsource(models),
            inspect.getsource(store),
            inspect.getsource(service),
        ]
    )


def test_registry_exposes_no_execute_run_or_dispatch_methods() -> None:
    public_methods = {
        name
        for name, value in inspect.getmembers(MissionRegistry, predicate=inspect.isfunction)
        if not name.startswith("_")
    }

    assert public_methods == {
        "attach_blueprint",
        "open_mission",
        "record_event",
        "summarize_mission",
    }
    assert public_methods.isdisjoint({"execute", "run", "dispatch", "execute_mission"})


def test_mission_model_fields_have_no_authority_like_names() -> None:
    model_types = (Mission, MissionBlueprint, Workstream, MissionActivity, MissionEvent)

    for model_type in model_types:
        field_names = {field.name for field in dataclasses.fields(model_type)}
        assert field_names.isdisjoint(FORBIDDEN_MODEL_FIELD_NAMES)


def test_mission_status_values_have_no_authority_or_execution_vocabulary() -> None:
    for status in MissionStatus:
        for forbidden in FORBIDDEN_STATUS_VOCABULARY:
            assert forbidden not in status.value


def test_registry_instance_attributes_have_no_authority_like_names() -> None:
    registry = MissionRegistry()
    attribute_names = set(vars(registry))

    for forbidden in FORBIDDEN_REGISTRY_ATTRIBUTES:
        assert all(forbidden not in attribute_name for attribute_name in attribute_names)


def imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_mission_core_has_no_authority_runtime_dependencies() -> None:
    imports = imported_modules(mission_source())

    for forbidden in FORBIDDEN_IMPORT_FRAGMENTS:
        assert all(not module.startswith(forbidden) for module in imports)


def test_mission_core_has_no_forbidden_authority_strings() -> None:
    source = mission_source()

    assert "PolicyDecision" not in source
    assert "execution_mode" not in source
    for forbidden in FORBIDDEN_SOURCE_STRINGS:
        assert forbidden not in source


def test_attach_blueprint_records_state_only() -> None:
    registry = MissionRegistry()
    mission = registry.open_mission(
        macro_goal="Represent intent.",
        title="Authority isolation",
        created_by="test",
        source_surface="unit",
    )
    blueprint = MissionBlueprint(mission_id=mission.mission_id, summary="A blueprint is state only.")

    attached = registry.attach_blueprint(mission.mission_id, blueprint)
    summary = registry.summarize_mission(mission.mission_id)

    assert attached.blueprint_id == blueprint.blueprint_id
    assert summary["blueprint_id"] == blueprint.blueprint_id
    assert summary["event_count"] == 2
