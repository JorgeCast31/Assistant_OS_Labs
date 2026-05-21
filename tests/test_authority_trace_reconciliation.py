"""S-AUTHORITY-TRACE-RECONCILIATION-01: Authority Trace Read Model tests.

Verifies:
1.  build_authority_trace_snapshot() returns trace_version '1'
2.  Trace chain includes all 9 stages
3.  Entity status exposes authority_trace support descriptor
4.  mso_direct deterministic status response includes authority trace summary
5.  Police decision_ref absence reported honestly, not fabricated
6.  Runner fail_closed=True visible
7.  Trace does not claim execution when used_execution=False
8.  Trace handles missing/None result metadata fail-soft (never raises)
9.  code_api external_local is represented honestly
10. Existing MSO entity/seat/intent tests still pass (verified by separate run)

None of these tests call Police, Runner, AuthorityArtifact, or live providers.
The trace is a read-model — observational only.
"""
from __future__ import annotations

import pytest

from assistant_os.mso.authority_trace import build_authority_trace_snapshot
from assistant_os.mso.entity_status import build_mso_entity_status
from assistant_os.surface_behavior import get_surface_behavior_response


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------


class _AuditStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_audit_dict(self) -> dict:
        return dict(self._payload)


# ---------------------------------------------------------------------------
# Autouse fixture — reset MSO state
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_mso_state():
    try:
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        reset_dynamic_capabilities()
        reset_task_registry()
    except Exception:
        pass
    try:
        from assistant_os.context_store import clear_store
        clear_store()
    except Exception:
        pass
    try:
        from assistant_os.mso.prepared_action_queue import clear_confirmable_action_queue_for_tests
        clear_confirmable_action_queue_for_tests()
    except Exception:
        pass
    yield
    try:
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        reset_dynamic_capabilities()
        reset_task_registry()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# mso_direct routing helper
# ---------------------------------------------------------------------------


def _route_mso_direct(text: str) -> dict | None:
    return get_surface_behavior_response(
        surface="mso_direct",
        text=text,
        context_id="ctx-trace-test",
        identity=_AuditStub({"principal": "anon"}),
        guard_result=_AuditStub({"decision": "allow"}),
    )


# ---------------------------------------------------------------------------
# 1. trace_version is "1"
# ---------------------------------------------------------------------------


def test_trace_version_is_1() -> None:
    """build_authority_trace_snapshot() must return trace_version='1'."""
    trace = build_authority_trace_snapshot()
    assert trace["trace_version"] == "1"


# ---------------------------------------------------------------------------
# 2. Chain includes all 9 stages
# ---------------------------------------------------------------------------


_REQUIRED_CHAIN_STAGES = {
    "mso_kernel",
    "intent_contract",
    "policy",
    "governance",
    "capability_token",
    "police_gate",
    "authority_artifact",
    "runner",
    "outcome",
}


def test_trace_chain_includes_all_stages() -> None:
    """Trace chain must include all 9 sovereign stages."""
    trace = build_authority_trace_snapshot()
    chain = set(trace["chain"])
    assert _REQUIRED_CHAIN_STAGES.issubset(chain), (
        f"Missing stages: {_REQUIRED_CHAIN_STAGES - chain}"
    )


def test_trace_chain_is_ordered_list() -> None:
    """Trace chain must be an ordered list (not a set)."""
    trace = build_authority_trace_snapshot()
    assert isinstance(trace["chain"], list)
    assert len(trace["chain"]) >= 9


# ---------------------------------------------------------------------------
# 3. Entity status exposes authority_trace support descriptor
# ---------------------------------------------------------------------------


def test_entity_status_has_authority_trace() -> None:
    """build_mso_entity_status() must include 'authority_trace' key."""
    result = build_mso_entity_status()
    assert "authority_trace" in result


def test_entity_status_authority_trace_supported() -> None:
    """entity_status.authority_trace.supported must be True."""
    result = build_mso_entity_status()
    assert result["authority_trace"]["supported"] is True


def test_entity_status_authority_trace_version() -> None:
    """entity_status.authority_trace.trace_version must be '1'."""
    result = build_mso_entity_status()
    assert result["authority_trace"]["trace_version"] == "1"


def test_entity_status_authority_trace_chain_present() -> None:
    """entity_status.authority_trace.chain must list all stages."""
    result = build_mso_entity_status()
    chain = set(result["authority_trace"]["chain"])
    assert _REQUIRED_CHAIN_STAGES.issubset(chain)


def test_entity_status_authority_trace_police_decision_not_embedded() -> None:
    """entity_status.authority_trace.police_decision_ref_embedded must be False."""
    result = build_mso_entity_status()
    assert result["authority_trace"]["police_decision_ref_embedded"] is False


def test_entity_status_authority_trace_runner_fail_closed_visible() -> None:
    """entity_status.authority_trace.runner_fail_closed_visible must be True."""
    result = build_mso_entity_status()
    assert result["authority_trace"]["runner_fail_closed_visible"] is True


# ---------------------------------------------------------------------------
# 4. mso_direct status response includes authority trace summary
# ---------------------------------------------------------------------------


def test_mso_direct_status_has_authority_trace_summary() -> None:
    """mso_direct status query must include 'authority_trace_summary' in response."""
    resp = _route_mso_direct("mso status")
    assert resp is not None
    assert "authority_trace_summary" in resp


