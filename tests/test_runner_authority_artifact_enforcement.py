"""
S-RUNNER-AUTHORITY-ARTIFACT-ENFORCEMENT-01

Tests for V2 AuthorityArtifact schema and fail-closed Runner enforcement.

RED: All tests here must fail before the implementation is written.
"""
from __future__ import annotations

import pytest

from assistant_os.authority import (
    AUTHORITY_ARTIFACT_SECRET_ENV_VAR,
    sign_authority_artifact,
    verify_authority_artifact,
)
from assistant_os.runners.runner_models import RunnerExecutionRequest
from assistant_os.runners.runner_service import RunnerService
from assistant_os.sandbox.authorized_plan import AuthorizedPlan


@pytest.fixture(autouse=True)
def _artifact_secret(monkeypatch):
    monkeypatch.setenv(
        AUTHORITY_ARTIFACT_SECRET_ENV_VAR,
        "enforcement-sprint-test-secret",
    )


@pytest.fixture
def sample_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('enforcement')\n", encoding="utf-8")
    return repo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sovereign_payload(execution_id: str = "exec-s-001", **overrides) -> dict:
    from assistant_os.authority.artifact import AUTHORITY_ARTIFACT_VERSION_V2
    payload = {
        "artifact_version": AUTHORITY_ARTIFACT_VERSION_V2,
        "execution_id": execution_id,
        "plan_id": execution_id,
        "authorized_plan_hash": "hash-sovereign-001",
        "policy_id": "default",
        "policy_decision_ref": f"decision:{execution_id}",
        "governance_ref": "gov-sovereign-001",
        "approval_id": f"approval:{execution_id}",
        "execution_mode": "confirm",
        "capability_scope": ["code_fix"],
        "runtime_profile": "python3.11",
        "authority_source": "mso",
        "authority_class": "sovereign",
    }
    payload.update(overrides)
    return payload


def _external_local_payload(execution_id: str = "exec-el-001", **overrides) -> dict:
    from assistant_os.authority.artifact import AUTHORITY_ARTIFACT_VERSION_V2
    payload = {
        "artifact_version": AUTHORITY_ARTIFACT_VERSION_V2,
        "execution_id": execution_id,
        "plan_id": execution_id,
        "authorized_plan_hash": "hash-el-001",
        "policy_id": "default",
        "policy_decision_ref": f"external_local:code_api:{execution_id}",
        "governance_ref": f"external_local:code_api:{execution_id}",
        "approval_id": f"external_local:code_api:{execution_id}",
        "execution_mode": "external_local",
        "capability_scope": ["code_execute"],
        "runtime_profile": "python3.11",
        "authority_source": "code_api",
        "authority_class": "external_local",
    }
    payload.update(overrides)
    return payload


def _authorized_plan(
    *,
    authority_artifact,
    execution_id: str,
    plan_hash: str,
    capability_scope: list[str] | None = None,
) -> AuthorizedPlan:
    return AuthorizedPlan(
        execution_id=execution_id,
        plan_id=execution_id,
        authorized_plan_hash=plan_hash,
        policy_id="default",
        capability_scope=capability_scope or ["code_fix"],
        runtime_profile="python3.11",
        authority_artifact=authority_artifact,
    )


def _request(repo_path: str, authorized_plan: AuthorizedPlan | None) -> RunnerExecutionRequest:
    execution_id = authorized_plan.execution_id if authorized_plan is not None else "exec-no-plan"
    return RunnerExecutionRequest(
        execution_id=execution_id,
        repo_path=repo_path,
        authorized_plan=authorized_plan,
    )


# ---------------------------------------------------------------------------
# 1. Artifact schema tests
# ---------------------------------------------------------------------------

