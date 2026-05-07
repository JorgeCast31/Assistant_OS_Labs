import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assistant_os" / "agents" / "permissions.py"


FORBIDDEN_IMPORTS = (
    "assistant_os.core",
    "assistant_os.policy",
    "assistant_os.mso",
    "assistant_os.runners",
    "assistant_os.pipelines",
    "assistant_os.executors",
    "assistant_os.capabilities",
    "assistant_os.grants",
    "assistant_os.context_store",
    "assistant_os.missions",
    "assistant_os.api",
    "assistant_os.police.gate_models",
    "assistant_os.police.enforcement",
    "assistant_os.police.harness",
)


FORBIDDEN_TERMS = (
    "PoliceDecision",
    "PoliceOutcome",
    "PoliceReason",
    "PoliceGateRequest",
    "enforcement.check",
    "apply_police_gate",
    "CapabilityToken",
    "OperationBinding",
    "AuthorizedPlan",
    "token_ref",
    "binding_ref",
    "authorized_plan_ref",
    "verify_token",
    "consume_token",
    "token_issuer",
    "token_verifier",
    "runner",
    "pipeline",
    "execute",
    "dispatch",
    "sandbox",
    "entrypoint",
)


ALLOWED_REGISTRY_KEYS = {
    "name",
    "domain",
    "version",
    "description",
    "input_contract",
    "output_contract",
    "requires_review",
    "capability_scope",
}


def test_agent_permission_bridge_has_no_forbidden_authority_imports():
    source = SOURCE.read_text()

    for forbidden_import in FORBIDDEN_IMPORTS:
        assert forbidden_import not in source


def test_agent_permission_bridge_has_no_forbidden_authority_terms():
    source = SOURCE.read_text()

    for forbidden_term in FORBIDDEN_TERMS:
        assert forbidden_term not in source


def test_agent_permission_bridge_reads_only_allowed_registry_keys():
    tree = ast.parse(SOURCE.read_text())
    registry_keys: list[str] = []

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "definition"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            registry_keys.append(node.args[0].value)

        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "definition"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            registry_keys.append(node.slice.value)

    assert registry_keys
    assert set(registry_keys) <= ALLOWED_REGISTRY_KEYS
    assert "entrypoint" not in registry_keys
