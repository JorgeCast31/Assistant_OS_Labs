from __future__ import annotations

from dataclasses import replace

import pytest
from unittest.mock import patch

from assistant_os.authority import (
    AUTHORITY_ARTIFACT_SECRET_ENV_VAR,
    AuthorityArtifact,
    verify_authority_artifact,
)
from assistant_os.context_store import clear_store, get_pending_plan
from assistant_os.contracts import (
    ACTION_CODE_FIX,
    EXECUTION_MODE_CONFIRM,
    RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED,
    RISK_MEDIUM,
    normalize_request,
    now_iso,
)
from assistant_os.core.orchestrator import handle_request
from assistant_os.mso.contracts import GovernanceDecision
from assistant_os.pipelines.code_pipeline import _build_authorized_plan_from_kernel


@pytest.fixture(autouse=True)
def _clear_context_store():
    clear_store()
    yield
    clear_store()


@pytest.fixture(autouse=True)
def _artifact_secret(monkeypatch):
    monkeypatch.setenv(AUTHORITY_ARTIFACT_SECRET_ENV_VAR, "authority-boundary-secret")


def _governance_decision() -> GovernanceDecision:
    return GovernanceDecision(
        governance_ref="gov-boundary-001",
        action="permit",
        target_domain="CODE",
        target_action=ACTION_CODE_FIX,
        effective_execution_mode=EXECUTION_MODE_CONFIRM,
        risk_level="medium",
        justification="test governance",
        reasons=[],
        constraints=[],
        interventions=[],
        capability_mode="static",
        base_execution_mode=EXECUTION_MODE_CONFIRM,
        operational_mode="NORMAL",
        created_at=now_iso(),
        dynamic_factors=[],
        anomaly_signals=[],
    )


def _structured_code_fix_request(tmp_path):
    return normalize_request(
        text="fix src/foo.py",
        metadata={
            "action": ACTION_CODE_FIX,
            "domain": "CODE",
            "risk_level": RISK_MEDIUM,
            "requires_confirmation": True,
            "domain_payload": {
                "workspace": str(tmp_path),
                "target_file": "src/foo.py",
            },
        },
    )


class TestCodeAuthorityArtifactBoundary:
    @patch("assistant_os.core.orchestrator._consult_mso_advisory", return_value=None)
    @patch("assistant_os.core.orchestrator._evaluate_mso_governance", return_value=_governance_decision())
    def test_confirm_path_stores_authority_context_from_canonical_inputs(
        self,
        _mock_governance,
        _mock_advisory,
        tmp_path,
    ):
        req = _structured_code_fix_request(tmp_path)

        result = handle_request(req)

        assert result["result_type"] == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED
        plan_id = result["data"]["plan_id"]
        stored = get_pending_plan(plan_id)
        assert stored is not None

        authority_context = stored["plan"].get("_authority_context") or {}
        assert authority_context["policy_decision_ref"] == f"decision:{plan_id}"
        assert authority_context["approval_id"] == f"approval:confirm:{plan_id}"
        assert authority_context["governance_ref"] == "gov-boundary-001"
        assert authority_context["execution_mode"] == EXECUTION_MODE_CONFIRM

    def test_authority_artifact_created_from_canonical_authority_inputs(self, tmp_path):
        plan = {
            "plan_id": "kernel-plan-boundary-001",
            "action": ACTION_CODE_FIX,
            "domain_payload": {"workspace": str(tmp_path)},
            "_authority_context": {
                "approval_id": "approval-boundary-001",
                "policy_decision_ref": "decision:kernel-plan-boundary-001",
                "governance_ref": "gov-boundary-001",
                "execution_mode": EXECUTION_MODE_CONFIRM,
            },
        }

        authorized_plan = _build_authorized_plan_from_kernel(plan)

        artifact = authorized_plan.authority_artifact
        assert isinstance(artifact, AuthorityArtifact)
        assert artifact.execution_id == "kernel-plan-boundary-001"
        assert artifact.plan_id == "kernel-plan-boundary-001"
        assert artifact.policy_decision_ref == "decision:kernel-plan-boundary-001"
        assert artifact.governance_ref == "gov-boundary-001"
        assert artifact.approval_id == "approval-boundary-001"
        assert artifact.execution_mode == EXECUTION_MODE_CONFIRM
        assert artifact.policy_id == authorized_plan.policy_id
        assert artifact.capability_scope == ["code_fix"]

    def test_authority_artifact_signature_verifies_immediately_after_creation(self, tmp_path):
        plan = {
            "plan_id": "kernel-plan-boundary-002",
            "action": ACTION_CODE_FIX,
            "domain_payload": {"workspace": str(tmp_path)},
            "_authority_context": {
                "approval_id": "approval-boundary-002",
                "policy_decision_ref": "decision:kernel-plan-boundary-002",
                "governance_ref": "gov-boundary-002",
                "execution_mode": EXECUTION_MODE_CONFIRM,
            },
        }

        authorized_plan = _build_authorized_plan_from_kernel(plan)
        artifact = authorized_plan.authority_artifact

        assert isinstance(artifact, AuthorityArtifact)
        assert verify_authority_artifact(artifact) is True
        authorized_plan.validate()

    def test_changing_carried_authority_field_breaks_boundary_validation(self, tmp_path):
        plan = {
            "plan_id": "kernel-plan-boundary-003",
            "action": ACTION_CODE_FIX,
            "domain_payload": {"workspace": str(tmp_path)},
            "_authority_context": {
                "approval_id": "approval-boundary-003",
                "policy_decision_ref": "decision:kernel-plan-boundary-003",
                "governance_ref": "gov-boundary-003",
                "execution_mode": EXECUTION_MODE_CONFIRM,
            },
        }

        authorized_plan = _build_authorized_plan_from_kernel(plan)
        authorized_plan.policy_id = "readonly"

        with pytest.raises(ValueError, match="must match AuthorizedPlan.policy_id"):
            authorized_plan.validate()

    def test_changing_signed_authority_field_breaks_verification(self, tmp_path):
        plan = {
            "plan_id": "kernel-plan-boundary-004",
            "action": ACTION_CODE_FIX,
            "domain_payload": {"workspace": str(tmp_path)},
            "_authority_context": {
                "approval_id": "approval-boundary-004",
                "policy_decision_ref": "decision:kernel-plan-boundary-004",
                "governance_ref": "gov-boundary-004",
                "execution_mode": EXECUTION_MODE_CONFIRM,
            },
        }

        authorized_plan = _build_authorized_plan_from_kernel(plan)
        artifact = authorized_plan.authority_artifact
        assert isinstance(artifact, AuthorityArtifact)

        authorized_plan.authority_artifact = replace(artifact, execution_mode="blocked")
        with pytest.raises(ValueError, match="valid signature"):
            authorized_plan.validate()

    def test_authority_artifact_serializes_existing_policy_verdict_only(self, tmp_path):
        plan = {
            "plan_id": "kernel-plan-boundary-005",
            "action": ACTION_CODE_FIX,
            "domain_payload": {"workspace": str(tmp_path)},
            "_authority_context": {
                "approval_id": "approval-boundary-005",
                "policy_decision_ref": "decision:kernel-plan-boundary-005",
                "governance_ref": "gov-boundary-005",
                "execution_mode": EXECUTION_MODE_CONFIRM,
            },
        }

        authorized_plan = _build_authorized_plan_from_kernel(plan)
        artifact = authorized_plan.authority_artifact

        assert isinstance(artifact, AuthorityArtifact)
        assert artifact.execution_mode == EXECUTION_MODE_CONFIRM
