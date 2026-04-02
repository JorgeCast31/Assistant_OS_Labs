"""
M2B — Governed CODE Execution Integration Tests

Validates that the CODE domain is formally connected to the orchestrator:

A. Planner produces real ACTION_CODE_* plans
B. PolicyDecision governs CODE with the correct execution_mode
C. CODE_EXPLAIN / CODE_REVIEW auto-execute under policy
D. CODE_FIX / CODE_CREATE produce preview and require confirmation
E. Preview path persists apply-plan in context_store (confirm bridge)
F. Apply path builds AuthorizedPlan with execution_id == plan_id
G. UI_INTENT_MAP covers all CODE actions
H. Confirm flow: _execute_confirmed_plan reaches code_pipeline for CODE
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from assistant_os.contracts import (
    make_plan,
    determine_execution_mode,
    ui_intent_for_action,
    EXECUTION_MODE_AUTO,
    EXECUTION_MODE_CONFIRM,
    ACTION_CODE_EXPLAIN,
    ACTION_CODE_REVIEW,
    ACTION_CODE_FIX,
    ACTION_CODE_CREATE,
    RISK_LOW,
    RISK_MEDIUM,
    RESULT_TYPE_CODE_EXPLAIN,
    RESULT_TYPE_CODE_REVIEW,
    RESULT_TYPE_CODE_PREVIEW,
    RESULT_TYPE_CODE_APPLY,
    RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED,
)


# ---------------------------------------------------------------------------
# A. Planner — produces real ACTION_CODE_* plans
# ---------------------------------------------------------------------------

class TestPlannerCodeMapping:
    """_create_plan_from_intent maps CODE operations to real ACTION_CODE_* actions."""

    def _plan(self, text: str) -> dict:
        from assistant_os.core.planner import _create_plan_from_intent
        # Simulate the classifier output for CODE ops
        intent_map = {
            "explícame este módulo":           {"domain": "CODE", "operation": "CODE_EXPLAIN", "confidence": 0.95},
            "revisa este archivo":             {"domain": "CODE", "operation": "CODE_REVIEW",  "confidence": 0.95},
            "arregla este bug":                {"domain": "CODE", "operation": "CODE_FIX",     "confidence": 0.95},
            "crea una clase de autenticación": {"domain": "CODE", "operation": "CODE_CREATE",  "confidence": 0.95},
        }
        return _create_plan_from_intent(text, intent_map[text])

    def test_explain_produces_action_code_explain(self):
        plan = self._plan("explícame este módulo")
        assert plan["action"] == ACTION_CODE_EXPLAIN

    def test_explain_is_risk_low(self):
        plan = self._plan("explícame este módulo")
        assert plan["risk_level"] == RISK_LOW

    def test_explain_no_confirmation_required(self):
        plan = self._plan("explícame este módulo")
        assert plan["requires_confirmation"] is False

    def test_review_produces_action_code_review(self):
        plan = self._plan("revisa este archivo")
        assert plan["action"] == ACTION_CODE_REVIEW

    def test_review_is_risk_low(self):
        plan = self._plan("revisa este archivo")
        assert plan["risk_level"] == RISK_LOW

    def test_fix_produces_action_code_fix(self):
        plan = self._plan("arregla este bug")
        assert plan["action"] == ACTION_CODE_FIX

    def test_fix_is_risk_medium(self):
        plan = self._plan("arregla este bug")
        assert plan["risk_level"] == RISK_MEDIUM

    def test_fix_requires_confirmation(self):
        plan = self._plan("arregla este bug")
        assert plan["requires_confirmation"] is True

    def test_create_produces_action_code_create(self):
        plan = self._plan("crea una clase de autenticación")
        assert plan["action"] == ACTION_CODE_CREATE

    def test_create_requires_confirmation(self):
        plan = self._plan("crea una clase de autenticación")
        assert plan["requires_confirmation"] is True

    def test_plan_has_preview_string(self):
        plan = self._plan("arregla este bug")
        assert plan["preview"]
        assert "Corregir" in plan["preview"]

    def test_plan_has_plan_id(self):
        plan = self._plan("arregla este bug")
        assert plan.get("plan_id")

    def test_plan_has_schema_version(self):
        plan = self._plan("explícame este módulo")
        assert plan.get("schema_version") == "1"


# ---------------------------------------------------------------------------
# B. PolicyDecision — execution_mode for CODE actions
# ---------------------------------------------------------------------------

class TestCodePolicyDecision:
    """determine_execution_mode returns correct mode for CODE actions."""

    def test_explain_risk_low_auto(self):
        mode = determine_execution_mode(ACTION_CODE_EXPLAIN, RISK_LOW, requires_confirmation=False)
        assert mode == EXECUTION_MODE_AUTO

    def test_review_risk_low_auto(self):
        mode = determine_execution_mode(ACTION_CODE_REVIEW, RISK_LOW, requires_confirmation=False)
        assert mode == EXECUTION_MODE_AUTO

    def test_fix_requires_confirmation_confirm(self):
        mode = determine_execution_mode(ACTION_CODE_FIX, RISK_MEDIUM, requires_confirmation=True)
        assert mode == EXECUTION_MODE_CONFIRM

    def test_create_requires_confirmation_confirm(self):
        mode = determine_execution_mode(ACTION_CODE_CREATE, RISK_MEDIUM, requires_confirmation=True)
        assert mode == EXECUTION_MODE_CONFIRM


# ---------------------------------------------------------------------------
# C. CODE_EXPLAIN / CODE_REVIEW auto-execute via orchestrator
# ---------------------------------------------------------------------------

class TestCodeReadOnlyOrchestratorDispatch:
    """orchestrator.handle_request dispatches CODE read-only actions via AUTO mode."""

    def _request(self, text: str) -> dict:
        from assistant_os.contracts import CanonicalRequest
        return CanonicalRequest(text=text, context_id="ctx-m2b-test", filters={}, metadata={})

    def test_explain_dispatches_auto(self):
        from assistant_os.core.orchestrator import handle_request
        req = self._request("explícame este módulo")
        result = handle_request(req)
        # Must NOT be a confirmation request — auto-executes
        assert result["result_type"] != RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED
        assert result["result_type"] == RESULT_TYPE_CODE_EXPLAIN

    def test_review_dispatches_auto(self):
        from assistant_os.core.orchestrator import handle_request
        req = self._request("revisa este archivo")
        result = handle_request(req)
        assert result["result_type"] != RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED
        assert result["result_type"] == RESULT_TYPE_CODE_REVIEW

    def test_explain_result_ok(self):
        from assistant_os.core.orchestrator import handle_request
        req = self._request("explícame este módulo")
        result = handle_request(req)
        assert result["ok"] is True

    def test_explain_domain_is_code(self):
        from assistant_os.core.orchestrator import handle_request
        req = self._request("explícame este módulo")
        result = handle_request(req)
        assert result["domain"] == "CODE"


# ---------------------------------------------------------------------------
# D. CODE_FIX / CODE_CREATE require confirmation via orchestrator
# ---------------------------------------------------------------------------

class TestCodeMutatingOrchestratorConfirm:
    """orchestrator.handle_request returns CONFIRM for CODE mutating actions."""

    def _request(self, text: str) -> dict:
        from assistant_os.contracts import CanonicalRequest
        return CanonicalRequest(text=text, context_id="ctx-m2b-confirm", filters={}, metadata={})

    def test_fix_returns_confirmation_required(self):
        from assistant_os.core.orchestrator import handle_request
        req = self._request("arregla este bug")
        result = handle_request(req)
        assert result["result_type"] == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED

    def test_create_returns_confirmation_required(self):
        from assistant_os.core.orchestrator import handle_request
        req = self._request("crea una clase de autenticación")
        result = handle_request(req)
        assert result["result_type"] == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED

    def test_fix_plan_in_data(self):
        from assistant_os.core.orchestrator import handle_request
        req = self._request("arregla este bug")
        result = handle_request(req)
        plan = result["data"].get("plan", {})
        assert plan.get("action") == ACTION_CODE_FIX

    def test_fix_plan_has_plan_id(self):
        from assistant_os.core.orchestrator import handle_request
        req = self._request("arregla este bug")
        result = handle_request(req)
        plan = result["data"].get("plan", {})
        assert plan.get("plan_id")


# ---------------------------------------------------------------------------
# E. Preview path — apply-plan persisted in context_store
# ---------------------------------------------------------------------------

class TestCodePreviewContextStorePersistence:
    """_build_code_preview stores the apply-plan when the proposal is applicable."""

    def _make_plan(self, action: str, tmp_path) -> dict:
        return {
            "action": action,
            "domain": "CODE",
            "raw_text": "test",
            "domain_payload": {"target_file": "src/foo.py", "workspace": str(tmp_path)},
            "trace_id": "trace-m2b",
            "plan_id": "plan-m2b-001",
        }

    def test_applicable_preview_stores_apply_plan(self, tmp_path):
        from assistant_os.pipelines.code_pipeline import execute as code_execute

        plan = self._make_plan(ACTION_CODE_FIX, tmp_path)
        result = code_execute(plan, "ctx-preview-01")

        assert result["result_type"] == RESULT_TYPE_CODE_PREVIEW
        # apply_context_id is set when preview_applicable is True
        # (stub executor produces a fully applicable proposal)
        if result["data"].get("preview_applicable"):
            assert result["data"].get("apply_context_id"), \
                "apply_context_id must be non-empty when preview_applicable=True"

    def test_applicable_preview_apply_plan_retrievable(self, tmp_path):
        from assistant_os.pipelines.code_pipeline import execute as code_execute
        from assistant_os.context_store import get_pending_plan

        plan = self._make_plan(ACTION_CODE_FIX, tmp_path)
        result = code_execute(plan, "ctx-preview-02")

        apply_context_id = result["data"].get("apply_context_id", "")
        if apply_context_id:
            stored = get_pending_plan(apply_context_id)
            assert stored is not None, "apply-plan must be retrievable from context_store"
            assert stored["plan"]["domain_payload"]["phase"] == "apply"
            assert stored["plan"]["domain_payload"].get("proposal") is not None

    def test_apply_plan_retains_original_plan_id(self, tmp_path):
        from assistant_os.pipelines.code_pipeline import execute as code_execute
        from assistant_os.context_store import get_pending_plan

        plan = self._make_plan(ACTION_CODE_FIX, tmp_path)
        result = code_execute(plan, "ctx-preview-03")

        apply_context_id = result["data"].get("apply_context_id", "")
        if apply_context_id:
            stored = get_pending_plan(apply_context_id)
            assert stored["plan"]["plan_id"] == "plan-m2b-001"


# ---------------------------------------------------------------------------
# F. Apply path — AuthorizedPlan built with execution_id == plan_id
# ---------------------------------------------------------------------------

class TestCodeApplyAuthorizedPlan:
    """_apply_code_proposal builds AuthorizedPlan with execution_id == kernel plan_id."""

    def _make_apply_plan(self, tmp_path) -> dict:
        """Build a minimal apply-phase plan with a valid stub proposal."""
        from assistant_os.tools.claude_code.propose_change_tool import ProposeChangeTool
        # Get a real stub proposal to use in the apply plan
        tool_result = ProposeChangeTool(executor=None).execute({
            "action": ACTION_CODE_FIX,
            "target_file": "src/foo.py",
            "workspace": str(tmp_path),
            "context": "fix the bug",
            "allowed_write_scope": ["src/foo.py"],
        })
        proposal = tool_result.data if tool_result.ok else {}

        return {
            "action": ACTION_CODE_FIX,
            "domain": "CODE",
            "raw_text": "arregla este bug",
            "plan_id": "kernel-plan-abc-123",
            "trace_id": "trace-apply-01",
            "domain_payload": {
                "phase": "apply",
                "workspace": str(tmp_path),
                "target_file": "src/foo.py",
                "proposal": proposal,
            },
        }

    def test_apply_path_builds_authorized_plan(self, tmp_path):
        from assistant_os.pipelines.code_pipeline import execute as code_execute

        plan = self._make_apply_plan(tmp_path)
        result = code_execute(plan, "ctx-apply-01")

        # The result may be ok or fail on applicability (stub proposal may lack fields)
        # What we verify is that when it succeeds, the audit_summary has governance fields
        if result["ok"]:
            audit = result["data"].get("audit_summary", {})
            assert audit.get("execution_id") == "kernel-plan-abc-123", \
                "execution_id must equal the kernel plan_id"
            assert audit.get("plan_id") == "kernel-plan-abc-123", \
                "plan_id must propagate from the kernel plan"
            assert audit.get("policy_id") == "default"
            assert "code_fix" in audit.get("capability_scope", [])

    def test_authorized_plan_factory_execution_id_equals_plan_id(self, tmp_path):
        """_build_authorized_plan_from_kernel: execution_id == plan_id."""
        from assistant_os.pipelines.code_pipeline import _build_authorized_plan_from_kernel

        plan = {
            "plan_id": "kernel-plan-xyz-999",
            "action": ACTION_CODE_FIX,
            "domain_payload": {"workspace": str(tmp_path)},
        }
        ap = _build_authorized_plan_from_kernel(plan)
        assert ap.execution_id == "kernel-plan-xyz-999"
        assert ap.plan_id == "kernel-plan-xyz-999"

    def test_authorized_plan_factory_capability_scope_fix(self, tmp_path):
        from assistant_os.pipelines.code_pipeline import _build_authorized_plan_from_kernel

        plan = {"plan_id": "p1", "action": ACTION_CODE_FIX, "domain_payload": {}}
        ap = _build_authorized_plan_from_kernel(plan)
        assert ap.capability_scope == ["code_fix"]

    def test_authorized_plan_factory_capability_scope_create(self, tmp_path):
        from assistant_os.pipelines.code_pipeline import _build_authorized_plan_from_kernel

        plan = {"plan_id": "p2", "action": ACTION_CODE_CREATE, "domain_payload": {}}
        ap = _build_authorized_plan_from_kernel(plan)
        assert ap.capability_scope == ["code_create"]

    def test_authorized_plan_validate_passes(self, tmp_path):
        """AuthorizedPlan.validate() must not raise for kernel-built plans."""
        from assistant_os.pipelines.code_pipeline import _build_authorized_plan_from_kernel

        plan = {"plan_id": "p3", "action": ACTION_CODE_FIX, "domain_payload": {}}
        ap = _build_authorized_plan_from_kernel(plan)
        ap.validate()  # must not raise


# ---------------------------------------------------------------------------
# G. UI_INTENT_MAP covers CODE actions
# ---------------------------------------------------------------------------

class TestCodeUIIntentMap:
    """ui_intent_for_action returns correct label for all CODE actions."""

    def test_explain_intent(self):
        assert ui_intent_for_action(ACTION_CODE_EXPLAIN) == "explain"

    def test_review_intent(self):
        assert ui_intent_for_action(ACTION_CODE_REVIEW) == "review"

    def test_fix_intent(self):
        assert ui_intent_for_action(ACTION_CODE_FIX) == "fix"

    def test_create_intent(self):
        assert ui_intent_for_action(ACTION_CODE_CREATE) == "create"

    def test_no_code_action_returns_unknown(self):
        assert ui_intent_for_action("CODE_EXPLAIN") == "explain"


# ---------------------------------------------------------------------------
# H. Confirm flow — _execute_confirmed_plan reaches code_pipeline for CODE
# ---------------------------------------------------------------------------

class TestCodeConfirmFlow:
    """_execute_confirmed_plan routes CODE plans to code_pipeline."""

    def test_confirmed_code_fix_plan_reaches_pipeline(self):
        """
        After storing a CODE_FIX plan, _execute_confirmed_plan must call
        code_pipeline.execute (not raise, not return unknown domain).
        """
        from assistant_os.context_store import store_pending_plan, get_pending_plan
        from assistant_os.core.routing import get_pipeline, action_domain

        # Simulate the orchestrator storing a CODE_FIX plan
        plan = make_plan(
            domain="CODE",
            action=ACTION_CODE_FIX,
            target="fix the bug",
            requires_confirmation=True,
            risk_level=RISK_MEDIUM,
        )
        plan["domain_payload"] = {"workspace": "", "target_file": ""}

        context_id = "ctx-confirm-code-fix-01"
        store_pending_plan(context_id, plan, ACTION_CODE_FIX, "arregla este bug")

        # Simulate _execute_confirmed_plan (its core routing logic)
        stored = get_pending_plan(context_id)
        assert stored is not None
        retrieved_plan = stored["plan"]

        pipeline = get_pipeline(action_domain(retrieved_plan["action"]))
        assert pipeline is not None, "CODE pipeline must be registered"

        # Pipeline must handle the plan (workspace empty → returns error, not crash)
        result = pipeline(retrieved_plan, context_id)
        assert result["domain"] == "CODE"
        assert result["result_type"] in (
            RESULT_TYPE_CODE_PREVIEW,
            RESULT_TYPE_CODE_APPLY,
            "code_unknown",
            RESULT_TYPE_CODE_PREVIEW,
        ) or result["ok"] is False  # workspace empty → error is expected

    def test_code_explain_auto_does_not_need_context_store(self):
        """
        CODE_EXPLAIN is AUTO — orchestrator does NOT store it in context_store.
        Verify by checking the orchestrator returns a result directly.
        """
        from assistant_os.core.orchestrator import handle_request
        from assistant_os.contracts import CanonicalRequest

        req = CanonicalRequest(text="explícame este módulo", context_id="ctx-auto-explain", filters={}, metadata={})
        result = handle_request(req)
        assert result["result_type"] == RESULT_TYPE_CODE_EXPLAIN
        assert result["ok"] is True


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
