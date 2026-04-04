"""
ExecutionPlan → RunnerExecutionRequest boundary tests.

Validates the formal field map of _build_runner_execution_request:
  direct           — must come from domain_payload; absent → ExecutionPlanViolation
  derived          — mechanical extraction from authorized content; no reinterpretation
  transport        — metadata that identifies routing only
  omitted_permitted — fields explicitly None for CODE apply path

Five mandatory scenarios:
  1. Direct field absent       → explicit contract failure
  2. Derived valid             → correct extraction, no reinterpretation
  3. Derived invalid (filtered) → unsafe entries removed, not silently passed through
  4. Metadata                  → only transport keys present, no operational values
  5. Omitted fields            → explicitly None, not accidentally missing
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from assistant_os.contracts import ACTION_CODE_FIX, RISK_MEDIUM
from assistant_os.pipelines.code_pipeline import execute as code_execute


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(action: str, payload: dict | None = None) -> dict:
    import uuid
    return {
        "action": action,
        "domain": "CODE",
        "raw_text": "arregla el bug",
        "domain_payload": payload or {},
        "trace_id": "test_trace_epb",
        "plan_id": str(uuid.uuid4()),
        "risk_level": RISK_MEDIUM,
        "requires_confirmation": True,
    }


def _get_real_proposal(tmp_path) -> dict:
    """Run a preview and return the proposal envelope."""
    result = code_execute(
        _make_plan(ACTION_CODE_FIX, payload={
            "target_file": "src/foo.py",
            "workspace": str(tmp_path),
        }),
        "ctx-epb-preview",
    )
    assert result["ok"], f"preview failed: {result}"
    return result["data"]["proposal"]


RUNNER_PATCH = "assistant_os.executors.runner_backed_executor.RunnerBackedExecutor"


# ---------------------------------------------------------------------------
# 1. Direct field absent → explicit contract failure
# ---------------------------------------------------------------------------

class TestDirectFieldAbsent:
    """Each DIRECT field must be present in domain_payload; absence → ExecutionPlanViolation."""

    def test_workspace_absent_fails_explicitly(self, tmp_path):
        """Apply without workspace fails explicitly via _validate_workspace (InvalidWorkspace).

        workspace is a DIRECT field validated in _execute_mutating before
        _apply_code_proposal is reached.  The failure is explicit and immediate —
        not a silent fallback.
        """
        import assistant_os.pipelines.code_pipeline as cp
        orig_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            proposal = _get_real_proposal(tmp_path)
            apply_plan = _make_plan(ACTION_CODE_FIX, payload={
                "phase": "apply",
                "proposal": proposal,
                "execution_mode": "FULL_EXECUTE",
                # workspace intentionally absent
            })
            result = code_execute(apply_plan, "ctx-epb-1a")
        finally:
            cp._applied_proposals = orig_set

        assert not result["ok"]
        # _validate_workspace fires in _execute_mutating before _apply_code_proposal.
        assert result["error"]["type"] == "InvalidWorkspace", (
            f"Expected InvalidWorkspace, got: {result['error']}"
        )
        assert "workspace" in result["error"]["message"].lower()

    def test_execution_mode_absent_fails_explicitly(self, tmp_path):
        """Apply without execution_mode in domain_payload raises ExecutionPlanViolation."""
        import assistant_os.pipelines.code_pipeline as cp
        orig_set = cp._applied_proposals
        cp._applied_proposals = set()
        try:
            proposal = _get_real_proposal(tmp_path)
            apply_plan = _make_plan(ACTION_CODE_FIX, payload={
                "phase": "apply",
                "proposal": proposal,
                "workspace": str(tmp_path),
                # execution_mode intentionally absent
            })
            result = code_execute(apply_plan, "ctx-epb-1b")
        finally:
            cp._applied_proposals = orig_set

        assert not result["ok"]
        assert result["error"]["type"] == "ExecutionPlanViolation"
        assert result["data"]["guard_failure"] == "MissingExecutionMode"


# ---------------------------------------------------------------------------
# 2. Derived field valid → correct extraction, no reinterpretation
# ---------------------------------------------------------------------------

class TestDerivedFieldValid:
    """DERIVED fields must be extracted mechanically from authorized plan content."""

    def test_changes_extracted_from_proposal(self, tmp_path):
        """_build_runner_execution_request extracts changes from proposal unchanged."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "workspace": str(tmp_path),
            "execution_mode": "FULL_EXECUTE",
        })
        proposal = {
            "proposal_id": "p-deriv",
            "changes": [{"op": "file_replace", "path": "src/foo.py", "content": "hello"}],
        }
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, proposal, ap)
        assert req.changes == [{"op": "file_replace", "path": "src/foo.py", "content": "hello"}]

    def test_execution_id_equals_plan_id(self, tmp_path):
        """DERIVED: execution_id is a mechanical projection of plan_id."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "workspace": str(tmp_path),
            "execution_mode": "FULL_EXECUTE",
        })
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, {"proposal_id": "p-id", "changes": []}, ap)
        assert req.execution_id == plan["plan_id"]
        assert req.execution_id == ap.execution_id

    def test_repo_path_equals_workspace(self, tmp_path):
        """DIRECT: repo_path is exactly domain_payload['workspace'], no transformation."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "workspace": str(tmp_path),
            "execution_mode": "FULL_EXECUTE",
        })
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, {"proposal_id": "p-path", "changes": []}, ap)
        assert req.repo_path == str(tmp_path)


