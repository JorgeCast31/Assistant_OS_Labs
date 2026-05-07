import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assistant_os" / "missions" / "execution_candidate.py"


FORBIDDEN_TERMS = (
    "PoliceDecision",
    "PoliceOutcome",
    "PoliceReason",
    "PoliceGateRequest",
    "enforcement.check",
    "CapabilityToken",
    "AuthorizedPlan",
    "OperationBinding",
    "token_ref",
    "binding_ref",
    "authorized_plan_ref",
    "runner",
    "pipeline",
    "execute",
    "dispatch",
    "sandbox",
    "token_verifier",
    "consume_token",
    "verify_token",
    "entrypoint",
    "permitted",
)


FORBIDDEN_IMPORTS = (
    "assistant_os.runners",
    "assistant_os.pipelines",
    "assistant_os.executors",
    "assistant_os.capabilities",
    "assistant_os.grants",
    "assistant_os.police.enforcement",
    "assistant_os.police.harness",
    "assistant_os.police.gate_models",
    "assistant_os.api",
    "assistant_os.core",
    "assistant_os.mso",
    "assistant_os.policy",
)


FORBIDDEN_STORE_OR_WRITE_NAMES = (
    "MissionStore",
    "save",
    "persist",
    "write",
)


def _source() -> str:
    return SOURCE.read_text()


def test_candidate_source_has_no_forbidden_authority_terms():
    source = _source()

    for forbidden_term in FORBIDDEN_TERMS:
        assert forbidden_term not in source


def test_candidate_source_has_no_forbidden_imports():
    source = _source()

    for forbidden_import in FORBIDDEN_IMPORTS:
        assert forbidden_import not in source


def test_candidate_module_imports_only_allowed_assistant_os_modules():
    tree = ast.parse(_source())
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    assistant_imports = [
        imported for imported in imports if imported.startswith("assistant_os.")
    ]

    assert assistant_imports == [
        "assistant_os.agents.permissions",
        "assistant_os.police.models",
    ]


def test_candidate_module_has_no_store_or_write_surfaces():
    tree = ast.parse(_source())

    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)

    for forbidden_name in FORBIDDEN_STORE_OR_WRITE_NAMES:
        assert forbidden_name not in names
