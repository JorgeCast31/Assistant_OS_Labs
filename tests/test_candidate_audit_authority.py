import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assistant_os" / "missions" / "candidate_audit.py"

FORBIDDEN_TERMS = [
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
    "authorized",
    "persist",
    "save",
    "write",
]

FORBIDDEN_IMPORTS = [
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
    "assistant_os.context_store",
]


def test_candidate_audit_source_avoids_future_authority_terms() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    found = [term for term in FORBIDDEN_TERMS if term in source]

    assert found == []


def test_candidate_audit_imports_stay_isolated() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    forbidden = [
        module
        for module in imports
        for forbidden_import in FORBIDDEN_IMPORTS
        if module == forbidden_import or module.startswith(f"{forbidden_import}.")
    ]

    assert forbidden == []
