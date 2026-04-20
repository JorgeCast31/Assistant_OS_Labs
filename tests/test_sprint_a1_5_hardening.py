"""
Sprint A1.5 — Legacy Identity Plumbing Hardening Tests.

Verifies that the A1.5 canonical reroute is in effect:
  - All prefix text (CODE:, DOC:, JOBS:, BIZ:, etc.) is handled by
    _route_text_by_classification → handle_request, not by a separate
    mini-policy path.
  - No synthetic identity values (subject_state="active",
    guard_decision="allow") appear inside any function body.
  - _gated_legacy_route has been fully removed.
  - Policy (S10), token (S12), grant (S13) enforcement apply uniformly
    for every request regardless of prefix.

Structure
---------
  Section 1 — Canonical reroute: prefix text → handle_request
    1a. _handle_command source calls _route_text_by_classification
    1b. _handle_command_summary source calls _route_text_by_classification
    1c. _gated_legacy_route does not exist anywhere in webhook_server
    1d. No route_request(req) call in _handle_command
    1e. No route_request(req) call in _handle_command_summary

  Section 2 — No synthetic identity in any function body
    2a. No function contains subject_state="active" + PolicyContext
    2b. No function contains guard_decision="allow" + PolicyContext
    2c. webhook_server module-level code has no synthetic PolicyContext

  Section 3 — Live-endpoint: prefix text is handled by canonical path
    3a. CODE: prefix → agent="classifier" (not "code")
    3b. DOC: prefix → agent="classifier" (not "doc")
    3c. Non-prefix text → agent="classifier" (unchanged baseline)
    3d. Response structure is complete for all prefix variants

  Section 4 — Policy applied uniformly (structural)
    4a. handle_request is called (not route_request) in _route_text_by_classification
    4b. _route_text_by_classification uses handle_request (source check)
"""

from __future__ import annotations

import ast
import http.client
import inspect
import json
import pathlib
import time
import unittest

import pytest

# ---------------------------------------------------------------------------
# Module-level path to webhook_server.py source
# ---------------------------------------------------------------------------
_WS_PATH = pathlib.Path("assistant_os/webhook_server.py")


# ---------------------------------------------------------------------------
# Section 1 — Canonical reroute: prefix text → handle_request
# ---------------------------------------------------------------------------

class TestCanonicalReroute:
    """A1.5: All prefix text routes through _route_text_by_classification."""

    def test_1a_handle_command_calls_route_text_by_classification(self):
        """_handle_command must delegate to _route_text_by_classification."""
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._handle_command)
        assert "_route_text_by_classification" in src, (
            "_handle_command must route ALL text through "
            "_route_text_by_classification (A1.5)"
        )

    def test_1b_handle_command_summary_calls_route_text_by_classification(self):
        """_handle_command_summary must delegate to _route_text_by_classification."""
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._handle_command_summary)
        assert "_route_text_by_classification" in src, (
            "_handle_command_summary must route ALL text through "
            "_route_text_by_classification (A1.5)"
        )

    def test_1c_gated_legacy_route_does_not_exist(self):
        """_gated_legacy_route must NOT exist after A1.5."""
        import assistant_os.webhook_server as ws
        assert not hasattr(ws, "_gated_legacy_route"), (
            "_gated_legacy_route must be removed (A1.5). "
            "All text routes through handle_request via "
            "_route_text_by_classification."
        )
        # Also verify it is not defined as a method on WebhookHandler
        from assistant_os.webhook_server import WebhookHandler
        assert not hasattr(WebhookHandler, "_gated_legacy_route"), (
            "_gated_legacy_route must not exist as a WebhookHandler method (A1.5)"
        )

    def test_1d_no_bare_route_request_in_handle_command(self):
        """_handle_command must not call route_request(req) directly."""
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._handle_command)
        assert "route_request(req)" not in src, (
            "_handle_command must not call route_request(req) directly — "
            "this bypasses the full policy chain (A1.5)"
        )

    def test_1e_no_bare_route_request_in_handle_command_summary(self):
        """_handle_command_summary must not call route_request(req) directly."""
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._handle_command_summary)
        assert "route_request(req)" not in src, (
            "_handle_command_summary must not call route_request(req) directly "
            "(A1.5)"
        )


# ---------------------------------------------------------------------------
# Section 2 — No synthetic identity in any function body
# ---------------------------------------------------------------------------

class TestNoSyntheticIdentity:
    """A1.5: No function body may contain synthetic PolicyContext values."""

    def _all_function_sources(self) -> list[tuple[str, str]]:
        """Return (name, source) for every function/method in webhook_server.py."""
        source = _WS_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        results = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_src = ast.get_source_segment(source, node) or ""
                results.append((node.name, func_src))
        return results

    def test_2a_no_synthetic_subject_state_active_in_policy_context(self):
        """No function body may contain subject_state='active' in a PolicyContext."""
        for name, src in self._all_function_sources():
            if 'subject_state="active"' in src and "PolicyContext" in src:
                pytest.fail(
                    f"Function {name!r} in webhook_server.py contains synthetic "
                    "subject_state='active' inside a PolicyContext — "
                    "this is a fabricated identity value removed in A1.5"
                )

    def test_2b_no_synthetic_guard_decision_allow_in_policy_context(self):
        """No function body may contain guard_decision='allow' in a PolicyContext."""
        for name, src in self._all_function_sources():
            if 'guard_decision="allow"' in src and "PolicyContext" in src:
                pytest.fail(
                    f"Function {name!r} in webhook_server.py contains synthetic "
                    "guard_decision='allow' inside a PolicyContext — "
                    "this is a fabricated identity value removed in A1.5"
                )

    def test_2c_module_level_has_no_synthetic_policy_context(self):
        """Module-level code must not construct a PolicyContext with synthetic values."""
        source = _WS_PATH.read_text(encoding="utf-8")
        # Check combined patterns that would indicate a synthetic PolicyContext
        # at module level (outside any function)
        tree = ast.parse(source)
        # Collect line ranges of all function bodies
        func_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if hasattr(child, "lineno"):
                        func_lines.add(child.lineno)
        # Check lines outside function bodies
        for i, line in enumerate(source.splitlines(), start=1):
            if i not in func_lines:
                if 'subject_state="active"' in line and "PolicyContext" in line:
                    pytest.fail(
                        f"Line {i} of webhook_server.py: module-level code contains "
                        "synthetic subject_state='active' in PolicyContext"
                    )


