"""
Tests for assistant_os.mso.kernel — MSO Sovereign Runtime Kernel.

Validates that the kernel is a transparent delegation boundary:
handle_sovereign_request must delegate to core.orchestrator.handle_request
without altering the request object or the return value.
"""
import pytest


def test_mso_kernel_delegates_to_orchestrator(monkeypatch):
    called = {}

    def fake_handle_request(request):
        called["request"] = request
        return {"ok": True}

    monkeypatch.setattr(
        "assistant_os.core.orchestrator.handle_request",
        fake_handle_request,
    )

    from assistant_os.mso.kernel import handle_sovereign_request

    request = object()
    result = handle_sovereign_request(request, source="test")

    assert result == {"ok": True}
    assert called["request"] is request


def test_mso_kernel_source_does_not_affect_result(monkeypatch):
    """source parameter must be silently ignored — no behavior change."""
    results = []

    def fake_handle_request(request):
        results.append("called")
        return {"status": "ok"}

    monkeypatch.setattr(
        "assistant_os.core.orchestrator.handle_request",
        fake_handle_request,
    )

    from assistant_os.mso.kernel import handle_sovereign_request

    req = object()
    r1 = handle_sovereign_request(req, source=None)
    r2 = handle_sovereign_request(req, source="webhook_server.chat_process")
    r3 = handle_sovereign_request(req)

    assert r1 == r2 == r3 == {"status": "ok"}
    assert len(results) == 3


def test_mso_kernel_propagates_exception(monkeypatch):
    """Exceptions from the orchestrator must propagate unchanged."""

    def fake_handle_request(request):
        raise ValueError("orchestrator error")

    monkeypatch.setattr(
        "assistant_os.core.orchestrator.handle_request",
        fake_handle_request,
    )

    from assistant_os.mso.kernel import handle_sovereign_request

    with pytest.raises(ValueError, match="orchestrator error"):
        handle_sovereign_request(object(), source="test")
