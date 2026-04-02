"""
M2C — Audited CODE Apply Bridge Tests

Validates that the CODE apply path routes EXCLUSIVELY through:
  AuthorizedPlan → RunnerExecutionRequest → RunnerBackedExecutor → RunnerService

Five mandatory scenarios from the M2C dispatch:
  1. confirm → runner executes (happy path)
  2. preview does NOT call RunnerBackedExecutor
  3. no confirm → blocked at orchestrator (EXECUTION_MODE_CONFIRM)
  4. execution_id == plan_id (governance binding)
  5. runner failure → structured error (no silent fallback)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from assistant_os.contracts import (
    determine_execution_mode,
    ACTION_CODE_FIX,
    ACTION_CODE_CREATE,
    RESULT_TYPE_CODE_APPLY,
    RESULT_TYPE_CODE_PREVIEW,
    EXECUTION_MODE_CONFIRM,
    RISK_MEDIUM,
)
from assistant_os.pipelines.code_pipeline import execute as code_execute


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(action: str, text: str = "arregla el bug", payload: dict | None = None) -> dict:
    """Build a raw plan dict matching the shape code_pipeline expects."""
    import uuid
    return {
        "action": action,
        "domain": "CODE",
        "raw_text": text,
        "domain_payload": payload or {},
        "trace_id": "test_trace_m2c",
        "plan_id": str(uuid.uuid4()),
        "risk_level": RISK_MEDIUM,
        "requires_confirmation": True,
    }


def _mock_runner_ok(execution_id: str | None = None) -> MagicMock:
    r = MagicMock()
    r.execution_id = execution_id or "exec-test-m2c"
    r.final_status = "success"
    r.error = None
    r.modified_files = ["src/foo.py"]
    r.report_json_path = None
    r.report_md_path = None
    return r


def _mock_runner_failed(msg: str = "docker daemon unavailable") -> MagicMock:
    r = MagicMock()
    r.execution_id = "exec-failed-m2c"
    r.final_status = "failed"
    r.error = msg
    r.modified_files = []
    r.report_json_path = None
    r.report_md_path = None
    return r


RUNNER_PATCH = "assistant_os.executors.runner_backed_executor.RunnerBackedExecutor"


# ---------------------------------------------------------------------------
# Scenario 1: confirm → runner executes (happy path)
# ---------------------------------------------------------------------------

class TestConfirmRunnerExecutes:
    """After confirmation, apply MUST route through RunnerBackedExecutor."""

    def test_apply_calls_runner_backed_executor(self, tmp_path):
        """RunnerBackedExecutor.execute is called exactly once on apply."""
        import assistant_os.pipelines.code_pipeline as cp
        orig_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            proposal = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={
                    "target_file": "src/foo.py", "workspace": str(tmp_path),
                }),
                "ctx-m2c-1a",
            )["data"]["proposal"]

            apply_plan = _make_plan(ACTION_CODE_FIX, payload={
                "phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
            })

            with patch(RUNNER_PATCH) as MockExec:
                MockExec.return_value.execute.return_value = _mock_runner_ok()
                result = code_execute(apply_plan, "ctx-m2c-1b")

            assert result["ok"], f"apply failed: {result}"
            assert result["result_type"] == RESULT_TYPE_CODE_APPLY
            MockExec.return_value.execute.assert_called_once()
        finally:
            cp._applied_proposals = orig_set

    def test_apply_result_contains_execution_id(self, tmp_path):
        """Successful apply result exposes execution_id from the runner."""
        import assistant_os.pipelines.code_pipeline as cp
        orig_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            proposal = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={
                    "target_file": "src/foo.py", "workspace": str(tmp_path),
                }),
                "ctx-m2c-1c",
            )["data"]["proposal"]

            apply_plan = _make_plan(ACTION_CODE_FIX, payload={
                "phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
            })

            with patch(RUNNER_PATCH) as MockExec:
                MockExec.return_value.execute.return_value = _mock_runner_ok("exec-from-runner")
                result = code_execute(apply_plan, "ctx-m2c-1d")

            assert result["ok"]
            assert "execution_id" in result["data"]
        finally:
            cp._applied_proposals = orig_set

    def test_apply_result_audit_summary_execution_source_runner(self, tmp_path):
        """audit_summary.execution_source must be 'runner' on successful apply."""
        import assistant_os.pipelines.code_pipeline as cp
        orig_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            proposal = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={
                    "target_file": "src/foo.py", "workspace": str(tmp_path),
                }),
                "ctx-m2c-1e",
            )["data"]["proposal"]

            apply_plan = _make_plan(ACTION_CODE_FIX, payload={
                "phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
            })

            with patch(RUNNER_PATCH) as MockExec:
                MockExec.return_value.execute.return_value = _mock_runner_ok()
                result = code_execute(apply_plan, "ctx-m2c-1f")

            assert result["ok"]
            audit = result["data"].get("audit_summary", {})
            assert audit.get("execution_source") == "runner"
        finally:
            cp._applied_proposals = orig_set


# ---------------------------------------------------------------------------
# Scenario 2: preview does NOT call RunnerBackedExecutor
# ---------------------------------------------------------------------------

class TestPreviewDoesNotCallRunner:
    """Preview (phase != 'apply') must never invoke RunnerBackedExecutor."""

    def test_preview_never_calls_runner(self, tmp_path):
        """ProposeChangeTool path — runner is not touched during preview."""
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "target_file": "src/foo.py",
            "workspace": str(tmp_path),
        })

        with patch(RUNNER_PATCH) as MockExec:
            result = code_execute(plan, "ctx-m2c-2a")

        assert result["ok"], f"preview failed: {result}"
        assert result["result_type"] == RESULT_TYPE_CODE_PREVIEW
        MockExec.assert_not_called()

    def test_preview_result_has_no_execution_id(self, tmp_path):
        """Preview result must not carry execution_id (not yet executed)."""
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "target_file": "src/foo.py",
            "workspace": str(tmp_path),
        })
        result = code_execute(plan, "ctx-m2c-2b")
        assert result["ok"]
        assert "execution_id" not in result["data"]

    def test_read_only_explain_never_calls_runner(self):
        """CODE_EXPLAIN is read-only — runner must never be invoked."""
        from assistant_os.contracts import ACTION_CODE_EXPLAIN
        plan = _make_plan(ACTION_CODE_EXPLAIN)

        with patch(RUNNER_PATCH) as MockExec:
            result = code_execute(plan, "ctx-m2c-2c")

        assert result["ok"]
        MockExec.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 3: no confirm → blocked at orchestrator
# ---------------------------------------------------------------------------

class TestNoConfirmBlockedAtOrchestrator:
    """CODE_FIX / CODE_CREATE must require confirmation at the policy level."""

    def test_code_fix_execution_mode_is_confirm(self):
        """determine_execution_mode returns CONFIRM for CODE_FIX with requires_confirmation."""
        mode = determine_execution_mode(
            action=ACTION_CODE_FIX,
            risk_level=RISK_MEDIUM,
            requires_confirmation=True,
        )
        assert mode == EXECUTION_MODE_CONFIRM, (
            f"Expected CONFIRM for CODE_FIX, got {mode!r}"
        )

    def test_code_create_execution_mode_is_confirm(self):
        """determine_execution_mode returns CONFIRM for CODE_CREATE."""
        mode = determine_execution_mode(
            action=ACTION_CODE_CREATE,
            risk_level=RISK_MEDIUM,
            requires_confirmation=True,
        )
        assert mode == EXECUTION_MODE_CONFIRM

    def test_code_fix_preview_result_requires_confirmation(self, tmp_path):
        """CODE_FIX preview result carries requires_confirmation=True."""
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "target_file": "src/foo.py", "workspace": str(tmp_path),
        })
        result = code_execute(plan, "ctx-m2c-3a")
        assert result["ok"]
        assert result["data"].get("requires_confirmation") is True

    def test_apply_blocked_when_proposal_is_empty(self, tmp_path):
        """Apply with empty patch_preview is blocked by NotApplicable pre-gate."""
        apply_plan = _make_plan(ACTION_CODE_FIX, payload={
            "phase": "apply",
            "proposal": {
                "proposal_id": "nonexistent",
                "patch_preview": "",
                "affected_files": ["src/foo.py"],
                "allowed_write_scope": ["src/foo.py"],
                "risk_level": "medium",
                "proposal_artifacts": {"operation_types": ["modify"]},
            },
            "workspace": str(tmp_path),
        })
        result = code_execute(apply_plan, "ctx-m2c-3b")
        assert not result["ok"]
        assert result["error"]["type"] in ("NotApplicable", "ProposalAlreadyApplied")


# ---------------------------------------------------------------------------
# Scenario 4: execution_id == plan_id
# ---------------------------------------------------------------------------

class TestExecutionIdEqualsPlanId:
    """The AuthorizedPlan binds execution_id to plan_id from the kernel plan."""

    def test_authorized_plan_built_with_execution_id_eq_plan_id(self, tmp_path):
        """_build_authorized_plan_from_kernel sets execution_id == plan_id."""
        from assistant_os.pipelines.code_pipeline import _build_authorized_plan_from_kernel
        plan = _make_plan(ACTION_CODE_FIX, payload={"workspace": str(tmp_path)})
        ap = _build_authorized_plan_from_kernel(plan)
        assert ap.execution_id == ap.plan_id == plan["plan_id"]

    def test_runner_execution_request_carries_correct_execution_id(self, tmp_path):
        """RunnerExecutionRequest.execution_id must match AuthorizedPlan.execution_id."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={"workspace": str(tmp_path)})
        proposal = {"proposal_id": "p1", "changes": []}
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, proposal, ap)
        assert req.execution_id == ap.execution_id

    def test_audit_summary_execution_id_equals_plan_id(self, tmp_path):
        """audit_summary in apply result shows execution_id == plan_id."""
        import assistant_os.pipelines.code_pipeline as cp
        orig_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            proposal = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={
                    "target_file": "src/foo.py", "workspace": str(tmp_path),
                }),
                "ctx-m2c-4a",
            )["data"]["proposal"]

            apply_plan = _make_plan(ACTION_CODE_FIX, payload={
                "phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
            })
            plan_id = apply_plan["plan_id"]

            with patch(RUNNER_PATCH) as MockExec:
                MockExec.return_value.execute.return_value = _mock_runner_ok(
                    execution_id=plan_id
                )
                result = code_execute(apply_plan, "ctx-m2c-4b")

            assert result["ok"]
            audit = result["data"]["audit_summary"]
            assert audit["execution_id"] == audit["plan_id"], (
                f"execution_id {audit['execution_id']!r} != plan_id {audit['plan_id']!r}"
            )
        finally:
            cp._applied_proposals = orig_set


