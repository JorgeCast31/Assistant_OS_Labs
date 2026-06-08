"""
SC-02a — Kill Parallel Authority Paths
Test suite validating fail-closed behaviour of legacy ungoverned writers
and absence of process_chat_input exposure in the transport layer.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_chat_core():
    """Import chat_core without triggering heavy side-effects."""
    import assistant_os.chat_core as cc
    return cc


# ---------------------------------------------------------------------------
# T1 — Legacy FIN writer fails closed
# ---------------------------------------------------------------------------

def test_execute_fin_item_fails_closed():
    """_execute_fin_item must return fail-closed without calling append_expense_row."""
    cc = _load_chat_core()

    spy = MagicMock(return_value={"ok": True, "row_number": 99})

    with patch("assistant_os.integrations.sheets.append_expense_row", spy):
        ok, message, meta = cc._execute_fin_item(
            {
                "monto": 10.0,
                "moneda": "USD",
                "categoria": "Comida",
                "responsable": "Jorge",
                "descripcion": "test",
            }
        )

    assert ok is False, "Expected fail-closed (ok=False)"
    assert meta.get("blocked") is True, "Expected blocked=True in meta"
    assert meta.get("reason") == "ungoverned_legacy_path_disabled", (
        f"Unexpected reason: {meta.get('reason')!r}"
    )
    spy.assert_not_called()


# ---------------------------------------------------------------------------
# T2 — Legacy WORK create fails closed
# ---------------------------------------------------------------------------

def test_execute_work_item_fails_closed():
    """_execute_work_item must return fail-closed without calling create_work_item."""
    cc = _load_chat_core()

    spy = MagicMock(return_value={"ok": True, "page_id": "abc", "url": "http://x"})

    with patch("assistant_os.integrations.notion.create_work_item", spy):
        ok, message, meta = cc._execute_work_item(
            {"title": "Test task", "status": "INBOX"}
        )

    assert ok is False, "Expected fail-closed (ok=False)"
    assert meta.get("blocked") is True, "Expected blocked=True in meta"
    assert meta.get("reason") == "ungoverned_legacy_path_disabled", (
        f"Unexpected reason: {meta.get('reason')!r}"
    )
    spy.assert_not_called()


# ---------------------------------------------------------------------------
# T2b — Legacy WORK delete fails closed
# ---------------------------------------------------------------------------

def test_execute_work_delete_fails_closed():
    """_execute_work_delete must return fail-closed without calling archive_pages."""
    cc = _load_chat_core()

    spy = MagicMock(return_value=2)

    with patch("assistant_os.integrations.notion.archive_pages", spy):
        ok, message, meta = cc._execute_work_delete(
            keywords=["test"], delete_all=False
        )

    assert ok is False, "Expected fail-closed (ok=False)"
    assert meta.get("blocked") is True, "Expected blocked=True in meta"
    assert meta.get("reason") == "ungoverned_legacy_path_disabled", (
        f"Unexpected reason: {meta.get('reason')!r}"
    )
    spy.assert_not_called()


# ---------------------------------------------------------------------------
# T3 — Transport does not expose process_chat_input
# ---------------------------------------------------------------------------

def test_webhook_server_does_not_expose_process_chat_input():
    """
    webhook_server.py must not import or reference process_chat_input.
    Verified via AST to avoid import side-effects.
    """
    src = (
        Path(__file__).parent.parent
        / "assistant_os"
        / "webhook_server.py"
    )
    assert src.exists(), f"webhook_server.py not found at {src}"

    tree = ast.parse(src.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        # ImportFrom: from .chat_core import process_chat_input
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name != "process_chat_input", (
                    "webhook_server.py must not import process_chat_input"
                )
        # Import: import process_chat_input (unlikely but guard anyway)
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "process_chat_input" not in alias.name, (
                    "webhook_server.py must not import process_chat_input"
                )
        # Name reference in code body
        if isinstance(node, ast.Name) and node.id == "process_chat_input":
            raise AssertionError(
                "webhook_server.py references process_chat_input as a Name"
            )
        # Attribute access (e.g. chat_core.process_chat_input)
        if isinstance(node, ast.Attribute) and node.attr == "process_chat_input":
            raise AssertionError(
                "webhook_server.py references process_chat_input as an Attribute"
            )