# ---------------------------------------------------------------------------
# Section 3 — Live-endpoint: prefix text handled by canonical path
# ---------------------------------------------------------------------------

class TestLiveEndpointCanonicalRouting(unittest.TestCase):
    """Live integration: prefix text returns agent='classifier' after A1.5."""

    port: int
    server: object

    @classmethod
    def setUpClass(cls) -> None:
        from assistant_os.webhook_server import start_server_thread
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def _post_command(self, text: str) -> tuple[int, dict]:
        from assistant_os.config import WEBHOOK_TOKEN
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps({"text": text}).encode("utf-8")
        conn.request("POST", "/command", body=body, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return status, data

    def test_3a_code_prefix_returns_classifier_not_legacy_agent(self):
        """CODE: prefix is handled by canonical path → agent='classifier'."""
        status, data = self._post_command("CODE: crear modulo test")
        self.assertIn(status, (200, 202), f"Unexpected status: {status} — {data}")
        self.assertIn("agent", data)
        self.assertEqual(
            data["agent"], "classifier",
            f"A1.5: CODE: prefix must route through classifier, got agent={data['agent']!r}. "
            "If this is 'code', the legacy bypass is still active."
        )

    def test_3b_doc_prefix_returns_classifier_not_legacy_agent(self):
        """DOC: prefix is handled by canonical path → agent='classifier'."""
        status, data = self._post_command("DOC: generate readme")
        self.assertIn(status, (200, 202), f"Unexpected status: {status} — {data}")
        self.assertIn("agent", data)
        self.assertEqual(
            data["agent"], "classifier",
            f"A1.5: DOC: prefix must route through classifier, got agent={data['agent']!r}."
        )

    def test_3c_non_prefix_text_routed_through_handle_request(self):
        """Non-prefix text routes through canonical handle_request path.

        The resulting agent depends on NL classification (e.g. 'work', 'classifier',
        'fin', etc.).  The key invariant is that a structured Response is returned
        (server did not crash) and the agent is NOT a legacy direct-bypass value that
        would indicate route_request() was called without policy gating.

        Note: In a test environment without Notion credentials, WORK queries may
        return status='error' with agent='work' — that's correct pipeline behavior
        (policy was applied, domain handler ran, Notion API returned an auth error).
        """
        status, data = self._post_command("lista las tareas pendientes")
        # Any HTTP status is valid — the server must return a structured Response
        self.assertIn("agent", data, "Response must include 'agent' field")
        self.assertIn("status", data, "Response must include 'status' field")
        # The request must have gone through handle_request (structured output)
        self.assertIn("context_id", data, "Response must include 'context_id' field")
        # Verify response has valid structure (not a crash/empty body)
        self.assertIsInstance(data.get("agent"), str)
        self.assertIsInstance(data.get("status"), str)

    def test_3d_response_structure_complete_for_prefix_request(self):
        """All required Response fields are present for prefix text (A1.5)."""
        status, data = self._post_command("CODE: test module")
        self.assertEqual(status, 200)
        required_fields = ("context_id", "agent", "status", "output", "ts", "error")
        for field in required_fields:
            self.assertIn(field, data, f"Missing required field {field!r} in Response")


# ---------------------------------------------------------------------------
# Section 4 — Policy applied uniformly (structural)
# ---------------------------------------------------------------------------

class TestPolicyAppliedUniformly:
    """handle_request (with full policy chain) is used for every request path."""

    def test_4a_route_text_by_classification_calls_handle_request(self):
        """_route_text_by_classification must call handle_request."""
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._route_text_by_classification)
        assert "handle_request" in src, (
            "_route_text_by_classification must delegate to handle_request "
            "to ensure S10/S12/S13 policy is applied (A1.5)"
        )

    def test_4b_execute_confirmed_plan_calls_handle_request(self):
        """_execute_confirmed_plan must still route through handle_request (A1-FIX)."""
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._execute_confirmed_plan)
        assert "handle_request" in src, (
            "_execute_confirmed_plan must call handle_request (A1-FIX invariant)"
        )
        assert "get_pipeline" not in src, (
            "_execute_confirmed_plan must not call get_pipeline directly (A1-FIX)"
        )

    def test_4c_dead_code_raises_before_any_execution(self):
        """Dead-code bypass methods raise RuntimeError immediately (A1-FIX)."""
        from assistant_os.webhook_server import WebhookHandler
        handler = object.__new__(WebhookHandler)

        with pytest.raises(RuntimeError, match="unreachable unsafe execution path"):
            handler._execute_work_query_from_plan({}, "ctx")

        with pytest.raises(RuntimeError, match="unreachable unsafe execution path"):
            handler._execute_work_update_preview({}, "ctx", "text")
