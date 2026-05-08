from pathlib import Path


AUDIT_MODULE_DIR = Path("assistant_os") / "audit"

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
    "assistant_os.context_store",
)

FORBIDDEN_TEXT = (
    "PoliceDecision",
    "PoliceOutcome",
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
    "sandbox execution",
    "token_verifier",
    "consume_token",
    "verify_token",
    "entrypoint",
    "permitted",
    "authorize",
    "clear",
    "delete",
    "update",
    "sqlite",
    "SQL",
    "docs/atlas",
)


def _audit_sources() -> list[Path]:
    return sorted(AUDIT_MODULE_DIR.glob("*.py"))


def test_audit_module_does_not_import_authority_or_runtime_modules() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in _audit_sources())

    for forbidden_import in FORBIDDEN_IMPORTS:
        assert forbidden_import not in source


def test_audit_module_does_not_contain_forbidden_authority_terms() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in _audit_sources())

    for forbidden_text in FORBIDDEN_TEXT:
        assert forbidden_text not in source


def test_typed_stores_do_not_import_sandbox() -> None:
    source = (AUDIT_MODULE_DIR / "stores.py").read_text(encoding="utf-8")

    assert "assistant_os.sandbox" not in source


def test_sandbox_shim_reexports_jsonl_store() -> None:
    source = (Path("assistant_os") / "sandbox" / "audit_store.py").read_text(
        encoding="utf-8"
    )

    assert "assistant_os.audit.jsonl_store" in source


def test_domain_modules_do_not_import_typed_audit_stores() -> None:
    domain_paths = [
        Path("assistant_os") / "police" / "models.py",
        Path("assistant_os") / "police" / "audit.py",
        Path("assistant_os") / "missions" / "candidate_audit.py",
        Path("assistant_os") / "missions" / "models.py",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in domain_paths)

    assert "assistant_os.audit.stores" not in source
