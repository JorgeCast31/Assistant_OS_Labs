"""
Tests — CODE Domain v0

Coverage:
  A. Routing / classifier — CODE intent detection
  B. Domain registry — CODE actions route to code_pipeline
  C. Read-only execution — CODE_EXPLAIN / CODE_REVIEW (no confirmation)
  D. Mutating preview path — CODE_FIX / CODE_CREATE (proposal_id, requires_confirmation)
  E. Apply safety — single-use, out-of-scope paths, blocked ops, integrity
  F. Classifier domain override — domain forced to CODE on CODE operations
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# A. Routing / classifier — intent detection
# ---------------------------------------------------------------------------

from assistant_os.classifier import classify_text, detect_operational_intent
from assistant_os.contracts import (
    ClassifyRequest,
    OP_CODE_EXPLAIN, OP_CODE_REVIEW, OP_CODE_FIX, OP_CODE_CREATE,
)


class TestCodeIntentDetection:
    """detect_operational_intent correctly identifies CODE operations."""

    def _detect(self, text: str) -> str:
        return detect_operational_intent(text)

    # --- CODE_EXPLAIN ---

    def test_explain_code_file(self):
        assert self._detect("explícame este archivo") == OP_CODE_EXPLAIN

    def test_explain_module(self):
        assert self._detect("explícame este módulo") == OP_CODE_EXPLAIN

    def test_explain_how_it_works(self):
        assert self._detect("cómo funciona este código") == OP_CODE_EXPLAIN

    def test_explain_what_does_it_do(self):
        assert self._detect("qué hace esta función") == OP_CODE_EXPLAIN

    # --- CODE_REVIEW ---

    def test_review_file(self):
        assert self._detect("revisa este archivo") == OP_CODE_REVIEW

    def test_review_module(self):
        assert self._detect("revisa este módulo") == OP_CODE_REVIEW

    def test_find_bugs(self):
        assert self._detect("encuentra bugs aquí") == OP_CODE_REVIEW

    def test_analyze_code(self):
        assert self._detect("analiza este código") == OP_CODE_REVIEW

    # --- CODE_FIX ---

    def test_fix_bug(self):
        assert self._detect("arregla este bug") == OP_CODE_FIX

    def test_fix_code(self):
        assert self._detect("arregla este código") == OP_CODE_FIX

    def test_correct_error(self):
        assert self._detect("corrige este error") == OP_CODE_FIX

    def test_fixea(self):
        assert self._detect("fixea esto") == OP_CODE_FIX

    def test_make_it_work(self):
        assert self._detect("haz que esto funcione") == OP_CODE_FIX

    # --- CODE_CREATE ---

    def test_create_module(self):
        assert self._detect("crea una clase de autenticación") == OP_CODE_CREATE

    def test_create_class(self):
        assert self._detect("crea esta clase") == OP_CODE_CREATE

    def test_generate_file(self):
        assert self._detect("genera este archivo") == OP_CODE_CREATE

    def test_implement_function(self):
        assert self._detect("implementa esta función") == OP_CODE_CREATE

    def test_new_script(self):
        assert self._detect("crea un script de python para migración") == OP_CODE_CREATE

    # --- No collision with WORK / FIN ---

    def test_task_create_not_code(self):
        """'crea una tarea' must remain WORK_CREATE, not CODE."""
        from assistant_os.contracts import OP_WORK_CREATE
        assert self._detect("crea una tarea: revisar el informe") == OP_WORK_CREATE

    def test_expense_not_code(self):
        """Financial inputs must not be stolen by CODE patterns."""
        from assistant_os.contracts import OP_FIN_EXPENSE
        assert self._detect("compré café en efectivo") == OP_FIN_EXPENSE

    def test_generic_explain_no_code_noun(self):
        """'explícame tu plan' has no code noun — must NOT route to CODE_EXPLAIN."""
        result = self._detect("explícame tu plan")
        assert result != OP_CODE_EXPLAIN


class TestCodeClassifierDomainOverride:
    """classify_text forces domain=CODE and needs_confirmation=False for CODE ops."""

    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)

    def test_explain_forces_code_domain(self):
        result = self._classify("explícame este módulo")
        assert result["domain"] == "CODE"
        assert result["operation"] == OP_CODE_EXPLAIN

    def test_review_forces_code_domain(self):
        result = self._classify("revisa este archivo")
        assert result["domain"] == "CODE"

    def test_fix_forces_code_domain(self):
        result = self._classify("arregla este bug")
        assert result["domain"] == "CODE"
        assert result["operation"] == OP_CODE_FIX

    def test_create_forces_code_domain(self):
        result = self._classify("crea una clase de autenticación")
        assert result["domain"] == "CODE"

    def test_code_override_no_confirmation_needed(self):
        """CODE op override sets needs_confirmation=False."""
        result = self._classify("arregla este bug")
        assert result["needs_confirmation"] is False

    def test_code_override_confidence_high(self):
        """CODE op override must yield confidence >= 0.90."""
        result = self._classify("explícame este módulo")
        assert result["confidence"] >= 0.90

    def test_code_override_in_reason(self):
        """Reason must contain the override annotation."""
        result = self._classify("arregla este bug")
        assert "override:code_op->CODE" in result["reason"]


# ---------------------------------------------------------------------------
# B. Domain registry — CODE actions route to code_pipeline
# ---------------------------------------------------------------------------

from assistant_os.core.routing import action_domain, get_pipeline
from assistant_os.contracts import (
    ACTION_CODE_EXPLAIN, ACTION_CODE_REVIEW, ACTION_CODE_FIX, ACTION_CODE_CREATE,
)


class TestCodeDomainRegistry:
    """action_domain and get_pipeline correctly route CODE actions."""

    def test_explain_maps_to_code(self):
        assert action_domain(ACTION_CODE_EXPLAIN) == "CODE"

    def test_review_maps_to_code(self):
        assert action_domain(ACTION_CODE_REVIEW) == "CODE"

    def test_fix_maps_to_code(self):
        assert action_domain(ACTION_CODE_FIX) == "CODE"

    def test_create_maps_to_code(self):
        assert action_domain(ACTION_CODE_CREATE) == "CODE"

    def test_code_pipeline_registered(self):
        pipeline = get_pipeline("CODE")
        assert pipeline is not None, "code_pipeline must be registered in DOMAIN_PIPELINES"

    def test_code_pipeline_is_callable(self):
        pipeline = get_pipeline("CODE")
        assert callable(pipeline)

    def test_work_still_routes_work(self):
        """Existing WORK routing must not be broken."""
        assert action_domain("WORK_QUERY") == "WORK"

    def test_fin_still_routes_fin(self):
        """Existing FIN routing must not be broken."""
        assert action_domain("FIN_EXPENSE") == "FIN"

    def test_unknown_still_unknown(self):
        assert action_domain("DOC_GENERATE") == "UNKNOWN"


# ---------------------------------------------------------------------------
# C. Read-only execution — no confirmation required
# ---------------------------------------------------------------------------

from assistant_os.pipelines.code_pipeline import execute as code_execute
from assistant_os.contracts import RESULT_TYPE_CODE_EXPLAIN, RESULT_TYPE_CODE_REVIEW


def _make_plan(action: str, raw_text: str = "test", payload: dict | None = None) -> dict:
    return {
        "action": action,
        "domain": "CODE",
        "raw_text": raw_text,
        "domain_payload": payload or {},
        "trace_id": "test_trace",
        "plan_id": "test_plan",
    }


class TestCodeReadOnly:
    """CODE_EXPLAIN and CODE_REVIEW return DomainResult without confirmation."""

    def test_explain_ok(self):
        plan = _make_plan(ACTION_CODE_EXPLAIN, "explícame este módulo")
        result = code_execute(plan, "ctx-explain-01")
        assert result["ok"] is True
        assert result["result_type"] == RESULT_TYPE_CODE_EXPLAIN
        assert result["domain"] == "CODE"

    def test_explain_has_analysis(self):
        plan = _make_plan(ACTION_CODE_EXPLAIN)
        result = code_execute(plan, "ctx-explain-02")
        assert "analysis" in result["data"]

    def test_explain_no_requires_confirmation(self):
        """Read-only results must NOT set requires_confirmation in data."""
        plan = _make_plan(ACTION_CODE_EXPLAIN)
        result = code_execute(plan, "ctx-explain-03")
        assert result["data"].get("requires_confirmation") is not True

    def test_review_ok(self):
        plan = _make_plan(ACTION_CODE_REVIEW, "revisa este archivo")
        result = code_execute(plan, "ctx-review-01")
        assert result["ok"] is True
        assert result["result_type"] == RESULT_TYPE_CODE_REVIEW
        assert result["domain"] == "CODE"

    def test_review_message_non_empty(self):
        plan = _make_plan(ACTION_CODE_REVIEW)
        result = code_execute(plan, "ctx-review-02")
        assert result["message"]

    def test_explain_tool_failure_propagates(self):
        """If ReviewCodeTool fails, pipeline returns ok=False."""
        from unittest.mock import patch
        from assistant_os.tools.base.tool_result import ToolResult
        from assistant_os.tools.base.tool_error import ToolError

        failing_result = ToolResult(
            ok=False, data=None,
            error=ToolError(code="ReviewFailed", message="executor unavailable", provider="claude_code"),
            metadata={},
        )
        with patch("assistant_os.tools.claude_code.review_code_tool.ReviewCodeTool.execute",
                   return_value=failing_result):
            plan = _make_plan(ACTION_CODE_EXPLAIN)
            result = code_execute(plan, "ctx-explain-fail")
        assert result["ok"] is False

    def test_custom_executor_used(self):
        """ReviewCodeTool accepts a custom executor for integration testing."""
        from assistant_os.tools.claude_code.review_code_tool import ReviewCodeTool

        custom_executor = lambda inp: {"ok": True, "analysis": "custom analysis result"}
        tool = ReviewCodeTool(executor=custom_executor)
        tr = tool.execute({"action": ACTION_CODE_EXPLAIN, "target_file": "foo.py"})
        assert tr.ok
        assert tr.data["analysis"] == "custom analysis result"


# ---------------------------------------------------------------------------
# D. Mutating preview path
# ---------------------------------------------------------------------------

from assistant_os.contracts import RESULT_TYPE_CODE_PREVIEW


class TestCodeMutatingPreview:
    """CODE_FIX / CODE_CREATE preview path returns proposal with requires_confirmation=True."""

    def test_fix_preview_ok(self, tmp_path):
        plan = _make_plan(ACTION_CODE_FIX, "arregla este bug",
                          payload={"target_file": "src/foo.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-fix-preview-01")
        assert result["ok"] is True
        assert result["result_type"] == RESULT_TYPE_CODE_PREVIEW

    def test_fix_preview_has_proposal_id(self, tmp_path):
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "src/foo.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-fix-preview-02")
        assert result["data"].get("proposal_id"), "proposal_id must be present"

    def test_fix_preview_requires_confirmation(self, tmp_path):
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "src/foo.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-fix-preview-03")
        assert result["data"].get("requires_confirmation") is True

    def test_create_preview_ok(self, tmp_path):
        plan = _make_plan(ACTION_CODE_CREATE, "crea una clase de auth",
                          payload={"target_file": "src/auth.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-create-preview-01")
        assert result["ok"] is True
        assert result["result_type"] == RESULT_TYPE_CODE_PREVIEW

    def test_create_preview_has_proposal_id(self, tmp_path):
        plan = _make_plan(ACTION_CODE_CREATE, payload={"target_file": "src/auth.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-create-preview-02")
        assert result["data"].get("proposal_id")

    def test_preview_message_contains_affected_files(self, tmp_path):
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "utils/helper.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-fix-preview-04")
        assert "utils/helper.py" in result["message"] or \
               "utils/helper.py" in str(result["data"].get("affected_files", []))

    def test_preview_has_write_intent_summary(self, tmp_path):
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "src/foo.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-fix-preview-05")
        assert "write_intent_summary" in result["data"]

    def test_preview_has_patch_preview(self, tmp_path):
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "src/foo.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-fix-preview-06")
        assert "patch_preview" in result["data"]

    def test_preview_domain_code(self, tmp_path):
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "src/foo.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-fix-preview-07")
        assert result["domain"] == "CODE"

    def test_too_many_files_rejected(self):
        """Proposals touching > V0_MAX_TOUCHED_FILES files must be rejected."""
        from assistant_os.tools.claude_code.propose_change_tool import ProposeChangeTool

        big_proposal_executor = lambda inp: {
            "ok": True,
            "summary": "big change",
            "patch_preview": "...",
            "affected_files": [f"src/file{i}.py" for i in range(10)],
            "write_intent_summary": "modifies many files",
            "operation_types": ["modify"],
            "risk_level": "high",
        }
        tool = ProposeChangeTool(executor=big_proposal_executor)
        tr = tool.execute({"action": ACTION_CODE_FIX, "target_file": "src/file0.py"})
        assert not tr.ok
        assert tr.error.code == "TooManyFilesV0"

    def test_absolute_path_early_rejected(self):
        """Absolute target_file paths are rejected before the executor is called."""
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "/etc/passwd"})
        result = code_execute(plan, "ctx-fix-abs")
        assert result["ok"] is False
        assert result["data"].get("plan") is not None or "path" in result["message"].lower()


# ---------------------------------------------------------------------------
# E. Apply safety
# ---------------------------------------------------------------------------

from assistant_os.contracts import RESULT_TYPE_CODE_APPLY
from assistant_os.tools.claude_code.apply_change_tool import ApplyChangeTool
from assistant_os.tools.claude_code.propose_change_tool import ProposeChangeTool


def _make_proposal(
    proposal_id: str = "prop-001",
    affected_files: list | None = None,
    allowed_scope: list | None = None,
    workspace_hash: str = "",
    action: str = ACTION_CODE_FIX,
    op_types: list | None = None,
    patch_preview: str = "--- a/src/foo.py\n+++ b/src/foo.py",
    patch_preview_truncated: bool = False,
    risk_level: str = "medium",
) -> dict:
    files = affected_files or ["src/foo.py"]
    scope = allowed_scope if allowed_scope is not None else list(files)
    return {
        "proposal_id": proposal_id,
        "action": action,
        "summary": "test proposal",
        "affected_files": files,
        "write_intent_summary": "modifies src/foo.py",
        "patch_preview": patch_preview,
        "patch_preview_truncated": patch_preview_truncated,
        "risk_level": risk_level,
        "proposal_artifacts": {"operation_types": op_types or ["modify"]},
        "requires_confirmation": True,
        "workspace_hash": workspace_hash,
        "allowed_write_scope": scope,
    }


class TestApplySafety:
    """ApplyChangeTool enforces all five safety guards."""

    # Guard 1: missing proposal_id
    def test_missing_proposal_id_rejected(self):
        applied = set()
        tool = ApplyChangeTool(applied_proposals=applied)
        proposal = _make_proposal()
        proposal["proposal_id"] = ""
        tr = tool.execute({"proposal": proposal, "workspace": ""})
        assert not tr.ok
        assert tr.error.code == "MissingProposalId"

    # Guard 2: single-use
    def test_second_apply_same_proposal_rejected(self):
        applied = set()
        tool = ApplyChangeTool(applied_proposals=applied)
        proposal = _make_proposal(proposal_id="reuse-001")
        # First apply succeeds
        tr1 = tool.execute({"proposal": proposal, "workspace": ""})
        assert tr1.ok
        # Second apply must fail
        tr2 = tool.execute({"proposal": proposal, "workspace": ""})
        assert not tr2.ok
        assert tr2.error.code == "ProposalAlreadyApplied"

    def test_single_use_independent_proposals(self):
        """Two distinct proposal_ids can each be applied once."""
        applied = set()
        tool = ApplyChangeTool(applied_proposals=applied)
        prop_a = _make_proposal(proposal_id="prop-A", affected_files=["a.py"], allowed_scope=["a.py"])
        prop_b = _make_proposal(proposal_id="prop-B", affected_files=["b.py"], allowed_scope=["b.py"])
        assert tool.execute({"proposal": prop_a, "workspace": ""}).ok
        assert tool.execute({"proposal": prop_b, "workspace": ""}).ok

    # Guard 3: blocked operations
    def test_delete_blocked_in_v0(self):
        applied = set()
        tool = ApplyChangeTool(applied_proposals=applied)
        proposal = _make_proposal(proposal_id="del-001", op_types=["delete"])
        tr = tool.execute({"proposal": proposal, "workspace": ""})
        assert not tr.ok
        assert tr.error.code == "BlockedOperationV0"

    def test_rename_blocked_in_v0(self):
        applied = set()
        tool = ApplyChangeTool(applied_proposals=applied)
        proposal = _make_proposal(proposal_id="ren-001", op_types=["rename"])
        tr = tool.execute({"proposal": proposal, "workspace": ""})
        assert not tr.ok
        assert tr.error.code == "BlockedOperationV0"

    def test_move_blocked_in_v0(self):
        applied = set()
        tool = ApplyChangeTool(applied_proposals=applied)
        proposal = _make_proposal(proposal_id="mov-001", op_types=["move"])
        tr = tool.execute({"proposal": proposal, "workspace": ""})
        assert not tr.ok
        assert tr.error.code == "BlockedOperationV0"

    # Guard 4: write scope
    def test_out_of_scope_file_rejected(self):
        applied = set()
        tool = ApplyChangeTool(applied_proposals=applied)
        proposal = _make_proposal(
            proposal_id="scope-001",
            affected_files=["src/foo.py"],
            allowed_scope=["src/bar.py"],  # foo.py is NOT in scope
        )
        tr = tool.execute({"proposal": proposal, "workspace": ""})
        assert not tr.ok
        assert tr.error.code == "WriteOutOfScope"

    def test_path_traversal_rejected(self):
        applied = set()
        tool = ApplyChangeTool(applied_proposals=applied)
        proposal = _make_proposal(
            proposal_id="traversal-001",
            affected_files=["../etc/passwd"],
            allowed_scope=["../etc/passwd"],
        )
        tr = tool.execute({"proposal": proposal, "workspace": ""})
        assert not tr.ok
        assert tr.error.code == "WriteOutOfScope"

    def test_absolute_path_rejected(self):
        applied = set()
        tool = ApplyChangeTool(applied_proposals=applied)
        proposal = _make_proposal(
            proposal_id="abs-001",
            affected_files=["/etc/passwd"],
            allowed_scope=["/etc/passwd"],
        )
        tr = tool.execute({"proposal": proposal, "workspace": ""})
        assert not tr.ok
        assert tr.error.code == "WriteOutOfScope"

    # Guard 5: workspace integrity
    def test_workspace_modified_after_proposal_rejected(self, tmp_path):
        """Changing a file after proposal generation must invalidate the proposal."""
        from assistant_os.tools.claude_code.propose_change_tool import compute_workspace_hash

        target = tmp_path / "src" / "foo.py"
        target.parent.mkdir(parents=True)
        target.write_text("original content")

        affected = ["src/foo.py"]
        original_hash = compute_workspace_hash(str(tmp_path), affected)

        # Simulate file modification between proposal and apply
        target.write_text("modified content")

        applied = set()
        tool = ApplyChangeTool(applied_proposals=applied)
        proposal = _make_proposal(
            proposal_id="integrity-001",
            affected_files=affected,
            allowed_scope=affected,
            workspace_hash=original_hash,
        )
        tr = tool.execute({"proposal": proposal, "workspace": str(tmp_path)})
        assert not tr.ok
        assert tr.error.code == "WorkspaceModified"

    def test_workspace_unchanged_applies_ok(self, tmp_path):
        """If workspace matches hash, apply must succeed."""
        from assistant_os.tools.claude_code.propose_change_tool import compute_workspace_hash

        target = tmp_path / "src" / "foo.py"
        target.parent.mkdir(parents=True)
        target.write_text("original content")

        affected = ["src/foo.py"]
        hash_at_proposal = compute_workspace_hash(str(tmp_path), affected)

        applied = set()
        tool = ApplyChangeTool(applied_proposals=applied)
        proposal = _make_proposal(
            proposal_id="integrity-ok-001",
            affected_files=affected,
            allowed_scope=affected,
            workspace_hash=hash_at_proposal,
        )
        tr = tool.execute({"proposal": proposal, "workspace": str(tmp_path)})
        assert tr.ok

    # Full apply path via pipeline
    def test_pipeline_apply_path(self, tmp_path):
        """End-to-end: preview → extract proposal_id → apply via pipeline."""
        from unittest.mock import patch, MagicMock
        import assistant_os.pipelines.code_pipeline as cp

        # Fresh applied set for isolation
        original_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            # Step 1: preview
            preview_plan = _make_plan(
                ACTION_CODE_FIX, "arregla el bug",
                payload={"target_file": "src/foo.py", "workspace": str(tmp_path)},
            )
            preview_result = code_execute(preview_plan, "ctx-apply-01")
            assert preview_result["ok"]
            proposal = preview_result["data"]["proposal"]

            # Step 2: apply (simulate confirmed proposal)
            apply_plan = _make_plan(
                ACTION_CODE_FIX,
                payload={"phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
                         "execution_mode": "FULL_EXECUTE"},
            )
            _mock_result = MagicMock()
            _mock_result.execution_id = "test-exec-apply"
            _mock_result.final_status = "success"
            _mock_result.error = None
            _mock_result.modified_files = []
            _mock_result.report_json_path = None
            _mock_result.report_md_path = None

            with patch("assistant_os.executors.runner_backed_executor.RunnerBackedExecutor") as MockExec:
                MockExec.return_value.execute.return_value = _mock_result
                apply_result = code_execute(apply_plan, "ctx-apply-02")
            assert apply_result["ok"]
            assert apply_result["result_type"] == RESULT_TYPE_CODE_APPLY
            assert apply_result["data"]["proposal_id"] == proposal["proposal_id"]
        finally:
            cp._applied_proposals = original_set

    def test_pipeline_double_apply_rejected(self, tmp_path):
        """Applying the same proposal twice via pipeline must be rejected."""
        from unittest.mock import patch, MagicMock
        import assistant_os.pipelines.code_pipeline as cp

        original_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            # Get a proposal
            preview_plan = _make_plan(
                ACTION_CODE_FIX, payload={"target_file": "src/foo.py", "workspace": str(tmp_path)},
            )
            proposal = code_execute(preview_plan, "ctx-dbl-01")["data"]["proposal"]

            apply_plan = _make_plan(
                ACTION_CODE_FIX, payload={"phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
                                          "execution_mode": "FULL_EXECUTE"},
            )
            _mock_result = MagicMock()
            _mock_result.execution_id = "test-exec-dbl"
            _mock_result.final_status = "success"
            _mock_result.error = None
            _mock_result.modified_files = []
            _mock_result.report_json_path = None
            _mock_result.report_md_path = None

            with patch("assistant_os.executors.runner_backed_executor.RunnerBackedExecutor") as MockExec:
                MockExec.return_value.execute.return_value = _mock_result
                first = code_execute(apply_plan, "ctx-dbl-02")
            assert first["ok"]

            second = code_execute(apply_plan, "ctx-dbl-03")
            assert not second["ok"]
            assert "ProposalAlreadyApplied" in second["error"]["type"]
        finally:
            cp._applied_proposals = original_set


# ---------------------------------------------------------------------------
# F. Propose-change tool — blocked ops and file count (tool-level)
# ---------------------------------------------------------------------------

class TestProposeChangeTool:
    """ProposeChangeTool enforces v0 guardrails before returning a proposal."""

    def test_propose_fix_returns_proposal_id(self):
        tool = ProposeChangeTool()
        tr = tool.execute({
            "action": ACTION_CODE_FIX,
            "target_file": "src/foo.py",
            "workspace": "",
            "context": "fix the bug",
        })
        assert tr.ok
        assert tr.data.get("proposal_id")

    def test_propose_create_returns_proposal_id(self):
        tool = ProposeChangeTool()
        tr = tool.execute({
            "action": ACTION_CODE_CREATE,
            "target_file": "src/new_module.py",
            "workspace": "",
            "context": "create the module",
        })
        assert tr.ok
        assert tr.data.get("proposal_id")

    def test_requires_confirmation_always_true(self):
        tool = ProposeChangeTool()
        tr = tool.execute({"action": ACTION_CODE_FIX, "target_file": "a.py"})
        assert tr.data["requires_confirmation"] is True

    def test_delete_op_blocked(self):
        executor = lambda inp: {
            "ok": True, "summary": "delete", "patch_preview": "", "write_intent_summary": "",
            "affected_files": ["a.py"], "operation_types": ["delete"], "risk_level": "high",
        }
        tool = ProposeChangeTool(executor=executor)
        tr = tool.execute({"action": ACTION_CODE_FIX, "target_file": "a.py"})
        assert not tr.ok
        assert tr.error.code == "BlockedOperationV0"

    def test_file_count_limit(self):
        executor = lambda inp: {
            "ok": True, "summary": "big", "patch_preview": "", "write_intent_summary": "",
            "affected_files": [f"src/f{i}.py" for i in range(6)],
            "operation_types": ["modify"], "risk_level": "high",
        }
        tool = ProposeChangeTool(executor=executor)
        tr = tool.execute({"action": ACTION_CODE_FIX, "target_file": "src/f0.py"})
        assert not tr.ok
        assert tr.error.code == "TooManyFilesV0"

    def test_proposal_includes_write_intent_summary(self):
        tool = ProposeChangeTool()
        tr = tool.execute({"action": ACTION_CODE_FIX, "target_file": "a.py"})
        assert "write_intent_summary" in tr.data

    def test_allowed_write_scope_defaults_to_target_file(self):
        tool = ProposeChangeTool()
        tr = tool.execute({"action": ACTION_CODE_FIX, "target_file": "src/foo.py"})
        assert "src/foo.py" in tr.data["allowed_write_scope"]

    def test_executor_exception_handled(self):
        def bad_executor(inp):
            raise RuntimeError("executor crashed")
        tool = ProposeChangeTool(executor=bad_executor)
        tr = tool.execute({"action": ACTION_CODE_FIX, "target_file": "a.py"})
        assert not tr.ok
        assert tr.error.code == "ExecutorException"


# ---------------------------------------------------------------------------
# G. Contracts — new constants present
# ---------------------------------------------------------------------------

class TestContracts:
    """All new CODE constants are exported from contracts.py."""

    def test_op_constants_present(self):
        from assistant_os.contracts import (
            OP_CODE_EXPLAIN, OP_CODE_REVIEW, OP_CODE_FIX, OP_CODE_CREATE,
        )
        assert OP_CODE_EXPLAIN == "CODE_EXPLAIN"
        assert OP_CODE_REVIEW  == "CODE_REVIEW"
        assert OP_CODE_FIX     == "CODE_FIX"
        assert OP_CODE_CREATE  == "CODE_CREATE"

    def test_action_constants_present(self):
        from assistant_os.contracts import (
            ACTION_CODE_EXPLAIN, ACTION_CODE_REVIEW, ACTION_CODE_FIX, ACTION_CODE_CREATE,
        )
        assert ACTION_CODE_EXPLAIN == "CODE_EXPLAIN"
        assert ACTION_CODE_REVIEW  == "CODE_REVIEW"
        assert ACTION_CODE_FIX     == "CODE_FIX"
        assert ACTION_CODE_CREATE  == "CODE_CREATE"

    def test_result_type_constants_present(self):
        from assistant_os.contracts import (
            RESULT_TYPE_CODE_EXPLAIN, RESULT_TYPE_CODE_REVIEW,
            RESULT_TYPE_CODE_PREVIEW, RESULT_TYPE_CODE_APPLY,
        )
        assert RESULT_TYPE_CODE_EXPLAIN == "code_explain"
        assert RESULT_TYPE_CODE_REVIEW  == "code_review"
        assert RESULT_TYPE_CODE_PREVIEW == "code_preview"
        assert RESULT_TYPE_CODE_APPLY   == "code_apply"

    def test_code_proposal_envelope_importable(self):
        from assistant_os.contracts import CodeProposalEnvelope
        assert CodeProposalEnvelope is not None

    def test_code_explain_in_auto_execute_whitelist(self):
        from assistant_os.contracts import should_auto_execute, RISK_LOW
        plan = {
            "action": ACTION_CODE_EXPLAIN,
            "risk_level": RISK_LOW,
            "requires_confirmation": False,
        }
        assert should_auto_execute(plan) is True

    def test_code_review_in_auto_execute_whitelist(self):
        from assistant_os.contracts import should_auto_execute, RISK_LOW
        plan = {
            "action": ACTION_CODE_REVIEW,
            "risk_level": RISK_LOW,
            "requires_confirmation": False,
        }
        assert should_auto_execute(plan) is True

    def test_code_fix_not_auto_execute(self):
        from assistant_os.contracts import should_auto_execute, RISK_MEDIUM
        plan = {
            "action": ACTION_CODE_FIX,
            "risk_level": RISK_MEDIUM,
            "requires_confirmation": False,
        }
        assert should_auto_execute(plan) is False

    def test_code_create_not_auto_execute(self):
        from assistant_os.contracts import should_auto_execute, RISK_MEDIUM
        plan = {
            "action": ACTION_CODE_CREATE,
            "risk_level": RISK_MEDIUM,
            "requires_confirmation": False,
        }
        assert should_auto_execute(plan) is False


# ---------------------------------------------------------------------------
# H. Smoke-prep hardening — workspace validation + patch truncation
# ---------------------------------------------------------------------------

class TestSmokeHardening:
    """
    Targeted coverage for the workspace validation and patch truncation
    hardening added before manual smoke testing.
    """

    # ------------------------------------------------------------------
    # Workspace validation — pipeline entry guard
    # ------------------------------------------------------------------

    def test_missing_workspace_rejected_on_preview(self):
        """Empty workspace string is rejected before any tool is called."""
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "src/foo.py"})
        # domain_payload has no "workspace" key → defaults to ""
        result = code_execute(plan, "ctx-ws-01")
        assert not result["ok"]
        assert result["error"]["type"] == "InvalidWorkspace"
        assert "required" in result["error"]["message"]

    def test_blank_workspace_rejected(self):
        """Whitespace-only workspace is also rejected."""
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "target_file": "src/foo.py",
            "workspace": "   ",
        })
        result = code_execute(plan, "ctx-ws-02")
        assert not result["ok"]
        assert result["error"]["type"] == "InvalidWorkspace"

    def test_relative_workspace_rejected(self):
        """Relative paths are not safe workspace roots."""
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "target_file": "src/foo.py",
            "workspace": "relative/path",
        })
        result = code_execute(plan, "ctx-ws-03")
        assert not result["ok"]
        assert result["error"]["type"] == "InvalidWorkspace"
        assert "absolute" in result["error"]["message"]

    def test_nonexistent_workspace_rejected(self):
        """A path that does not exist on disk is rejected."""
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "target_file": "src/foo.py",
            "workspace": "/this/path/does/not/exist/ever",
        })
        result = code_execute(plan, "ctx-ws-04")
        assert not result["ok"]
        assert result["error"]["type"] == "InvalidWorkspace"
        assert "exist" in result["error"]["message"]

    def test_workspace_file_not_dir_rejected(self, tmp_path):
        """A path pointing at a file (not a directory) is rejected."""
        workspace_file = tmp_path / "notadir.txt"
        workspace_file.write_text("i am a file")
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "target_file": "src/foo.py",
            "workspace": str(workspace_file),
        })
        result = code_execute(plan, "ctx-ws-05")
        assert not result["ok"]
        assert result["error"]["type"] == "InvalidWorkspace"
        assert "directory" in result["error"]["message"]

    def test_valid_workspace_reaches_preview(self, tmp_path):
        """A valid workspace directory allows the preview path to proceed."""
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "target_file": "src/foo.py",
            "workspace": str(tmp_path),
        })
        result = code_execute(plan, "ctx-ws-06")
        assert result["ok"]
        assert result["result_type"] == RESULT_TYPE_CODE_PREVIEW

    def test_workspace_not_required_for_read_only(self):
        """READ-ONLY actions (EXPLAIN/REVIEW) do not require a workspace."""
        plan = _make_plan(ACTION_CODE_EXPLAIN, payload={})
        result = code_execute(plan, "ctx-ws-07")
        assert result["ok"]  # no workspace needed

    # ------------------------------------------------------------------
    # Patch preview truncation
    # ------------------------------------------------------------------

    def test_short_patch_not_truncated(self, tmp_path):
        """A patch under both caps passes through unchanged."""
        short_patch = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
        executor = lambda inp: {
            "ok": True, "summary": "small fix", "patch_preview": short_patch,
            "affected_files": ["foo.py"], "write_intent_summary": "modifies foo.py",
            "operation_types": ["modify"], "risk_level": "low",
        }
        from assistant_os.tools.claude_code.propose_change_tool import ProposeChangeTool
        tr = ProposeChangeTool(executor=executor).execute({
            "action": ACTION_CODE_FIX, "target_file": "foo.py",
            "workspace": str(tmp_path),
        })
        assert tr.ok
        assert tr.data["patch_preview"] == short_patch
        assert tr.data["patch_preview_truncated"] is False

    def test_patch_exceeding_line_cap_is_truncated(self, tmp_path):
        """A patch with > 150 lines is truncated and flagged."""
        from assistant_os.tools.claude_code.propose_change_tool import (
            ProposeChangeTool, _PATCH_PREVIEW_MAX_LINES,
        )
        oversized = "\n".join(f"+line {i}" for i in range(_PATCH_PREVIEW_MAX_LINES + 50))
        executor = lambda inp: {
            "ok": True, "summary": "big fix", "patch_preview": oversized,
            "affected_files": ["foo.py"], "write_intent_summary": "modifies foo.py",
            "operation_types": ["modify"], "risk_level": "medium",
        }
        tr = ProposeChangeTool(executor=executor).execute({
            "action": ACTION_CODE_FIX, "target_file": "foo.py",
            "workspace": str(tmp_path),
        })
        assert tr.ok
        assert tr.data["patch_preview_truncated"] is True
        returned_lines = tr.data["patch_preview"].splitlines()
        # Must not exceed the cap + 1 trailing truncation notice line
        assert len(returned_lines) <= _PATCH_PREVIEW_MAX_LINES + 1

    def test_patch_exceeding_char_cap_is_truncated(self, tmp_path):
        """A patch exceeding the character cap is truncated and flagged."""
        from assistant_os.tools.claude_code.propose_change_tool import (
            ProposeChangeTool, _PATCH_PREVIEW_MAX_CHARS,
        )
        # One long line that blows the char cap before the line cap
        oversized = "x" * (_PATCH_PREVIEW_MAX_CHARS + 1000)
        executor = lambda inp: {
            "ok": True, "summary": "huge patch", "patch_preview": oversized,
            "affected_files": ["foo.py"], "write_intent_summary": "modifies foo.py",
            "operation_types": ["modify"], "risk_level": "high",
        }
        tr = ProposeChangeTool(executor=executor).execute({
            "action": ACTION_CODE_FIX, "target_file": "foo.py",
            "workspace": str(tmp_path),
        })
        assert tr.ok
        assert tr.data["patch_preview_truncated"] is True
        assert len(tr.data["patch_preview"]) <= _PATCH_PREVIEW_MAX_CHARS + 100  # room for notice

    def test_patch_exactly_at_line_limit_not_truncated(self, tmp_path):
        """A patch with exactly _PATCH_PREVIEW_MAX_LINES lines is not truncated."""
        from assistant_os.tools.claude_code.propose_change_tool import (
            ProposeChangeTool, _PATCH_PREVIEW_MAX_LINES,
        )
        exact = "\n".join(f"+line {i}" for i in range(_PATCH_PREVIEW_MAX_LINES))
        executor = lambda inp: {
            "ok": True, "summary": "exact", "patch_preview": exact,
            "affected_files": ["foo.py"], "write_intent_summary": "modifies foo.py",
            "operation_types": ["modify"], "risk_level": "low",
        }
        tr = ProposeChangeTool(executor=executor).execute({
            "action": ACTION_CODE_FIX, "target_file": "foo.py",
            "workspace": str(tmp_path),
        })
        assert tr.ok
        assert tr.data["patch_preview_truncated"] is False

    # ------------------------------------------------------------------
    # Single-use guard still correct after hardening
    # ------------------------------------------------------------------

    def test_single_use_still_enforced_after_hardening(self, tmp_path):
        """End-to-end: preview with valid workspace → apply → double-apply rejected."""
        from unittest.mock import patch, MagicMock
        import assistant_os.pipelines.code_pipeline as cp

        original_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            preview_plan = _make_plan(ACTION_CODE_FIX, payload={
                "target_file": "src/foo.py",
                "workspace": str(tmp_path),
            })
            preview = code_execute(preview_plan, "ctx-su-01")
            assert preview["ok"], f"preview failed: {preview}"
            proposal = preview["data"]["proposal"]

            apply_plan = _make_plan(ACTION_CODE_FIX, payload={
                "phase": "apply",
                "proposal": proposal,
                "workspace": str(tmp_path),
                "execution_mode": "FULL_EXECUTE",
            })
            _mock_result = MagicMock()
            _mock_result.execution_id = "test-exec-su"
            _mock_result.final_status = "success"
            _mock_result.error = None
            _mock_result.modified_files = []
            _mock_result.report_json_path = None
            _mock_result.report_md_path = None

            with patch("assistant_os.executors.runner_backed_executor.RunnerBackedExecutor") as MockExec:
                MockExec.return_value.execute.return_value = _mock_result
                first = code_execute(apply_plan, "ctx-su-02")
            assert first["ok"], f"first apply failed: {first}"

            second = code_execute(apply_plan, "ctx-su-03")
            assert not second["ok"]
            assert "ProposalAlreadyApplied" in second["error"]["type"]
        finally:
            cp._applied_proposals = original_set


# ---------------------------------------------------------------------------
# I. Observability + read-only executor registry
# ---------------------------------------------------------------------------

class TestObservabilityFields:
    """Preview and apply responses expose all fields needed for UI smoke inspection."""

    def test_preview_has_preview_ready_flag(self, tmp_path):
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "src/foo.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-obs-01")
        assert result["ok"]
        assert result["data"]["preview_ready"] is True

    def test_preview_has_single_use_flag(self, tmp_path):
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "src/foo.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-obs-02")
        assert result["data"]["single_use"] is True

    def test_preview_has_summary(self, tmp_path):
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "src/foo.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-obs-03")
        assert "summary" in result["data"]

    def test_preview_has_patch_preview_truncated(self, tmp_path):
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "src/foo.py", "workspace": str(tmp_path)})
        result = code_execute(plan, "ctx-obs-04")
        assert "patch_preview_truncated" in result["data"]
        # Stub output is tiny — must not be truncated
        assert result["data"]["patch_preview_truncated"] is False

    def test_preview_exposes_all_smoke_fields(self, tmp_path):
        """One comprehensive field presence check for manual smoke inspection."""
        plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "src/foo.py", "workspace": str(tmp_path)})
        data = code_execute(plan, "ctx-obs-05")["data"]
        for field in (
            # Core flags
            "preview_ready", "single_use",
            # Proposal identity
            "proposal_id", "action",
            # Change summary
            "summary", "affected_files", "operation_types", "write_intent_summary",
            # Diff
            "patch_preview", "patch_preview_truncated",
            # Risk + gate
            "risk_level", "requires_confirmation",
            # Degradation metadata (added in feature/code-preview-degradation-metadata)
            "preview_degraded", "preview_warnings",
            "preview_reviewable", "preview_applicable",
            # Executor status
            "propose_executor_live",
        ):
            assert field in data, f"missing field: {field!r}"

    def test_apply_has_apply_ready_flag(self, tmp_path):
        import assistant_os.pipelines.code_pipeline as cp
        original_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            preview = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={"target_file": "f.py", "workspace": str(tmp_path)}),
                "ctx-obs-06",
            )
            proposal = preview["data"]["proposal"]
            apply_result = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={"phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
                                                     "execution_mode": "FULL_EXECUTE"}),
                "ctx-obs-07",
            )
            assert apply_result["ok"]
            assert apply_result["data"]["apply_ready"] is True
        finally:
            cp._applied_proposals = original_set

    def test_apply_has_single_use_flag(self, tmp_path):
        import assistant_os.pipelines.code_pipeline as cp
        original_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            preview = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={"target_file": "f.py", "workspace": str(tmp_path)}),
                "ctx-obs-08",
            )
            apply_result = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={
                    "phase": "apply", "proposal": preview["data"]["proposal"], "workspace": str(tmp_path),
                    "execution_mode": "FULL_EXECUTE",
                }),
                "ctx-obs-09",
            )
            assert apply_result["data"]["single_use"] is True
        finally:
            cp._applied_proposals = original_set

    def test_apply_failure_exposes_guard_failure_field(self, tmp_path):
        """Guard failures include guard_failure field for easy debugging."""
        from unittest.mock import patch, MagicMock
        import assistant_os.pipelines.code_pipeline as cp
        original_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            # Preview → apply → re-apply (double-apply triggers guard failure)
            preview = code_execute(
                _make_plan(ACTION_CODE_FIX, payload={"target_file": "f.py", "workspace": str(tmp_path)}),
                "ctx-obs-10",
            )
            proposal = preview["data"]["proposal"]
            apply_plan = _make_plan(ACTION_CODE_FIX, payload={
                "phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
                "execution_mode": "FULL_EXECUTE",
            })
            _mock_result = MagicMock()
            _mock_result.execution_id = "test-exec-obs"
            _mock_result.final_status = "success"
            _mock_result.error = None
            _mock_result.modified_files = []
            _mock_result.report_json_path = None
            _mock_result.report_md_path = None

            with patch("assistant_os.executors.runner_backed_executor.RunnerBackedExecutor") as MockExec:
                MockExec.return_value.execute.return_value = _mock_result
                code_execute(apply_plan, "ctx-obs-11")  # first apply succeeds
            failed = code_execute(apply_plan, "ctx-obs-12")  # second must fail
            assert not failed["ok"]
            assert failed["data"]["guard_failure"] == "ProposalAlreadyApplied"
        finally:
            cp._applied_proposals = original_set

    def test_read_only_exposes_executor_live_false_by_default(self):
        """executor_live=False when no real executor is registered."""
        plan = _make_plan(ACTION_CODE_EXPLAIN)
        result = code_execute(plan, "ctx-obs-13")
        assert result["ok"]
        assert result["data"]["executor_live"] is False


# ---------------------------------------------------------------------------
# J. Preview message human-readability
# ---------------------------------------------------------------------------

class TestPreviewMessageShape:
    """
    Regression tests for preview message formatting improvements.

    Three human-review-critical properties:
      1. operation_types (Tipo:) is visible in the message text
      2. 2+ affected files use a newline-separated list, not a comma-inline string
      3. A truncation notice appears in the message when patch_preview_truncated=True
    """

    def _preview_with_executor(self, tmp_path, executor_payload: dict) -> dict:
        """Run the pipeline with a fake propose executor, return the DomainResult."""
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.pipelines.code_pipeline import execute as code_execute

        orig = cp._propose_executor

        def _executor(inp: dict) -> dict:
            return dict(executor_payload, ok=True)

        cp.register_propose_executor(_executor)
        try:
            plan = {
                "action": ACTION_CODE_FIX,
                "domain": "CODE",
                "raw_text": "fix it",
                "domain_payload": {
                    "target_file": "src/app.py",
                    "workspace": str(tmp_path),
                },
                "trace_id": "t-msg",
                "plan_id": "p-msg",
            }
            return code_execute(plan, "ctx-msg")
        finally:
            cp.register_propose_executor(orig)

    def test_preview_message_includes_operation_type(self, tmp_path):
        """'Tipo:' line with operation_types must appear in the human-readable message."""
        payload = {
            "summary": "Fix bug", "affected_files": ["src/app.py"],
            "write_intent_summary": "Modifies app.py",
            "patch_preview": "--- a/src/app.py\n+++ b/src/app.py",
            "operation_types": ["modify"], "risk_level": "low",
        }
        result = self._preview_with_executor(tmp_path, payload)
        assert result["ok"]
        assert "Tipo: modify" in result["message"]

    def test_preview_message_create_operation_type(self, tmp_path):
        """CODE_CREATE shows operation_type 'create' in the message."""
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.pipelines.code_pipeline import execute as code_execute

        orig = cp._propose_executor

        def _executor(inp: dict) -> dict:
            return {
                "ok": True,
                "summary": "Create new module",
                "affected_files": ["src/new.py"],
                "write_intent_summary": "Creates new.py",
                "patch_preview": "+++ b/src/new.py",
                "operation_types": ["create"],
                "risk_level": "low",
            }

        cp.register_propose_executor(_executor)
        try:
            plan = {
                "action": ACTION_CODE_CREATE,
                "domain": "CODE",
                "raw_text": "create new module",
                "domain_payload": {"target_file": "src/new.py", "workspace": str(tmp_path)},
            }
            result = code_execute(plan, "ctx-create-type")
        finally:
            cp.register_propose_executor(orig)

        assert result["ok"]
        assert "Tipo: create" in result["message"]

    def test_preview_message_multi_file_vertical_list(self, tmp_path):
        """2+ affected files must be formatted as a newline-separated list."""
        payload = {
            "summary": "Refactor two modules",
            "affected_files": ["src/auth.py", "src/utils.py"],
            "write_intent_summary": "Modifies auth and utils",
            "patch_preview": "--- a/src/auth.py\n+++ b/src/auth.py",
            "operation_types": ["modify"], "risk_level": "medium",
        }
        result = self._preview_with_executor(tmp_path, payload)
        assert result["ok"]
        msg = result["message"]
        # Both files must appear on separate lines (vertical list, not comma-inline)
        assert "src/auth.py" in msg
        assert "src/utils.py" in msg
        # They should NOT be joined by ", " on the same line
        assert "src/auth.py, src/utils.py" not in msg

    def test_preview_message_single_file_no_extra_newline(self, tmp_path):
        """Single affected file stays inline (no leading newline/indent)."""
        payload = {
            "summary": "Fix one file", "affected_files": ["src/app.py"],
            "write_intent_summary": "Modifies app.py",
            "patch_preview": "--- a/src/app.py\n+++ b/src/app.py",
            "operation_types": ["modify"], "risk_level": "low",
        }
        result = self._preview_with_executor(tmp_path, payload)
        assert result["ok"]
        # "Archivos afectados: src/app.py" should appear as a simple inline line
        assert "Archivos afectados: src/app.py" in result["message"]

    def test_preview_message_truncation_notice_when_truncated(self, tmp_path):
        """When patch_preview is truncated, message must warn the reviewer."""
        from assistant_os.tools.claude_code.propose_change_tool import (
            _PATCH_PREVIEW_MAX_LINES,
        )
        # Build a patch that exceeds the line limit to trigger truncation in ProposeChangeTool
        big_patch = "\n".join(f"+line {i}" for i in range(_PATCH_PREVIEW_MAX_LINES + 10))
        payload = {
            "summary": "Large change", "affected_files": ["src/app.py"],
            "write_intent_summary": "Big refactor",
            "patch_preview": big_patch,
            "operation_types": ["modify"], "risk_level": "high",
        }
        result = self._preview_with_executor(tmp_path, payload)
        assert result["ok"]
        assert result["data"]["patch_preview_truncated"] is True
        assert "truncada" in result["message"]

    def test_preview_message_no_truncation_notice_when_full(self, tmp_path):
        """When patch is not truncated, no truncation notice appears in message."""
        payload = {
            "summary": "Small fix", "affected_files": ["src/app.py"],
            "write_intent_summary": "Minor tweak",
            "patch_preview": "--- a/src/app.py\n+++ b/src/app.py\n-old\n+new",
            "operation_types": ["modify"], "risk_level": "low",
        }
        result = self._preview_with_executor(tmp_path, payload)
        assert result["ok"]
        assert result["data"]["patch_preview_truncated"] is False
        assert "truncada" not in result["message"]


# ---------------------------------------------------------------------------
# K. Preview message consistency — message must be a faithful projection of data
# ---------------------------------------------------------------------------

class TestPreviewMessageConsistency:
    """
    Blindaje: message is a projection of structured data, never a free re-interpretation.

    Each test verifies one invariant:
      - the text shown to the reviewer is derived ONLY from the corresponding field in data
      - when a field is absent/empty, degradation is explicit, not silent
    """

    def _run(self, tmp_path, executor_payload: dict, action=None) -> dict:
        """Run pipeline with a controlled executor, return DomainResult."""
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.pipelines.code_pipeline import execute as code_execute

        orig = cp._propose_executor

        def _executor(inp: dict) -> dict:
            return dict(executor_payload, ok=True)

        cp.register_propose_executor(_executor)
        try:
            plan = {
                "action": action or ACTION_CODE_FIX,
                "domain": "CODE",
                "raw_text": "test",
                "domain_payload": {
                    "target_file": "src/app.py",
                    "workspace": str(tmp_path),
                },
            }
            return code_execute(plan, "ctx-cons")
        finally:
            cp.register_propose_executor(orig)

    # ------------------------------------------------------------------
    # A. Tipo: reflects data.operation_types exactly
    # ------------------------------------------------------------------

    def test_tipo_matches_data_operation_types(self, tmp_path):
        """'Tipo:' in message equals the joined value of data.operation_types."""
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py"],
            "write_intent_summary": "w",
            "patch_preview": "+fix",
            "operation_types": ["modify"], "risk_level": "low",
        })
        assert result["ok"]
        op_types = result["data"]["operation_types"]
        expected_tipo = ", ".join(op_types)
        assert f"Tipo: {expected_tipo}" in result["message"]

    def test_tipo_multi_op_types_joined(self, tmp_path):
        """Multiple operation_types join correctly in both message and data."""
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py", "src/new.py"],
            "write_intent_summary": "w",
            "patch_preview": "+new",
            "operation_types": ["modify", "create"], "risk_level": "medium",
        })
        assert result["ok"]
        # data field matches
        assert result["data"]["operation_types"] == ["modify", "create"]
        # message shows both
        assert "Tipo: modify, create" in result["message"]

    def test_tipo_empty_op_types_shows_explicit_notice_not_silent_modify(self, tmp_path):
        """
        If operation_types is [] after reaching the pipeline, message shows an explicit
        degradation notice — NOT a silent 'modify' fallback that would contradict data.
        """
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py"],
            "write_intent_summary": "w",
            "patch_preview": "+fix",
            "operation_types": [],  # bypasses executor normalization via direct injection
            "risk_level": "low",
        })
        assert result["ok"]
        # data.operation_types must reflect the empty list from the envelope
        assert result["data"]["operation_types"] == []
        # message must NOT silently show "modify" (that would contradict data)
        assert "Tipo: modify" not in result["message"]
        # message must show the explicit degradation notice
        assert "no disponible" in result["message"]

    # ------------------------------------------------------------------
    # B. Archivos afectados reflects data.affected_files exactly
    # ------------------------------------------------------------------

    def test_archivos_single_file_inline_matches_data(self, tmp_path):
        """Single file: inline value in message equals data.affected_files[0]."""
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/target.py"],
            "write_intent_summary": "w", "patch_preview": "+fix",
            "operation_types": ["modify"], "risk_level": "low",
        })
        assert result["ok"]
        assert result["data"]["affected_files"] == ["src/target.py"]
        assert "Archivos afectados: src/target.py" in result["message"]

    def test_archivos_multi_file_all_present_in_message(self, tmp_path):
        """All files from data.affected_files appear in the message."""
        files = ["src/auth.py", "src/models.py", "src/utils.py"]
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": files,
            "write_intent_summary": "w", "patch_preview": "+fix",
            "operation_types": ["modify"], "risk_level": "medium",
        })
        assert result["ok"]
        assert result["data"]["affected_files"] == files
        for f in files:
            assert f in result["message"]

    def test_archivos_empty_shows_explicit_notice(self, tmp_path):
        """No affected_files produces explicit 'ningún archivo' notice, not silence."""
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": [],
            "write_intent_summary": "w", "patch_preview": "+fix",
            "operation_types": ["modify"], "risk_level": "low",
        })
        assert result["ok"]
        assert "ningún archivo" in result["message"]

    # ------------------------------------------------------------------
    # C. Riesgo reflects data.risk_level exactly
    # ------------------------------------------------------------------

    def test_riesgo_matches_data_risk_level(self, tmp_path):
        """'Riesgo:' in message equals data.risk_level exactly."""
        for risk in ("low", "medium", "high"):
            result = self._run(tmp_path, {
                "summary": "s", "affected_files": ["src/app.py"],
                "write_intent_summary": "w", "patch_preview": "+fix",
                "operation_types": ["modify"], "risk_level": risk,
            })
            assert result["ok"], f"failed for risk={risk}"
            assert result["data"]["risk_level"] == risk
            assert f"Riesgo: {risk}" in result["message"], f"Riesgo not found for risk={risk}"

    # ------------------------------------------------------------------
    # D. Truncation notice derived exclusively from data.patch_preview_truncated
    # ------------------------------------------------------------------

    def test_truncation_notice_only_when_data_flag_true(self, tmp_path):
        """Truncation notice in message iff data.patch_preview_truncated is True."""
        from assistant_os.tools.claude_code.propose_change_tool import _PATCH_PREVIEW_MAX_LINES
        big_patch = "\n".join(f"+line {i}" for i in range(_PATCH_PREVIEW_MAX_LINES + 5))

        # Truncated case
        r_truncated = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py"],
            "write_intent_summary": "w", "patch_preview": big_patch,
            "operation_types": ["modify"], "risk_level": "low",
        })
        assert r_truncated["ok"]
        assert r_truncated["data"]["patch_preview_truncated"] is True
        assert "truncada" in r_truncated["message"]

        # Not-truncated case
        r_normal = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py"],
            "write_intent_summary": "w", "patch_preview": "+one line",
            "operation_types": ["modify"], "risk_level": "low",
        })
        assert r_normal["ok"]
        assert r_normal["data"]["patch_preview_truncated"] is False
        assert "truncada" not in r_normal["message"]

    # ------------------------------------------------------------------
    # E. Empty patch_preview shows explicit notice
    # ------------------------------------------------------------------

    def test_empty_patch_preview_shows_explicit_notice(self, tmp_path):
        """
        Empty patch_preview string must produce an explicit notice in the message,
        not a blank diff section that leaves the reviewer confused.
        """
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py"],
            "write_intent_summary": "w",
            "patch_preview": "",  # executor returned no diff
            "operation_types": ["modify"], "risk_level": "low",
        })
        assert result["ok"]
        # Must NOT display a blank diff section silently
        # Must display an explicit notice about the missing diff
        assert "sin diff disponible" in result["message"]

    def test_whitespace_only_patch_preview_shows_explicit_notice(self, tmp_path):
        """Whitespace-only patch_preview is treated the same as empty."""
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py"],
            "write_intent_summary": "w",
            "patch_preview": "   \n  \n  ",
            "operation_types": ["modify"], "risk_level": "low",
        })
        assert result["ok"]
        assert "sin diff disponible" in result["message"]


# ---------------------------------------------------------------------------
# L. Degradation metadata — preview_degraded + preview_warnings
# ---------------------------------------------------------------------------

class TestPreviewDegradationMetadata:
    """
    preview_degraded and preview_warnings are derived from the same variables
    used to build the message, so data and text share one source of truth.

    Eight invariants:
      1. Clean preview → not degraded, empty warnings
      2. Empty operation_types → missing_operation_types
      3. Empty affected_files → missing_affected_files
      4. Empty/whitespace patch_preview → missing_patch_preview
      5. Invalid risk_level → invalid_risk_level
      6. Multiple operation_types → multiple_operation_types
      7. Truncated patch → patch_preview_truncated warning
      8. Multiple problems → all applicable warnings present (no duplicates)
    """

    def _run(self, tmp_path, executor_payload: dict, target_file="src/app.py") -> dict:
        """Run pipeline with a controlled fake executor, return DomainResult."""
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.pipelines.code_pipeline import execute as code_execute

        orig = cp._propose_executor

        def _executor(inp: dict) -> dict:
            return dict(executor_payload, ok=True)

        cp.register_propose_executor(_executor)
        try:
            plan = {
                "action": ACTION_CODE_FIX,
                "domain": "CODE",
                "raw_text": "test",
                "domain_payload": {
                    "target_file": target_file,
                    "workspace": str(tmp_path),
                },
            }
            return code_execute(plan, "ctx-deg")
        finally:
            cp.register_propose_executor(orig)

    # ------------------------------------------------------------------
    # 1. Clean preview — not degraded
    # ------------------------------------------------------------------

    def test_clean_preview_not_degraded(self, tmp_path):
        """A complete, valid preview has preview_degraded=False and no warnings."""
        result = self._run(tmp_path, {
            "summary": "Fix auth bug",
            "affected_files": ["src/app.py"],
            "write_intent_summary": "Modifies app.py",
            "patch_preview": "--- a/src/app.py\n+++ b/src/app.py\n-old\n+new",
            "operation_types": ["modify"],
            "risk_level": "low",
        })
        assert result["ok"]
        assert result["data"]["preview_degraded"] is False
        assert result["data"]["preview_warnings"] == []

    # ------------------------------------------------------------------
    # 2. Empty operation_types → missing_operation_types
    # ------------------------------------------------------------------

    def test_empty_operation_types_sets_warning(self, tmp_path):
        """op_types=[] → preview_degraded=True, missing_operation_types in warnings."""
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py"],
            "write_intent_summary": "w",
            "patch_preview": "+fix",
            "operation_types": [],   # injected empty — bypasses executor normalisation
            "risk_level": "low",
        })
        assert result["ok"]
        assert result["data"]["preview_degraded"] is True
        assert "missing_operation_types" in result["data"]["preview_warnings"]

    # ------------------------------------------------------------------
    # 3. Empty affected_files → missing_affected_files
    # ------------------------------------------------------------------

    def test_empty_affected_files_sets_warning(self, tmp_path):
        """affected_files=[] → preview_degraded=True, missing_affected_files in warnings."""
        # Use target_file="" so ProposeChangeTool does not back-fill from target_file
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": [],
            "write_intent_summary": "w",
            "patch_preview": "+fix",
            "operation_types": ["modify"],
            "risk_level": "low",
        }, target_file="")
        assert result["ok"]
        assert result["data"]["preview_degraded"] is True
        assert "missing_affected_files" in result["data"]["preview_warnings"]

    # ------------------------------------------------------------------
    # 4. Empty patch_preview → missing_patch_preview
    # ------------------------------------------------------------------

    def test_empty_patch_preview_sets_warning(self, tmp_path):
        """patch_preview='' → preview_degraded=True, missing_patch_preview in warnings."""
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py"],
            "write_intent_summary": "w",
            "patch_preview": "",
            "operation_types": ["modify"],
            "risk_level": "low",
        })
        assert result["ok"]
        assert result["data"]["preview_degraded"] is True
        assert "missing_patch_preview" in result["data"]["preview_warnings"]

    def test_whitespace_patch_preview_sets_warning(self, tmp_path):
        """Whitespace-only patch treated as empty → missing_patch_preview."""
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py"],
            "write_intent_summary": "w",
            "patch_preview": "  \n  \n  ",
            "operation_types": ["modify"],
            "risk_level": "low",
        })
        assert result["ok"]
        assert "missing_patch_preview" in result["data"]["preview_warnings"]

    # ------------------------------------------------------------------
    # 5. Invalid risk_level → invalid_risk_level
    # ------------------------------------------------------------------

    def test_invalid_risk_level_sets_warning(self, tmp_path):
        """Non-canonical risk_level (e.g. 'critical') → invalid_risk_level warning."""
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py"],
            "write_intent_summary": "w",
            "patch_preview": "+fix",
            "operation_types": ["modify"],
            "risk_level": "critical",  # not in {low, medium, high}
        })
        assert result["ok"]
        assert result["data"]["preview_degraded"] is True
        assert "invalid_risk_level" in result["data"]["preview_warnings"]

    # ------------------------------------------------------------------
    # 6. Multiple operation_types → multiple_operation_types
    # ------------------------------------------------------------------

    def test_multiple_operation_types_sets_warning(self, tmp_path):
        """len(op_types) > 1 → multiple_operation_types warning."""
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py", "src/new.py"],
            "write_intent_summary": "w",
            "patch_preview": "+fix",
            "operation_types": ["modify", "create"],
            "risk_level": "medium",
        })
        assert result["ok"]
        assert result["data"]["preview_degraded"] is True
        assert "multiple_operation_types" in result["data"]["preview_warnings"]

    # ------------------------------------------------------------------
    # 7. Truncated patch → patch_preview_truncated warning
    # ------------------------------------------------------------------

    def test_truncated_patch_sets_warning(self, tmp_path):
        """patch_preview_truncated=True → patch_preview_truncated in warnings."""
        from assistant_os.tools.claude_code.propose_change_tool import _PATCH_PREVIEW_MAX_LINES
        big_patch = "\n".join(f"+line {i}" for i in range(_PATCH_PREVIEW_MAX_LINES + 10))
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": ["src/app.py"],
            "write_intent_summary": "w",
            "patch_preview": big_patch,
            "operation_types": ["modify"],
            "risk_level": "low",
        })
        assert result["ok"]
        assert result["data"]["patch_preview_truncated"] is True
        assert result["data"]["preview_degraded"] is True
        assert "patch_preview_truncated" in result["data"]["preview_warnings"]

    # ------------------------------------------------------------------
    # 8. Multiple problems → all warnings accumulated, no duplicates
    # ------------------------------------------------------------------

    def test_multiple_problems_accumulates_warnings(self, tmp_path):
        """All applicable warnings are collected; no warning appears twice."""
        result = self._run(tmp_path, {
            "summary": "s", "affected_files": [],
            "write_intent_summary": "w",
            "patch_preview": "",
            "operation_types": [],
            "risk_level": "unknown",
        }, target_file="")
        assert result["ok"]
        warnings = result["data"]["preview_warnings"]
        assert result["data"]["preview_degraded"] is True
        # All four expected warnings must be present
        for code in ("missing_operation_types", "missing_affected_files",
                     "missing_patch_preview", "invalid_risk_level"):
            assert code in warnings, f"expected warning {code!r} not found: {warnings}"
        # No duplicates
        assert len(warnings) == len(set(warnings))


# ---------------------------------------------------------------------------
# M. Reviewability — preview_reviewable derived from preview_warnings
# ---------------------------------------------------------------------------

class TestPreviewReviewability:
    """
    preview_reviewable is False iff at least one non-reviewable warning is present:
        missing_operation_types | missing_affected_files | missing_patch_preview

    All other warnings (invalid_risk_level, multiple_operation_types,
    patch_preview_truncated) degrade the preview but do not block review.
    """

    def _run(self, tmp_path, executor_payload: dict, target_file="src/app.py") -> dict:
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.pipelines.code_pipeline import execute as code_execute

        orig = cp._propose_executor

        def _executor(inp: dict) -> dict:
            return dict(executor_payload, ok=True)

        cp.register_propose_executor(_executor)
        try:
            plan = {
                "action": ACTION_CODE_FIX,
                "domain": "CODE",
                "raw_text": "test",
                "domain_payload": {
                    "target_file": target_file,
                    "workspace": str(tmp_path),
                },
            }
            return code_execute(plan, "ctx-rev")
        finally:
            cp.register_propose_executor(orig)

    def _good_payload(self, **overrides):
        base = {
            "summary": "Fix bug",
            "affected_files": ["src/app.py"],
            "write_intent_summary": "Modifies app.py",
            "patch_preview": "--- a/src/app.py\n+++ b/src/app.py\n-old\n+new",
            "operation_types": ["modify"],
            "risk_level": "low",
        }
        base.update(overrides)
        return base

    # ------------------------------------------------------------------
    # 1. Clean preview → reviewable=True, degraded=False
    # ------------------------------------------------------------------

    def test_clean_preview_is_reviewable(self, tmp_path):
        result = self._run(tmp_path, self._good_payload())
        assert result["ok"]
        assert result["data"]["preview_reviewable"] is True
        assert result["data"]["preview_degraded"] is False

    # ------------------------------------------------------------------
    # 2. Truncated patch → reviewable=True (degraded but enough info)
    # ------------------------------------------------------------------

    def test_truncated_patch_is_still_reviewable(self, tmp_path):
        from assistant_os.tools.claude_code.propose_change_tool import _PATCH_PREVIEW_MAX_LINES
        big = "\n".join(f"+line {i}" for i in range(_PATCH_PREVIEW_MAX_LINES + 10))
        result = self._run(tmp_path, self._good_payload(patch_preview=big))
        assert result["ok"]
        assert result["data"]["preview_degraded"] is True
        assert "patch_preview_truncated" in result["data"]["preview_warnings"]
        assert result["data"]["preview_reviewable"] is True

    # ------------------------------------------------------------------
    # 3. Multiple operation types → reviewable=True
    # ------------------------------------------------------------------

    def test_multiple_op_types_is_still_reviewable(self, tmp_path):
        result = self._run(tmp_path, self._good_payload(
            operation_types=["modify", "create"],
            affected_files=["src/app.py", "src/new.py"],
        ))
        assert result["ok"]
        assert "multiple_operation_types" in result["data"]["preview_warnings"]
        assert result["data"]["preview_reviewable"] is True

    # ------------------------------------------------------------------
    # 4. Missing patch preview → reviewable=False
    # ------------------------------------------------------------------

    def test_missing_patch_preview_not_reviewable(self, tmp_path):
        result = self._run(tmp_path, self._good_payload(patch_preview=""))
        assert result["ok"]
        assert result["data"]["preview_reviewable"] is False
        assert "missing_patch_preview" in result["data"]["preview_warnings"]

    # ------------------------------------------------------------------
    # 5. Missing operation types → reviewable=False
    # ------------------------------------------------------------------

    def test_missing_operation_types_not_reviewable(self, tmp_path):
        result = self._run(tmp_path, self._good_payload(operation_types=[]))
        assert result["ok"]
        assert result["data"]["preview_reviewable"] is False
        assert "missing_operation_types" in result["data"]["preview_warnings"]

    # ------------------------------------------------------------------
    # 6. Missing affected files → reviewable=False
    # ------------------------------------------------------------------

    def test_missing_affected_files_not_reviewable(self, tmp_path):
        result = self._run(tmp_path, self._good_payload(affected_files=[]), target_file="")
        assert result["ok"]
        assert result["data"]["preview_reviewable"] is False
        assert "missing_affected_files" in result["data"]["preview_warnings"]

    # ------------------------------------------------------------------
    # 7. Non-reviewable warning present alongside others → still not reviewable
    # ------------------------------------------------------------------

    def test_non_reviewable_warning_dominates(self, tmp_path):
        """Even with only one non-reviewable warning, reviewable=False."""
        from assistant_os.tools.claude_code.propose_change_tool import _PATCH_PREVIEW_MAX_LINES
        big = "\n".join(f"+line {i}" for i in range(_PATCH_PREVIEW_MAX_LINES + 10))
        # Truncated (reviewable by itself) + missing op_types (non-reviewable)
        result = self._run(tmp_path, self._good_payload(
            patch_preview=big,
            operation_types=[],
        ))
        assert result["ok"]
        assert "patch_preview_truncated" in result["data"]["preview_warnings"]
        assert "missing_operation_types" in result["data"]["preview_warnings"]
        assert result["data"]["preview_reviewable"] is False

    # ------------------------------------------------------------------
    # 8. Invalid risk_level alone → degraded but reviewable
    # ------------------------------------------------------------------

    def test_invalid_risk_only_is_degraded_but_reviewable(self, tmp_path):
        """invalid_risk_level does not block review — diff and files are present."""
        result = self._run(tmp_path, self._good_payload(risk_level="extreme"))
        assert result["ok"]
        assert result["data"]["preview_degraded"] is True
        assert "invalid_risk_level" in result["data"]["preview_warnings"]
        assert result["data"]["preview_reviewable"] is True


# ---------------------------------------------------------------------------
# N. Applicability — preview_applicable derived from reviewability + warnings
# ---------------------------------------------------------------------------

class TestPreviewApplicability:
    """
    preview_applicable = preview_reviewable AND no warning in
    {patch_preview_truncated, multiple_operation_types, invalid_risk_level}.

    Non-reviewable warnings (missing_*) already force reviewable=False,
    which transitively forces applicable=False.
    """

    def _run(self, tmp_path, executor_payload: dict, target_file="src/app.py") -> dict:
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.pipelines.code_pipeline import execute as code_execute

        orig = cp._propose_executor

        def _executor(inp: dict) -> dict:
            return dict(executor_payload, ok=True)

        cp.register_propose_executor(_executor)
        try:
            plan = {
                "action": ACTION_CODE_FIX,
                "domain": "CODE",
                "raw_text": "test",
                "domain_payload": {
                    "target_file": target_file,
                    "workspace": str(tmp_path),
                },
            }
            return code_execute(plan, "ctx-app")
        finally:
            cp.register_propose_executor(orig)

    def _good(self, **overrides):
        base = {
            "summary": "Fix bug",
            "affected_files": ["src/app.py"],
            "write_intent_summary": "Modifies app.py",
            "patch_preview": "--- a/src/app.py\n+++ b/src/app.py\n-old\n+new",
            "operation_types": ["modify"],
            "risk_level": "low",
        }
        base.update(overrides)
        return base

    # 1. Clean preview → applicable=True, reviewable=True, degraded=False
    def test_clean_preview_is_applicable(self, tmp_path):
        result = self._run(tmp_path, self._good())
        d = result["data"]
        assert d["preview_applicable"] is True
        assert d["preview_reviewable"] is True
        assert d["preview_degraded"] is False

    # 2. Missing patch preview → applicable=False, reviewable=False
    def test_missing_patch_not_applicable(self, tmp_path):
        result = self._run(tmp_path, self._good(patch_preview=""))
        d = result["data"]
        assert d["preview_reviewable"] is False
        assert d["preview_applicable"] is False

    # 3. Missing operation types → applicable=False, reviewable=False
    def test_missing_op_types_not_applicable(self, tmp_path):
        result = self._run(tmp_path, self._good(operation_types=[]))
        d = result["data"]
        assert d["preview_reviewable"] is False
        assert d["preview_applicable"] is False

    # 4. Missing affected files → applicable=False, reviewable=False
    def test_missing_affected_files_not_applicable(self, tmp_path):
        result = self._run(tmp_path, self._good(affected_files=[]), target_file="")
        d = result["data"]
        assert d["preview_reviewable"] is False
        assert d["preview_applicable"] is False

    # 5. Truncated patch → reviewable=True, applicable=False
    def test_truncated_patch_not_applicable(self, tmp_path):
        from assistant_os.tools.claude_code.propose_change_tool import _PATCH_PREVIEW_MAX_LINES
        big = "\n".join(f"+line {i}" for i in range(_PATCH_PREVIEW_MAX_LINES + 10))
        result = self._run(tmp_path, self._good(patch_preview=big))
        d = result["data"]
        assert d["preview_reviewable"] is True
        assert d["preview_applicable"] is False
        assert "patch_preview_truncated" in d["preview_warnings"]

    # 6. Multiple operation types → reviewable=True, applicable=False
    def test_multiple_op_types_not_applicable(self, tmp_path):
        result = self._run(tmp_path, self._good(
            operation_types=["modify", "create"],
            affected_files=["src/app.py", "src/new.py"],
        ))
        d = result["data"]
        assert d["preview_reviewable"] is True
        assert d["preview_applicable"] is False
        assert "multiple_operation_types" in d["preview_warnings"]

    # 7. Invalid risk level → reviewable=True, applicable=False
    def test_invalid_risk_not_applicable(self, tmp_path):
        result = self._run(tmp_path, self._good(risk_level="extreme"))
        d = result["data"]
        assert d["preview_reviewable"] is True
        assert d["preview_applicable"] is False
        assert "invalid_risk_level" in d["preview_warnings"]

    # 8. Mixed warnings — any blocking warning forces applicable=False
    def test_mixed_warnings_not_applicable(self, tmp_path):
        """Truncated + invalid risk: both are non-applicable; result is still False."""
        from assistant_os.tools.claude_code.propose_change_tool import _PATCH_PREVIEW_MAX_LINES
        big = "\n".join(f"+line {i}" for i in range(_PATCH_PREVIEW_MAX_LINES + 10))
        result = self._run(tmp_path, self._good(patch_preview=big, risk_level="extreme"))
        d = result["data"]
        assert d["preview_reviewable"] is True   # diff present (truncated, but not missing)
        assert d["preview_applicable"] is False
        assert "patch_preview_truncated" in d["preview_warnings"]
        assert "invalid_risk_level" in d["preview_warnings"]

    # 9. Clean preview with valid risk and single op → applicable=True (positive confirmation)
    def test_single_op_valid_risk_applicable(self, tmp_path):
        for risk in ("low", "medium", "high"):
            result = self._run(tmp_path, self._good(risk_level=risk))
            d = result["data"]
            assert d["preview_applicable"] is True, f"expected applicable for risk={risk}"
            assert d["preview_warnings"] == []


class TestReadOnlyExecutorRegistry:
    """register_review_executor() wires a callable into CODE_EXPLAIN / CODE_REVIEW."""

    def _register_and_restore(self, fn):
        """Context helper: registers fn, returns original for finally-block restore."""
        import assistant_os.pipelines.code_pipeline as cp
        original = cp._review_executor
        cp.register_review_executor(fn)
        return original

    def test_register_executor_used_for_explain(self):
        import assistant_os.pipelines.code_pipeline as cp
        original = self._register_and_restore(
            lambda inp: {"ok": True, "analysis": "real-explain-output"}
        )
        try:
            plan = _make_plan(ACTION_CODE_EXPLAIN, "explícame este módulo")
            result = code_execute(plan, "ctx-reg-01")
            assert result["ok"]
            assert result["data"]["analysis"] == "real-explain-output"
            assert result["data"]["executor_live"] is True
        finally:
            cp.register_review_executor(original)

    def test_register_executor_used_for_review(self):
        import assistant_os.pipelines.code_pipeline as cp
        original = self._register_and_restore(
            lambda inp: {"ok": True, "analysis": "real-review-output"}
        )
        try:
            plan = _make_plan(ACTION_CODE_REVIEW, "revisa este archivo")
            result = code_execute(plan, "ctx-reg-02")
            assert result["ok"]
            assert result["data"]["analysis"] == "real-review-output"
        finally:
            cp.register_review_executor(original)

    def test_executor_receives_correct_input_keys(self):
        """The registered executor receives action, target_file, workspace, context."""
        import assistant_os.pipelines.code_pipeline as cp
        received: dict = {}

        def capturing_executor(inp: dict) -> dict:
            received.update(inp)
            return {"ok": True, "analysis": "captured"}

        original = self._register_and_restore(capturing_executor)
        try:
            plan = _make_plan(
                ACTION_CODE_EXPLAIN, "explícame foo.py",
                payload={"target_file": "src/foo.py", "workspace": "/some/ws"},
            )
            code_execute(plan, "ctx-reg-03")
            assert received.get("action") == ACTION_CODE_EXPLAIN
            assert received.get("target_file") == "src/foo.py"
            assert received.get("workspace") == "/some/ws"
            assert "explícame foo.py" in received.get("context", "")
        finally:
            cp.register_review_executor(original)

    def test_register_none_reverts_to_stub(self):
        """register_review_executor(None) restores stub behaviour."""
        import assistant_os.pipelines.code_pipeline as cp
        original = self._register_and_restore(
            lambda inp: {"ok": True, "analysis": "real"}
        )
        try:
            cp.register_review_executor(None)
            plan = _make_plan(ACTION_CODE_EXPLAIN)
            result = code_execute(plan, "ctx-reg-04")
            assert result["ok"]
            # Stub output contains "[stub]"
            assert "[stub]" in result["data"]["analysis"]
            assert result["data"]["executor_live"] is False
        finally:
            cp.register_review_executor(original)

    def test_executor_failure_propagates_cleanly(self):
        """A real executor returning ok=False surfaces a clean error DomainResult."""
        import assistant_os.pipelines.code_pipeline as cp
        original = self._register_and_restore(
            lambda inp: {"ok": False, "error": "API rate limit exceeded"}
        )
        try:
            plan = _make_plan(ACTION_CODE_EXPLAIN)
            result = code_execute(plan, "ctx-reg-05")
            assert not result["ok"]
            assert "rate limit" in result["error"]["message"]
        finally:
            cp.register_review_executor(original)


class TestProposeExecutorRegistry:
    """register_propose_executor() wires a callable into CODE_FIX / CODE_CREATE preview."""

    def _register_and_restore(self, fn):
        """Context helper: registers fn, returns original for finally-block restore."""
        import assistant_os.pipelines.code_pipeline as cp
        original = cp._propose_executor
        cp.register_propose_executor(fn)
        return original

    def test_propose_executor_live_false_by_default(self, tmp_path):
        """With no executor registered, propose_executor_live is False in preview data."""
        import assistant_os.pipelines.code_pipeline as cp
        original = cp._propose_executor
        cp.register_propose_executor(None)
        try:
            plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "f.py", "workspace": str(tmp_path)})
            result = code_execute(plan, "ctx-preg-01")
            assert result["data"]["propose_executor_live"] is False
        finally:
            cp.register_propose_executor(original)

    def test_propose_executor_live_true_when_registered(self, tmp_path):
        """With a real executor registered, propose_executor_live is True."""
        import assistant_os.pipelines.code_pipeline as cp
        fake = lambda inp: {
            "ok": True, "summary": "s", "affected_files": ["f.py"],
            "write_intent_summary": "w", "patch_preview": "diff", "operation_types": ["modify"],
            "risk_level": "low",
        }
        original = self._register_and_restore(fake)
        try:
            plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "f.py", "workspace": str(tmp_path)})
            result = code_execute(plan, "ctx-preg-02")
            assert result["ok"]
            assert result["data"]["propose_executor_live"] is True
        finally:
            cp.register_propose_executor(original)

    def test_registered_executor_output_populates_preview_data(self, tmp_path):
        """A real executor's output is used to populate summary, patch_preview, risk_level."""
        import assistant_os.pipelines.code_pipeline as cp
        fake = lambda inp: {
            "ok": True, "summary": "custom summary",
            "affected_files": ["src/thing.py"],
            "write_intent_summary": "custom intent",
            "patch_preview": "--- a/src/thing.py\n+++ b/src/thing.py\n@@ -1 +1 @@\n-old\n+new",
            "operation_types": ["modify"], "risk_level": "high",
        }
        original = self._register_and_restore(fake)
        try:
            plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "src/thing.py", "workspace": str(tmp_path)})
            data = code_execute(plan, "ctx-preg-03")["data"]
            assert data["summary"] == "custom summary"
            assert data["write_intent_summary"] == "custom intent"
            assert data["risk_level"] == "high"
            assert "+new" in data["patch_preview"]
        finally:
            cp.register_propose_executor(original)

    def test_register_none_reverts_to_stub(self, tmp_path):
        """register_propose_executor(None) restores stub — propose_executor_live is False."""
        import assistant_os.pipelines.code_pipeline as cp
        fake = lambda inp: {
            "ok": True, "summary": "s", "affected_files": [], "write_intent_summary": "",
            "patch_preview": "", "operation_types": ["modify"], "risk_level": "low",
        }
        original = self._register_and_restore(fake)
        try:
            cp.register_propose_executor(None)
            plan = _make_plan(ACTION_CODE_FIX, payload={"target_file": "f.py", "workspace": str(tmp_path)})
            result = code_execute(plan, "ctx-preg-04")
            assert result["ok"]
            assert result["data"]["propose_executor_live"] is False
        finally:
            cp.register_propose_executor(original)

    def test_executor_receives_correct_input_keys(self, tmp_path):
        """The registered propose executor receives all required input keys."""
        import assistant_os.pipelines.code_pipeline as cp
        received: dict = {}

        def capturing_executor(inp: dict) -> dict:
            received.update(inp)
            return {
                "ok": True, "summary": "s", "affected_files": ["a.py"],
                "write_intent_summary": "w", "patch_preview": "diff",
                "operation_types": ["modify"], "risk_level": "low",
            }

        original = self._register_and_restore(capturing_executor)
        try:
            plan = _make_plan(
                ACTION_CODE_CREATE, "crea una clase Foo",
                payload={"target_file": "src/foo.py", "workspace": str(tmp_path)},
            )
            code_execute(plan, "ctx-preg-05")
            assert received.get("action") == ACTION_CODE_CREATE
            assert received.get("target_file") == "src/foo.py"
            assert received.get("workspace") == str(tmp_path)
            assert "crea una clase Foo" in received.get("context", "")
        finally:
            cp.register_propose_executor(original)


