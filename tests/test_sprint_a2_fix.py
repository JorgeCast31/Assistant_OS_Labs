"""
Sprint A2-FIX — Token Boundary Hardening Invariant Tests.

Verifies that ALL execution paths are token-gated and no callable method
can execute without evaluate_policy → issue_token → verify_token → consume_token.

Audit A2 found four categories of bypass closed in A2-FIX:
  - MEDIUM: Schema endpoints bypassed handle_request / policy / token entirely
  - MEDIUM: 4 WebhookHandler methods were callable bypass paths (no token gate)
  - MEDIUM: X-Assistant-Admin-Token validated by presence only (not value)
  - LOW:    Token binding verification — clarified as already complete (all 5 fields)

Structure
---------
  Section 1 — Latent bypass methods neutered
    1a. _execute_work_create raises RuntimeError
    1b. _execute_work_delete raises RuntimeError
    1c. _execute_work_update_bulk raises RuntimeError
    1d. _execute_work_update raises RuntimeError
    1e. All four error messages name handle_request
    1f. All four error messages name policy

  Section 2 — Schema endpoint policy gate installed
    2a. _apply_schema_policy_gate method exists on WebhookHandler
    2b. _handle_work_schema_plan source references _apply_schema_policy_gate
    2c. _handle_work_schema_commit source references _apply_schema_policy_gate
    2d. _apply_schema_policy_gate calls evaluate_policy (S10)
    2e. _apply_schema_policy_gate calls issue_token (S12)
    2f. _apply_schema_policy_gate calls verify_token
    2g. _apply_schema_policy_gate calls consume_token

  Section 3 — Admin token validated against configured secret
    3a. WEBHOOK_ADMIN_TOKEN exists in config
    3b. _handle_work_schema_plan source references WEBHOOK_ADMIN_TOKEN
    3c. _handle_work_schema_commit source references WEBHOOK_ADMIN_TOKEN
    3d. Schema handler rejects requests when header value mismatches secret

  Section 4 — Token binding verification completeness
    4a. verify_token checks all 5 binding fields (principal_id, subject_state,
        action_type, capability, operation_key)
    4b. Mismatched action_type causes verify_token to return False
    4c. Mismatched capability causes verify_token to return False
    4d. Mismatched operation_key causes verify_token to return False

  Section 5 — Token lifecycle integrity
    5a. issue_token only reachable after PolicyDecision.APPROVED in handle_request
    5b. _require_token is the only verify+consume call site in orchestrator
    5c. consume_token is called immediately after verify_token succeeds
    5d. No execution path skips _require_token
"""

from __future__ import annotations

import inspect

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler():
    from assistant_os.webhook_server import WebhookHandler
    return object.__new__(WebhookHandler)


# ---------------------------------------------------------------------------
# Section 1 — Latent bypass methods neutered
# ---------------------------------------------------------------------------

class TestLatentBypassMethodsNeutered:
    """All four bypass methods raise RuntimeError immediately (A2-FIX)."""

    def test_1a_execute_work_create_raises(self):
        handler = _make_handler()
        with pytest.raises(RuntimeError, match="unreachable unsafe execution path"):
            handler._execute_work_create({}, "ctx")

    def test_1b_execute_work_delete_raises(self):
        handler = _make_handler()
        with pytest.raises(RuntimeError, match="unreachable unsafe execution path"):
            handler._execute_work_delete({}, "ctx")

    def test_1c_execute_work_update_bulk_raises(self):
        handler = _make_handler()
        with pytest.raises(RuntimeError, match="unreachable unsafe execution path"):
            handler._execute_work_update_bulk({}, "ctx")

    def test_1d_execute_work_update_raises(self):
        handler = _make_handler()
        with pytest.raises(RuntimeError, match="unreachable unsafe execution path"):
            handler._execute_work_update({}, "ctx")

    def test_1e_all_error_messages_name_handle_request(self):
        handler = _make_handler()
        methods = [
            lambda: handler._execute_work_create({}, "ctx"),
            lambda: handler._execute_work_delete({}, "ctx"),
            lambda: handler._execute_work_update_bulk({}, "ctx"),
            lambda: handler._execute_work_update({}, "ctx"),
        ]
        for call in methods:
            try:
                call()
            except RuntimeError as exc:
                assert "handle_request" in str(exc), (
                    f"RuntimeError must name handle_request, got: {exc}"
                )

    def test_1f_all_error_messages_name_policy(self):
        handler = _make_handler()
        methods = [
            lambda: handler._execute_work_create({}, "ctx"),
            lambda: handler._execute_work_delete({}, "ctx"),
            lambda: handler._execute_work_update_bulk({}, "ctx"),
            lambda: handler._execute_work_update({}, "ctx"),
        ]
        for call in methods:
            try:
                call()
            except RuntimeError as exc:
                assert "policy" in str(exc).lower(), (
                    f"RuntimeError must name policy enforcement, got: {exc}"
                )