class TestArtifactSchemaV2:
    def test_v2_artifact_includes_authority_source_and_class(self):
        from assistant_os.authority.artifact import AUTHORITY_ARTIFACT_VERSION_V2
        artifact = sign_authority_artifact(_sovereign_payload())
        d = artifact.to_dict()
        assert d["artifact_version"] == AUTHORITY_ARTIFACT_VERSION_V2
        assert d["authority_source"] == "mso"
        assert d["authority_class"] == "sovereign"

    def test_authority_source_and_class_are_signed(self):
        artifact = sign_authority_artifact(_sovereign_payload()).to_dict()
        artifact["authority_source"] = "tampered"
        assert verify_authority_artifact(artifact) is False

    def test_authority_class_is_signed(self):
        artifact = sign_authority_artifact(_sovereign_payload()).to_dict()
        artifact["authority_class"] = "external_local"
        assert verify_authority_artifact(artifact) is False

    def test_missing_authority_source_fails(self):
        from assistant_os.authority.artifact import canonicalize_authority_artifact
        payload = _sovereign_payload()
        del payload["authority_source"]
        with pytest.raises(ValueError, match="missing required fields"):
            canonicalize_authority_artifact(payload)

    def test_missing_authority_class_fails(self):
        from assistant_os.authority.artifact import canonicalize_authority_artifact
        payload = _sovereign_payload()
        del payload["authority_class"]
        with pytest.raises(ValueError, match="missing required fields"):
            canonicalize_authority_artifact(payload)

    def test_invalid_authority_source_fails_validation(self):
        payload = _sovereign_payload(authority_source="unknown_source")
        with pytest.raises(ValueError, match="authority_source"):
            sign_authority_artifact(payload)

    def test_invalid_authority_class_fails_validation(self):
        payload = _sovereign_payload(authority_class="unknown_class")
        with pytest.raises(ValueError, match="authority_class"):
            sign_authority_artifact(payload)

    def test_mismatched_combo_mso_external_local_fails(self):
        payload = _sovereign_payload(authority_source="mso", authority_class="external_local")
        with pytest.raises(ValueError, match="authority_source.*authority_class|authority_class.*authority_source|Invalid authority combination"):
            sign_authority_artifact(payload)

    def test_mismatched_combo_code_api_sovereign_fails(self):
        payload = _external_local_payload(authority_source="code_api", authority_class="sovereign")
        with pytest.raises(ValueError, match="authority_source.*authority_class|authority_class.*authority_source|Invalid authority combination"):
            sign_authority_artifact(payload)

    def test_sovereign_artifact_with_sentinel_governance_refs_fails(self):
        payload = _sovereign_payload(
            policy_decision_ref="external_local:code_api:exec-s-001",
            governance_ref="external_local:code_api:exec-s-001",
            approval_id="external_local:code_api:exec-s-001",
            execution_mode="external_local",
        )
        with pytest.raises(ValueError, match="sovereign.*external_local|governance|sentinel"):
            sign_authority_artifact(payload)

    def test_external_local_artifact_with_traceable_refs_passes(self):
        artifact = sign_authority_artifact(_external_local_payload())
        assert verify_authority_artifact(artifact.to_dict()) is True

    def test_v1_artifact_rejected_for_execution(self):
        from assistant_os.authority.artifact import AUTHORITY_ARTIFACT_VERSION_V1
        payload = _sovereign_payload(artifact_version=AUTHORITY_ARTIFACT_VERSION_V1)
        del payload["authority_source"]
        del payload["authority_class"]
        with pytest.raises(ValueError):
            sign_authority_artifact(payload)


# ---------------------------------------------------------------------------
# 2. Runner fail-closed enforcement tests
# ---------------------------------------------------------------------------