# ---------------------------------------------------------------------------
# 3. Derived field invalid → filtered, not silently passed through
# ---------------------------------------------------------------------------

class TestDerivedFieldFiltered:
    """Invalid derived content is removed by validation — never forwarded to runner."""

    def test_path_traversal_changes_filtered_to_none(self, tmp_path):
        """Changes with path traversal are filtered; result is None, not the unsafe entry."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "workspace": str(tmp_path),
            "execution_mode": "FULL_EXECUTE",
        })
        proposal = {
            "proposal_id": "p-trav",
            "changes": [
                {"op": "file_replace", "path": "../../etc/passwd", "content": "evil"},
            ],
        }
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, proposal, ap)
        assert req.changes is None, (
            f"Path traversal must be filtered; got {req.changes!r}"
        )

    def test_absolute_path_changes_filtered(self, tmp_path):
        """Changes with absolute paths are filtered, not passed through."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "workspace": str(tmp_path),
            "execution_mode": "FULL_EXECUTE",
        })
        proposal = {
            "proposal_id": "p-abs",
            "changes": [
                {"op": "file_replace", "path": "/etc/passwd", "content": "evil"},
            ],
        }
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, proposal, ap)
        assert req.changes is None

    def test_empty_content_changes_filtered(self, tmp_path):
        """Changes with empty content are filtered, not forwarded."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "workspace": str(tmp_path),
            "execution_mode": "FULL_EXECUTE",
        })
        proposal = {
            "proposal_id": "p-empty",
            "changes": [
                {"op": "file_replace", "path": "src/foo.py", "content": ""},
            ],
        }
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, proposal, ap)
        assert req.changes is None

    def test_valid_and_invalid_mixed_keeps_only_valid(self, tmp_path):
        """Mixed valid+invalid changes: only valid entries survive filtering."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "workspace": str(tmp_path),
            "execution_mode": "FULL_EXECUTE",
        })
        proposal = {
            "proposal_id": "p-mix",
            "changes": [
                {"op": "file_replace", "path": "../../evil.py", "content": "bad"},
                {"op": "file_replace", "path": "src/good.py", "content": "good"},
            ],
        }
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, proposal, ap)
        assert req.changes == [{"op": "file_replace", "path": "src/good.py", "content": "good"}]


# ---------------------------------------------------------------------------
# 4. Metadata — only transport keys, no operational values
# ---------------------------------------------------------------------------

class TestMetadataTransportOnly:
    """metadata must contain exactly the four transport keys; no operational data."""

    ALLOWED_KEYS = {"source", "domain", "action", "plan_id"}

    def test_metadata_key_set_is_exact(self, tmp_path):
        """metadata has exactly {source, domain, action, plan_id} — nothing else."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "workspace": str(tmp_path),
            "execution_mode": "FULL_EXECUTE",
        })
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, {"proposal_id": "p-meta", "changes": []}, ap)
        assert set(req.metadata.keys()) == self.ALLOWED_KEYS, (
            f"Unexpected metadata keys: {set(req.metadata.keys()) ^ self.ALLOWED_KEYS}"
        )

    def test_metadata_transport_constants(self, tmp_path):
        """source and domain are transport constants identifying pipeline origin."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "workspace": str(tmp_path),
            "execution_mode": "FULL_EXECUTE",
        })
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, {"proposal_id": "p-const", "changes": []}, ap)
        assert req.metadata["source"] == "assistant_os"
        assert req.metadata["domain"] == "CODE"

    def test_metadata_plan_fields_from_plan(self, tmp_path):
        """action and plan_id in metadata come from the plan, not invented."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "workspace": str(tmp_path),
            "execution_mode": "FULL_EXECUTE",
        })
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, {"proposal_id": "p-pf", "changes": []}, ap)
        assert req.metadata["action"] == ACTION_CODE_FIX
        assert req.metadata["plan_id"] == plan["plan_id"]

    def test_metadata_no_workspace_in_metadata(self, tmp_path):
        """workspace must NOT appear in metadata — it is repo_path, not a transport field."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "workspace": str(tmp_path),
            "execution_mode": "FULL_EXECUTE",
        })
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, {"proposal_id": "p-nw", "changes": []}, ap)
        assert "workspace" not in req.metadata
        assert "execution_mode" not in req.metadata


# ---------------------------------------------------------------------------
# 5. Omitted fields explicitly None
# ---------------------------------------------------------------------------

class TestOmittedFields:
    """OMITTED_PERMITTED fields must be explicitly None — not accidentally missing."""

    def test_omitted_fields_are_none(self, tmp_path):
        """base_commit, test_spec, validation_spec, workspace_spec, code are None."""
        from assistant_os.pipelines.code_pipeline import (
            _build_authorized_plan_from_kernel,
            _build_runner_execution_request,
        )
        plan = _make_plan(ACTION_CODE_FIX, payload={
            "workspace": str(tmp_path),
            "execution_mode": "FULL_EXECUTE",
        })
        ap = _build_authorized_plan_from_kernel(plan)
        req = _build_runner_execution_request(plan, {"proposal_id": "p-omit", "changes": []}, ap)

        assert req.base_commit is None,    "base_commit: CODE domain does not pin commits"
        assert req.test_spec is None,      "test_spec: not used in CODE pipeline"
        assert req.validation_spec is None, "validation_spec: not used in CODE pipeline"
        assert req.workspace_spec is None, "workspace_spec: not used in CODE pipeline"
        assert req.code is None,           "code: CODE_FIX/CREATE use file_replace, not inline code"