# ---------------------------------------------------------------------------
# Scenario 5: runner failure → structured error (no silent fallback)
# ---------------------------------------------------------------------------

class TestRunnerFailureStructuredError:
    """On runner failure the apply result must be a structured error — no fallback."""

    def test_runner_failed_status_returns_structured_error(self, tmp_path):
        """RunnerExecutionResult with final_status='failed' → structured RunnerFailed error."""
        import assistant_os.pipelines.code_pipeline as cp
        orig_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            proposal = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={
                    "target_file": "src/foo.py", "workspace": str(tmp_path),
                }),
                "ctx-m2c-5a",
            )["data"]["proposal"]

            apply_plan = _make_plan(ACTION_CODE_FIX, payload={
                "phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
            })

            with patch(RUNNER_PATCH) as MockExec:
                MockExec.return_value.execute.return_value = _mock_runner_failed(
                    "test suite forced failure"
                )
                result = code_execute(apply_plan, "ctx-m2c-5b")

            assert not result["ok"]
            assert result["error"]["type"] == "RunnerFailed"
            assert result["data"]["audit_summary"]["execution_source"] == "runner"
        finally:
            cp._applied_proposals = orig_set

    def test_runner_exception_returns_structured_error(self, tmp_path):
        """RunnerBackedExecutor.execute raises → structured RunnerException error."""
        import assistant_os.pipelines.code_pipeline as cp
        orig_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            proposal = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={
                    "target_file": "src/foo.py", "workspace": str(tmp_path),
                }),
                "ctx-m2c-5c",
            )["data"]["proposal"]

            apply_plan = _make_plan(ACTION_CODE_FIX, payload={
                "phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
            })

            with patch(RUNNER_PATCH) as MockExec:
                MockExec.return_value.execute.side_effect = RuntimeError("infra down")
                result = code_execute(apply_plan, "ctx-m2c-5d")

            assert not result["ok"]
            assert result["error"]["type"] == "RunnerException"
            assert "infra down" in result["error"]["message"]
        finally:
            cp._applied_proposals = orig_set

    def test_runner_failure_no_fallback_to_apply_change_tool(self, tmp_path):
        """On runner failure, ApplyChangeTool must NOT be imported or called."""
        import assistant_os.pipelines.code_pipeline as cp
        orig_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            proposal = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={
                    "target_file": "src/foo.py", "workspace": str(tmp_path),
                }),
                "ctx-m2c-5e",
            )["data"]["proposal"]

            apply_plan = _make_plan(ACTION_CODE_FIX, payload={
                "phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
            })

            with patch(RUNNER_PATCH) as MockExec:
                MockExec.return_value.execute.side_effect = RuntimeError("infra down")
                with patch(
                    "assistant_os.tools.claude_code.apply_change_tool.ApplyChangeTool"
                ) as MockApply:
                    result = code_execute(apply_plan, "ctx-m2c-5f")

            MockApply.assert_not_called()
            assert not result["ok"]
        finally:
            cp._applied_proposals = orig_set

    def test_runner_failure_exposes_audit_summary(self, tmp_path):
        """Even on runner failure, audit_summary with governance fields is present."""
        import assistant_os.pipelines.code_pipeline as cp
        orig_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            proposal = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={
                    "target_file": "src/foo.py", "workspace": str(tmp_path),
                }),
                "ctx-m2c-5g",
            )["data"]["proposal"]

            apply_plan = _make_plan(ACTION_CODE_FIX, payload={
                "phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
            })

            with patch(RUNNER_PATCH) as MockExec:
                MockExec.return_value.execute.return_value = _mock_runner_failed()
                result = code_execute(apply_plan, "ctx-m2c-5h")

            assert not result["ok"]
            audit = result["data"].get("audit_summary")
            assert audit is not None, "audit_summary missing on failure result"
            for key in ("action", "execution_source", "execution_id",
                        "plan_id", "policy_id", "capability_scope"):
                assert key in audit, f"audit_summary missing key {key!r} on failure"
        finally:
            cp._applied_proposals = orig_set
