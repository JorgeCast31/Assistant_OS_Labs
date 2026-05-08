from pathlib import Path
import subprocess


SOURCE = Path("assistant_os/mso/candidate_orchestration.py")


FORBIDDEN_IMPORTS = (
    "assistant_os.core",
    "assistant_os.runners",
    "assistant_os.pipelines",
    "assistant_os.executors",
    "assistant_os.capabilities",
    "assistant_os.grants",
    "assistant_os.api",
    "assistant_os.police.enforcement",
    "assistant_os.police.harness",
    "assistant_os.police.gate_models",
)

CANDIDATE_FORBIDDEN_STORE_IMPORTS = (
    "assistant_os.audit.stores",
    "PoliceAuditEventStore",
    "CandidateAuditRecordStore",
    "JsonlAuditStore",
)

AUDIT_WIRING_SOURCE = Path("assistant_os/mso/audit_wiring.py")

AUDIT_WIRING_FORBIDDEN_IMPORTS = (
    "assistant_os.core",
    "assistant_os.runners",
    "assistant_os.pipelines",
    "assistant_os.executors",
    "assistant_os.capabilities",
    "assistant_os.grants",
    "assistant_os.api",
    "assistant_os.police.enforcement",
    "assistant_os.police.gate_models",
    "assistant_os.mso.runtime",
)


FORBIDDEN_TEXT = (
    "handle_request",
    "run_mso_cycle",
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
    "Machine Operator",
    "entrypoint",
    "permitted",
    "authorized",
    "consume_token",
    "verify_token",
    "token_verifier",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
)

AUDIT_WIRING_FORBIDDEN_TEXT = FORBIDDEN_TEXT + (
    "sqlite",
    "SQL",
    "docs/atlas",
)


def _source_text() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_candidate_orchestration_avoids_forbidden_imports() -> None:
    text = _source_text()

    for forbidden in FORBIDDEN_IMPORTS:
        assert forbidden not in text


def test_candidate_orchestration_avoids_concrete_audit_stores() -> None:
    text = _source_text()

    for forbidden in CANDIDATE_FORBIDDEN_STORE_IMPORTS:
        assert forbidden not in text


def test_candidate_orchestration_avoids_forbidden_authority_terms() -> None:
    text = _source_text()

    for forbidden in FORBIDDEN_TEXT:
        assert forbidden not in text


def test_audit_wiring_avoids_forbidden_imports() -> None:
    text = AUDIT_WIRING_SOURCE.read_text(encoding="utf-8")

    for forbidden in AUDIT_WIRING_FORBIDDEN_IMPORTS:
        assert forbidden not in text


def test_audit_wiring_avoids_forbidden_authority_terms() -> None:
    text = AUDIT_WIRING_SOURCE.read_text(encoding="utf-8")

    for forbidden in AUDIT_WIRING_FORBIDDEN_TEXT:
        assert forbidden not in text


def test_runtime_cycle_file_is_not_changed() -> None:
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "assistant_os/mso/runtime.py" not in result.stdout.splitlines()