class TestRunnerFailClosed:
    def test_runner_rejects_missing_authorized_plan(self, sample_repo):
        req = RunnerExecutionRequest(
            execution_id="exec-no-plan",
            repo_path=str(sample_repo),
            authorized_plan=None,
        )
        result = RunnerService().run(req)
        assert result.final_status == "failed"
        assert result.workspace_path is None
        assert result.error is not None
        assert "authorized_plan" in result.error.lower() or "authority" in result.error.lower()

    def test_runner_rejects_missing_authority_artifact(self, sample_repo):
        plan = AuthorizedPlan(
            execution_id="exec-no-artifact",
            plan_id="exec-no-artifact",
            authorized_plan_hash="hash-no-artifact",
            policy_id="default",
            capability_scope=["code_fix"],
            runtime_profile="python3.11",
            authority_artifact=None,
        )
        req = RunnerExecutionRequest(
            execution_id="exec-no-artifact",
            repo_path=str(sample_repo),
            authorized_plan=plan,
        )
        result = RunnerService().run(req)
        assert result.final_status == "failed"
        assert result.workspace_path is None
        assert result.error is not None
        assert "authority_artifact" in result.error.lower() or "authority artifact" in result.error.lower()

    def test_runner_rejects_invalid_signature(self, sample_repo):
        artifact = sign_authority_artifact(_sovereign_payload()).to_dict()
        artifact["signature"] = "deadbeef" * 8
        plan = _authorized_plan(
            authority_artifact=artifact,
            execution_id="exec-s-001",
            plan_hash="hash-sovereign-001",
        )
        result = RunnerService().run(_request(str(sample_repo), plan))
        assert result.final_status == "failed"
        assert "Authority artifact verification failed" in (result.error or "")

    def test_runner_rejects_replay(self, sample_repo):
        service = RunnerService()
        artifact = sign_authority_artifact(_sovereign_payload(execution_id="exec-replay-001"))
        plan = _authorized_plan(
            authority_artifact=artifact,
            execution_id="exec-replay-001",
            plan_hash="hash-sovereign-001",
        )
        first = service.run(_request(str(sample_repo), plan))
        second = service.run(_request(str(sample_repo), plan))
        assert first.error is None
        assert second.final_status == "failed"
        assert "replay" in (second.error or "").lower()

    def test_runner_rejects_unknown_authority_source(self, sample_repo):
        payload = _sovereign_payload(execution_id="exec-bad-src")
        # Build artifact with unknown source by bypassing sign validation — tamper after signing
        # Since sign_authority_artifact validates, we need a different approach:
        # sign a valid artifact then tamper the source (which will break signature)
        # Instead test that an artifact with unknown source embedded is rejected at Runner
        # We can't easily produce one without bypassing signing — so test via Runner with tampered artifact
        artifact = sign_authority_artifact(_sovereign_payload(execution_id="exec-bad-src")).to_dict()
        artifact["authority_source"] = "unknown_source"
        # signature now invalid — Runner should reject it at signature check
        plan = _authorized_plan(
            authority_artifact=artifact,
            execution_id="exec-bad-src",
            plan_hash="hash-sovereign-001",
        )
        result = RunnerService().run(_request(str(sample_repo), plan))
        assert result.final_status == "failed"
        assert result.error is not None

    def test_runner_permits_valid_sovereign_artifact(self, sample_repo):
        artifact = sign_authority_artifact(_sovereign_payload())
        plan = _authorized_plan(
            authority_artifact=artifact,
            execution_id="exec-s-001",
            plan_hash="hash-sovereign-001",
        )
        result = RunnerService().run(_request(str(sample_repo), plan))
        assert result.error is None
        assert result.final_status == "needs_review"

    def test_runner_permits_valid_external_local_artifact(self, sample_repo):
        artifact = sign_authority_artifact(_external_local_payload(execution_id="exec-el-run"))
        plan = _authorized_plan(
            authority_artifact=artifact,
            execution_id="exec-el-run",
            plan_hash="hash-el-001",
            capability_scope=["code_execute"],
        )
        result = RunnerService().run(_request(str(sample_repo), plan))
        assert result.error is None
        assert result.final_status == "needs_review"

    def test_runner_replay_check_applies_to_external_local(self, sample_repo):
        service = RunnerService()
        artifact = sign_authority_artifact(_external_local_payload(execution_id="exec-el-replay"))
        plan = _authorized_plan(
            authority_artifact=artifact,
            execution_id="exec-el-replay",
            plan_hash="hash-el-001",
            capability_scope=["code_execute"],
        )
        first = service.run(_request(str(sample_repo), plan))
        second = service.run(_request(str(sample_repo), plan))
        assert first.error is None
        assert second.final_status == "failed"
        assert "replay" in (second.error or "").lower()


# ---------------------------------------------------------------------------
# 3. code_pipeline produces sovereign artifact
# ---------------------------------------------------------------------------

