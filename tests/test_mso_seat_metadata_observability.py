"""S-MSO-SEAT-METADATA-OBSERVABILITY-01: MSO Seat Metadata Observability tests.

Spec reference: S-MSO-SEAT-METADATA-OBSERVABILITY-01

Verifies:
- build_mso_seat_status() returns correct shape with active_seat and available_seats
- Static metadata (cost_tier, quality_tier, latency_tier) present on all seats
- Provider-specific invariants: OpenAI/Gemma=not_implemented, Llama=config-derived,
  Anthropic=config-derived (key-dependent)
- Runtime-only in-memory seat provider setter validates correctly
- mso_direct seat query phrases return deterministic responses with correct invariants
- build_mso_entity_status() includes mso_seat field (observability extension)

None of these tests invoke an LLM, start a server, or make network calls.
Provider availability is always config-derived — no fabrication.
"""
from __future__ import annotations

import pytest

from assistant_os.mso.seat_status import (
    build_mso_seat_status,
    reset_runtime_seat_override_for_tests,
    set_runtime_seat_provider,
)
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
# Autouse fixture — reset seat override and MSO state around every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_seat_state():
    """Reset in-memory seat override and MSO registry state around each test."""
    reset_runtime_seat_override_for_tests()
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
    yield
    reset_runtime_seat_override_for_tests()
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
        context_id="ctx-mso-seat-metadata-test",
        identity=_AuditStub({"principal": "anon"}),
        guard_result=_AuditStub({"decision": "allow"}),
    )


# ---------------------------------------------------------------------------
# Tests — build_mso_seat_status() shape and invariants
# ---------------------------------------------------------------------------


def test_seat_status_returns_active_seat() -> None:
    """build_mso_seat_status() must return a dict with 'active_seat' key."""
    result = build_mso_seat_status()
    assert "active_seat" in result
    assert isinstance(result["active_seat"], dict)


def test_seat_status_lists_all_known_providers() -> None:
    """build_mso_seat_status() must include all 4 known providers in available_seats."""
    result = build_mso_seat_status()
    assert "available_seats" in result
    providers = {s["provider"] for s in result["available_seats"]}
    assert {"anthropic", "openai", "llama", "gemma"}.issubset(providers)


def test_seat_status_used_execution_invariant() -> None:
    """build_mso_seat_status() must always carry used_execution=False (hard invariant)."""
    result = build_mso_seat_status()
    assert result["used_execution"] is False


def test_seat_status_cognitive_only_invariant() -> None:
    """build_mso_seat_status() must always carry cognitive_only=True (hard invariant)."""
    result = build_mso_seat_status()
    assert result["cognitive_only"] is True


def test_active_seat_can_execute_always_false() -> None:
    """active_seat.can_execute must always be False (execution invariant)."""
    result = build_mso_seat_status()
    assert result["active_seat"]["can_execute"] is False


def test_active_seat_cognitive_only_always_true() -> None:
    """active_seat.cognitive_only must always be True."""
    result = build_mso_seat_status()
    assert result["active_seat"]["cognitive_only"] is True


def test_available_seats_include_cost_tier() -> None:
    """All available seats must carry a cost_tier field from static operator metadata."""
    result = build_mso_seat_status()
    for seat in result["available_seats"]:
        assert "cost_tier" in seat, f"Missing cost_tier on seat: {seat['provider']}"


def test_available_seats_include_quality_tier() -> None:
    """All available seats must carry a quality_tier field from static operator metadata."""
    result = build_mso_seat_status()
    for seat in result["available_seats"]:
        assert "quality_tier" in seat, f"Missing quality_tier on seat: {seat['provider']}"


def test_available_seats_include_latency_tier() -> None:
    """All available seats must carry a latency_tier field from static operator metadata."""
    result = build_mso_seat_status()
    for seat in result["available_seats"]:
        assert "latency_tier" in seat, f"Missing latency_tier on seat: {seat['provider']}"


def test_seat_status_includes_selection_metadata() -> None:
    """build_mso_seat_status() must include a 'selection' dict with allowed_providers."""
    result = build_mso_seat_status()
    assert "selection" in result
    selection = result["selection"]
    assert "allowed_providers" in selection
    assert isinstance(selection["allowed_providers"], list)
    assert len(selection["allowed_providers"]) > 0


# ---------------------------------------------------------------------------
# Tests — provider-specific invariants
# ---------------------------------------------------------------------------


def test_openai_reported_as_not_implemented() -> None:
    """OpenAI provider must have status='not_implemented' — no adapter exists."""
    result = build_mso_seat_status()
    openai_seats = [s for s in result["available_seats"] if s["provider"] == "openai"]
    assert openai_seats, "openai must appear in available_seats"
    assert openai_seats[0]["status"] == "not_implemented"


def test_gemma_reported_as_not_implemented() -> None:
    """Gemma provider must have status='not_implemented' — no adapter exists."""
    result = build_mso_seat_status()
    gemma_seats = [s for s in result["available_seats"] if s["provider"] == "gemma"]
    assert gemma_seats, "gemma must appear in available_seats"
    assert gemma_seats[0]["status"] == "not_implemented"