def test_mso_direct_status_trace_summary_has_available() -> None:
    """authority_trace_summary.available must be True for status queries."""
    resp = _route_mso_direct("estado del mso")
    assert resp is not None
    assert resp["authority_trace_summary"]["available"] is True


def test_mso_direct_status_trace_summary_used_execution_false() -> None:
    """authority_trace_summary.used_execution must be False."""
    resp = _route_mso_direct("show mso status")
    assert resp is not None
    assert resp["authority_trace_summary"]["used_execution"] is False


# ---------------------------------------------------------------------------
# 5. Police decision_ref absence reported honestly
# ---------------------------------------------------------------------------


def test_trace_police_decision_ref_is_null() -> None:
    """Trace police.decision_ref must be null — not fabricated."""
    trace = build_authority_trace_snapshot()
    assert trace["police"]["decision_ref"] is None


def test_trace_police_decision_visibility_not_persisted() -> None:
    """Trace police.decision_visibility must report not_persisted_yet or runtime_only."""
    trace = build_authority_trace_snapshot()
    visibility = trace["police"]["decision_visibility"]
    assert visibility in ("not_persisted_yet", "runtime_decision_not_persisted", "runtime_only")


def test_trace_police_gate_integrated() -> None:
    """Trace police.gate_integrated must be True (Police is wired in the chain)."""
    trace = build_authority_trace_snapshot()
    assert trace["police"]["gate_integrated"] is True


# ---------------------------------------------------------------------------
# 6. Runner fail_closed=True visible
# ---------------------------------------------------------------------------


def test_trace_runner_fail_closed() -> None:
    """Trace runner.fail_closed must be True."""
    trace = build_authority_trace_snapshot()
    assert trace["runner"]["fail_closed"] is True


def test_trace_runner_executed_false_without_result() -> None:
    """Trace runner.executed must be False when no result is supplied."""
    trace = build_authority_trace_snapshot()
    assert trace["runner"]["executed"] is False


# ---------------------------------------------------------------------------
# 7. Trace does not claim execution when used_execution=False
# ---------------------------------------------------------------------------


def test_trace_no_execution_claimed_by_default() -> None:
    """Trace must not claim execution when no result is given."""
    trace = build_authority_trace_snapshot()
    assert trace["used_execution"] is False
    assert trace["execution_allowed"] is False


def test_trace_with_explicit_no_execution_result() -> None:
    """Trace built from a result with used_execution=False must not claim execution."""
    mock_result = {
        "ok": True,
        "result_type": "status_response",
        "domain": "MSO",
        "message": "Status ok",
        "data": {},
        "execution_status": "not_executed",
        "used_execution": False,
        "execution_allowed": False,
        "can_execute_now": False,
    }
    trace = build_authority_trace_snapshot(mock_result)
    assert trace["used_execution"] is False
    assert trace["execution_allowed"] is False


# ---------------------------------------------------------------------------
# 8. Trace handles None / empty / malformed input fail-soft
# ---------------------------------------------------------------------------


def test_trace_handles_none_input() -> None:
    """build_authority_trace_snapshot(None) must not raise."""
    trace = build_authority_trace_snapshot(None)
    assert isinstance(trace, dict)
    assert trace["trace_version"] == "1"


def test_trace_handles_empty_dict() -> None:
    """build_authority_trace_snapshot({}) must not raise."""
    trace = build_authority_trace_snapshot({})
    assert isinstance(trace, dict)


def test_trace_handles_malformed_input() -> None:
    """build_authority_trace_snapshot with unexpected keys must not raise."""
    trace = build_authority_trace_snapshot({"unexpected": "data", "nested": {"x": 1}})
    assert isinstance(trace, dict)
    assert trace["trace_version"] == "1"


# ---------------------------------------------------------------------------
# 9. code_api external_local represented honestly
# ---------------------------------------------------------------------------


def test_trace_artifact_code_api_external_local() -> None:
    """Trace built for code_api must reflect external_local authority class."""
    mock_result = {
        "ok": True,
        "result_type": "executed",
        "domain": "CODE",
        "message": "Done",
        "data": {"authority_source": "code_api", "authority_class": "external_local"},
        "execution_status": "real",
        "used_execution": True,
    }
    trace = build_authority_trace_snapshot(mock_result)
    artifact = trace["artifact"]
    assert artifact["authority_source"] == "code_api"
    assert artifact["authority_class"] == "external_local"


def test_trace_mso_sovereign_authority_class() -> None:
    """Default (no result) trace artifact must reflect mso/sovereign."""
    trace = build_authority_trace_snapshot()
    artifact = trace["artifact"]
    assert artifact["authority_source"] in ("mso", None, "unknown")
    assert artifact["artifact_version"] == "2"


# ---------------------------------------------------------------------------
# Regression: existing snapshot has 'available' key
# ---------------------------------------------------------------------------


def test_trace_has_available_key() -> None:
    """Trace must have 'available' key set to True."""
    trace = build_authority_trace_snapshot()
    assert trace["available"] is True


def test_trace_mso_kernel_boundary() -> None:
    """Trace mso.kernel_boundary must be True."""
    trace = build_authority_trace_snapshot()
    assert trace["mso"]["kernel_boundary"] is True


def test_trace_mso_orchestrator_owned() -> None:
    """Trace mso.orchestrator_owned must be True."""
    trace = build_authority_trace_snapshot()
    assert trace["mso"]["orchestrator_owned"] is True
