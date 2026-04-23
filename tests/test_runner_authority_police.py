from __future__ import annotations

import pytest

from assistant_os.authority import (
    AUTHORITY_ARTIFACT_SECRET_ENV_VAR,
    AUTHORITY_ARTIFACT_VERSION_V1,
    sign_authority_artifact,
)
from assistant_os.runners.runner_models import RunnerExecutionRequest
from assistant_os.runners.runner_service import RunnerService
from assistant_os.sandbox.authorized_plan import AuthorizedPlan


@pytest.fixture(autouse=True)
def _artifact_secret(monkeypatch):
    monkeypatch.setenv(
        AUTHORITY_ARTIFACT_SECRET_ENV_VAR,
        "runner-authority-police-test-secret",
    )


@pytest.fixture
def sample_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('runner authority police')\n", encoding="utf-8")
    return repo


def _artifact_payload(**overrides):
    payload = {
        "artifact_version": AUTHORITY_ARTIFACT_VERSION_V1,
        "execution_id": "runner-authority-001",
        "plan_id": "runner-authority-001",
        "authorized_plan_hash": "plan-hash-001",
        "policy_id": "default",
        "policy_decision_ref": "decision:runner-authority-001",
        "governance_ref": "gov-runner-001",
        "approval_id": "approval-runner-001",
        "execution_mode": "confirm",
        "capability_scope": ["code_fix"],
        "runtime_profile": "python3.11",
    }
    payload.update(overrides)
    return payload


def _authorized_plan(*, authority_artifact, **overrides):
    params = {
        "execution_id": "runner-authority-001",
        "plan_id": "runner-authority-001",
        "authorized_plan_hash": "plan-hash-001",
        "policy_id": "default",
        "capability_scope": ["code_fix"],
        "runtime_profile": "python3.11",
        "authority_artifact": authority_artifact,
    }
    params.update(overrides)
    return AuthorizedPlan(**params)


def _request(repo_path: str, authorized_plan: AuthorizedPlan) -> RunnerExecutionRequest:
    return RunnerExecutionRequest(
        execution_id=authorized_plan.execution_id,
        repo_path=repo_path,
        authorized_plan=authorized_plan,
    )


class TestRunnerAuthorityPolice:
    def test_valid_authority_artifact_passes_preflight(self, sample_repo):
        artifact = sign_authority_artifact(_artifact_payload())
        plan = _authorized_plan(authority_artifact=artifact)

        result = RunnerService().run(_request(str(sample_repo), plan))

        assert result.error is None
        assert result.workspace_path is not None
        assert result.final_status == "needs_review"

    def test_invalid_signature_fails_closed(self, sample_repo):
        artifact = sign_authority_artifact(_artifact_payload()).to_dict()
        artifact["signature"] = "invalid-signature"
        plan = _authorized_plan(authority_artifact=artifact)

        result = RunnerService().run(_request(str(sample_repo), plan))

        assert result.final_status == "failed"
        assert result.workspace_path is None
        assert "Authority artifact verification failed" in (result.error or "")
        assert "valid signature" in (result.error or "")

    def test_tampered_payload_fails_closed(self, sample_repo):
        artifact = sign_authority_artifact(_artifact_payload()).to_dict()
        artifact["execution_mode"] = "blocked"
        plan = _authorized_plan(authority_artifact=artifact)

        result = RunnerService().run(_request(str(sample_repo), plan))

        assert result.final_status == "failed"
        assert result.workspace_path is None
        assert "Authority artifact verification failed" in (result.error or "")
        assert "valid signature" in (result.error or "")

    def test_missing_required_fields_fail_closed(self, sample_repo):
        artifact = sign_authority_artifact(_artifact_payload()).to_dict()
        del artifact["approval_id"]
        plan = _authorized_plan(authority_artifact=artifact)

        result = RunnerService().run(_request(str(sample_repo), plan))

        assert result.final_status == "failed"
        assert result.workspace_path is None
        assert "Authority artifact verification failed" in (result.error or "")
        assert "missing required fields" in (result.error or "")
