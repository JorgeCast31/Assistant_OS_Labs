"""S-POLICE-DECISION-OBSERVABILITY-01: Police Decision Observability tests.

Verifies:
1.  AUTO pipeline permitted path result includes police_decision_metadata key.
2.  Police permit metadata structure: decision_ref (non-None), permitted=True,
    visibility='runtime_trace'.
3.  Police deny result includes police_decision_metadata with permitted=False.
4.  AUTO cognitive permitted path result includes police_decision_metadata.
5.  CONFIRM execution result includes police_decision_metadata.
6.  Authority trace uses police_decision_metadata when present in context
    (visibility='runtime_trace', permitted filled in, decision_ref non-None).
7.  Authority trace falls back to not_persisted_yet when police_decision_metadata absent.
8.  Entity status reports police_decision_observability support descriptor.

None of these tests bypass Police enforcement — they all route through real gate logic.
'police.enforcement.check' is monkeypatched to return deterministic decisions without
token/registry validation, following the exact pattern of test_police_main_path_integration.
"""
from __future__ import annotations

import pytest

from assistant_os.contracts import (
    normalize_request,
    make_domain_result,
    ACTION_WORK_QUERY,
    ACTION_BASIC_COGNITIVE_EXECUTION,
    RISK_LOW,
)
from assistant_os.police.gate_models import (
    PoliceDecision,
    PoliceGateRequest,
    PoliceOutcome,
    PoliceReason,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_stores():
    """Reset all process-local registries before and after each test."""
    from assistant_os.police.token_registry import _reset_for_testing as _ptr
    from assistant_os.police.authorized_plan_registry import _reset_for_testing as _apr
    from assistant_os.capabilities.token_issuer import _reset_registry as _ctr
    from assistant_os.context_store import clear_store
    _ptr(); _apr(); _ctr(); clear_store()
    yield
    _ptr(); _apr(); _ctr(); clear_store()


# ---------------------------------------------------------------------------
# Helpers — mirror test_police_main_path_integration patterns exactly
# ---------------------------------------------------------------------------


def _make_active_structured_request(
    action: str = ACTION_WORK_QUERY,
    risk: str = RISK_LOW,
    requires_confirmation: bool = False,
) -> dict:
    req = dict(normalize_request(text="test request"))
    req["subject_state"] = "active"
    req["guard_decision"] = "allow"
    req["action_type"] = "read"
    req["principal_id"] = "test-principal"
    req["metadata"] = {
        "action": action,
        "risk_level": risk,
        "requires_confirmation": requires_confirmation,
    }
    return req


def _make_confirm_request(plan_id: str) -> dict:
    req = dict(normalize_request(text="confirm execution"))
    req["subject_state"] = "active"
    req["guard_decision"] = "allow"
    req["action_type"] = "read"
    req["principal_id"] = "test-principal"
    req["metadata"] = {"confirm_plan_id": plan_id}
    return req


def _ok_result(domain: str = "WORK") -> dict:
    return make_domain_result(
        ok=True, result_type="work_query", domain=domain, message="ok"
    )


def _police_permit_factory(captured: list | None = None):
    def _check(request: PoliceGateRequest) -> PoliceDecision:
        if captured is not None:
            captured.append(request)
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.PERMITTED,
            reason=PoliceReason.ALLOWED,
            detail="permitted in test",
            permitted=True,
        )
    return _check


def _police_deny_factory(captured: list | None = None):
    def _check(request: PoliceGateRequest) -> PoliceDecision:
        if captured is not None:
            captured.append(request)
        return PoliceDecision(
            execution_id=request.execution_id,
            trace_id=request.trace_id,
            outcome=PoliceOutcome.DENIED,
            reason=PoliceReason.TOKEN_MISSING,
            detail="denied in test",
            permitted=False,
        )
    return _check


# ---------------------------------------------------------------------------
# 1. AUTO pipeline permit path — result includes police_decision_metadata
# ---------------------------------------------------------------------------


def test_auto_pipeline_permit_result_has_police_metadata(monkeypatch):
    """AUTO pipeline path: permitted result must include 'police_decision_metadata' key."""
    from assistant_os.core.orchestrator import handle_request
    from assistant_os.core.routing import DOMAIN_PIPELINES

    monkeypatch.setitem(DOMAIN_PIPELINES, "WORK", lambda plan, ctx: _ok_result())
    monkeypatch.setattr(
        "assistant_os.police.enforcement.check",
        _police_permit_factory(),
    )

    req = _make_active_structured_request(ACTION_WORK_QUERY, requires_confirmation=False)
    result = handle_request(req)

    assert result["ok"] is True
    assert "police_decision_metadata" in result, (
        "Result must include 'police_decision_metadata' after Police permits"
    )


