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


def _source_text() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_candidate_orchestration_avoids_forbidden_imports() -> None:
    text = _source_text()

    for forbidden in FORBIDDEN_IMPORTS:
        assert forbidden not in text


def test_candidate_orchestration_avoids_forbidden_authority_terms() -> None:
    text = _source_text()

    for forbidden in FORBIDDEN_TEXT:
        assert forbidden not in text


def test_runtime_cycle_file_is_not_changed() -> None:
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "assistant_os/mso/runtime.py" not in result.stdout.splitlines()