class TestCodePipelineSovereignArtifact:
    def _code_plan(self, plan_id: str = "plan-pipeline-v2") -> dict:
        return {
            "plan_id": plan_id,
            "action": "code_fix",
            "domain_payload": {"workspace": "/repo"},
            "_authority_context": {
                "token_ref": "tok-001",
                "binding_ref": "binding:code_fix:auto",
                "authorized_plan_ref": "ap-001",
                "capability_name": "code_fix",
                "governance_ref": "gov-001",
                "policy_decision_ref": "decision:plan-pipeline-v2",
                "execution_id": plan_id,
                "trace_id": "trace-001",
                "approval_id": "approval:plan-pipeline-v2",
                "execution_mode": "auto",
            },
        }

    def test_kernel_path_produces_mso_sovereign_artifact(self):
        from assistant_os.pipelines.code_pipeline import _build_authorized_plan_from_kernel
        plan = self._code_plan()
        ap = _build_authorized_plan_from_kernel(plan)
        assert ap.authority_artifact is not None
        d = ap.authority_artifact.to_dict() if hasattr(ap.authority_artifact, "to_dict") else dict(ap.authority_artifact)
        assert d["authority_source"] == "mso"
        assert d["authority_class"] == "sovereign"

    def test_kernel_path_artifact_is_v2(self):
        from assistant_os.authority.artifact import AUTHORITY_ARTIFACT_VERSION_V2
        from assistant_os.pipelines.code_pipeline import _build_authorized_plan_from_kernel
        plan = self._code_plan()
        ap = _build_authorized_plan_from_kernel(plan)
        assert ap.authority_artifact is not None
        d = ap.authority_artifact.to_dict() if hasattr(ap.authority_artifact, "to_dict") else dict(ap.authority_artifact)
        assert d["artifact_version"] == AUTHORITY_ARTIFACT_VERSION_V2

    def test_kernel_path_artifact_passes_validate(self):
        from assistant_os.pipelines.code_pipeline import _build_authorized_plan_from_kernel
        plan = self._code_plan()
        ap = _build_authorized_plan_from_kernel(plan)
        ap.validate()  # must not raise


# ---------------------------------------------------------------------------
# 4. code_api produces external_local artifact
# ---------------------------------------------------------------------------

class TestCodeApiExternalLocalArtifact:
    def _body(self, execution_id: str = "exec-api-v2") -> dict:
        return {
            "repo_path": "/repo",
            "code": "print('test')",
            "plan_id": execution_id,
            "policy_id": "default",
            "capability_scope": ["code_execute"],
        }

    def test_code_api_produces_external_local_artifact(self):
        from assistant_os.api.code_api import _build_authorized_plan
        plan = _build_authorized_plan("exec-api-v2", self._body())
        assert plan.authority_artifact is not None
        d = plan.authority_artifact.to_dict() if hasattr(plan.authority_artifact, "to_dict") else dict(plan.authority_artifact)
        assert d["authority_source"] == "code_api"
        assert d["authority_class"] == "external_local"

    def test_code_api_artifact_is_v2(self):
        from assistant_os.authority.artifact import AUTHORITY_ARTIFACT_VERSION_V2
        from assistant_os.api.code_api import _build_authorized_plan
        plan = _build_authorized_plan("exec-api-v2", self._body())
        assert plan.authority_artifact is not None
        d = plan.authority_artifact.to_dict() if hasattr(plan.authority_artifact, "to_dict") else dict(plan.authority_artifact)
        assert d["artifact_version"] == AUTHORITY_ARTIFACT_VERSION_V2

    def test_code_api_artifact_is_signed_and_validates(self):
        from assistant_os.api.code_api import _build_authorized_plan
        plan = _build_authorized_plan("exec-api-v2", self._body())
        assert plan.authority_artifact is not None
        assert verify_authority_artifact(plan.authority_artifact.to_dict()) is True
        plan.validate()  # must not raise

    def test_code_api_artifact_uses_traceable_refs(self):
        from assistant_os.api.code_api import _build_authorized_plan
        execution_id = "exec-api-traceable"
        plan = _build_authorized_plan(execution_id, self._body(execution_id))
        d = plan.authority_artifact.to_dict() if hasattr(plan.authority_artifact, "to_dict") else dict(plan.authority_artifact)
        assert execution_id in d["policy_decision_ref"]
        assert execution_id in d["governance_ref"]
        assert execution_id in d["approval_id"]
        assert d["execution_mode"] == "external_local"

    def test_code_api_does_not_claim_mso_authority(self):
        from assistant_os.api.code_api import _build_authorized_plan
        plan = _build_authorized_plan("exec-api-v2", self._body())
        d = plan.authority_artifact.to_dict() if hasattr(plan.authority_artifact, "to_dict") else dict(plan.authority_artifact)
        assert d["authority_source"] != "mso"
        assert d["authority_class"] != "sovereign"
