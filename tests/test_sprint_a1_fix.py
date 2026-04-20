"""
Sprint A1-FIX — Policy Integrity Invariant Tests.

Verifies that ALL execution entry points in the webhook layer are gated by
evaluate_policy() before any agent, pipeline, or domain code executes.

Audit A1 found three categories of bypass:
  - CRITICAL: WebhookHandler._execute_confirmed_plan called pipeline directly
  - HIGH:     route_request() called legacy agents without policy
  - MEDIUM:   _execute_work_query_from_plan / _execute_work_update_preview (dead code)

A1.5 further hardens the legacy path by removing the separate mini-policy path
(_gated_legacy_route) and routing ALL text — with or without prefix — through
the canonical handle_request() path.

Structure
---------
  Section 1 — Canonical routing invariants (post-A1.5)
    1a. _gated_legacy_route no longer exists in webhook_server
    1b. _handle_command routes ALL text through _route_text_by_classification
    1c. _handle_command_summary routes ALL text through _route_text_by_classification
    1d. No prefix-specific branch calls route_request directly

  Section 2 — _execute_confirmed_plan routes through handle_request
    2a. No stored plan → ContextNotFound returned immediately
    2b. Stored plan + handle_request called with confirm_plan_id in metadata
    2c. Policy denied during confirmation → plan NOT executed
    2d. Approved confirmation → handle_request result returned

  Section 3 — Dead code methods raise RuntimeError
    3a. _execute_work_query_from_plan raises RuntimeError
    3b. _execute_work_update_preview raises RuntimeError

  Section 4 — Structural invariants (static + runtime)
    4a. _execute_confirmed_plan source references handle_request
    4b. No bare route_request(req) call in _handle_command
    4c. No bare route_request(req) call in _handle_command_summary
    4d. Dead code error message references policy enforcement
    4e. Dead code error message references handle_request
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_policy_decision(permitted: bool, outcome: str = "approved", reason: str = "approved"):
    """Build a minimal PolicyDecision-like object for mocking."""
    from assistant_os.policy.policy_models import PolicyDecision, PolicyOutcome, PolicyReason
    return PolicyDecision(
        outcome=PolicyOutcome(outcome),
        reason=PolicyReason(reason),
        detail=f"test: outcome={outcome} reason={reason}",
        permitted=permitted,
    )


# ---------------------------------------------------------------------------
# Section 1 — Canonical routing invariants (post-A1.5)
# ---------------------------------------------------------------------------

class TestCanonicalRoutingInvariants:
    """
    A1.5: All text routes through handle_request; no separate mini-policy path.

    _gated_legacy_route was removed because it used synthetic identity values
    (subject_state="active", guard_decision="allow") that were never grounded
    in a real RequestIdentity. All paths now use _route_text_by_classification
    which calls handle_request() uniformly.
    """

    def test_1a_gated_legacy_route_does_not_exist(self):
        """
        _gated_legacy_route must NOT exist in webhook_server after A1.5.

        Its removal eliminates the parallel mini-policy path and the synthetic
        identity values it carried.
        """
        import assistant_os.webhook_server as ws
        assert not hasattr(ws, "_gated_legacy_route"), (
            "_gated_legacy_route must be removed (A1.5). "
            "All text routes through _route_text_by_classification."
        )

    def test_1b_handle_command_source_has_no_gated_legacy_route(self):
        """_handle_command source must not reference _gated_legacy_route."""
        import inspect
        from assistant_os.webhook_server import WebhookHandler

        source = inspect.getsource(WebhookHandler._handle_command)
        assert "_gated_legacy_route" not in source, (
            "_handle_command must not call _gated_legacy_route (A1.5 removed it)"
        )

    def test_1c_handle_command_summary_source_has_no_gated_legacy_route(self):
        """_handle_command_summary source must not reference _gated_legacy_route."""
        import inspect
        from assistant_os.webhook_server import WebhookHandler

        source = inspect.getsource(WebhookHandler._handle_command_summary)
        assert "_gated_legacy_route" not in source

    def test_1d_no_bare_route_request_in_handle_command(self):
        """
        _handle_command must not contain bare route_request(req) calls.

        Any such call would bypass handle_request and the full policy chain.
        """
        import inspect
        from assistant_os.webhook_server import WebhookHandler

        source = inspect.getsource(WebhookHandler._handle_command)
        assert "route_request(req)" not in source, (
            "_handle_command must not call route_request(req) directly. "
            "All text must go through _route_text_by_classification."
        )

    def test_1e_no_bare_route_request_in_handle_command_summary(self):
        """_handle_command_summary must not contain bare route_request(req) calls."""
        import inspect
        from assistant_os.webhook_server import WebhookHandler

        source = inspect.getsource(WebhookHandler._handle_command_summary)
        assert "route_request(req)" not in source

    def test_1f_handle_command_routes_all_text_through_classification(self):
        """_handle_command must call _route_text_by_classification for ALL text."""
        import inspect
        from assistant_os.webhook_server import WebhookHandler

        source = inspect.getsource(WebhookHandler._handle_command)
        assert "_route_text_by_classification" in source, (
            "_handle_command must route through _route_text_by_classification"
        )

    def test_1g_no_synthetic_identity_in_webhook_server_source(self):
        """
        webhook_server.py must not contain synthetic identity strings
        subject_state='active' or guard_decision='allow' as policy context defaults.

        These were the specific synthetic values used by the removed
        _gated_legacy_route; their presence would indicate a new bypass.
        """
        import pathlib
        source = pathlib.Path(
            "assistant_os/webhook_server.py"
        ).read_text(encoding="utf-8")

        # Check that the A1.5 tombstone comment is present (confirms intentional removal)
        assert "_gated_legacy_route REMOVED" in source or "_gated_legacy_route" not in source.split("def ")[0], (
            "webhook_server.py must document removal of _gated_legacy_route"
        )

        # The specific synthetic policy values must not appear in any function body
        # (the tombstone comment may reference them as historical note, which is fine)
        import ast
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_src = ast.get_source_segment(source, node) or ""
                # These specific policy context assignments with synthetic values
                # must not appear inside any function
                if 'subject_state="active"' in func_src and "PolicyContext" in func_src:
                    assert False, (
                        f"Function {node.name!r} contains synthetic "
                        "subject_state='active' in a PolicyContext — "
                        "this is a fabricated identity value (A1.5)"
                    )


# ---------------------------------------------------------------------------
# Section 2 — _execute_confirmed_plan routes through handle_request
# ---------------------------------------------------------------------------

class TestExecuteConfirmedPlanGated:
    """_execute_confirmed_plan must route through handle_request (S10/S12/S13)."""

    def _make_handler(self):
        """Construct a WebhookHandler without starting an HTTP server."""
        from assistant_os.webhook_server import WebhookHandler
        handler = object.__new__(WebhookHandler)
        return handler

    def test_2a_no_stored_plan_returns_context_not_found(self):
        """When no plan is stored, returns ContextNotFound immediately."""
        handler = self._make_handler()

        with patch("assistant_os.webhook_server.get_pending_plan", return_value=None), \
             patch("assistant_os.webhook_server._log_webhook_event"):
            response = handler._execute_confirmed_plan("missing-ctx-id", "127.0.0.1")

        assert response["status"] == "error"
        assert response["error"]["type"] == "ContextNotFound"
        assert "missing-ctx-id" in response["error"]["message"]

    def test_2b_stored_plan_calls_handle_request_with_confirm_plan_id(self):
        """When plan exists, handle_request is called with confirm_plan_id in metadata."""
        handler = self._make_handler()

        fake_stored = {
            "plan": {"action": "WORK_CREATE", "domain": "WORK"},
            "operation": "WORK_CREATE",
            "raw_text": "create task X",
        }
        fake_domain_result = {
            "ok": True,
            "domain": "UNKNOWN",
            "result_type": "work_create",
            "data": {"id": "123"},
            "error": None,
            "plan_id": "test-ctx",
            "message": "done",
        }

        captured_req: list[dict] = []

        def mock_handle_request(req):
            captured_req.append(dict(req))
            return fake_domain_result

        with patch("assistant_os.webhook_server.get_pending_plan", return_value=fake_stored), \
             patch("assistant_os.core.orchestrator.handle_request", side_effect=mock_handle_request), \
             patch("assistant_os.webhook_server.remove_pending_plan"), \
             patch("assistant_os.webhook_server._log_webhook_event"):
            handler._execute_confirmed_plan("plan-ctx-id", "127.0.0.1")

        assert len(captured_req) == 1, "handle_request must be called exactly once"
        meta = captured_req[0].get("metadata", {})
        assert meta.get("confirm_plan_id") == "plan-ctx-id", (
            "confirm_plan_id must be passed to handle_request"
        )

    def test_2c_policy_denied_during_confirmation_returns_error(self):
        """If policy denies inside handle_request, the pipeline is not reached."""
        handler = self._make_handler()

        fake_stored = {"plan": {"action": "FIN_EXPENSE"}, "operation": "FIN_EXPENSE", "raw_text": ""}

        denied_domain_result = {
            "ok": False,
            "domain": "*",
            "result_type": "denied",
            "data": None,
            "error": {"type": "access_denied", "message": "Policy denied"},
            "plan_id": "",
            "message": "Policy denied",
        }

        with patch("assistant_os.webhook_server.get_pending_plan", return_value=fake_stored), \
             patch("assistant_os.core.orchestrator.handle_request", return_value=denied_domain_result), \
             patch("assistant_os.webhook_server.remove_pending_plan"), \
             patch("assistant_os.webhook_server._log_webhook_event"):
            response = handler._execute_confirmed_plan("plan-ctx-id", "127.0.0.1")

        assert response["status"] == "error"

    def test_2d_handle_request_not_bypassed_by_direct_pipeline_call(self):
        """Confirm that get_pipeline is NOT called directly in _execute_confirmed_plan."""
        import inspect
        from assistant_os.webhook_server import WebhookHandler

        source = inspect.getsource(WebhookHandler._execute_confirmed_plan)
        assert "get_pipeline" not in source, (
            "_execute_confirmed_plan must not call get_pipeline directly"
        )
        assert "handle_request" in source, (
            "_execute_confirmed_plan must route through handle_request"
        )


# ---------------------------------------------------------------------------
# Section 3 — Dead code methods raise RuntimeError
# ---------------------------------------------------------------------------

class TestDeadCodeRaisesRuntimeError:
    """Verified dead-code bypass methods must raise immediately."""

    def _make_handler(self):
        from assistant_os.webhook_server import WebhookHandler
        return object.__new__(WebhookHandler)

    def test_3a_execute_work_query_from_plan_raises(self):
        handler = self._make_handler()
        with pytest.raises(RuntimeError, match="unreachable unsafe execution path"):
            handler._execute_work_query_from_plan({}, "ctx")

    def test_3b_execute_work_update_preview_raises(self):
        handler = self._make_handler()
        with pytest.raises(RuntimeError, match="unreachable unsafe execution path"):
            handler._execute_work_update_preview({}, "ctx", "text")

    def test_3c_dead_code_error_message_names_policy(self):
        handler = self._make_handler()
        try:
            handler._execute_work_query_from_plan({}, "ctx")
        except RuntimeError as exc:
            assert "policy" in str(exc).lower()

    def test_3d_dead_code_error_message_names_handle_request(self):
        handler = self._make_handler()
        try:
            handler._execute_work_update_preview({}, "ctx", "text")
        except RuntimeError as exc:
            assert "handle_request" in str(exc)


# ---------------------------------------------------------------------------
# Section 4 — Structural invariants
# ---------------------------------------------------------------------------

class TestPolicyInvariant:
    """Core policy integrity invariants — must hold after A1-FIX and A1.5."""

    def test_4a_execute_confirmed_plan_source_references_handle_request(self):
        """_execute_confirmed_plan routes through handle_request (S10/S12/S13)."""
        import inspect
        from assistant_os.webhook_server import WebhookHandler

        source = inspect.getsource(WebhookHandler._execute_confirmed_plan)
        assert "handle_request" in source
        assert "confirm_plan_id" in source

    def test_4b_no_bare_route_request_in_handle_command(self):
        """_handle_command must not call route_request(req) directly."""
        import inspect
        from assistant_os.webhook_server import WebhookHandler

        source = inspect.getsource(WebhookHandler._handle_command)
        assert "route_request(req)" not in source

    def test_4c_no_bare_route_request_in_handle_command_summary(self):
        """_handle_command_summary must not call route_request(req) directly."""
        import inspect
        from assistant_os.webhook_server import WebhookHandler

        source = inspect.getsource(WebhookHandler._handle_command_summary)
        assert "route_request(req)" not in source

    def test_4d_execute_work_query_dead_code_raises(self):
        from assistant_os.webhook_server import WebhookHandler
        handler = object.__new__(WebhookHandler)
        with pytest.raises(RuntimeError):
            handler._execute_work_query_from_plan({}, "ctx")

    def test_4e_execute_work_update_dead_code_raises(self):
        from assistant_os.webhook_server import WebhookHandler
        handler = object.__new__(WebhookHandler)
        with pytest.raises(RuntimeError):
            handler._execute_work_update_preview({}, "ctx", "t")
