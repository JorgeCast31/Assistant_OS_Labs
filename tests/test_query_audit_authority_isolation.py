import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUERY_DIR = ROOT / "assistant_os" / "query"
AUDIT_RECORDS = QUERY_DIR / "audit_records.py"
POLICE_DIR = ROOT / "assistant_os" / "police"
POLICE_ENFORCER_AND_GATE_FILES = (
    POLICE_DIR / "enforcer.py",
    POLICE_DIR / "gate_models.py",
    POLICE_DIR / "enforcement.py",
)

FORBIDDEN_IMPORTS = {
    "assistant_os.mso",
    "assistant_os.police.enforcer",
    "assistant_os.police.gate_models",
    "assistant_os.police.enforcement",
    "assistant_os.runners",
    "assistant_os.pipelines",
    "assistant_os.executors",
    "assistant_os.capabilities",
    "assistant_os.grants",
    "assistant_os.sandbox",
    "assistant_os.api",
    "assistant_os.core",
    "assistant_os.policy",
}

FORBIDDEN_VOCABULARY = {
    "PoliceDecision",
    "PoliceOutcome",
    "PoliceGateRequest",
    "TokenGate",
    "CapabilityToken",
    "AuthorizedPlan",
    "OperationBinding",
    "token_ref",
}

FORBIDDEN_FIELDS = {
    "authorized",
    "permitted",
    "approved",
    "execution_enabled",
    "gate_passed",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imported_module_names(path: Path) -> list[str]:
    tree = ast.parse(_read(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_query_package_does_not_import_forbidden_modules() -> None:
    for source_path in sorted(QUERY_DIR.glob("*.py")):
        imports = _imported_module_names(source_path)
        forbidden = [
            module
            for module in imports
            for blocked in FORBIDDEN_IMPORTS
            if module == blocked or module.startswith(f"{blocked}.")
        ]
        assert forbidden == []


def test_audit_records_contains_no_police_decision_or_token_gate_vocabulary() -> None:
    source = _read(AUDIT_RECORDS)

    for term in FORBIDDEN_VOCABULARY:
        assert term not in source


def test_audit_records_contains_no_authority_field_names() -> None:
    source = _read(AUDIT_RECORDS)

    for term in FORBIDDEN_FIELDS:
        assert term not in source


def test_audit_records_contains_no_emit_call() -> None:
    source = _read(AUDIT_RECORDS)

    assert ".emit(" not in source
    assert "emit(" not in source


def test_audit_records_contains_no_sql_or_runtime_action_terms() -> None:
    source = _read(AUDIT_RECORDS)
    allowed_phrase = "authority to execute"

    for term in ("sqlite", "SQL", "cursor", "runner", "pipeline", "dispatch"):
        assert term not in source

    source_without_qualifier = source.replace(allowed_phrase, "")
    assert "execute" not in source_without_qualifier


def test_audit_records_contains_observational_only_qualifier() -> None:
    source = _read(AUDIT_RECORDS)

    assert "_OBSERVATIONAL_ONLY" in source


def test_police_enforcer_and_gate_modules_do_not_import_query_audit_records() -> None:
    for source_path in POLICE_ENFORCER_AND_GATE_FILES:
        imports = _imported_module_names(source_path)
        assert "assistant_os.query.audit_records" not in imports


def test_audit_records_does_not_import_mso_audit_wiring() -> None:
    imports = _imported_module_names(AUDIT_RECORDS)

    assert "assistant_os.mso.audit_wiring" not in imports