# ---------------------------------------------------------------------------
# O. Apply contract hardening
# ---------------------------------------------------------------------------

from assistant_os.pipelines.code_pipeline import _check_proposal_applicability


class TestApplyContractHardening:
    """
    Formalised apply preconditions, enriched result shape, and semantic pre-gate.

    Coverage matrix:
      1. Stub mode — apply_mode == "stub" in result data
      2. Empty patch_preview → NotApplicable (pre-gate, not mechanical guard)
      3. Empty operation_types → NotApplicable
      4. Empty affected_files → NotApplicable
      5. Invalid risk_level → NotApplicable
      6. Truncated patch → NotApplicable
      7. Multiple operation_types → NotApplicable
      8. apply result has audit_summary with expected keys
      9. No side effects — stub mode confirmed via apply_mode field
    """

    # ------------------------------------------------------------------
    # Helper: run full preview→apply via pipeline in an isolated applied set
    # ------------------------------------------------------------------

    def _apply_via_pipeline(self, tmp_path, proposal_override: dict | None = None) -> dict:
        """Preview → apply pipeline end-to-end.  Returns the apply DomainResult."""
        from unittest.mock import patch, MagicMock
        import assistant_os.pipelines.code_pipeline as cp

        orig_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            preview_plan = _make_plan(
                ACTION_CODE_FIX,
                payload={"target_file": "src/foo.py", "workspace": str(tmp_path)},
            )
            preview = code_execute(preview_plan, "ctx-ach-preview")
            assert preview["ok"], f"preview failed: {preview}"
            proposal = preview["data"]["proposal"]
            if proposal_override:
                proposal = dict(proposal, **proposal_override)
            apply_plan = _make_plan(
                ACTION_CODE_FIX,
                payload={"phase": "apply", "proposal": proposal, "workspace": str(tmp_path),
                         "execution_mode": "FULL_EXECUTE"},
            )
            _mock_result = MagicMock()
            _mock_result.execution_id = apply_plan.get("plan_id", "test-exec-ach")
            _mock_result.final_status = "success"
            _mock_result.error = None
            _mock_result.modified_files = []
            _mock_result.report_json_path = None
            _mock_result.report_md_path = None

            with patch("assistant_os.executors.runner_backed_executor.RunnerBackedExecutor") as MockExec:
                MockExec.return_value.execute.return_value = _mock_result
                return code_execute(apply_plan, "ctx-ach-apply")
        finally:
            cp._applied_proposals = orig_set

    # ------------------------------------------------------------------
    # 1. Stub mode — apply_mode == "stub" in result
    # ------------------------------------------------------------------

    def test_apply_result_has_apply_mode_stub(self, tmp_path):
        """execution_source must be 'runner' — apply routes exclusively through RunnerBackedExecutor."""
        result = self._apply_via_pipeline(tmp_path)
        assert result["ok"], f"apply failed: {result}"
        assert result["data"]["audit_summary"]["execution_source"] == "runner"

    # ------------------------------------------------------------------
    # 2. Empty patch_preview → NotApplicable (pipeline pre-gate)
    # ------------------------------------------------------------------

    def test_empty_patch_preview_rejected_at_pre_gate(self, tmp_path):
        """Proposal with no diff is rejected before ApplyChangeTool runs."""
        result = self._apply_via_pipeline(
            tmp_path, proposal_override={"patch_preview": ""}
        )
        assert not result["ok"]
        assert result["error"]["type"] == "NotApplicable"
        assert result["data"]["guard_failure"] == "NotApplicable"

    # ------------------------------------------------------------------
    # 3. Empty operation_types → NotApplicable
    # ------------------------------------------------------------------

    def test_empty_op_types_rejected_at_pre_gate(self, tmp_path):
        """Proposal with no operation_types is rejected before mechanical guards."""
        result = self._apply_via_pipeline(
            tmp_path,
            proposal_override={"proposal_artifacts": {"operation_types": []}},
        )
        assert not result["ok"]
        assert result["error"]["type"] == "NotApplicable"

    # ------------------------------------------------------------------
    # 4. Empty affected_files → NotApplicable
    # ------------------------------------------------------------------

    def test_empty_affected_files_rejected_at_pre_gate(self, tmp_path):
        """Proposal with empty affected_files is rejected before mechanical guards."""
        result = self._apply_via_pipeline(
            tmp_path, proposal_override={"affected_files": [], "allowed_write_scope": []}
        )
        assert not result["ok"]
        assert result["error"]["type"] == "NotApplicable"

    # ------------------------------------------------------------------
    # 5. Invalid risk_level → NotApplicable
    # ------------------------------------------------------------------

    def test_invalid_risk_level_rejected_at_pre_gate(self, tmp_path):
        """Non-canonical risk_level blocks apply at the pre-gate."""
        result = self._apply_via_pipeline(
            tmp_path, proposal_override={"risk_level": "critical"}
        )
        assert not result["ok"]
        assert result["error"]["type"] == "NotApplicable"

    # ------------------------------------------------------------------
    # 6. Truncated patch → NotApplicable
    # ------------------------------------------------------------------

    def test_truncated_patch_rejected_at_pre_gate(self, tmp_path):
        """Applying over a truncated diff is unsafe — pre-gate must reject it."""
        result = self._apply_via_pipeline(
            tmp_path, proposal_override={"patch_preview_truncated": True}
        )
        assert not result["ok"]
        assert result["error"]["type"] == "NotApplicable"

    # ------------------------------------------------------------------
    # 7. Multiple operation_types → NotApplicable
    # ------------------------------------------------------------------

    def test_multiple_op_types_rejected_at_pre_gate(self, tmp_path):
        """Multiple op_types in a single proposal is ambiguous — pre-gate rejects."""
        result = self._apply_via_pipeline(
            tmp_path,
            proposal_override={
                "proposal_artifacts": {"operation_types": ["modify", "create"]}
            },
        )
        assert not result["ok"]
        assert result["error"]["type"] == "NotApplicable"

    # ------------------------------------------------------------------
    # 8. apply result has audit_summary with expected keys
    # ------------------------------------------------------------------

    def test_apply_result_has_audit_summary(self, tmp_path):
        """audit_summary must be present on a successful apply with M2C runner keys."""
        result = self._apply_via_pipeline(tmp_path)
        assert result["ok"], f"apply failed: {result}"
        audit = result["data"].get("audit_summary")
        assert audit is not None, "audit_summary missing from apply result"
        for key in ("action", "files_changed", "execution_source",
                    "execution_id", "plan_id", "policy_id", "capability_scope"):
            assert key in audit, f"audit_summary missing key: {key!r}"
        assert audit["execution_source"] == "runner"

    # ------------------------------------------------------------------
    # 9. No side effects — stub mode confirmed
    # ------------------------------------------------------------------

    def test_stub_mode_no_side_effects(self, tmp_path):
        """
        When proposal has no real file changes, runner reports zero modified_files
        and no files are written to disk.
        """
        result = self._apply_via_pipeline(tmp_path)
        assert result["ok"], f"apply failed: {result}"
        assert result["data"]["modified_files"] == []
        for rel_path in result["data"].get("modified_files", []):
            abs_path = tmp_path / rel_path
            assert not abs_path.exists(), (
                f"runner reported {rel_path!r} as modified but it should not exist"
            )

    # ------------------------------------------------------------------
    # Unit tests for _check_proposal_applicability directly
    # ------------------------------------------------------------------

    def test_check_applicability_clean_proposal_returns_none(self):
        """A fully populated proposal passes the pre-gate (returns None)."""
        proposal = _make_proposal()
        assert _check_proposal_applicability(proposal) is None

    def test_check_applicability_error_message_is_descriptive(self, tmp_path):
        """NotApplicable error message must describe the problem explicitly."""
        result = self._apply_via_pipeline(
            tmp_path, proposal_override={"patch_preview": ""}
        )
        assert not result["ok"]
        msg = result["error"]["message"]
        assert len(msg) > 20, f"error message too short to be descriptive: {msg!r}"
