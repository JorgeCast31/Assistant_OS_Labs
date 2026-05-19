"""
Integration tests for S-POLICE-MAIN-PATH-INTEGRATION-01A.

Invariant under test:
    No executable dispatch may leave the MSO runtime unless Police permits.

Coverage:
    Test 1 — Kernel forwards kwargs (forced_operation) to orchestrator
    Test 2 — Police permits AUTO dispatch → pipeline executes
    Test 3 — Police denies AUTO dispatch → pipeline blocked, denied result
    Test 4 — Read-only action (no capability) gets 'read_only' capability_name
    Test 5 — CONFIRM path stores full authority context in pending plan
    Test 6 — Confirm execution calls Police before pipeline
    Test 7 — Police deny in CONFIRM path blocks pipeline
"""
from __future__ import annotations

import pytest

from assistant_os.contracts import (
    normalize_request,
    make_domain_result,
    ACTION_WORK_QUERY,
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
# Helpers
# ---------------------------------------------------------------------------

def _make_active_structured_request(
    action: str = ACTION_WORK_QUERY,
    risk: str = RISK_LOW,
    requires_confirmation: bool = False,
) -> dict:
    """Build a structured-path request that passes policy (active subject)."""
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
    """Build a confirm-execution request for an already-stored plan."""
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
    """Return a police check stub that always permits and optionally captures requests."""
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
    """Return a police check stub that always denies and optionally captures requests."""
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
# Test 1 — Kernel forwards kwargs to orchestrator
# ---------------------------------------------------------------------------

def test_kernel_forwards_kwargs_to_orchestrator(monkeypatch):
    """handle_sovereign_request must forward **kwargs (e.g. forced_operation) to handle_request."""
    received = {}

    def fake_handle_request(request, **kwargs):
        received["request"] = request
        received["kwargs"] = kwargs
        return make_domain_result(ok=True, result_type="test", domain="*", message="ok")

    monkeypatch.setattr("assistant_os.core.orchestrator.handle_request", fake_handle_request)

    from assistant_os.mso.kernel import handle_sovereign_request

    req = {"text": "test", "context_id": "ctx-test-1"}
    handle_sovereign_request(req, source="test", forced_operation="work_query")

    assert received["kwargs"].get("forced_operation") == "work_query", (
        "forced_operation kwarg must be forwarded to handle_request"
    )


# ---------------------------------------------------------------------------
# Test 2 — Police permits AUTO dispatch → pipeline executes
# ---------------------------------------------------------------------------

def test_police_permits_auto_dispatch_allows_pipeline(monkeypatch):
    """When Police returns PERMITTED, the domain pipeline must execute."""
    from assistant_os.core.orchestrator import handle_request
    from assistant_os.core.routing import DOMAIN_PIPELINES

    pipeline_calls = []
    police_calls = []

    def fake_pipeline(plan, ctx):
        pipeline_calls.append(1)
        return _ok_result()

    monkeypatch.setitem(DOMAIN_PIPELINES, "WORK", fake_pipeline)
    monkeypatch.setattr(
        "assistant_os.police.enforcement.check",
        _police_permit_factory(police_calls),
    )

    req = _make_active_structured_request(ACTION_WORK_QUERY, requires_confirmation=False)
    result = handle_request(req)

    assert len(police_calls) == 1, "Police must be called exactly once before dispatch"
    assert len(pipeline_calls) == 1, "Pipeline must execute when Police permits"
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# Test 3 — Police denies AUTO dispatch → pipeline blocked
# ---------------------------------------------------------------------------

def test_police_denies_auto_dispatch_blocks_pipeline(monkeypatch):
    """When Police returns DENIED, the domain pipeline must NOT execute."""
    from assistant_os.core.orchestrator import handle_request
    from assistant_os.core.routing import DOMAIN_PIPELINES

    pipeline_calls = []
    police_calls = []

    def fake_pipeline(plan, ctx):
        pipeline_calls.append(1)
        return _ok_result()

    monkeypatch.setitem(DOMAIN_PIPELINES, "WORK", fake_pipeline)
    monkeypatch.setattr(
        "assistant_os.police.enforcement.check",
        _police_deny_factory(police_calls),
    )

    req = _make_active_structured_request(ACTION_WORK_QUERY, requires_confirmation=False)
    result = handle_request(req)

    assert len(police_calls) == 1, "Police must be called"
    assert len(pipeline_calls) == 0, "Pipeline must NOT execute when Police denies"
    assert result["ok"] is False
    assert result.get("result_type") == "denied"


# ---------------------------------------------------------------------------
# Test 4 — Read-only action gets 'read_only' capability_name
# ---------------------------------------------------------------------------

def test_read_only_action_gets_read_only_capability_name(monkeypatch):
    """Dispatchable actions with no MO capability must use 'read_only' as capability_name."""
    from assistant_os.core.orchestrator import handle_request
    from assistant_os.core.routing import DOMAIN_PIPELINES

    captured = []

    def fake_pipeline(plan, ctx):
        return _ok_result()

    monkeypatch.setitem(DOMAIN_PIPELINES, "WORK", fake_pipeline)
    monkeypatch.setattr(
        "assistant_os.police.enforcement.check",
        _police_permit_factory(captured),
    )

    # WORK_QUERY with action_type="read" → required_capability returns None
    req = _make_active_structured_request(ACTION_WORK_QUERY, requires_confirmation=False)
    handle_request(req)

    assert len(captured) == 1, "Police must be called once"
    assert captured[0].capability_name == "read_only", (
        f"Expected capability_name='read_only' for read action, "
        f"got '{captured[0].capability_name}'"
    )


# ---------------------------------------------------------------------------
# Test 5 — CONFIRM path stores authority context in pending plan
# ---------------------------------------------------------------------------

def test_confirm_path_stores_authority_context():
    """When execution_mode=confirm, pending plan must contain full police authority context."""
    from assistant_os.core.orchestrator import handle_request
    from assistant_os.context_store import get_pending_plan

    req = _make_active_structured_request(ACTION_WORK_QUERY, requires_confirmation=True)
    result = handle_request(req)

    assert result.get("result_type") == "plan_confirmation_required", (
        f"Expected plan_confirmation_required, got {result.get('result_type')}"
    )
    plan_id = (result.get("data") or {}).get("plan_id", "")
    assert plan_id, "plan_id must be present in plan_confirmation_required result"

    stored = get_pending_plan(plan_id)
    assert stored is not None, "Plan must be persisted in context_store"

    authority = stored["plan"].get("_authority_context", {})
    required_fields = (
        "token_ref",
        "binding_ref",
        "authorized_plan_ref",
        "capability_name",
        "governance_ref",
        "policy_decision_ref",
        "execution_id",
        "trace_id",
    )
    for field in required_fields:
        assert field in authority, (
            f"_authority_context must contain '{field}'. "
            f"Present fields: {list(authority.keys())}"
        )
        assert authority[field], (
            f"_authority_context['{field}'] must be non-empty, "
            f"got: {authority.get(field)!r}"
        )


# ---------------------------------------------------------------------------
# Test 6 — Confirm execution calls Police before pipeline
# ---------------------------------------------------------------------------

def test_confirm_execution_calls_police(monkeypatch):
    """Executing a confirmed plan must call Police before the pipeline runs."""
    from assistant_os.core.orchestrator import handle_request
    from assistant_os.core.routing import DOMAIN_PIPELINES

    pipeline_calls = []
    police_calls = []

    def fake_pipeline(plan, ctx):
        pipeline_calls.append(1)
        return _ok_result()

    monkeypatch.setitem(DOMAIN_PIPELINES, "WORK", fake_pipeline)
    monkeypatch.setattr(
        "assistant_os.police.enforcement.check",
        _police_permit_factory(police_calls),
    )

    # Step 1: create pending plan (CONFIRM path — no police dispatch, only registration)
    req_confirm = _make_active_structured_request(ACTION_WORK_QUERY, requires_confirmation=True)
    result1 = handle_request(req_confirm)
    assert result1.get("result_type") == "plan_confirmation_required"
    plan_id = (result1.get("data") or {}).get("plan_id", "")
    assert plan_id, "plan_id must be in result"

    police_calls_after_plan_creation = len(police_calls)

    # Step 2: execute the confirmed plan
    req_execute = _make_confirm_request(plan_id)
    result2 = handle_request(req_execute)

    assert len(police_calls) > police_calls_after_plan_creation, (
        "Police must be called during confirm execution"
    )
    assert len(pipeline_calls) == 1, "Pipeline must execute after Police permits"
    assert result2["ok"] is True


# ---------------------------------------------------------------------------
# Test 7 — Police deny in CONFIRM execution blocks pipeline
# ---------------------------------------------------------------------------

def test_police_deny_in_confirm_blocks_pipeline(monkeypatch):
    """When Police denies at confirm execution time, the pipeline must NOT run."""
    from assistant_os.core.orchestrator import handle_request
    from assistant_os.core.routing import DOMAIN_PIPELINES

    pipeline_calls = []
    police_calls = []

    def fake_pipeline(plan, ctx):
        pipeline_calls.append(1)
        return _ok_result()

    monkeypatch.setitem(DOMAIN_PIPELINES, "WORK", fake_pipeline)
    monkeypatch.setattr(
        "assistant_os.police.enforcement.check",
        _police_deny_factory(police_calls),
    )

    # Step 1: create pending plan — police.enforcement.check is NOT called during creation
    req_confirm = _make_active_structured_request(ACTION_WORK_QUERY, requires_confirmation=True)
    result1 = handle_request(req_confirm)
    assert result1.get("result_type") == "plan_confirmation_required"
    plan_id = (result1.get("data") or {}).get("plan_id", "")
    assert plan_id

    # Step 2: execute confirmed plan — Police denies → pipeline must not run
    req_execute = _make_confirm_request(plan_id)
    result2 = handle_request(req_execute)

    assert len(police_calls) >= 1, "Police must be called during confirm execution"
    assert len(pipeline_calls) == 0, "Pipeline must NOT execute when Police denies at confirm time"
    assert result2["ok"] is False
