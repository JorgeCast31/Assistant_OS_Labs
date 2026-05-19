from dataclasses import replace

import pytest

from assistant_os.authority import sign_authority_artifact, verify_authority_artifact
from assistant_os.capabilities.token_issuer import issue_token
from assistant_os.capabilities.token_models import OperationBinding
from assistant_os.capabilities.token_verifier import verify_token
from assistant_os.contracts import ACTION_CODE_FIX, EXECUTION_MODE_CONFIRM
from assistant_os.pipelines.code_pipeline import _build_authorized_plan_from_kernel
from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
from assistant_os.sandbox.authorized_plan import AuthorizedPlan
from assistant_os.sandbox.execution_result import ExecutionMetadata
from assistant_os.sandbox.execution_run import ExecutionRun


def _artifact_payload(**overrides):
    from assistant_os.authority import AUTHORITY_ARTIFACT_VERSION_V2
    payload = {
        "artifact_version": AUTHORITY_ARTIFACT_VERSION_V2,
        "execution_id": "exec-seat-context",
        "plan_id": "plan-seat-context",
        "authorized_plan_hash": "hash-seat-context",
        "policy_id": "default",
        "policy_decision_ref": "decision:seat-context",
        "governance_ref": "governance:seat-context",
        "approval_id": "approval:seat-context",
        "execution_mode": EXECUTION_MODE_CONFIRM,
        "capability_scope": ["code_fix"],
        "runtime_profile": "python3.11",
        "authority_source": "mso",
        "authority_class": "sovereign",
    }
    payload.update(overrides)
    return payload


def _code_plan(**authority_overrides):
    authority_context = {
        "approval_id": "approval:seat-context",
        "policy_decision_ref": "decision:seat-context",
        "governance_ref": "governance:seat-context",
        "execution_mode": EXECUTION_MODE_CONFIRM,
        "delegated_seat_ref": "seat-authority-context",
    }
    authority_context.update(authority_overrides)
    return {
        "plan_id": "plan-seat-context",
        "action": ACTION_CODE_FIX,
        "domain_payload": {"workspace": "C:/tmp"},
        "_authority_context": authority_context,
    }


def test_authority_artifact_signs_delegated_seat_ref():
    artifact = sign_authority_artifact(
        _artifact_payload(delegated_seat_ref="seat-authority-context")
    )

    assert artifact.delegated_seat_ref == "seat-authority-context"
    assert artifact.to_dict()["delegated_seat_ref"] == "seat-authority-context"
    assert verify_authority_artifact(artifact) is True


def test_authority_artifact_verification_fails_when_delegated_seat_ref_changes():
    artifact = sign_authority_artifact(
        _artifact_payload(delegated_seat_ref="seat-authority-context")
    ).to_dict()
    artifact["delegated_seat_ref"] = "seat-other"

    assert verify_authority_artifact(artifact) is False


def test_authorized_plan_carries_delegated_seat_ref_from_authority_context():
    authorized_plan = _build_authorized_plan_from_kernel(_code_plan())

    assert authorized_plan.delegated_seat_ref == "seat-authority-context"
    assert authorized_plan.validate() is None
    assert authorized_plan.authority_artifact.delegated_seat_ref == (
        "seat-authority-context"
    )


def test_authorized_plan_rejects_mismatched_delegated_seat_ref_artifact():
    authorized_plan = _build_authorized_plan_from_kernel(_code_plan())
    authorized_plan.authority_artifact = sign_authority_artifact(
        authorized_plan.authority_artifact.to_dict()
        | {
            "delegated_seat_ref": "seat-other",
        }
    )

    with pytest.raises(ValueError, match="delegated_seat_ref"):
        authorized_plan.validate()


def test_operation_binding_and_token_include_delegated_seat_ref():
    binding = OperationBinding(
        principal_id="user-1",
        subject_state="active",
        action_type="write",
        capability="write_files",
        operation_key="ctx-seat",
        delegated_seat_ref="seat-authority-context",
    )

    token = issue_token(binding)

    assert token.delegated_seat_ref == "seat-authority-context"
    assert verify_token(token, binding) is True
    assert (
        verify_token(
            token,
            replace(binding, delegated_seat_ref="seat-other"),
        )
        is False
    )


def test_authorized_plan_metadata_surfaces_delegated_seat_ref():
    authorized_plan = AuthorizedPlan(
        execution_id="exec-seat-context",
        plan_id="plan-seat-context",
        authorized_plan_hash="hash-seat-context",
        policy_id="default",
        capability_scope=["code_fix"],
        delegated_seat_ref="seat-authority-context",
    )

    run = ExecutionRun(
        execution_id=authorized_plan.execution_id,
        plan_id=authorized_plan.plan_id,
        authorized_plan_hash=authorized_plan.authorized_plan_hash,
        policy_id=authorized_plan.policy_id,
        runtime_profile=authorized_plan.runtime_profile,
        delegated_seat_ref=authorized_plan.delegated_seat_ref,
    )
    metadata = ExecutionMetadata(
        execution_id=authorized_plan.execution_id,
        plan_id=authorized_plan.plan_id,
        policy_id=authorized_plan.policy_id,
        runtime_profile=authorized_plan.runtime_profile,
        duration_ms=10,
        exit_code=0,
        timed_out=False,
        truncated=False,
        authorized_plan_hash=authorized_plan.authorized_plan_hash,
        delegated_seat_ref=authorized_plan.delegated_seat_ref,
    )
    event = ExecutionEvent(
        event_type=AuditEventType.EXECUTION_STARTED,
        execution_id=authorized_plan.execution_id,
        plan_id=authorized_plan.plan_id,
        timestamp=1.0,
        status="running",
        authorized_plan_hash=authorized_plan.authorized_plan_hash,
        policy_id=authorized_plan.policy_id,
        delegated_seat_ref=authorized_plan.delegated_seat_ref,
    )

    assert run.to_dict()["delegated_seat_ref"] == "seat-authority-context"
    assert metadata.to_dict()["delegated_seat_ref"] == "seat-authority-context"
    assert event.to_dict()["delegated_seat_ref"] == "seat-authority-context"
