from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
import requests

from assistant_os.mso.machine_operator_adapter import (
    MachineOperatorAdapterContext,
    OpenClawGatewayMachineOperatorAdapter,
    reset_machine_operator_backend_health,
)
from assistant_os.mso.sovereign_state_store import (
    SovereignDecisionReason,
    SovereignExecutionDecision,
)
from assistant_os.openclaw_backend.server import start_server_thread


def _future_iso(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_iso(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _context(
    capability_name: str = "browser.navigate",
    capability_tier: str = "interactive",
) -> MachineOperatorAdapterContext:
    return MachineOperatorAdapterContext(
        plan_id="plan-neg-001",
        execution_id="exec-neg-001",
        trace_id="trace-neg-001",
        policy_decision_ref="policy-neg-001",
        capability_name=capability_name,
        capability_tier=capability_tier,
        policy_reason_code="allowed",
        policy_message=f"MACHINE_OPERATOR capability allowed: {capability_name}",
    )


def _approval(
    *,
    approval_id: str = "approval-neg-001",
    expires_at: str | None = None,
    capability_scope: list[str] | None = None,
) -> dict[str, object]:
    return {
        "approval_id": approval_id,
        "approved_for": "single_step",
        "capability_scope": capability_scope if capability_scope is not None else ["browser.navigate"],
        "expires_at": expires_at if expires_at is not None else _future_iso(),
        "issued_by": "reviewer:test",
        "reason": "negative validation test",
    }


def _request(
    *,
    capability_name: str = "browser.navigate",
    capability_tier: str = "interactive",
    approval: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "intent_id": "intent-neg-001",
        "correlation_id": "corr-neg-001",
        "capability_name": capability_name,
        "capability_tier": capability_tier,
        "arguments": {"url": "https://example.test"},
        "policy_context": {
            "policy_decision_ref": "policy-neg-001",
            "governance_ref": "gov-neg-001",
            "execution_mode": "auto",
            "approval_mode": "required",
            "constraints": ["bounded_scope"],
            "allowlist_refs": ["allowlist:web-safe"],
            "secret_refs": [],
        },
        "budget": {
            "max_steps": 2,
            "max_duration_ms": 8000,
            "max_output_bytes": 4096,
            "max_side_effects": 0,
        },
        "requested_side_effects": [],
        "approval": approval,
    }


class _RuntimeRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def status(self) -> dict[str, bool]:
        return {
            "runtime_available": True,
            "runtime_initialized": True,
            "runtime_usable": True,
        }

    def readiness(self) -> dict[str, bool]:
        return self.status()

    def execute(self, **kwargs):
        self.calls += 1
        return None

    def close_all(self) -> None:
        return

    def cleanup_evidence(self) -> dict[str, int]:
        return {"deleted_files": 0}


class _BlockedSovereignStore:
    def is_execution_allowed(self, query):
        return SovereignExecutionDecision(
            state="blocked",
            allowed=False,
            reason=SovereignDecisionReason(
                code="kill_switch_active",
                message="Kill switch active (simulated).",
                source="test",
            ),
            kill_switch_state="active",
            governance_ref=query.governance_ref,
            policy_decision_ref=query.policy_decision_ref,
            approval_id=query.approval_id,
        )


def test_case1_missing_artifact_no_approval_field_blocks_execution():
    reset_machine_operator_backend_health()
    adapter = OpenClawGatewayMachineOperatorAdapter()
    request = _request(approval=_approval())
    request.pop("approval", None)

    with patch("assistant_os.mso.machine_operator_adapter.requests.post", Mock()) as post_mock:
        result = adapter.execute(request, _context())

    assert result.status == "failed"
    assert result.metadata["backend_execution_attempted"] is False
    assert result.metadata["backend_execution_performed"] is False
    assert result.metadata["backend_status"] == "not_executed"
    assert "missing required fields" in result.observation.detail
    assert "approval" in result.observation.detail
    assert post_mock.called is False


@pytest.mark.parametrize(
    "missing_field",
    ["approval_id", "expires_at", "capability_scope"],
)
def test_case2_partial_artifact_missing_required_field_blocks_execution(missing_field: str):
    reset_machine_operator_backend_health()
    adapter = OpenClawGatewayMachineOperatorAdapter()
    approval = _approval()
    approval.pop(missing_field, None)
    request = _request(approval=approval)

    with patch("assistant_os.mso.machine_operator_adapter.requests.post", Mock()) as post_mock:
        result = adapter.execute(request, _context())

    assert result.status == "failed"
    assert result.metadata["backend_execution_attempted"] is False
    assert result.metadata["backend_execution_performed"] is False
    assert result.metadata["backend_status"] == "not_executed"
    assert "approval" in result.observation.detail
    assert missing_field in result.observation.detail
    assert post_mock.called is False


def test_case3_expired_artifact_blocks_execution():
    reset_machine_operator_backend_health()
    adapter = OpenClawGatewayMachineOperatorAdapter()
    request = _request(approval=_approval(expires_at=_past_iso()))

    with patch("assistant_os.mso.machine_operator_adapter.requests.post", Mock()) as post_mock:
        result = adapter.execute(request, _context())

    assert result.status == "denied"
    assert result.metadata["backend_execution_attempted"] is False
    assert result.metadata["backend_execution_performed"] is False
    assert result.metadata["backend_status"] == "not_executed"
    assert "expired" in result.observation.detail.lower()
    assert post_mock.called is False


def test_case4_wrong_scope_blocks_execution():
    reset_machine_operator_backend_health()
    adapter = OpenClawGatewayMachineOperatorAdapter()
    request = _request(approval=_approval(capability_scope=["browser.snapshot"]))

    with patch("assistant_os.mso.machine_operator_adapter.requests.post", Mock()) as post_mock:
        result = adapter.execute(request, _context())

    assert result.status == "denied"
    assert result.metadata["backend_execution_attempted"] is False
    assert result.metadata["backend_execution_performed"] is False
    assert result.metadata["backend_status"] == "not_executed"
    assert "capability_scope mismatch" in result.observation.detail
    assert post_mock.called is False


def test_case5_kill_switch_active_blocks_before_runtime():
    runtime = _RuntimeRecorder()
    payload = {
        "intent_id": "intent-neg-ks-001",
        "correlation_id": "corr-neg-ks-001",
        "capability_name": "browser.snapshot",
        "arguments": {"url": "https://example.test"},
        "policy": {
            "approval_id": "approval-ks-001",
            "policy_decision_ref": "policy-ks-001",
            "governance_ref": "governance-ks-001",
            "capability_scope": "browser.snapshot",
            "expires_at": _future_iso(),
        },
    }

    with patch.multiple(
        "assistant_os.openclaw_backend.config",
        OPENCLAW_AUTH_HEADER_NAME="X-OpenClaw-Token",
        OPENCLAW_EXPECTED_AUTH_TOKEN="test-token",
    ), patch(
        "assistant_os.openclaw_backend.server._sovereign_store",
        _BlockedSovereignStore(),
    ):
        server, port = start_server_thread(
            host="127.0.0.1",
            port=0,
            runtime_dispatcher=runtime,
            require_ready=False,
        )
        try:
            response = requests.post(
                f"http://127.0.0.1:{port}/v1/machine-operator/execute",
                json=payload,
                headers={"X-OpenClaw-Token": "test-token"},
                timeout=5,
            )
        finally:
            server.shutdown()
            server.server_close()

    body = response.json()
    assert response.status_code == 403
    assert runtime.calls == 0
    assert body["error"]["type"] == "sovereign_blocked"
    assert body["error"]["reason_code"] == "kill_switch_active"
    assert body["error"]["kill_switch_state"] == "active"
