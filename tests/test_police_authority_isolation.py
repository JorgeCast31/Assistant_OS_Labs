import ast
from pathlib import Path

from assistant_os.police.enforcer import PoliceEnforcer


ROOT = Path(__file__).resolve().parents[1]
POLICE_DIR = ROOT / "assistant_os" / "police"
POLICE_V0_FILES = [
    POLICE_DIR / "models.py",
    POLICE_DIR / "enforcer.py",
    POLICE_DIR / "audit.py",
]
POLICE_INIT_FILE = POLICE_DIR / "__init__.py"
POLICE_GATE_FILES = [
    POLICE_DIR / "gate_models.py",
    POLICE_DIR / "enforcement.py",
    POLICE_DIR / "harness.py",
]
POLICE_PRODUCTION_FILES = [POLICE_INIT_FILE] + POLICE_V0_FILES + POLICE_GATE_FILES

FORBIDDEN_IMPORTS = {
    "assistant_os.core",
    "assistant_os.policy",
    "assistant_os.mso",
    "assistant_os.runners",
    "assistant_os.pipelines",
    "assistant_os.executors",
    "assistant_os.capabilities",
    "assistant_os.grants",
    "assistant_os.sandbox",
    "assistant_os.context_store",
    "assistant_os.missions",
    "assistant_os.api",
}

V0_FORBIDDEN_TERMS = {
    "PoliceDecision",
    "PoliceOutcome",
    "PoliceReason",
    "PoliceGateRequest",
    "token_ref",
    "binding_ref",
    "authorized_plan_ref",
    "CapabilityToken",
    "OperationBinding",
    "AuthorizedPlan",
    "consume_token",
    "verify_token",
    "sandbox",
    "harness",
    "apply_police_gate",
}

INIT_FORBIDDEN_TERMS = {
    "PoliceDecision",
    "PoliceOutcome",
    "PoliceReason",
    "PoliceGateRequest",
    "harness",
    "apply_police_gate",
    "check",
}

INIT_FORBIDDEN_IMPORTS = {
    "assistant_os.police.enforcement",
    "from .enforcement",
    "import enforcement",
}

GATE_ALLOWED_TERMS = {
    "PoliceDecision",
    "PoliceOutcome",
    "PoliceReason",
    "PoliceGateRequest",
    "token_ref",
    "binding_ref",
    "authorized_plan_ref",
}

GATE_FORBIDDEN_TERMS = {
    "PoliceEvaluation",
    "PoliceEvaluationType",
    "PoliceEnforcer",
    "PoliceCheckRequest",
    "CapabilityToken",
    "OperationBinding",
    "AuthorizedPlan",
    "consume_token",
    "verify_token",
    "token_issuer",
    "token_verifier",
    "execution_mode",
    "orchestrator",
    "runner",
    "pipeline",
    "execute",
    "dispatch",
    "grant_token",
    "approval_id",
    "confirm_plan_id",
    "task_registry",
    "context_store",
    "MissionRegistry",
    "MissionActivity",
}

WRITE_CALLS = {"open", "Path.write_text", "Path.write_bytes"}
WRITE_ATTRIBUTES = {"write", "write_text", "write_bytes"}


def _read_source(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    return data.decode("utf-8")


def test_police_module_imports_no_forbidden_modules():
    for source_path in POLICE_PRODUCTION_FILES:
        tree = ast.parse(_read_source(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue

            for name in names:
                assert not any(
                    name == forbidden or name.startswith(f"{forbidden}.")
                    for forbidden in FORBIDDEN_IMPORTS
                ), f"{source_path} imports forbidden module {name}"


def test_police_v0_files_contain_no_gate_contract_terms():
    for source_path in POLICE_V0_FILES:
        source = _read_source(source_path)
        for term in V0_FORBIDDEN_TERMS:
            assert term not in source, f"{source_path} contains forbidden term {term}"


def test_police_gate_files_contain_no_runtime_authority_terms():
    for source_path in POLICE_GATE_FILES:
        source = _read_source(source_path)
        for term in GATE_FORBIDDEN_TERMS:
            assert term not in source, f"{source_path} contains forbidden term {term}"
        for term in GATE_ALLOWED_TERMS:
            if term in source:
                assert term in GATE_ALLOWED_TERMS


def test_police_init_does_not_export_gate_types():
    source = _read_source(POLICE_INIT_FILE)

    for term in INIT_FORBIDDEN_TERMS:
        assert term not in source, f"__init__.py contains gate export term {term}"
    for imported_name in INIT_FORBIDDEN_IMPORTS:
        assert imported_name not in source, (
            f"__init__.py contains gate import term {imported_name}"
        )


def test_police_gate_files_import_no_runtime_authority_modules():
    forbidden_imports = {
        "assistant_os.capabilities",
        "assistant_os.sandbox",
        "assistant_os.runners",
        "assistant_os.pipelines",
        "assistant_os.executors",
        "assistant_os.policy",
        "assistant_os.mso",
        "assistant_os.missions",
        "assistant_os.api",
    }

    for source_path in POLICE_GATE_FILES:
        tree = ast.parse(_read_source(source_path))
        for imported_name in _imported_module_names(tree):
            assert not any(
                imported_name == forbidden
                or imported_name.startswith(f"{forbidden}.")
                for forbidden in forbidden_imports
            ), f"{source_path} imports forbidden module {imported_name}"


def test_police_enforcer_exposes_no_runtime_methods():
    methods = set(dir(PoliceEnforcer))

    assert "execute" not in methods
    assert "run" not in methods
    assert "dispatch" not in methods


def test_police_module_does_not_write_to_disk():
    for source_path in POLICE_PRODUCTION_FILES:
        tree = ast.parse(_read_source(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_name = _call_name(node.func)
                assert call_name not in WRITE_CALLS
                assert _call_attribute(node.func) not in WRITE_ATTRIBUTES


def test_apply_police_gate_is_not_used_by_production_outside_police():
    for source_path in _production_python_files_outside_police():
        source = _read_source(source_path)
        assert "apply_police_gate" not in source, (
            f"{source_path} imports or uses dry Police gate harness"
        )


def test_no_production_file_outside_police_imports_police_harness():
    for source_path in _production_python_files_outside_police():
        tree = ast.parse(_read_source(source_path))
        for imported_name in _imported_module_names(tree):
            assert imported_name != "assistant_os.police.harness", (
                f"{source_path} imports assistant_os.police.harness"
            )


def test_no_file_outside_tests_imports_police_enforcement_yet():
    for source_path in _python_files_outside_tests():
        if source_path == POLICE_DIR / "enforcement.py":
            continue
        if source_path == POLICE_DIR / "__init__.py":
            continue

        tree = ast.parse(_read_source(source_path))
        for imported_name in _imported_module_names(tree):
            assert imported_name != "assistant_os.police.enforcement", (
                f"{source_path} imports assistant_os.police.enforcement"
            )


def _imported_module_names(tree):
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


def _production_python_files_outside_police():
    assistant_os_dir = ROOT / "assistant_os"
    police_dir = assistant_os_dir / "police"

    return [
        path
        for path in sorted(assistant_os_dir.rglob("*.py"))
        if police_dir not in path.parents
    ]


def _python_files_outside_tests():
    ignored_parts = {
        ".git",
        ".next",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "archive",
        "node_modules",
        "tests",
        "tests_generated",
        "var",
        "logs",
    }

    return [
        path
        for path in sorted(ROOT.rglob("*.py"))
        if not ignored_parts.intersection(path.relative_to(ROOT).parts)
    ]


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _call_attribute(node):
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""
