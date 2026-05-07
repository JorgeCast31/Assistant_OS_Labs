import ast
from pathlib import Path

from assistant_os.police.enforcer import PoliceEnforcer


ROOT = Path(__file__).resolve().parents[1]
POLICE_DIR = ROOT / "assistant_os" / "police"
PRODUCTION_FILES = sorted(POLICE_DIR.glob("*.py"))

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

FORBIDDEN_TERMS = {
    "PolicyDecision",
    "PoliceDecision",
    "PoliceOutcome",
    "execution_mode",
    "run",
    "execute",
    "dispatch",
    "orchestrator",
    "runner",
    "pipeline",
    "grant_token",
    "approval_id",
    "confirm_plan_id",
    "task_registry",
    "context_store",
    "MissionRegistry",
    "MissionActivity",
    "CapabilityToken",
    "OperationBinding",
    "AuthorizedPlan",
    "consume_token",
    "verify_token",
    "token_issuer",
    "token_verifier",
    "sandbox",
}

WRITE_CALLS = {"open", "Path.write_text", "Path.write_bytes"}
WRITE_ATTRIBUTES = {"write", "write_text", "write_bytes"}


def test_police_module_imports_no_forbidden_modules():
    for source_path in PRODUCTION_FILES:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
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


def test_police_production_source_contains_no_forbidden_terms():
    for source_path in PRODUCTION_FILES:
        source = source_path.read_text(encoding="utf-8")
        for term in FORBIDDEN_TERMS:
            assert term not in source, f"{source_path} contains forbidden term {term}"


def test_police_enforcer_exposes_no_runtime_methods():
    methods = set(dir(PoliceEnforcer))

    assert "execute" not in methods
    assert "run" not in methods
    assert "dispatch" not in methods


def test_police_module_does_not_write_to_disk():
    for source_path in PRODUCTION_FILES:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_name = _call_name(node.func)
                assert call_name not in WRITE_CALLS
                assert _call_attribute(node.func) not in WRITE_ATTRIBUTES


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
