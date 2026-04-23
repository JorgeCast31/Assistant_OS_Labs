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
        "runner-replay-prevention-test-secret",
    )


@pytest.fixture
def sample_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('authority replay test')\n", encoding="utf-8")
    return repo


def _artifact_payload(execution_id: str, **overrides):
    payload = {
        "artifact_version": AUTHORITY_ARTIFACT_VERSION_V1,
        "execution_id": execution_id,
        "plan_id": execution_id,
        "authorized_plan_hash": "plan-hash-001",
        "policy_id": "default",
        "policy_decision_ref": f"decision:{execution_id}",
        "governance_ref": "gov-runner-001",
        "approval_id": f"approval:{execution_id}",
        "execution_mode": "confirm",
        "capability_scope": ["code_fix"],
        "runtime_profile": "python3.11",
    }
    payload.update(overrides)
    return payload


def _authorized_plan(*, execution_id: str, authority_artifact) -> AuthorizedPlan:
    return AuthorizedPlan(
        execution_id=execution_id,
        plan_id=execution_id,
        authorized_plan_hash="plan-hash-001",
        policy_id="default",
        capability_scope=["code_fix"],
        runtime_profile="python3.11",
        authority_artifact=authority_artifact,
    )


def _request(repo_path: str, plan: AuthorizedPlan) -> RunnerExecutionRequest:
    return RunnerExecutionRequest(
        execution_id=plan.execution_id,
        repo_path=repo_path,
        authorized_plan=plan,
    )


class TestAuthorityReplayPrevention:
    def test_replay_of_same_artifact_fails(self, sample_repo):
        service = RunnerService()
        artifact = sign_authority_artifact(_artifact_payload(execution_id="runner-replay-001"))
        plan = _authorized_plan(execution_id="runner-replay-001", authority_artifact=artifact)

        first = service.run(_request(str(sample_repo), plan))
        second = service.run(_request(str(sample_repo), plan))

        assert first.error is None
        assert second.final_status == "failed"
        assert "replay detected" in (second.error or "")

    def test_distinct_artifacts_succeed(self, sample_repo):
        service = RunnerService()

        artifact_a = sign_authority_artifact(_artifact_payload(execution_id="runner-replay-101"))
        artifact_b = sign_authority_artifact(_artifact_payload(execution_id="runner-replay-102"))

        plan_a = _authorized_plan(execution_id="runner-replay-101", authority_artifact=artifact_a)
        plan_b = _authorized_plan(execution_id="runner-replay-102", authority_artifact=artifact_b)

        result_a = service.run(_request(str(sample_repo), plan_a))
        result_b = service.run(_request(str(sample_repo), plan_b))

        assert result_a.error is None
        assert result_b.error is None
        assert result_a.final_status == "needs_review"
        assert result_b.final_status == "needs_review"