# ---------------------------------------------------------------------------
# 2. Permit metadata structure: decision_ref, permitted=True, visibility
# ---------------------------------------------------------------------------


def test_auto_pipeline_permit_metadata_structure(monkeypatch):
    """Police permit metadata must have decision_ref (non-None), permitted=True,
    visibility='runtime_trace'."""
    from assistant_os.core.orchestrator import handle_request
    from assistant_os.core.routing import DOMAIN_PIPELINES

    monkeypatch.setitem(DOMAIN_PIPELINES, "WORK", lambda plan, ctx: _ok_result())
    monkeypatch.setattr(
        "assistant_os.police.enforcement.check",
        _police_permit_factory(),
    )

    req = _make_active_structured_request(ACTION_WORK_QUERY, requires_confirmation=False)
    result = handle_request(req)

    meta = result.get("police_decision_metadata")
    assert meta is not None, "police_decision_metadata must be present"
    assert meta["permitted"] is True, "permitted must be True when Police permits"
    assert meta["visibility"] == "runtime_trace", (
        f"visibility must be 'runtime_trace', got {meta.get('visibility')!r}"
    )
    assert meta["decision_ref"] is not None, "decision_ref must be a non-None string"
    assert isinstance(meta["decision_ref"], str) and len(meta["decision_ref"]) > 0, (
        "decision_ref must be a non-empty string (Police decision_id UUID)"
    )


# ---------------------------------------------------------------------------
# 3. Deny result includes police_decision_metadata with permitted=False
# ---------------------------------------------------------------------------


def test_auto_pipeline_deny_result_has_police_metadata(monkeypatch):
    """Police deny result must include police_decision_metadata with permitted=False."""
    from assistant_os.core.orchestrator import handle_request
    from assistant_os.core.routing import DOMAIN_PIPELINES

    pipeline_calls = []
    monkeypatch.setitem(
        DOMAIN_PIPELINES, "WORK", lambda plan, ctx: (pipeline_calls.append(1) or _ok_result())
    )
    monkeypatch.setattr(
        "assistant_os.police.enforcement.check",
        _police_deny_factory(),
    )

    req = _make_active_structured_request(ACTION_WORK_QUERY, requires_confirmation=False)
    result = handle_request(req)

    assert result["ok"] is False, "Denied result must have ok=False"
    assert len(pipeline_calls) == 0, "Pipeline must NOT execute when denied"
    assert "police_decision_metadata" in result, (
        "Denied result must include 'police_decision_metadata'"
    )
    meta = result["police_decision_metadata"]
    assert meta["permitted"] is False, "permitted must be False when Police denies"
    assert meta["visibility"] == "runtime_trace", "visibility must be 'runtime_trace'"


# ---------------------------------------------------------------------------
# 4. AUTO cognitive permit path attaches police_decision_metadata
# ---------------------------------------------------------------------------


def test_auto_cognitive_permit_result_has_police_metadata(monkeypatch):
    """AUTO cognitive execution path (ACTION_BASIC_COGNITIVE_EXECUTION): permitted result
    must include police_decision_metadata."""
    from assistant_os.core.orchestrator import handle_request
    import assistant_os.core.orchestrator as _orch

    cognitive_calls = []

    def _fake_dispatch(plan, context_id):
        cognitive_calls.append(1)
        return make_domain_result(
            ok=True, result_type="cognitive_result", domain="COGNITIVE", message="ok"
        )

    monkeypatch.setattr(_orch, "_dispatch_cognitive_execution", _fake_dispatch)
    monkeypatch.setattr(
        "assistant_os.police.enforcement.check",
        _police_permit_factory(),
    )

    req = _make_active_structured_request(
        ACTION_BASIC_COGNITIVE_EXECUTION, requires_confirmation=False
    )
    result = handle_request(req)

    assert len(cognitive_calls) == 1, "Cognitive dispatch must execute after Police permits"
    assert "police_decision_metadata" in result, (
        "Cognitive AUTO result must include 'police_decision_metadata'"
    )
    meta = result["police_decision_metadata"]
    assert meta["permitted"] is True
    assert meta["visibility"] == "runtime_trace"


# ---------------------------------------------------------------------------
# 5. CONFIRM execution result includes police_decision_metadata
# ---------------------------------------------------------------------------


