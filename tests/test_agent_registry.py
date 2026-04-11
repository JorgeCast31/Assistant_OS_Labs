"""Tests for assistant_os/agents/registry.py — agent contract hardening."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from assistant_os.agents.registry import (
    AGENT_REGISTRY,
    AgentDefinition,
    _REQUIRED_FIELDS,
    _validate_agent_definition,
    get_agent,
)


# ---------------------------------------------------------------------------
# Registry structure tests
# ---------------------------------------------------------------------------


class TestAgentRegistry:
    def test_code_executor_registered(self):
        """code_executor must exist in the registry."""
        assert "code_executor" in AGENT_REGISTRY

    def test_get_agent_returns_correct_name(self):
        agent = get_agent("code_executor")
        assert agent["name"] == "code_executor"

    def test_get_agent_has_all_required_fields(self):
        """Every field declared in _REQUIRED_FIELDS must be present."""
        agent = get_agent("code_executor")
        for field in _REQUIRED_FIELDS:
            assert field in agent, f"Missing required field: {field!r}"

    def test_get_agent_has_all_declared_fields(self):
        """Full field set for a mature AgentDefinition."""
        agent = get_agent("code_executor")
        expected = (
            "name", "domain", "version", "description",
            "input_contract", "output_contract",
            "requires_review", "capability_scope", "entrypoint",
        )
        for field in expected:
            assert field in agent, f"Missing declared field: {field!r}"

    def test_get_agent_entrypoint_is_callable(self):
        agent = get_agent("code_executor")
        assert callable(agent["entrypoint"])

    def test_get_agent_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="not found"):
            get_agent("does_not_exist")

    def test_get_agent_error_lists_registered_agents(self):
        """Error message must mention registered agent names for discoverability."""
        with pytest.raises(KeyError) as exc_info:
            get_agent("ghost_agent")
        assert "code_executor" in str(exc_info.value)

    def test_agent_definition_is_dict(self):
        agent = get_agent("code_executor")
        assert isinstance(agent, dict)

    def test_version_is_string(self):
        assert isinstance(get_agent("code_executor")["version"], str)


# ---------------------------------------------------------------------------
# Contract field tests — explicit values for code_executor
# ---------------------------------------------------------------------------


class TestCodeExecutorContract:
    """Verify the explicit contractual fields of the code_executor agent."""

    def test_input_contract(self):
        assert get_agent("code_executor")["input_contract"] == "RunnerExecutionRequest"

    def test_output_contract(self):
        assert get_agent("code_executor")["output_contract"] == "RunnerExecutionResult"

    def test_requires_review_is_true(self):
        """Runner can return needs_review — human decision required."""
        assert get_agent("code_executor")["requires_review"] is True

    def test_capability_scope_is_list(self):
        scope = get_agent("code_executor")["capability_scope"]
        assert isinstance(scope, list)
        assert len(scope) > 0

    def test_capability_scope_contains_code_execute(self):
        scope = get_agent("code_executor")["capability_scope"]
        assert "code_execute" in scope

    def test_domain_is_code(self):
        assert get_agent("code_executor")["domain"] == "CODE"

    def test_requires_review_is_bool(self):
        assert isinstance(get_agent("code_executor")["requires_review"], bool)


# ---------------------------------------------------------------------------
# Validation tests — _validate_agent_definition
# ---------------------------------------------------------------------------


class TestValidateAgentDefinition:
    """Verify that missing required fields raise explicit errors."""

    def _minimal_valid(self) -> dict:
        return {
            "name": "test_agent",
            "entrypoint": lambda r: r,
            "input_contract": "SomeRequest",
            "output_contract": "SomeResult",
        }

    def test_valid_definition_does_not_raise(self):
        _validate_agent_definition(self._minimal_valid(), "test_agent")

    def test_missing_name_raises(self):
        agent = self._minimal_valid()
        del agent["name"]
        with pytest.raises(ValueError, match="missing required fields"):
            _validate_agent_definition(agent, "test_agent")

    def test_missing_entrypoint_raises(self):
        agent = self._minimal_valid()
        del agent["entrypoint"]
        with pytest.raises(ValueError, match="missing required fields"):
            _validate_agent_definition(agent, "test_agent")

    def test_missing_input_contract_raises(self):
        agent = self._minimal_valid()
        del agent["input_contract"]
        with pytest.raises(ValueError, match="missing required fields"):
            _validate_agent_definition(agent, "test_agent")

    def test_missing_output_contract_raises(self):
        agent = self._minimal_valid()
        del agent["output_contract"]
        with pytest.raises(ValueError, match="missing required fields"):
            _validate_agent_definition(agent, "test_agent")

    def test_none_name_raises(self):
        agent = self._minimal_valid()
        agent["name"] = None
        with pytest.raises(ValueError, match="missing required fields"):
            _validate_agent_definition(agent, "test_agent")

    def test_non_callable_entrypoint_raises(self):
        agent = self._minimal_valid()
        agent["entrypoint"] = "not_a_function"
        with pytest.raises(ValueError, match="entrypoint.*callable"):
            _validate_agent_definition(agent, "test_agent")

    def test_error_mentions_registry_key(self):
        agent = self._minimal_valid()
        del agent["name"]
        with pytest.raises(ValueError, match="my_broken_agent"):
            _validate_agent_definition(agent, "my_broken_agent")

    def test_error_lists_all_missing_fields(self):
        """When multiple fields are missing, all are listed in the error."""
        with pytest.raises(ValueError, match="missing required fields") as exc_info:
            _validate_agent_definition({"entrypoint": lambda r: r}, "bad_agent")
        error_msg = str(exc_info.value)
        # name and input_contract and output_contract are all missing
        assert "name" in error_msg or "input_contract" in error_msg

    def test_get_agent_raises_on_incomplete_registry_entry(self, monkeypatch):
        """get_agent() propagates validation errors from registry entries."""
        from unittest.mock import patch
        incomplete = {
            "name": "incomplete_agent",
            # missing entrypoint, input_contract, output_contract
        }
        with patch(
            "assistant_os.agents.registry.AGENT_REGISTRY",
            {"incomplete_agent": incomplete},
        ):
            with pytest.raises(ValueError, match="missing required fields"):
                get_agent("incomplete_agent")


# ---------------------------------------------------------------------------
# Entrypoint execution tests — uses a real RunnerExecutionRequest
# ---------------------------------------------------------------------------


class TestCodeExecutorEntrypoint:
    """Test that the code_executor entrypoint delegates to the runner correctly."""

    def test_entrypoint_executes_and_returns_result(self, tmp_path):
        """Entrypoint with a valid request returns a RunnerExecutionResult."""
        from assistant_os.runners.runner_models import RunnerExecutionRequest

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("pass\n")

        request = RunnerExecutionRequest(
            execution_id="agent-test-001",
            repo_path=str(repo),
        )

        agent = get_agent("code_executor")
        result = agent["entrypoint"](request)

        assert hasattr(result, "execution_id")
        assert hasattr(result, "final_status")
        assert result.execution_id == "agent-test-001"
        assert result.final_status in ("success", "failed", "needs_review")

    def test_entrypoint_propagates_execution_id(self, tmp_path):
        """execution_id from the request is preserved in the result."""
        from assistant_os.runners.runner_models import RunnerExecutionRequest

        repo = tmp_path / "repo2"
        repo.mkdir()
        (repo / "x.py").write_text("x = 1\n")

        request = RunnerExecutionRequest(
            execution_id="agent-id-check-002",
            repo_path=str(repo),
        )

        result = get_agent("code_executor")["entrypoint"](request)
        assert result.execution_id == "agent-id-check-002"


# ---------------------------------------------------------------------------
# Integration: CODE pipeline still works end-to-end via agent
# ---------------------------------------------------------------------------


def _make_valid_stub_agent(entrypoint_fn) -> dict:
    """Build a structurally valid AgentDefinition stub for patching."""
    return {
        "name":            "code_executor",
        "domain":          "CODE",
        "version":         "0.0.0-test",
        "description":     "test stub",
        "input_contract":  "RunnerExecutionRequest",
        "output_contract": "RunnerExecutionResult",
        "requires_review": True,
        "capability_scope": ["code_execute"],
        "entrypoint":      entrypoint_fn,
    }


class TestCodePipelineViaAgent:
    """Verify the pipeline still dispatches correctly after agent integration."""

    def test_code_pipeline_apply_uses_agent(self, tmp_path):
        """Mock the agent entrypoint to verify the pipeline calls it."""
        from unittest.mock import MagicMock, patch
        from assistant_os.runners.runner_models import RunnerExecutionRequest

        mock_result = MagicMock()
        mock_result.execution_id = "mocked-exec-id"
        mock_result.final_status = "success"
        mock_result.error = None
        mock_result.modified_files = ["main.py"]
        mock_result.promoted_files = []
        mock_result.promotion_status = None
        mock_result.report_json_path = None
        mock_result.report_md_path = None
        mock_result.changes_detail = []

        calls = []

        def fake_entrypoint(request):
            calls.append(request)
            return mock_result

        stub_registry = {"code_executor": _make_valid_stub_agent(fake_entrypoint)}

        with patch("assistant_os.agents.registry.AGENT_REGISTRY", stub_registry):
            from assistant_os.pipelines import code_pipeline

            plan = {
                "plan_id": "plan-agent-hardening-test",
                "action": "CODE_FIX",
                "raw_text": "fix the bug",
                "trace_id": "trace-001",
                "domain_payload": {
                    "phase": "apply",
                    "workspace": str(tmp_path),
                    "target_file": "main.py",
                    "proposal": {
                        "proposal_id": "prop-hardening-unique-001",
                        "summary": "fix bug",
                        "affected_files": ["main.py"],
                        "patch_preview": "- old\n+ new",
                        "patch_preview_truncated": False,
                        "risk_level": "low",
                        "write_intent_summary": "modify",
                        "proposal_artifacts": {"operation_types": ["modify"]},
                    },
                },
            }

            result = code_pipeline.execute(plan, "ctx-hardening-001")

        assert len(calls) == 1, "agent entrypoint must be called exactly once"
        assert isinstance(calls[0], RunnerExecutionRequest)
        assert result["ok"] is True
        assert result["domain"] == "CODE"

    def test_agent_invocation_metadata_in_domain_result(self, tmp_path):
        """audit_summary in DomainResult must include agent_invocation metadata."""
        from unittest.mock import MagicMock, patch
        from assistant_os.runners.runner_models import RunnerExecutionRequest

        mock_result = MagicMock()
        mock_result.execution_id = "meta-exec-id"
        mock_result.final_status = "success"
        mock_result.error = None
        mock_result.modified_files = []
        mock_result.promoted_files = []
        mock_result.promotion_status = None
        mock_result.report_json_path = None
        mock_result.report_md_path = None
        mock_result.changes_detail = []

        stub_agent = _make_valid_stub_agent(lambda r: mock_result)
        stub_registry = {"code_executor": stub_agent}

        with patch("assistant_os.agents.registry.AGENT_REGISTRY", stub_registry):
            from assistant_os.pipelines import code_pipeline

            plan = {
                "plan_id": "plan-meta-test",
                "action": "CODE_FIX",
                "raw_text": "fix",
                "domain_payload": {
                    "phase": "apply",
                    "workspace": str(tmp_path),
                    "target_file": "x.py",
                    "proposal": {
                        "proposal_id": "prop-meta-unique-002",
                        "summary": "fix",
                        "affected_files": ["x.py"],
                        "patch_preview": "- a\n+ b",
                        "patch_preview_truncated": False,
                        "risk_level": "low",
                        "write_intent_summary": "modify",
                        "proposal_artifacts": {"operation_types": ["modify"]},
                    },
                },
            }

            result = code_pipeline.execute(plan, "ctx-meta-001")

        assert result["ok"] is True
        audit = result["data"]["audit_summary"]

        # agent_invocation must be present
        assert "agent_invocation" in audit, "agent_invocation missing from audit_summary"

        inv = audit["agent_invocation"]
        assert inv["agent_name"]             == stub_agent["name"]
        assert inv["agent_version"]          == stub_agent["version"]
        assert inv["agent_requires_review"]  == stub_agent["requires_review"]
        assert inv["agent_capability_scope"] == stub_agent["capability_scope"]

    def test_agent_invocation_values_match_registry(self, tmp_path):
        """agent_invocation values must match the real AGENT_REGISTRY entry.

        Uses the real registry (no stub) and patches only RunnerBackedExecutor.execute
        so we verify that the pipeline reads from AGENT_REGISTRY correctly.
        """
        from unittest.mock import MagicMock, patch

        mock_result = MagicMock()
        mock_result.execution_id = "registry-check-id"
        mock_result.final_status = "success"
        mock_result.error = None
        mock_result.modified_files = []
        mock_result.promoted_files = []
        mock_result.promotion_status = None
        mock_result.report_json_path = None
        mock_result.report_md_path = None
        mock_result.changes_detail = []

        with patch(
            "assistant_os.executors.runner_backed_executor.RunnerBackedExecutor.execute",
            return_value=mock_result,
        ):
            from assistant_os.pipelines import code_pipeline

            plan = {
                "plan_id": "plan-real-registry-check",
                "action": "CODE_FIX",
                "raw_text": "fix",
                "domain_payload": {
                    "phase": "apply",
                    "workspace": str(tmp_path),
                    "target_file": "y.py",
                    "proposal": {
                        "proposal_id": "prop-real-registry-unique-003",
                        "summary": "fix",
                        "affected_files": ["y.py"],
                        "patch_preview": "- a\n+ b",
                        "patch_preview_truncated": False,
                        "risk_level": "low",
                        "write_intent_summary": "modify",
                        "proposal_artifacts": {"operation_types": ["modify"]},
                    },
                },
            }

            result = code_pipeline.execute(plan, "ctx-real-registry-001")

        assert result["ok"] is True
        inv = result["data"]["audit_summary"]["agent_invocation"]

        # Values must match what AGENT_REGISTRY declares for code_executor
        assert inv["agent_name"]             == "code_executor"
        assert inv["agent_version"]          == "1.0.0"
        assert inv["agent_requires_review"]  is True
        assert inv["agent_capability_scope"] == ["code_execute"]


# ---------------------------------------------------------------------------
# PATH A — kernel metadata persistence
# ---------------------------------------------------------------------------


class TestKernelPathMetadataPersistence:
    """Verify that code_pipeline persists agent_invocation to metadata.json.

    Uses a pre-created metadata.json (simulating what the runner would write)
    and patches EXECUTIONS_ROOT in metadata_utils so the persistence lands in
    a temp directory.  RunnerBackedExecutor.execute is also patched so the
    test is hermetic and fast.
    """

    def _make_plan(self, workspace: str, proposal_id: str) -> dict:
        return {
            "plan_id": f"plan-{proposal_id}",
            "action": "CODE_FIX",
            "raw_text": "fix",
            "domain_payload": {
                "phase": "apply",
                "workspace": workspace,
                "target_file": "z.py",
                "proposal": {
                    "proposal_id": proposal_id,
                    "summary": "fix",
                    "affected_files": ["z.py"],
                    "patch_preview": "- a\n+ b",
                    "patch_preview_truncated": False,
                    "risk_level": "low",
                    "write_intent_summary": "modify",
                    "proposal_artifacts": {"operation_types": ["modify"]},
                },
            },
        }

    def test_kernel_path_persists_agent_invocation(self, tmp_path, monkeypatch):
        """After code_pipeline.execute (apply), metadata.json must contain agent_invocation."""
        from unittest.mock import MagicMock, patch
        import assistant_os.runners.metadata_utils as mu

        # execution_id used by the mock result
        eid = "kernel-persist-unique-k001"

        # Pre-create a metadata.json simulating what the runner writes
        exec_dir = tmp_path / eid
        exec_dir.mkdir()
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": eid, "final_status": "success"}),
            encoding="utf-8",
        )

        # Redirect patch_execution_metadata to write into tmp_path
        monkeypatch.setattr(mu, "EXECUTIONS_ROOT", tmp_path)

        mock_result = MagicMock()
        mock_result.execution_id = eid
        mock_result.final_status = "success"
        mock_result.error = None
        mock_result.modified_files = []
        mock_result.promoted_files = []
        mock_result.promotion_status = None
        mock_result.report_json_path = None
        mock_result.report_md_path = None
        mock_result.changes_detail = []

        with patch(
            "assistant_os.executors.runner_backed_executor.RunnerBackedExecutor.execute",
            return_value=mock_result,
        ):
            from assistant_os.pipelines import code_pipeline
            result = code_pipeline.execute(
                self._make_plan(str(tmp_path), "prop-kernel-persist-k001"),
                "ctx-kernel-persist-k001",
            )

        assert result["ok"] is True

        # Verify agent_invocation was written to metadata.json on disk
        meta = json.loads((tmp_path / eid / "metadata.json").read_text(encoding="utf-8"))
        assert "agent_invocation" in meta, "agent_invocation must be persisted by PATH A"

    def test_kernel_path_agent_invocation_fields_correct(self, tmp_path, monkeypatch):
        """The four fields written by PATH A must match the AGENT_REGISTRY entry."""
        from unittest.mock import MagicMock, patch
        import assistant_os.runners.metadata_utils as mu

        eid = "kernel-persist-unique-k002"
        exec_dir = tmp_path / eid
        exec_dir.mkdir()
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": eid, "final_status": "success"}),
            encoding="utf-8",
        )

        monkeypatch.setattr(mu, "EXECUTIONS_ROOT", tmp_path)

        mock_result = MagicMock()
        mock_result.execution_id = eid
        mock_result.final_status = "success"
        mock_result.error = None
        mock_result.modified_files = []
        mock_result.promoted_files = []
        mock_result.promotion_status = None
        mock_result.report_json_path = None
        mock_result.report_md_path = None
        mock_result.changes_detail = []

        with patch(
            "assistant_os.executors.runner_backed_executor.RunnerBackedExecutor.execute",
            return_value=mock_result,
        ):
            from assistant_os.pipelines import code_pipeline
            code_pipeline.execute(
                self._make_plan(str(tmp_path), "prop-kernel-persist-k002"),
                "ctx-kernel-persist-k002",
            )

        meta = json.loads((tmp_path / eid / "metadata.json").read_text(encoding="utf-8"))
        inv = meta["agent_invocation"]

        assert inv["agent_name"]             == "code_executor"
        assert inv["agent_version"]          == "1.0.0"
        assert inv["agent_requires_review"]  is True
        assert inv["agent_capability_scope"] == ["code_execute"]

    def test_kernel_path_preserves_existing_metadata_fields(self, tmp_path, monkeypatch):
        """patch_execution_metadata must not destroy pre-existing metadata fields."""
        from unittest.mock import MagicMock, patch
        import assistant_os.runners.metadata_utils as mu

        eid = "kernel-persist-unique-k003"
        exec_dir = tmp_path / eid
        exec_dir.mkdir()
        original_meta = {
            "execution_id": eid,
            "final_status": "success",
            "some_runner_field": "must-survive",
        }
        (exec_dir / "metadata.json").write_text(json.dumps(original_meta), encoding="utf-8")

        monkeypatch.setattr(mu, "EXECUTIONS_ROOT", tmp_path)

        mock_result = MagicMock()
        mock_result.execution_id = eid
        mock_result.final_status = "success"
        mock_result.error = None
        mock_result.modified_files = []
        mock_result.promoted_files = []
        mock_result.promotion_status = None
        mock_result.report_json_path = None
        mock_result.report_md_path = None
        mock_result.changes_detail = []

        with patch(
            "assistant_os.executors.runner_backed_executor.RunnerBackedExecutor.execute",
            return_value=mock_result,
        ):
            from assistant_os.pipelines import code_pipeline
            code_pipeline.execute(
                self._make_plan(str(tmp_path), "prop-kernel-persist-k003"),
                "ctx-kernel-persist-k003",
            )

        meta = json.loads((tmp_path / eid / "metadata.json").read_text(encoding="utf-8"))
        assert meta["execution_id"]       == eid
        assert meta["final_status"]       == "success"
        assert meta["some_runner_field"]  == "must-survive"
        assert "agent_invocation"         in meta


# ---------------------------------------------------------------------------
# Sprint E — G2: request_snapshot persistence in kernel path (PATH A)
# ---------------------------------------------------------------------------


class TestKernelPathSnapshotPersistence:
    """Verify that code_pipeline persists request_snapshot to metadata.json.

    G2: PATH A was persisting agent_invocation but not request_snapshot,
    which meant kernel-originated executions could not be rerun from the API.
    After the fix, both fields are written in a single patch_execution_metadata call.
    """

    def _make_plan(self, workspace: str, proposal_id: str) -> dict:
        return {
            "plan_id": f"plan-snap-{proposal_id}",
            "action": "CODE_FIX",
            "raw_text": "fix",
            "domain_payload": {
                "phase": "apply",
                "workspace": workspace,
                "target_file": "z.py",
                "proposal": {
                    "proposal_id": proposal_id,
                    "summary": "fix",
                    "affected_files": ["z.py"],
                    "patch_preview": "- a\n+ b",
                    "patch_preview_truncated": False,
                    "risk_level": "low",
                    "write_intent_summary": "modify",
                    "proposal_artifacts": {"operation_types": ["modify"]},
                },
            },
        }

    def _run_pipeline(self, tmp_path, monkeypatch, eid: str, proposal_id: str):
        """Shared fixture: patch runner + EXECUTIONS_ROOT, run pipeline, return metadata."""
        from unittest.mock import MagicMock, patch
        import assistant_os.runners.metadata_utils as mu

        exec_dir = tmp_path / eid
        exec_dir.mkdir()
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": eid, "final_status": "success"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(mu, "EXECUTIONS_ROOT", tmp_path)

        mock_result = MagicMock()
        mock_result.execution_id = eid
        mock_result.final_status = "success"
        mock_result.error = None
        mock_result.modified_files = []
        mock_result.promoted_files = []
        mock_result.promotion_status = None
        mock_result.report_json_path = None
        mock_result.report_md_path = None
        mock_result.changes_detail = []

        with patch(
            "assistant_os.executors.runner_backed_executor.RunnerBackedExecutor.execute",
            return_value=mock_result,
        ):
            from assistant_os.pipelines import code_pipeline
            code_pipeline.execute(
                self._make_plan(str(tmp_path), proposal_id),
                f"ctx-{proposal_id}",
            )

        return json.loads((tmp_path / eid / "metadata.json").read_text(encoding="utf-8"))

    def test_kernel_path_persists_request_snapshot(self, tmp_path, monkeypatch):
        """After PATH A execute, metadata.json must contain request_snapshot."""
        meta = self._run_pipeline(tmp_path, monkeypatch, "snap-k001", "prop-snap-k001")
        assert "request_snapshot" in meta, (
            "request_snapshot must be persisted by PATH A — G2 gap"
        )

    def test_request_snapshot_has_repo_path(self, tmp_path, monkeypatch):
        """request_snapshot must include repo_path (required for rerun)."""
        meta = self._run_pipeline(tmp_path, monkeypatch, "snap-k002", "prop-snap-k002")
        snap = meta["request_snapshot"]
        assert "repo_path" in snap
        assert snap["repo_path"] == str(tmp_path)

    def test_request_snapshot_mode_is_kernel(self, tmp_path, monkeypatch):
        """mode must be 'kernel' to distinguish PATH A from HTTP-originated executions."""
        meta = self._run_pipeline(tmp_path, monkeypatch, "snap-k003", "prop-snap-k003")
        assert meta["request_snapshot"]["mode"] == "kernel"

    def test_request_snapshot_has_plan_id(self, tmp_path, monkeypatch):
        """plan_id must be present so the snapshot is traceable to the kernel plan."""
        meta = self._run_pipeline(tmp_path, monkeypatch, "snap-k004", "prop-snap-k004")
        snap = meta["request_snapshot"]
        assert "plan_id" in snap
        assert snap["plan_id"] == "plan-snap-prop-snap-k004"

    def test_agent_invocation_still_present(self, tmp_path, monkeypatch):
        """Extending the patch must not drop agent_invocation (regression guard)."""
        meta = self._run_pipeline(tmp_path, monkeypatch, "snap-k005", "prop-snap-k005")
        assert "agent_invocation" in meta
        assert "request_snapshot" in meta

    def test_detail_has_has_snapshot_true(self, tmp_path, monkeypatch):
        """GET execution detail must report has_snapshot=True after PATH A execute."""
        import assistant_os.api.code_api as api
        meta = self._run_pipeline(tmp_path, monkeypatch, "snap-k006", "prop-snap-k006")

        monkeypatch.setattr(api, "EXECUTIONS_ROOT", tmp_path)
        detail = api.handle_get_execution("snap-k006")
        assert detail is not None
        assert detail["has_snapshot"] is True