# ---------------------------------------------------------------------------
# Section 2 — Schema endpoint policy gate installed
# ---------------------------------------------------------------------------

class TestSchemaPolicyGateInstalled:
    """_apply_schema_policy_gate enforces S10/S12/S13 for schema endpoints."""

    def test_2a_apply_schema_policy_gate_method_exists(self):
        from assistant_os.webhook_server import WebhookHandler
        assert hasattr(WebhookHandler, "_apply_schema_policy_gate"), (
            "WebhookHandler must have _apply_schema_policy_gate (A2-FIX)"
        )

    def test_2b_handle_work_schema_plan_calls_policy_gate(self):
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._handle_work_schema_plan)
        assert "_apply_schema_policy_gate" in src, (
            "_handle_work_schema_plan must call _apply_schema_policy_gate (A2-FIX)"
        )

    def test_2c_handle_work_schema_commit_calls_policy_gate(self):
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._handle_work_schema_commit)
        assert "_apply_schema_policy_gate" in src, (
            "_handle_work_schema_commit must call _apply_schema_policy_gate (A2-FIX)"
        )

    def test_2d_policy_gate_calls_evaluate_policy(self):
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._apply_schema_policy_gate)
        assert "evaluate_policy" in src or "_eval_policy" in src, (
            "_apply_schema_policy_gate must call evaluate_policy (S10)"
        )

    def test_2e_policy_gate_calls_issue_token(self):
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._apply_schema_policy_gate)
        assert "issue_token" in src or "_issue_token" in src, (
            "_apply_schema_policy_gate must call issue_token (S12)"
        )

    def test_2f_policy_gate_calls_verify_token(self):
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._apply_schema_policy_gate)
        assert "verify_token" in src or "_vt(" in src, (
            "_apply_schema_policy_gate must call verify_token"
        )

    def test_2g_policy_gate_calls_consume_token(self):
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._apply_schema_policy_gate)
        assert "consume_token" in src or "_ct(" in src, (
            "_apply_schema_policy_gate must call consume_token (single-use)"
        )

    def test_2h_policy_gate_fails_closed_on_denied_policy(self):
        """_apply_schema_policy_gate returns error tuple when policy denies."""
        from unittest.mock import patch
        from assistant_os.policy.policy_models import PolicyDecision, PolicyOutcome, PolicyReason

        denied = PolicyDecision(
            outcome=PolicyOutcome("denied"),
            reason=PolicyReason("subject_state_blocked"),
            detail="test: denied",
            permitted=False,
        )
        handler = _make_handler()
        with patch("assistant_os.policy.policy_engine.evaluate_policy", return_value=denied):
            result = handler._apply_schema_policy_gate()

        assert result is not None, (
            "_apply_schema_policy_gate must return error tuple when policy denies"
        )
        assert isinstance(result, tuple) and len(result) == 2
        status, body = result
        assert status in (403, 500), f"Expected 4xx/5xx on policy denial, got {status}"

    def test_2i_policy_gate_returns_none_when_approved(self):
        """_apply_schema_policy_gate returns None (proceed) when policy approves."""
        from assistant_os.policy.policy_models import PolicyDecision, PolicyOutcome, PolicyReason
        from unittest.mock import patch

        approved = PolicyDecision(
            outcome=PolicyOutcome("approved"),
            reason=PolicyReason("approved"),
            detail="test: approved",
            permitted=True,
        )
        handler = _make_handler()
        with patch("assistant_os.policy.policy_engine.evaluate_policy", return_value=approved):
            result = handler._apply_schema_policy_gate()

        assert result is None, (
            "_apply_schema_policy_gate must return None when policy approves "
            f"(got {result!r})"
        )