def test_confirm_execution_result_has_police_metadata(monkeypatch):
    """CONFIRM path: executing a confirmed plan must produce a result with
    police_decision_metadata."""
    from assistant_os.core.orchestrator import handle_request
    from assistant_os.core.routing import DOMAIN_PIPELINES

    monkeypatch.setitem(DOMAIN_PIPELINES, "WORK", lambda plan, ctx: _ok_result())
    monkeypatch.setattr(
        "assistant_os.police.enforcement.check",
        _police_permit_factory(),
    )

    # Step 1: create pending plan (CONFIRM path)
    req_plan = _make_active_structured_request(ACTION_WORK_QUERY, requires_confirmation=True)
    result1 = handle_request(req_plan)
    assert result1.get("result_type") == "plan_confirmation_required"
    plan_id = (result1.get("data") or {}).get("plan_id", "")
    assert plan_id, "plan_id must be present"

    # Step 2: confirm execution
    req_exec = _make_confirm_request(plan_id)
    result2 = handle_request(req_exec)

    assert result2["ok"] is True
    assert "police_decision_metadata" in result2, (
        "CONFIRM execution result must include 'police_decision_metadata'"
    )
    meta = result2["police_decision_metadata"]
    assert meta["permitted"] is True
    assert meta["visibility"] == "runtime_trace"


# ---------------------------------------------------------------------------
# 6. Authority trace uses police_decision_metadata when present
# ---------------------------------------------------------------------------


def test_authority_trace_uses_police_metadata():
    """build_authority_trace_snapshot with police_decision_metadata in context must
    populate police stage with visibility='runtime_trace', permitted, decision_ref."""
    from assistant_os.mso.authority_trace import build_authority_trace_snapshot

    ctx = {
        "ok": True,
        "result_type": "work_query",
        "domain": "WORK",
        "execution_status": "real",
        "used_execution": True,
        "execution_allowed": True,
        "police_decision_metadata": {
            "decision_ref": "test-uuid-1234",
            "permitted": True,
            "outcome": "permitted",
            "reason": "allowed",
            "detail": "permitted in test",
            "visibility": "runtime_trace",
        },
    }
    trace = build_authority_trace_snapshot(ctx)
    police = trace["police"]

    assert police["decision_visibility"] == "runtime_trace", (
        f"When police_decision_metadata is present, decision_visibility must be "
        f"'runtime_trace', got {police['decision_visibility']!r}"
    )
    assert police["permitted"] is True, (
        "police.permitted must be True when metadata has permitted=True"
    )
    assert police["decision_ref"] == "test-uuid-1234", (
        "police.decision_ref must match decision_ref from police_decision_metadata"
    )


# ---------------------------------------------------------------------------
# 7. Authority trace fallback to not_persisted_yet when metadata absent
# ---------------------------------------------------------------------------


def test_authority_trace_fallback_without_police_metadata():
    """build_authority_trace_snapshot without police_decision_metadata must fall back
    to decision_visibility='not_persisted_yet' and decision_ref=None."""
    from assistant_os.mso.authority_trace import build_authority_trace_snapshot

    trace = build_authority_trace_snapshot()
    police = trace["police"]

    assert police["decision_visibility"] == "not_persisted_yet", (
        f"Without police_decision_metadata, decision_visibility must be "
        f"'not_persisted_yet', got {police['decision_visibility']!r}"
    )
    assert police["decision_ref"] is None, (
        "decision_ref must be None when no police_decision_metadata is present"
    )


# ---------------------------------------------------------------------------
# 8. Entity status reports police_decision_observability descriptor
# ---------------------------------------------------------------------------


def test_entity_status_police_observability_descriptor():
    """build_mso_entity_status() must include 'police_decision_observability' key."""
    from assistant_os.mso.entity_status import build_mso_entity_status

    result = build_mso_entity_status()
    assert "police_decision_observability" in result, (
        "entity_status must include 'police_decision_observability' descriptor"
    )


def test_entity_status_police_observability_supported():
    """police_decision_observability.supported must be True."""
    from assistant_os.mso.entity_status import build_mso_entity_status

    result = build_mso_entity_status()
    obs = result.get("police_decision_observability", {})
    assert obs.get("supported") is True, (
        "police_decision_observability.supported must be True"
    )


def test_entity_status_police_observability_visibility():
    """police_decision_observability.visibility must be 'runtime_trace'."""
    from assistant_os.mso.entity_status import build_mso_entity_status

    result = build_mso_entity_status()
    obs = result.get("police_decision_observability", {})
    assert obs.get("visibility") == "runtime_trace", (
        f"police_decision_observability.visibility must be 'runtime_trace', "
        f"got {obs.get('visibility')!r}"
    )


def test_entity_status_police_observability_decision_ref_in_result():
    """police_decision_observability must report that decision_ref is in result."""
    from assistant_os.mso.entity_status import build_mso_entity_status

    result = build_mso_entity_status()
    obs = result.get("police_decision_observability", {})
    assert obs.get("decision_ref_in_result") is True, (
        "police_decision_observability.decision_ref_in_result must be True"
    )