def test_llama_availability_is_config_derived() -> None:
    """Llama status must be one of the known config-derived statuses (not fabricated)."""
    result = build_mso_seat_status()
    llama_seats = [s for s in result["available_seats"] if s["provider"] == "llama"]
    assert llama_seats, "llama must appear in available_seats"
    allowed = {"available", "not_configured", "local_endpoint_missing", "api_key_missing"}
    assert llama_seats[0]["status"] in allowed, (
        f"Unexpected llama status: {llama_seats[0]['status']!r}"
    )


def test_anthropic_availability_is_config_derived() -> None:
    """Anthropic status must be 'available' (key set) or 'api_key_missing' (no key)."""
    result = build_mso_seat_status()
    anthropic_seats = [s for s in result["available_seats"] if s["provider"] == "anthropic"]
    assert anthropic_seats, "anthropic must appear in available_seats"
    allowed = {"available", "api_key_missing"}
    assert anthropic_seats[0]["status"] in allowed, (
        f"Unexpected anthropic status: {anthropic_seats[0]['status']!r}"
    )


# ---------------------------------------------------------------------------
# Tests — entity_status integration (Sprint 2 extension)
# ---------------------------------------------------------------------------


def test_entity_status_includes_mso_seat_key() -> None:
    """build_mso_entity_status() must include 'mso_seat' with active_seat (Sprint 2 ext)."""
    result = build_mso_entity_status()
    assert "mso_seat" in result
    assert "active_seat" in result["mso_seat"]


def test_entity_status_mso_seat_has_available_seats() -> None:
    """build_mso_entity_status().mso_seat must carry available_seats list."""
    result = build_mso_entity_status()
    mso_seat = result["mso_seat"]
    assert "available_seats" in mso_seat
    assert isinstance(mso_seat["available_seats"], list)


def test_entity_status_includes_observability() -> None:
    """build_mso_entity_status() must include 'observability' dict."""
    result = build_mso_entity_status()
    assert "observability" in result
    obs = result["observability"]
    assert "seat_observable" in obs
    assert obs["seat_observable"] is True


# ---------------------------------------------------------------------------
# Tests — mso_direct seat query phrases
# ---------------------------------------------------------------------------


def test_mso_direct_seat_status_phrase_routed() -> None:
    """'seat status' must route to a non-None mso_entity_status response."""
    result = _route_mso_direct("seat status")
    assert result is not None
    assert result["intent"] == "mso_entity_status"


def test_mso_direct_seat_query_used_execution_false() -> None:
    """mso_direct seat query must carry used_execution=False (cognitive invariant)."""
    result = _route_mso_direct("que seats tienes disponibles")
    assert result is not None
    assert result["used_execution"] is False


def test_mso_direct_seat_query_can_execute_now_false() -> None:
    """mso_direct seat query must carry can_execute_now=False."""
    result = _route_mso_direct("muestra estado del seat")
    assert result is not None
    assert result["can_execute_now"] is False


def test_mso_direct_seat_change_phrase_routed() -> None:
    """'cambia seat a llama' must route to mso_seat_change with used_execution=False."""
    result = _route_mso_direct("cambia seat a llama")
    assert result is not None
    assert result["intent"] == "mso_seat_change"
    assert result["used_execution"] is False
    assert result["can_execute_now"] is False


def test_mso_direct_seat_change_includes_seat_status() -> None:
    """mso_direct seat-change response must embed seat_status dict."""
    result = _route_mso_direct("change seat to anthropic")
    assert result is not None
    assert "seat_status" in result
    assert "active_seat" in result["seat_status"]


# ---------------------------------------------------------------------------
# Tests — runtime-only seat provider setter
# ---------------------------------------------------------------------------


def test_set_runtime_seat_provider_valid_accepted() -> None:
    """set_runtime_seat_provider('anthropic') must return ok=True (runtime-only)."""
    result = set_runtime_seat_provider("anthropic")
    assert result["ok"] is True
    assert result["runtime_only"] is True
    assert result["used_execution"] is False
    assert result["cognitive_only"] is True


def test_set_runtime_seat_provider_llama_accepted() -> None:
    """set_runtime_seat_provider('llama') must return ok=True (not not_implemented)."""
    result = set_runtime_seat_provider("llama")
    assert result["ok"] is True
    assert result["runtime_only"] is True
    assert result["used_execution"] is False


def test_set_runtime_seat_provider_invalid_rejected() -> None:
    """set_runtime_seat_provider with unknown name must return ok=False."""
    result = set_runtime_seat_provider("nonexistent_provider_xyz")
    assert result["ok"] is False
    assert result["used_execution"] is False


def test_set_runtime_seat_provider_not_implemented_rejected() -> None:
    """set_runtime_seat_provider('openai') must return ok=False (not_implemented)."""
    result = set_runtime_seat_provider("openai")
    assert result["ok"] is False
    assert result.get("availability") == "not_implemented"
    assert result["used_execution"] is False
    assert result["cognitive_only"] is True


def test_set_runtime_seat_provider_gemma_rejected() -> None:
    """set_runtime_seat_provider('gemma') must return ok=False (not_implemented)."""
    result = set_runtime_seat_provider("gemma")
    assert result["ok"] is False
    assert result.get("availability") == "not_implemented"
    assert result["used_execution"] is False


def test_set_runtime_seat_provider_empty_string_rejected() -> None:
    """set_runtime_seat_provider('') must return ok=False — fail-closed."""
    result = set_runtime_seat_provider("")
    assert result["ok"] is False
    assert result["used_execution"] is False
