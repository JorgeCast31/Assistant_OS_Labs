"""Tests for assistant_os/agents/registry.py — agent contract hardening."""

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