# ---------------------------------------------------------------------------
# Section 3 — Admin token validated against configured secret
# ---------------------------------------------------------------------------

class TestAdminTokenValidation:
    """X-Assistant-Admin-Token validated against WEBHOOK_ADMIN_TOKEN (A2-FIX)."""

    def test_3a_webhook_admin_token_in_config(self):
        from assistant_os import config
        assert hasattr(config, "WEBHOOK_ADMIN_TOKEN"), (
            "WEBHOOK_ADMIN_TOKEN must be defined in config (A2-FIX)"
        )

    def test_3b_schema_plan_handler_references_webhook_admin_token(self):
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._handle_work_schema_plan)
        assert "WEBHOOK_ADMIN_TOKEN" in src or "_SCHEMA_ADMIN_TOKEN" in src, (
            "_handle_work_schema_plan must validate against WEBHOOK_ADMIN_TOKEN (A2-FIX)"
        )

    def test_3c_schema_commit_handler_references_webhook_admin_token(self):
        from assistant_os.webhook_server import WebhookHandler
        src = inspect.getsource(WebhookHandler._handle_work_schema_commit)
        assert "WEBHOOK_ADMIN_TOKEN" in src or "_SCHEMA_ADMIN_TOKEN" in src, (
            "_handle_work_schema_commit must validate against WEBHOOK_ADMIN_TOKEN (A2-FIX)"
        )

    def test_3d_schema_plan_rejects_wrong_admin_token(self):
        """When WEBHOOK_ADMIN_TOKEN is set, wrong header value → 403."""
        import http.client
        import json
        import time
        from assistant_os.webhook_server import start_server_thread
        from assistant_os.config import WEBHOOK_TOKEN

        server, port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)
        try:
            import unittest.mock as _mock
            # Temporarily set WEBHOOK_ADMIN_TOKEN to a known secret
            with _mock.patch("assistant_os.webhook_server.WebhookHandler._apply_schema_policy_gate", return_value=None), \
                 _mock.patch("assistant_os.webhook_server.generate_schema_plan", return_value={"ok": True}), \
                 _mock.patch("assistant_os.config.WEBHOOK_ADMIN_TOKEN", "correct-secret"):
                # Patch the import inside the handler method
                import assistant_os.config as _cfg
                original = _cfg.WEBHOOK_ADMIN_TOKEN
                _cfg.WEBHOOK_ADMIN_TOKEN = "correct-secret"
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                    headers = {
                        "Content-Type": "application/json",
                        "X-Assistant-Token": WEBHOOK_TOKEN,
                        "X-Assistant-Admin-Token": "wrong-secret",
                    }
                    body = json.dumps({"changes": []}).encode("utf-8")
                    conn.request("POST", "/work/schema/plan", body=body, headers=headers)
                    resp = conn.getresponse()
                    status = resp.status
                    conn.close()
                    assert status == 403, (
                        f"Wrong admin token must return 403, got {status}"
                    )
                finally:
                    _cfg.WEBHOOK_ADMIN_TOKEN = original
        finally:
            server.shutdown()
            server.server_close()


# ---------------------------------------------------------------------------
# Section 4 — Token binding verification completeness
# ---------------------------------------------------------------------------

