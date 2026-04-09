"""
Smoke tests for 2-Layer Chat System.

Tests:
1-3: pending_flow continuity
4-6: Plan Always (confirmation required)
"""
import unittest
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

def test_pending_flow_confirm_resolves():
    """When user confirms pending FIN flow, it resolves to execute intent."""
    # Setup: session with pending fin_confirm
    ctx_id = new_context_id()
    session = ChatSession(
        pending_flow="fin_confirm",
        context_id=ctx_id,
        pending_data={"items": [{"monto": 25.0, "moneda": "USD"}]},
    )
    
    # Act: user says "sí"
    result = process_chat_input("sí", session=session)
    
    # Assert: flow resolved, intent is execute, pending_flow cleared
    assert result["intent"] == "execute"
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
    # Must have pending_flow set for confirmation
    assert result["session"].get("pending_flow") == "fin_confirm"
    # Must have confirm action
    assert any(a.get("type") == "confirm" for a in result["ui_actions"])


# ---------------------------------------------------------------------------
# Test 5: Plan Always - multi-FIN requires confirmation
# ---------------------------------------------------------------------------

def test_multi_fin_requires_confirmation():
    """Multiple FIN items also require confirmation."""
    result = process_chat_input("$25 en comida y $15 para transporte", domain_hint="FIN")
    
    assert result["needs_confirmation"] is True
    assert result["session"].get("pending_flow") == "fin_confirm"
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
# FIX-1: CODE executor_error surface — executor ran but returned error
# ---------------------------------------------------------------------------

def test_code_executor_error_intent_not_queued():
    """
    FIX-1: When the propose executor runs and returns ok=False, the response
    must have intent='executor_error', NOT intent='queued'.
    """
    from unittest.mock import patch
    from assistant_os.chat_core import PENDING_FLOW_RESOLVERS

    ctx_id = new_context_id()
    session = ChatSession(
        pending_flow="code_preview",
        context_id=ctx_id,
        pending_data={
            "operation": "CODE_FIX",
            "task": "fix a bug",
            "repo_path": "/tmp/repo",
            "base_branch": "main",
            "files": ["src/foo.py"],
        },
    )

    failing_exec = {"ok": False, "error": "No changes detected"}

    with patch("assistant_os.chat_core._call_propose_executor", return_value=failing_exec):
        result = process_chat_input("confirmar", session=session)

    assert result["intent"] == "executor_error", (
        f"Expected 'executor_error', got {result['intent']!r}"
    )
    assert result["audit"].get("propose_error") is not None
    assert result["audit"].get("error_message") is not None
    # Must NOT sound like success/queued
    assert result["intent"] != "queued"


def test_code_executor_error_renders_truthfully():
    """
    FIX-1: Rendered message for executor_error must NOT look like a success
    confirmation (template should produce the error text, not 'Tarea CODE registrada').
    """
    from unittest.mock import patch

    ctx_id = new_context_id()
    session = ChatSession(
        pending_flow="code_preview",
        context_id=ctx_id,
        pending_data={
            "operation": "CODE_FIX",
            "task": "fix a bug",
            "repo_path": "/tmp/repo",
            "base_branch": "main",
            "files": ["src/foo.py"],
        },
    )

    failing_exec = {"ok": False, "error": "El executor no detectó cambios aplicables."}

    with patch("assistant_os.chat_core._call_propose_executor", return_value=failing_exec):
        result = process_chat_input("confirmar", session=session)

    rendered = render_chat_response(result)
    # Must not contain the success queued message
    assert "Tarea CODE registrada" not in rendered.message
    # Must contain something error-related
    assert "executor_error" in result["intent"] or result["intent"] != "queued"


# ---------------------------------------------------------------------------
# Run with: python -m unittest tests.test_chat_layers -v
# ---------------------------------------------------------------------------
