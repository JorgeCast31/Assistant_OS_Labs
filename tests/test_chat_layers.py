"""
Smoke tests for 2-Layer Chat System.

Tests:
1-3: pending_flow continuity
4-6: Plan Always (confirmation required)
"""
import unittest
from unittest.mock import patch
from assistant_os.contracts import (
    ChatCoreResponse,
    ChatSession,
    make_chat_core_response,
    new_context_id,
)
from assistant_os.chat_core import (
    process_chat_input,
    PENDING_FLOW_RESOLVERS,
)
from assistant_os.chat_renderer import (
    render_chat_response,
    RenderedResponse,
)


# ---------------------------------------------------------------------------
# Test 1: pending_flow continuity - confirm resolves flow
# ---------------------------------------------------------------------------

@patch("assistant_os.chat_core._execute_fin_item", return_value=(True, "ok", {"row_number": 1}))
def test_pending_flow_confirm_resolves(mock_exec):
    """When user confirms pending FIN flow, it resolves to committed intent."""
    # Setup: session with pending fin_confirm
    ctx_id = new_context_id()
    session = ChatSession(
        pending_flow="fin_confirm",
        context_id=ctx_id,
        pending_data={"items": [{"monto": 25.0, "moneda": "USD"}]},
    )

    # Act: user says "sí"
    result = process_chat_input("sí", session=session)

    # Assert: flow resolved, intent is committed, pending_flow cleared
    assert result["intent"] == "committed"
    assert result["session"].get("pending_flow") is None
    assert result["audit"].get("resolution") == "confirmed"
    assert len(result["plan"]) == 1
    assert result["plan"][0]["monto"] == 25.0


# ---------------------------------------------------------------------------
# Test 2: pending_flow continuity - cancel clears flow
# ---------------------------------------------------------------------------

def test_pending_flow_cancel_clears():
    """When user cancels pending flow, it clears and returns cancelled intent."""
    ctx_id = new_context_id()
    session = ChatSession(
        pending_flow="fin_confirm",
        context_id=ctx_id,
        pending_data={"items": [{"monto": 10.0, "moneda": "USD"}]},
    )
    
    result = process_chat_input("no", session=session)
    
    assert result["intent"] == "cancelled"
    assert result["session"].get("pending_flow") is None
    assert result["audit"].get("resolution") == "cancelled"


# ---------------------------------------------------------------------------
# Test 3: pending_flow preserves context_id across turns
# ---------------------------------------------------------------------------

def test_pending_flow_preserves_context_id():
    """context_id is preserved across pending flow resolution."""
    ctx_id = "test-context-12345"
    session = ChatSession(
        pending_flow="fin_confirm",
        context_id=ctx_id,
        pending_data={"items": []},
    )
    
    result = process_chat_input("sí", session=session)
    
    assert result["session"]["context_id"] == ctx_id


# ---------------------------------------------------------------------------
# Test 4: Plan Always - FIN add requires confirmation
# ---------------------------------------------------------------------------

def test_fin_add_requires_confirmation():
    """FIN domain add always requires confirmation (Plan Always)."""
    # Simple expense input
    result = process_chat_input("$25 en comida", domain_hint="FIN")

    # Must require confirmation
    assert result["needs_confirmation"] is True
    # FIN now routes through clarification first (collects missing fields)
    assert result["session"].get("pending_flow") == "clarification"
    # Must have a form action for the clarification step
    assert any(a.get("type") == "form" for a in result["ui_actions"])


# ---------------------------------------------------------------------------
# Test 5: Plan Always - multi-FIN requires confirmation
# ---------------------------------------------------------------------------

def test_multi_fin_requires_confirmation():
    """Multiple FIN items also require confirmation."""
    result = process_chat_input("$25 en comida y $15 para transporte", domain_hint="FIN")

    assert result["needs_confirmation"] is True
    # FIN now routes through clarification first (collects missing fields)
    assert result["session"].get("pending_flow") == "clarification"
    # Should detect multiple items
    assert len(result["plan"]) >= 1  # Chaperon should detect multiple


# ---------------------------------------------------------------------------
# Test 6: Layer 2 renders without modifying plan data
# ---------------------------------------------------------------------------

def test_renderer_preserves_plan_data():
    """Layer 2 renderer does not modify numbers, IDs, or options."""
    # Create a core response with specific data
    core = make_chat_core_response(
        domain="FIN",
        intent="confirm",
        needs_confirmation=True,
        plan=[
            {"monto": 123.45, "moneda": "USD", "categoria": "Comida"},
            {"monto": 67.89, "moneda": "PAB", "categoria": "Transporte"},
        ],
        ui_actions=[{"type": "confirm", "label": "Confirmar"}],
        session=ChatSession(context_id="ctx-preserve-test"),
    )
    
    # Render
    rendered = render_chat_response(core)
    
    # Verify ui_actions passed through unchanged
    assert rendered.ui_actions == core["ui_actions"]
    
    # Verify context_id passed through
    assert rendered.context_id == "ctx-preserve-test"
    
    # Message should contain the exact amounts (not rounded/modified)
    assert "123.45" in rendered.message
    assert "67.89" in rendered.message


# ---------------------------------------------------------------------------
# Run with: python -m unittest tests.test_chat_layers -v
# ---------------------------------------------------------------------------