class TestTokenBindingVerification:
    """verify_token checks all 5 binding fields (A2 audit clarification)."""

    def _make_binding(self, **overrides):
        from assistant_os.capabilities.token_models import OperationBinding
        defaults = dict(
            principal_id="p1",
            subject_state="active",
            action_type="write",
            capability="write_files",
            operation_key="ctx-test-001",
        )
        defaults.update(overrides)
        return OperationBinding(**defaults)

    def _issue_token(self, binding):
        from assistant_os.capabilities.token_issuer import issue_token
        return issue_token(binding)

    def test_4a_verify_token_checks_all_five_fields(self):
        """verify_token source must reference all five binding fields."""
        from assistant_os.capabilities import token_verifier
        src = inspect.getsource(token_verifier.verify_token)
        for field in ("principal_id", "subject_state", "action_type", "capability", "operation_key"):
            assert field in src, (
                f"verify_token must check binding.{field} (A2 audit finding)"
            )

    def test_4b_mismatched_action_type_denied(self):
        binding = self._make_binding()
        token = self._issue_token(binding)
        wrong = self._make_binding(action_type="read")  # different action_type

        from assistant_os.capabilities.token_verifier import verify_token
        assert verify_token(token, wrong) is False, (
            "verify_token must return False when action_type mismatches"
        )

    def test_4c_mismatched_capability_denied(self):
        binding = self._make_binding()
        token = self._issue_token(binding)
        wrong = self._make_binding(capability="execute_code")  # different capability

        from assistant_os.capabilities.token_verifier import verify_token
        assert verify_token(token, wrong) is False, (
            "verify_token must return False when capability mismatches"
        )

    def test_4d_mismatched_operation_key_denied(self):
        binding = self._make_binding()
        token = self._issue_token(binding)
        wrong = self._make_binding(operation_key="different-ctx-id")

        from assistant_os.capabilities.token_verifier import verify_token
        assert verify_token(token, wrong) is False, (
            "verify_token must return False when operation_key mismatches"
        )

    def test_4e_exact_match_passes(self):
        binding = self._make_binding()
        token = self._issue_token(binding)

        from assistant_os.capabilities.token_verifier import verify_token
        assert verify_token(token, binding) is True, (
            "verify_token must return True when all five binding fields match"
        )


# ---------------------------------------------------------------------------
# Section 5 — Token lifecycle integrity
# ---------------------------------------------------------------------------

class TestTokenLifecycleIntegrity:
    """Issue only after APPROVED; consume immediately after verify; no skip paths."""

    def test_5a_issue_token_unreachable_before_policy_check_in_orchestrator(self):
        """issue_token call site is after the policy permitted check in orchestrator."""
        import ast
        import pathlib
        src = pathlib.Path("assistant_os/core/orchestrator.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        # Find handle_request function
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "handle_request":
                func_src = ast.get_source_segment(src, node) or ""
                # issue_token must appear AFTER the permitted check
                permitted_pos = func_src.find("_policy_decision.permitted")
                issue_pos = func_src.find("_issue_token(")
                assert permitted_pos > 0, "handle_request must check permitted"
                assert issue_pos > 0, "handle_request must call issue_token"
                assert issue_pos > permitted_pos, (
                    "issue_token must appear AFTER the policy permitted check "
                    "in handle_request source"
                )
                return
        pytest.fail("handle_request function not found in orchestrator.py")

    def test_5b_require_token_is_only_verify_consume_call_site(self):
        """_require_token is the only place that calls verify_token in orchestrator."""
        import pathlib
        src = pathlib.Path("assistant_os/core/orchestrator.py").read_text(encoding="utf-8")
        # Outside _require_token, verify_token must not appear directly
        # (it's called indirectly via _vt which is the alias inside _require_token)
        lines = src.splitlines()
        in_require_token = False
        for line in lines:
            stripped = line.strip()
            if "def _require_token(" in stripped:
                in_require_token = True
            elif stripped.startswith("def ") and in_require_token:
                in_require_token = False
            if not in_require_token and "verify_token(" in stripped:
                # Allow import lines
                if "import" not in stripped:
                    pytest.fail(
                        f"verify_token called outside _require_token: {stripped!r}"
                    )

    def test_5c_consume_token_follows_verify_in_require_token(self):
        """In _require_token source, consume_token appears after verify_token."""
        from assistant_os.core import orchestrator
        src = inspect.getsource(orchestrator._require_token)
        verify_pos = src.find("_vt(")
        consume_pos = src.find("_ct(")
        assert verify_pos > 0, "_require_token must call verify_token (_vt)"
        assert consume_pos > 0, "_require_token must call consume_token (_ct)"
        assert consume_pos > verify_pos, (
            "consume_token (_ct) must appear AFTER verify_token (_vt) in _require_token"
        )

    def test_5d_require_token_called_at_every_execution_dispatch_point(self):
        """_require_token appears at all three dispatch points in orchestrator source."""
        import pathlib
        src = pathlib.Path("assistant_os/core/orchestrator.py").read_text(encoding="utf-8")
        # Count occurrences of _require_token call (not the definition)
        call_count = src.count("_require_token(_cap_token")
        assert call_count >= 3, (
            f"_require_token must be called at ≥3 dispatch points "
            f"(confirm, structured AUTO, NL AUTO), found {call_count}"
        )
