import ast
from pathlib import Path

from assistant_os.api.mission_api import MissionAPIHandler


ROOT = Path(__file__).resolve().parents[1]
QUERY_PATH = ROOT / "assistant_os" / "missions" / "query.py"
API_PATH = ROOT / "assistant_os" / "api" / "mission_api.py"
ROUTING_PATH = ROOT / "assistant_os" / "core" / "routing.py"

FORBIDDEN_IMPORT_FRAGMENTS = (
    "assistant_os.policy",
    "assistant_os.core.orchestrator",
    "assistant_os.core.routing",
    "assistant_os.core.planning",
    "assistant_os.core.semantic",
    "assistant_os.executors",
    "assistant_os.grants",
    "assistant_os.mso",
    "assistant_os.pipelines",
    "assistant_os.capabilities",
    "assistant_os.context_store",
    "assistant_os.runners",
)

FORBIDDEN_SOURCE_STRINGS = (
    "build_plan",
    "build_policy",
    "get_pipeline",
    "evaluate_policy",
    "evaluate_governance",
    "store_pending_plan",
    "task_registry",
    "trace_aggregator",
    "capability_registry",
    "execution_mode",
    "PolicyDecision",
    "confirm_plan_id",
    "plan_confirmation_required",
    "do_POST",
    "do_PUT",
    "do_PATCH",
    "do_DELETE",
    "open_mission",
    "attach_blueprint",
    "record_event",
    "create_mission",
    "save_blueprint",
    "append_event",
    "update_mission_status",
)

WRITE_METHOD_NAMES = (
    "open_mission",
    "attach_blueprint",
    "record_event",
    "create_mission",
    "save_blueprint",
    "append_event",
    "update_mission_status",
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(_source(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_query_has_no_forbidden_imports() -> None:
    imports = _imports(QUERY_PATH)

    for forbidden in FORBIDDEN_IMPORT_FRAGMENTS:
        assert all(not module.startswith(forbidden) for module in imports)
    assert "assistant_os.missions.service" not in imports


def test_mission_api_has_no_forbidden_imports() -> None:
    imports = _imports(API_PATH)

    for forbidden in FORBIDDEN_IMPORT_FRAGMENTS:
        assert all(not module.startswith(forbidden) for module in imports)


def test_query_has_no_mission_registry_import() -> None:
    source = _source(QUERY_PATH)

    assert "MissionRegistry" not in source


def test_query_has_no_forbidden_source_strings() -> None:
    source = _source(QUERY_PATH)

    for forbidden in FORBIDDEN_SOURCE_STRINGS:
        assert forbidden not in source


def test_mission_api_has_no_forbidden_source_strings() -> None:
    source = _source(API_PATH)

    for forbidden in FORBIDDEN_SOURCE_STRINGS:
        assert forbidden not in source


def test_mission_api_has_no_registry_write_method_calls() -> None:
    tree = ast.parse(_source(API_PATH))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in WRITE_METHOD_NAMES


def test_domain_pipelines_does_not_contain_mission() -> None:
    tree = ast.parse(_source(ROUTING_PATH))
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "DOMAIN_PIPELINES":
                    assert isinstance(node.value, ast.Dict)
                    for key in node.value.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            values.add(key.value)

    assert "MISSION" not in values


def test_query_does_not_call_write_methods() -> None:
    tree = ast.parse(_source(QUERY_PATH))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in WRITE_METHOD_NAMES


def test_handler_exposes_no_non_get_methods() -> None:
    method_names = {name for name in MissionAPIHandler.__dict__ if name.startswith("do_")}

    assert method_names == {"do_GET"}


def test_mission_api_source_has_no_http_mutation_methods() -> None:
    source = _source(API_PATH)

    for method_name in ("do_POST", "do_PUT", "do_PATCH", "do_DELETE"):
        assert method_name not in source
