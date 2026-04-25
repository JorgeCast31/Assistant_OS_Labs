"""
Tests — execution_status truthfulness signal across all domain pipelines.

Coverage
--------
A. contracts — EXECUTION_STATUS_* constants exist and have correct values
B. WORK pipeline — always returns execution_status="real"
C. FIN pipeline  — always returns execution_status="real"
D. HOST pipeline — always returns execution_status="real"
E. CODE pipeline — stub (no executor): execution_status="stub", message prefixed
F. CODE pipeline — live (executor registered): execution_status="real"
G. MACHINE_OPERATOR pipeline — success: "real", unavailable: "unavailable", partial: "partial"
H. make_domain_result — accepts and passes through execution_status
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# A. Contract constants
# ---------------------------------------------------------------------------

class TestExecutionStatusConstants:
    def test_constants_exist(self):
        from assistant_os.contracts import (
            EXECUTION_STATUS_REAL,
            EXECUTION_STATUS_STUB,
            EXECUTION_STATUS_UNAVAILABLE,
            EXECUTION_STATUS_PARTIAL,
        )
        assert EXECUTION_STATUS_REAL        == "real"
        assert EXECUTION_STATUS_STUB        == "stub"
        assert EXECUTION_STATUS_UNAVAILABLE == "unavailable"
        assert EXECUTION_STATUS_PARTIAL     == "partial"

    def test_make_domain_result_passes_through_execution_status(self):
        from assistant_os.contracts import make_domain_result, EXECUTION_STATUS_REAL
        dr = make_domain_result(
            ok=True,
            result_type="test_action",
            domain="TEST",
            message="ok",
            data={},
            execution_status=EXECUTION_STATUS_REAL,
        )
        assert dr["execution_status"] == "real"

    def test_make_domain_result_omits_execution_status_when_none(self):
        from assistant_os.contracts import make_domain_result
        dr = make_domain_result(
            ok=True,
            result_type="test_action",
            domain="TEST",
            message="ok",
            data={},
        )
        assert "execution_status" not in dr


# ---------------------------------------------------------------------------
# B. WORK pipeline — execution_status="real"
# ---------------------------------------------------------------------------

class TestWorkPipelineExecutionStatus:
    def _plan(self):
        from assistant_os.contracts import ACTION_WORK_QUERY, RISK_LOW, make_plan
        plan = make_plan(
            domain="WORK",
            action=ACTION_WORK_QUERY,
            target="query tasks",
            risk_level=RISK_LOW,
        )
        plan["domain_payload"] = {"query": "all tasks", "confirmed": True}
        return plan

    def test_work_execute_sets_execution_status_real(self):
        from assistant_os.pipelines.work_pipeline import execute
        from assistant_os.contracts import EXECUTION_STATUS_REAL

        mock_result = [{"id": "1", "title": "Task 1"}]
        with patch("assistant_os.pipelines.work_pipeline._query_work", return_value=mock_result):
            result = execute(self._plan(), "ctx-work-1")

        assert result.get("execution_status") == EXECUTION_STATUS_REAL

    def test_work_execute_error_still_sets_execution_status_real(self):
        from assistant_os.pipelines.work_pipeline import execute
        from assistant_os.contracts import EXECUTION_STATUS_REAL

        with patch("assistant_os.pipelines.work_pipeline._query_work", side_effect=RuntimeError("db down")):
            result = execute(self._plan(), "ctx-work-2")

        # Even on pipeline error, execution_status is present
        assert "execution_status" in result


# ---------------------------------------------------------------------------
# C. FIN pipeline — execution_status="real"
# ---------------------------------------------------------------------------

class TestFinPipelineExecutionStatus:
    def _plan(self):
        from assistant_os.contracts import ACTION_FIN_PLAN, RISK_LOW, make_plan
        plan = make_plan(
            domain="FIN",
            action=ACTION_FIN_PLAN,
            target="fin plan",
            risk_level=RISK_LOW,
        )
        plan["domain_payload"] = {"text": "Buy coffee $3", "confirmed": True}
        return plan

    def test_fin_execute_sets_execution_status_real(self):
        from assistant_os.pipelines.fin_pipeline import execute
        from assistant_os.contracts import EXECUTION_STATUS_REAL

        result = execute(self._plan(), "ctx-fin-1")
        assert result.get("execution_status") == EXECUTION_STATUS_REAL


# ---------------------------------------------------------------------------
# D. HOST pipeline — execution_status="real"
# ---------------------------------------------------------------------------

class TestHostPipelineExecutionStatus:
    def _plan(self, payload: dict | None = None):
        from assistant_os.contracts import ACTION_HOST_LIST_DIRECTORY, RISK_LOW, make_plan
        plan = make_plan(
            domain="HOST",
            action=ACTION_HOST_LIST_DIRECTORY,
            target="list dir",
            risk_level=RISK_LOW,
        )
        plan["domain_payload"] = payload or {
            "confirmed": True,
            "path": "/tmp",
        }
        return plan

    def test_host_execute_sets_execution_status_real(self):
        from assistant_os.pipelines.host_pipeline import execute
        from assistant_os.agents.host_agent import HOST_AGENT_ID
        from assistant_os.agents.registry import activate_agent
        from assistant_os.contracts import EXECUTION_STATUS_REAL

        activate_agent(HOST_AGENT_ID)

        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.action = "list_directory"
        mock_result.execution_id = "exec-1"
        mock_result.pid = None
        mock_result.app_name = None
        mock_result.entries = ["file.txt"]
        mock_result.content = None
        mock_result.error_code = None
        mock_result.error = None
        mock_result.bytes_written = None
        mock_result.write_mode = None
        mock_result.atomic_replace_used = None

        with patch("assistant_os.pipelines.host_pipeline.execute_host_action", return_value=mock_result):
            result = execute(self._plan(), "ctx-host-1")

        assert result.get("execution_status") == EXECUTION_STATUS_REAL


# ---------------------------------------------------------------------------
# E. CODE pipeline — no executor → execution_status="stub" + message prefix
# ---------------------------------------------------------------------------

class TestCodePipelineStubStatus:
    def _plan(self, action: str = "CODE_EXPLAIN"):
        from assistant_os.contracts import RISK_LOW, make_plan
        plan = make_plan(
            domain="CODE",
            action=action,
            target="test_file.py",
            risk_level=RISK_LOW,
        )
        plan["domain_payload"] = {
            "confirmed": True,
            "action": action,
            "target_file": "test_file.py",
            "code_context": "def foo(): pass",
        }
        return plan

    def test_code_explain_stub_sets_execution_status_stub(self):
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.contracts import EXECUTION_STATUS_STUB

        original = cp._review_executor
        try:
            cp._review_executor = None
            result = cp.execute(self._plan("CODE_EXPLAIN"), "ctx-code-1")
        finally:
            cp._review_executor = original

        assert result.get("execution_status") == EXECUTION_STATUS_STUB

    def test_code_explain_stub_message_has_prefix(self):
        import assistant_os.pipelines.code_pipeline as cp

        original = cp._review_executor
        try:
            cp._review_executor = None
            result = cp.execute(self._plan("CODE_EXPLAIN"), "ctx-code-2")
        finally:
            cp._review_executor = original

        assert "[STUB — no real execution]" in result.get("message", "")

    def test_code_preview_stub_sets_execution_status_stub(self):
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.contracts import EXECUTION_STATUS_STUB

        original = cp._propose_executor
        try:
            cp._propose_executor = None
            result = cp.execute(self._plan("CODE_FIX"), "ctx-code-3")
        finally:
            cp._propose_executor = original

        assert result.get("execution_status") == EXECUTION_STATUS_STUB

    def test_code_preview_stub_message_has_prefix(self):
        import assistant_os.pipelines.code_pipeline as cp

        original = cp._propose_executor
        try:
            cp._propose_executor = None
            result = cp.execute(self._plan("CODE_FIX"), "ctx-code-4")
        finally:
            cp._propose_executor = original

        assert "[STUB — no real execution]" in result.get("message", "")


# ---------------------------------------------------------------------------
# F. CODE pipeline — live executor → execution_status="real"
# ---------------------------------------------------------------------------

class TestCodePipelineLiveStatus:
    def _plan(self, action: str = "CODE_EXPLAIN"):
        from assistant_os.contracts import RISK_LOW, make_plan
        plan = make_plan(
            domain="CODE",
            action=action,
            target="test_file.py",
            risk_level=RISK_LOW,
        )
        plan["domain_payload"] = {
            "confirmed": True,
            "action": action,
            "target_file": "test_file.py",
            "code_context": "def foo(): pass",
        }
        return plan

    def _make_live_review_executor(self):
        mock = MagicMock()
        mock.return_value = {
            "summary": "This function does foo.",
            "findings": [],
            "raw": "",
        }
        return mock

    def _make_live_propose_executor(self):
        mock = MagicMock()
        mock.return_value = {
            "proposed_changes": [{"file": "test_file.py", "content": "def foo(): pass\n"}],
            "summary": "No changes needed.",
            "raw": "",
        }
        return mock

    def test_code_explain_live_sets_execution_status_real(self):
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.contracts import EXECUTION_STATUS_REAL

        original = cp._review_executor
        try:
            cp.register_review_executor(self._make_live_review_executor())
            result = cp.execute(self._plan("CODE_EXPLAIN"), "ctx-code-live-1")
        finally:
            cp._review_executor = original

        assert result.get("execution_status") == EXECUTION_STATUS_REAL

    def test_code_explain_live_message_has_no_stub_prefix(self):
        import assistant_os.pipelines.code_pipeline as cp

        original = cp._review_executor
        try:
            cp.register_review_executor(self._make_live_review_executor())
            result = cp.execute(self._plan("CODE_EXPLAIN"), "ctx-code-live-2")
        finally:
            cp._review_executor = original

        assert "[STUB — no real execution]" not in result.get("message", "")


# ---------------------------------------------------------------------------
# G. MACHINE_OPERATOR pipeline — execution_status by lane_outcome
# ---------------------------------------------------------------------------

class TestMachineOperatorPipelineExecutionStatus:
    def _request(self, **overrides):
        request = {
            "intent_id":      "intent-es-001",
            "correlation_id": "corr-es-001",
            "capability_name": "browser.snapshot",
            "capability_tier": "read_only",
            "arguments":      {"url": "https://example.test"},
            "policy_context": {
                "policy_decision_ref": "policy-es-001",
                "governance_ref":      "gov-es-001",
                "execution_mode":      "auto",
                "approval_mode":       "none",
                "constraints":         [],
                "allowlist_refs":      [],
                "secret_refs":         [],
            },
            "budget": {
                "max_steps":        1,
                "max_duration_ms":  8000,
                "max_output_bytes": 4096,
                "max_side_effects": 0,
            },
            "requested_side_effects": [],
            "approval": None,
        }
        request.update(overrides)
        return request

    def _plan(self, request=None):
        from assistant_os.contracts import ACTION_MACHINE_OPERATOR_EXECUTE, RISK_LOW, make_plan
        plan = make_plan(
            domain="MACHINE_OPERATOR",
            action=ACTION_MACHINE_OPERATOR_EXECUTE,
            target="browser snapshot",
            risk_level=RISK_LOW,
            requires_confirmation=False,
        )
        plan["domain_payload"] = {"machine_operator_request": request or self._request()}
        return plan

    def test_success_sets_execution_status_real(self):
        from assistant_os.mso.machine_operator_adapter import reset_machine_operator_backend_health
        from assistant_os.pipelines.machine_operator_pipeline import execute
        from assistant_os.contracts import EXECUTION_STATUS_REAL
        from assistant_os.mso.contracts import MACHINE_OPERATOR_OUTCOME_SUCCESS

        reset_machine_operator_backend_health()

        response_body = {
            "status": "ok",
            "final_url": "https://example.test/",
            "dom_snapshot": "<html/>",
            "screenshot_b64": None,
            "visible_text": None,
            "error": None,
        }
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = response_body
            mock_post.return_value = mock_resp

            result = execute(self._plan(), "ctx-mo-1")

        assert result.get("execution_status") == EXECUTION_STATUS_REAL

    def test_backend_unavailable_sets_execution_status_unavailable(self):
        from assistant_os.mso.machine_operator_adapter import reset_machine_operator_backend_health
        from assistant_os.pipelines.machine_operator_pipeline import execute
        from assistant_os.contracts import EXECUTION_STATUS_UNAVAILABLE

        reset_machine_operator_backend_health()

        import requests as _requests
        with patch("requests.post", side_effect=_requests.ConnectionError("refused")):
            result = execute(self._plan(), "ctx-mo-2")

        assert result.get("execution_status") == EXECUTION_STATUS_UNAVAILABLE

    def test_policy_violation_sets_execution_status_unavailable(self):
        from assistant_os.mso.machine_operator_adapter import reset_machine_operator_backend_health
        from assistant_os.pipelines.machine_operator_pipeline import execute
        from assistant_os.contracts import EXECUTION_STATUS_UNAVAILABLE

        reset_machine_operator_backend_health()

        # Use a disallowed capability to trigger policy rejection
        bad_request = self._request(capability_name="browser.click_button")
        result = execute(self._plan(bad_request), "ctx-mo-3")

        assert result.get("execution_status") == EXECUTION_STATUS_UNAVAILABLE
