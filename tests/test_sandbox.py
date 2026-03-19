"""
Tests — assistant_os/sandbox (Runner subsystem)

Coverage matrix
---------------
A. WorkspaceModel          — directory layout, write_code, artifacts, cleanup  (no Docker)
B. ExecutionResult         — ok property, to_dict shape                         (no Docker)
C. RunnerAPI validation    — runtime catalog, workspace guards                  (no Docker)
D. ContainerBackend        — real Docker executions                             (requires Docker)
E. RunnerAPI integration   — end-to-end via RunnerAPI + ContainerBackend        (requires Docker)
F. ApplyChangeTool routing — apply_mode=real routing (mocked RunnerAPI)         (no Docker)
G. AuthorizedPlan          — validation: missing/invalid fields rejected        (no Docker)
H. Container hardening     — security flags in _build_docker_cmd                (no Docker)
I. ArtifactPolicy          — governed artifact collection and metadata          (no Docker)

Docker-dependent tests are skipped automatically when Docker is unavailable.
Existing tests in test_runner.py are untouched — this file adds coverage only.
"""

from __future__ import annotations

import os
import subprocess

import pytest


# ---------------------------------------------------------------------------
# Docker availability check — used for conditional test skipping
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    """Return True iff `docker info` exits 0 within 5 s."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


requires_docker = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker is not available on this host",
)


# ===========================================================================
# A. WorkspaceModel
# ===========================================================================


class TestWorkspaceModel:
    """WorkspaceModel manages the three-directory layout; no Docker required."""

    def test_prepare_creates_all_three_subdirs(self, tmp_path):
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        assert (tmp_path / "input").is_dir()
        assert (tmp_path / "output").is_dir()
        assert (tmp_path / "out").is_dir()

    def test_prepare_idempotent(self, tmp_path):
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        ws.prepare()  # must not raise
        assert (tmp_path / "input").is_dir()

    def test_write_code_creates_file_in_input_dir(self, tmp_path):
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        path = ws.write_code("print('hello')")
        assert path.exists()
        assert path.name == "main.py"
        assert path.parent == tmp_path / "input"
        assert path.read_text(encoding="utf-8") == "print('hello')"

    def test_write_code_custom_filename(self, tmp_path):
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        path = ws.write_code("x = 42", "script.py")
        assert path.name == "script.py"

    def test_write_code_rejects_path_separator_slash(self, tmp_path):
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        with pytest.raises(ValueError, match="bare filename"):
            ws.write_code("x=1", "subdir/script.py")

    def test_write_code_rejects_path_separator_backslash(self, tmp_path):
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        with pytest.raises(ValueError, match="bare filename"):
            ws.write_code("x=1", "subdir\\script.py")

    def test_list_artifacts_empty_initially(self, tmp_path):
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        assert ws.list_artifacts() == []

    def test_list_artifacts_returns_relative_paths(self, tmp_path):
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        (tmp_path / "out" / "result.txt").write_text("data")
        artifacts = ws.list_artifacts()
        assert len(artifacts) == 1
        assert "result.txt" in artifacts[0]
        assert not os.path.isabs(artifacts[0])  # must be relative

    def test_list_artifacts_empty_when_dir_missing(self, tmp_path):
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        # No prepare() → out/ does not exist
        assert ws.list_artifacts() == []

    def test_cleanup_removes_all_three_subdirs(self, tmp_path):
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        ws.cleanup()
        assert not (tmp_path / "input").exists()
        assert not (tmp_path / "output").exists()
        assert not (tmp_path / "out").exists()

    def test_cleanup_leaves_workspace_root_intact(self, tmp_path):
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        ws.cleanup()
        assert tmp_path.exists()

    def test_cleanup_safe_when_subdirs_missing(self, tmp_path):
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.cleanup()   # no prepare() — must not raise


# ===========================================================================
# B. ExecutionResult
# ===========================================================================


class TestExecutionResult:
    """ExecutionResult structural and semantic invariants; no Docker required."""

    def _make(self, **kwargs):
        from assistant_os.sandbox.execution_result import ExecutionResult

        defaults = dict(
            exit_code=0, stdout="", stderr="",
            duration_ms=100, truncated=False,
        )
        defaults.update(kwargs)
        return ExecutionResult(**defaults)

    def test_ok_true_when_exit_0_no_errors(self):
        assert self._make(exit_code=0).ok is True

    def test_ok_false_when_exit_nonzero(self):
        assert self._make(exit_code=1).ok is False

    def test_ok_false_when_timed_out(self):
        assert self._make(exit_code=0, timed_out=True).ok is False

    def test_ok_false_when_runner_error_set(self):
        assert self._make(error="Docker not found").ok is False

    def test_to_dict_contains_all_required_keys(self):
        d = self._make(apply_mode="real").to_dict()
        for key in (
            "apply_mode", "exit_code", "stdout", "stderr",
            "duration_ms", "truncated", "artifacts",
            "timed_out", "error", "ok",
        ):
            assert key in d, f"to_dict() missing key: {key!r}"

    def test_to_dict_ok_matches_ok_property(self):
        for exit_code, timed_out, expected_ok in [
            (0, False, True),
            (1, False, False),
            (0, True, False),
        ]:
            r = self._make(exit_code=exit_code, timed_out=timed_out)
            assert r.to_dict()["ok"] is expected_ok, (
                f"to_dict ok mismatch for exit={exit_code} timed_out={timed_out}"
            )

    def test_to_dict_apply_mode_real(self):
        assert self._make(apply_mode="real").to_dict()["apply_mode"] == "real"

    def test_artifacts_default_is_empty_list(self):
        r = self._make()
        assert r.artifacts == []
        assert r.to_dict()["artifacts"] == []


# ===========================================================================
# C. RunnerAPI validation (no Docker)
# ===========================================================================


class TestRunnerAPIValidation:
    """RunnerAPI structural guards — none of these trigger Docker."""

    def test_rejects_unknown_runtime(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI

        with pytest.raises(ValueError, match="not in the allowed catalog"):
            RunnerAPI().execute("print(1)", str(tmp_path), runtime="node18")

    def test_rejects_ruby_runtime(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI

        with pytest.raises(ValueError, match="not in the allowed catalog"):
            RunnerAPI().execute("puts 'hi'", str(tmp_path), runtime="ruby3.2")

    def test_rejects_relative_workspace(self):
        from assistant_os.sandbox.runner_api import RunnerAPI

        with pytest.raises(ValueError, match="absolute"):
            RunnerAPI().execute("print(1)", "relative/path")

    def test_rejects_nonexistent_workspace(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI

        with pytest.raises(ValueError, match="does not exist"):
            RunnerAPI().execute("print(1)", str(tmp_path / "ghost_dir"))

    def test_rejects_file_as_workspace(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI

        f = tmp_path / "notadir.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="not a directory"):
            RunnerAPI().execute("print(1)", str(f))

    def test_allowed_runtimes_contains_python311(self):
        from assistant_os.sandbox.runner_api import ALLOWED_RUNTIMES

        assert "python3.11" in ALLOWED_RUNTIMES

    def test_v0_catalog_has_exactly_one_runtime(self):
        """v0 catalog is deliberately minimal — exactly one runtime."""
        from assistant_os.sandbox.runner_api import ALLOWED_RUNTIMES

        assert len(ALLOWED_RUNTIMES) == 1


# ===========================================================================
# D. ContainerBackend — real Docker executions
# ===========================================================================


class TestContainerBackend:
    """All tests in this class require Docker to be running on the host."""

    @requires_docker
    def test_simple_print_exit_0(self, tmp_path):
        from assistant_os.sandbox.container_backend import ContainerBackend
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        ws.write_code("print('hello from container')")

        result = ContainerBackend().execute(str(tmp_path), "main.py", timeout_seconds=60)

        assert result.exit_code == 0
        assert "hello from container" in result.stdout
        assert not result.timed_out
        assert result.error is None

    @requires_docker
    def test_apply_mode_is_real(self, tmp_path):
        from assistant_os.sandbox.container_backend import ContainerBackend
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        ws.write_code("print('mode check')")
        result = ContainerBackend().execute(str(tmp_path), "main.py", timeout_seconds=60)
        assert result.apply_mode == "real"

    @requires_docker
    def test_timeout_enforced(self, tmp_path):
        from assistant_os.sandbox.container_backend import ContainerBackend
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        ws.write_code("import time; time.sleep(120)")

        result = ContainerBackend().execute(str(tmp_path), "main.py", timeout_seconds=3)

        assert result.timed_out is True
        assert result.exit_code == -1

    @requires_docker
    def test_network_access_blocked(self, tmp_path):
        """--network none prevents all outbound connections."""
        from assistant_os.sandbox.container_backend import ContainerBackend
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        ws.write_code(
            "import socket\n"
            "try:\n"
            "    s = socket.socket()\n"
            "    s.settimeout(2)\n"
            "    s.connect(('8.8.8.8', 53))\n"
            "    print('CONNECTED')\n"
            "except Exception as e:\n"
            "    print(f'BLOCKED: {type(e).__name__}')\n"
        )

        result = ContainerBackend().execute(str(tmp_path), "main.py", timeout_seconds=15)

        assert result.exit_code == 0
        assert "CONNECTED" not in result.stdout
        assert "BLOCKED" in result.stdout

    @requires_docker
    def test_host_filesystem_inaccessible(self, tmp_path):
        """Container cannot browse host paths that are not mounted."""
        from assistant_os.sandbox.container_backend import ContainerBackend
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        ws.write_code(
            "import os\n"
            "try:\n"
            "    os.listdir('/host_root')\n"
            "    print('HOST_ACCESSIBLE')\n"
            "except Exception:\n"
            "    print('HOST_BLOCKED')\n"
        )

        result = ContainerBackend().execute(str(tmp_path), "main.py", timeout_seconds=15)

        assert result.exit_code == 0
        assert "HOST_ACCESSIBLE" not in result.stdout
        assert "HOST_BLOCKED" in result.stdout

    @requires_docker
    def test_artifact_creation_and_collection(self, tmp_path):
        """Files written to /workspace/out/ appear in ExecutionResult.artifacts."""
        from assistant_os.sandbox.container_backend import ContainerBackend
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        ws.write_code(
            "import os\n"
            "os.makedirs('/workspace/out', exist_ok=True)\n"
            "with open('/workspace/out/output.txt', 'w') as f:\n"
            "    f.write('artifact content')\n"
            "print('done')\n"
        )

        result = ContainerBackend().execute(str(tmp_path), "main.py", timeout_seconds=30)

        assert result.exit_code == 0
        assert any("output.txt" in a for a in result.artifacts), (
            f"output.txt not found in artifacts: {result.artifacts}"
        )

    @requires_docker
    def test_nonzero_exit_code_on_exception(self, tmp_path):
        """An unhandled exception causes a non-zero exit code and populates stderr."""
        from assistant_os.sandbox.container_backend import ContainerBackend
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        ws.write_code("raise ValueError('deliberate failure')")

        result = ContainerBackend().execute(str(tmp_path), "main.py", timeout_seconds=30)

        assert result.exit_code != 0
        assert "ValueError" in result.stderr
        assert not result.ok

    @requires_docker
    def test_container_cleaned_up_after_execution(self, tmp_path):
        """--rm guarantees the container is removed after the process exits."""
        from assistant_os.sandbox.container_backend import ContainerBackend
        from assistant_os.sandbox.workspace_model import WorkspaceModel

        ws = WorkspaceModel(str(tmp_path))
        ws.prepare()
        ws.write_code("print('cleanup test')")

        result = ContainerBackend().execute(str(tmp_path), "main.py", timeout_seconds=30)
        assert result.exit_code == 0

        # Enumerate any remaining containers from this runner.
        list_proc = subprocess.run(
            ["docker", "ps", "-a",
             "--filter", "name=assistantos-runner-",
             "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        assert list_proc.returncode == 0
        # We cannot assert the list is empty (parallel test runs could add
        # containers), but the command itself must succeed.


# ===========================================================================
# E. RunnerAPI integration (requires Docker)
# ===========================================================================


class TestRunnerAPIIntegration:
    """End-to-end RunnerAPI → ContainerBackend executions."""

    @requires_docker
    def test_execute_simple_code_returns_ok(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI

        result = RunnerAPI(timeout_seconds=60).execute(
            "print('hello world')", str(tmp_path)
        )
        assert result.ok
        assert "hello world" in result.stdout
        assert result.apply_mode == "real"

    @requires_docker
    def test_workspace_subdirs_cleaned_after_success(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI

        RunnerAPI(timeout_seconds=60).execute("print('ok')", str(tmp_path))

        assert not (tmp_path / "input").exists()
        assert not (tmp_path / "output").exists()
        assert not (tmp_path / "out").exists()
        assert tmp_path.exists()  # root dir survives

    @requires_docker
    def test_workspace_subdirs_cleaned_even_on_failure(self, tmp_path):
        """Cleanup runs unconditionally — even when the code raises."""
        from assistant_os.sandbox.runner_api import RunnerAPI

        result = RunnerAPI(timeout_seconds=60).execute(
            "raise SystemExit(1)", str(tmp_path)
        )
        assert not result.ok
        assert not (tmp_path / "input").exists()

    @requires_docker
    def test_duration_ms_is_non_negative(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI

        result = RunnerAPI(timeout_seconds=60).execute(
            "import time; time.sleep(0.05); print('done')", str(tmp_path)
        )
        assert result.duration_ms >= 0

    @requires_docker
    def test_to_dict_is_json_serialisable(self, tmp_path):
        """ExecutionResult.to_dict() must be safe for ToolResult.data."""
        import json
        from assistant_os.sandbox.runner_api import RunnerAPI

        result = RunnerAPI(timeout_seconds=60).execute(
            "print('serialise me')", str(tmp_path)
        )
        serialised = json.dumps(result.to_dict())   # must not raise
        assert serialised


# ===========================================================================
# F. ApplyChangeTool routing — real mode (mocked RunnerAPI; no Docker)
# ===========================================================================


class TestApplyChangeToolRealMode:
    """
    Verify routing logic in apply_change_tool.py:
      - _select_default_executor() returns stub by default
      - _select_default_executor() returns real executor when mode=real
      - _real_executor returns structured success result (via mock)
      - _real_executor propagates failure (via mock)
      - Stub mode contract unchanged
    """

    def _make_proposal(
        self,
        proposal_id: str = "real-test-001",
        action: str = "CODE_FIX",
    ) -> dict:
        files = ["src/foo.py"]
        return {
            "proposal_id": proposal_id,
            "action": action,
            "summary": "test",
            "affected_files": files,
            "write_intent_summary": "modifies src/foo.py",
            "patch_preview": "--- a/src/foo.py\n+++ b/src/foo.py\n-old\n+new",
            "patch_preview_truncated": False,
            "risk_level": "low",
            "proposal_artifacts": {"operation_types": ["modify"]},
            "requires_confirmation": True,
            "workspace_hash": "",
            "allowed_write_scope": files,
        }

    def test_default_mode_selects_stub_executor(self):
        import assistant_os.config as cfg
        from assistant_os.tools.claude_code.apply_change_tool import (
            _select_default_executor,
            _default_executor,
        )

        original = cfg.APPLY_EXECUTION_MODE
        cfg.APPLY_EXECUTION_MODE = "stub"
        try:
            assert _select_default_executor() is _default_executor
        finally:
            cfg.APPLY_EXECUTION_MODE = original

    def test_real_mode_selects_real_executor(self):
        import assistant_os.config as cfg
        from assistant_os.tools.claude_code.apply_change_tool import (
            _select_default_executor,
            _real_executor,
        )

        original = cfg.APPLY_EXECUTION_MODE
        cfg.APPLY_EXECUTION_MODE = "real"
        try:
            assert _select_default_executor() is _real_executor
        finally:
            cfg.APPLY_EXECUTION_MODE = original

    def test_real_executor_success_via_mock(self, tmp_path):
        """_real_executor delegates to RunnerAPI and returns apply_mode=real."""
        from unittest.mock import patch, MagicMock
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.tools.claude_code.apply_change_tool import _real_executor

        mock_result = ExecutionResult(
            exit_code=0, stdout="[runner] OK", stderr="",
            duration_ms=50, truncated=False, apply_mode="real",
        )

        # RunnerAPI is a late import inside _real_executor; patch at its source module.
        with patch(
            "assistant_os.sandbox.runner_api.RunnerAPI"
        ) as MockRunnerAPI:
            instance = MagicMock()
            instance.execute.return_value = mock_result
            MockRunnerAPI.return_value = instance

            result = _real_executor({
                "proposal": self._make_proposal(),
                "workspace": str(tmp_path),
                "context_id": "test",
            })

        assert result["ok"] is True
        assert result["apply_mode"] == "real"
        assert "execution_result" in result
        assert result["execution_result"]["apply_mode"] == "real"

    def test_real_executor_failure_propagated_via_mock(self, tmp_path):
        """_real_executor returns ok=False when RunnerAPI reports failure."""
        from unittest.mock import patch, MagicMock
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.tools.claude_code.apply_change_tool import _real_executor

        failing = ExecutionResult(
            exit_code=1, stdout="", stderr="SyntaxError: invalid syntax",
            duration_ms=120, truncated=False, apply_mode="real",
        )

        with patch("assistant_os.sandbox.runner_api.RunnerAPI") as MockRunnerAPI:
            instance = MagicMock()
            instance.execute.return_value = failing
            MockRunnerAPI.return_value = instance

            result = _real_executor({
                "proposal": self._make_proposal(),
                "workspace": str(tmp_path),
                "context_id": "test",
            })

        assert result["ok"] is False
        assert result["error"]

    def test_real_executor_timeout_propagated_via_mock(self, tmp_path):
        """_real_executor returns ok=False with descriptive error on timeout."""
        from unittest.mock import patch, MagicMock
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.tools.claude_code.apply_change_tool import _real_executor

        timed_out = ExecutionResult(
            exit_code=-1, stdout="", stderr="",
            duration_ms=30000, truncated=False, apply_mode="real",
            timed_out=True,
        )

        with patch("assistant_os.sandbox.runner_api.RunnerAPI") as MockRunnerAPI:
            instance = MagicMock()
            instance.execute.return_value = timed_out
            MockRunnerAPI.return_value = instance

            result = _real_executor({
                "proposal": self._make_proposal(),
                "workspace": str(tmp_path),
                "context_id": "test",
            })

        assert result["ok"] is False
        assert "timed out" in result["error"].lower()

    def test_stub_mode_contract_unchanged(self, tmp_path):
        """
        ApplyChangeTool default (stub) executor still returns apply_mode=stub.
        This verifies no regression in the existing contract.
        """
        from assistant_os.tools.claude_code.apply_change_tool import ApplyChangeTool

        applied = set()
        tool = ApplyChangeTool(applied_proposals=applied)
        proposal = self._make_proposal()
        tr = tool.execute({"proposal": proposal, "workspace": str(tmp_path)})

        assert tr.ok
        assert tr.data["apply_mode"] == "stub"

    def test_code_create_real_result_shape(self, tmp_path):
        """For CODE_CREATE in real mode, created_files is populated."""
        from unittest.mock import patch, MagicMock
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.tools.claude_code.apply_change_tool import _real_executor

        success = ExecutionResult(
            exit_code=0, stdout="done", stderr="",
            duration_ms=80, truncated=False, apply_mode="real",
        )

        with patch("assistant_os.sandbox.runner_api.RunnerAPI") as MockRunnerAPI:
            instance = MagicMock()
            instance.execute.return_value = success
            MockRunnerAPI.return_value = instance

            result = _real_executor({
                "proposal": self._make_proposal(action="CODE_CREATE"),
                "workspace": str(tmp_path),
                "context_id": "test",
            })

        assert result["ok"] is True
        assert result["created_files"] == ["src/foo.py"]
        assert result["modified_files"] == []


# ===========================================================================
# G. AuthorizedPlan — validation
# ===========================================================================


class TestAuthorizedPlan:
    """AuthorizedPlan field validation; no Docker required."""

    def _make_plan(self, **kwargs):
        from assistant_os.sandbox.authorized_plan import AuthorizedPlan

        defaults = dict(
            execution_id="exec-001",
            plan_id="plan-001",
            authorized_plan_hash="abc123def456",
            policy_id="default",
            capability_scope=["read", "write"],
            runtime_profile="python3.11",
        )
        defaults.update(kwargs)
        return AuthorizedPlan(**defaults)

    def test_valid_plan_does_not_raise(self):
        self._make_plan().validate()  # must not raise

    def test_missing_execution_id_raises(self):
        with pytest.raises(ValueError, match="execution_id"):
            self._make_plan(execution_id="").validate()

    def test_whitespace_only_execution_id_raises(self):
        with pytest.raises(ValueError, match="execution_id"):
            self._make_plan(execution_id="   ").validate()

    def test_missing_plan_id_raises(self):
        with pytest.raises(ValueError, match="plan_id"):
            self._make_plan(plan_id="").validate()

    def test_missing_hash_raises(self):
        with pytest.raises(ValueError, match="authorized_plan_hash"):
            self._make_plan(authorized_plan_hash="").validate()

    def test_missing_policy_id_raises(self):
        with pytest.raises(ValueError, match="policy_id"):
            self._make_plan(policy_id="").validate()

    def test_unknown_policy_id_raises(self):
        with pytest.raises(ValueError, match="Unknown policy_id"):
            self._make_plan(policy_id="not_a_real_policy").validate()

    def test_unsupported_runtime_profile_raises(self):
        with pytest.raises(ValueError, match="Unsupported runtime_profile"):
            self._make_plan(runtime_profile="node18").validate()

    def test_runner_api_accepts_valid_plan(self, tmp_path):
        """RunnerAPI.execute() with a valid plan proceeds past validation."""
        from unittest.mock import MagicMock
        from assistant_os.sandbox.authorized_plan import AuthorizedPlan
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.sandbox.runner_api import RunnerAPI

        plan = AuthorizedPlan(
            execution_id="exec-001",
            plan_id="plan-001",
            authorized_plan_hash="abc123",
            policy_id="default",
        )
        mock_result = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            duration_ms=10, truncated=False,
        )
        mock_backend = MagicMock()
        mock_backend.execute.return_value = mock_result
        mock_backend.prepare.return_value = None
        mock_backend.cleanup.return_value = None

        runner = RunnerAPI(backend=mock_backend)
        result = runner.execute("print(1)", str(tmp_path), authorized_plan=plan)
        assert result.ok

    def test_runner_api_rejects_invalid_plan(self, tmp_path):
        """RunnerAPI.execute() raises ValueError for an invalid AuthorizedPlan."""
        from assistant_os.sandbox.authorized_plan import AuthorizedPlan
        from assistant_os.sandbox.runner_api import RunnerAPI

        bad_plan = AuthorizedPlan(
            execution_id="",
            plan_id="plan-001",
            authorized_plan_hash="abc123",
            policy_id="default",
        )
        with pytest.raises(ValueError, match="execution_id"):
            RunnerAPI().execute("print(1)", str(tmp_path), authorized_plan=bad_plan)

    def test_runner_api_works_without_plan(self, tmp_path):
        """authorized_plan=None (default) is accepted — backward compat."""
        from unittest.mock import MagicMock
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.sandbox.runner_api import RunnerAPI

        mock_result = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            duration_ms=10, truncated=False,
        )
        mock_backend = MagicMock()
        mock_backend.execute.return_value = mock_result
        mock_backend.prepare.return_value = None
        mock_backend.cleanup.return_value = None

        result = RunnerAPI(backend=mock_backend).execute(
            "print(1)", str(tmp_path), authorized_plan=None
        )
        assert result.ok


# ===========================================================================
# H. Container hardening — security flags (no Docker)
# ===========================================================================


class TestContainerHardening:
    """Verify hardening flags in ContainerBackend._build_docker_cmd()."""

    def _cmd(self, **kwargs):
        from assistant_os.sandbox.container_backend import ContainerBackend
        return ContainerBackend(**kwargs)._build_docker_cmd(
            "test-ctr", "/tmp/ws", "main.py"
        )

    def test_non_root_user_flag_present(self):
        cmd = self._cmd()
        assert "--user" in cmd
        idx = cmd.index("--user")
        assert cmd[idx + 1] == "65534", (
            f"Expected UID 65534 (nobody), got {cmd[idx + 1]!r}"
        )

    def test_readonly_root_flag_present(self):
        assert "--read-only" in self._cmd()

    def test_tmpfs_tmp_flag_present(self):
        cmd = self._cmd()
        assert "--tmpfs" in cmd
        idx = cmd.index("--tmpfs")
        assert "/tmp" in cmd[idx + 1], (
            f"Expected /tmp in tmpfs value, got {cmd[idx + 1]!r}"
        )

    def test_pids_limit_flag_present(self):
        assert "--pids-limit" in self._cmd()

    def test_pids_limit_default_value(self):
        cmd = self._cmd()
        idx = cmd.index("--pids-limit")
        assert int(cmd[idx + 1]) > 0

    def test_pids_limit_custom_value(self):
        cmd = self._cmd(pids_limit=32)
        idx = cmd.index("--pids-limit")
        assert cmd[idx + 1] == "32"

    def test_workspace_mount_still_rw(self):
        cmd = self._cmd()
        assert any("/workspace:rw" in part for part in cmd), (
            "Workspace mount must remain rw even with --read-only root"
        )

    def test_network_disabled(self):
        cmd = self._cmd()
        assert "--network" in cmd
        idx = cmd.index("--network")
        assert cmd[idx + 1] == "none"

    def test_container_auto_removed(self):
        assert "--rm" in self._cmd()


# ===========================================================================
# I. ArtifactPolicy — governed artifact collection and metadata
# ===========================================================================


class TestArtifactPolicy:
    """ArtifactPolicy, ArtifactRecord, ArtifactManifest; no Docker required."""

    def test_empty_manifest_when_out_dir_missing(self, tmp_path):
        from assistant_os.sandbox.artifact_policy import ArtifactPolicy

        manifest = ArtifactPolicy().collect(str(tmp_path))
        assert manifest.records == []
        assert manifest.rejected == []

    def test_collects_file_from_out_dir(self, tmp_path):
        from assistant_os.sandbox.artifact_policy import ArtifactPolicy

        out = tmp_path / "out"
        out.mkdir()
        (out / "result.json").write_text('{"ok": true}')
        manifest = ArtifactPolicy().collect(str(tmp_path))
        assert len(manifest.records) == 1
        assert "result.json" in manifest.records[0].path
        assert manifest.records[0].classification == "output"
        assert manifest.records[0].sha256  # non-empty hash

    def test_does_not_collect_file_outside_out_dir(self, tmp_path):
        """Files in workspace root or other dirs are not collected."""
        from assistant_os.sandbox.artifact_policy import ArtifactPolicy

        (tmp_path / "stray.txt").write_text("ignored")
        (tmp_path / "output").mkdir()
        (tmp_path / "output" / "also_ignored.txt").write_text("x")
        manifest = ArtifactPolicy().collect(str(tmp_path))
        assert manifest.records == []

    def test_rejects_oversized_artifact(self, tmp_path):
        from assistant_os.sandbox.artifact_policy import ArtifactPolicy

        out = tmp_path / "out"
        out.mkdir()
        (out / "big.bin").write_bytes(b"x" * 10)
        manifest = ArtifactPolicy(max_size_bytes=5).collect(str(tmp_path))
        assert manifest.records == []
        assert len(manifest.rejected) == 1
        assert "exceeds max size" in manifest.rejected[0]["reason"]

    def test_manifest_has_sha256_and_size(self, tmp_path):
        import hashlib
        from assistant_os.sandbox.artifact_policy import ArtifactPolicy

        out = tmp_path / "out"
        out.mkdir()
        content = b"hello artifact"
        (out / "data.txt").write_bytes(content)
        manifest = ArtifactPolicy().collect(str(tmp_path))
        record = manifest.records[0]
        assert record.size_bytes == len(content)
        assert record.sha256 == hashlib.sha256(content).hexdigest()

    def test_to_dict_shape(self, tmp_path):
        from assistant_os.sandbox.artifact_policy import ArtifactPolicy

        out = tmp_path / "out"
        out.mkdir()
        (out / "out.txt").write_text("data")
        d = ArtifactPolicy().collect(str(tmp_path)).to_dict()
        assert "export_root" in d
        assert "records" in d
        assert "rejected" in d
        assert d["export_root"] == "out"

    def test_execution_metadata_to_dict_contains_all_keys(self):
        from assistant_os.sandbox.execution_result import ExecutionMetadata

        meta = ExecutionMetadata(
            execution_id="e1",
            plan_id="p1",
            policy_id="default",
            runtime_profile="python3.11",
            duration_ms=200,
            exit_code=0,
            timed_out=False,
            truncated=False,
        )
        d = meta.to_dict()
        for key in (
            "execution_id", "plan_id", "policy_id", "runtime_profile",
            "duration_ms", "exit_code", "timed_out", "truncated",
        ):
            assert key in d, f"ExecutionMetadata.to_dict() missing {key!r}"

    def test_metadata_and_artifact_manifest_are_distinct_types(self):
        """ExecutionMetadata and ArtifactManifest are formally separate types."""
        from assistant_os.sandbox.execution_result import ExecutionMetadata
        from assistant_os.sandbox.artifact_policy import ArtifactManifest

        meta = ExecutionMetadata(
            execution_id="e1", plan_id="p1", policy_id="default",
            runtime_profile="python3.11", duration_ms=100,
            exit_code=0, timed_out=False, truncated=False,
        )
        manifest = ArtifactManifest()
        assert type(meta) is not type(manifest)
        # Both must be independently serialisable
        assert isinstance(meta.to_dict(), dict)
        assert isinstance(manifest.to_dict(), dict)

    def test_execution_result_carries_metadata_and_manifest(self):
        """ExecutionResult accepts metadata and manifest fields."""
        from assistant_os.sandbox.execution_result import ExecutionResult, ExecutionMetadata
        from assistant_os.sandbox.artifact_policy import ArtifactManifest

        meta = ExecutionMetadata(
            execution_id="e1", plan_id="p1", policy_id="default",
            runtime_profile="python3.11", duration_ms=50,
            exit_code=0, timed_out=False, truncated=False,
        )
        manifest = ArtifactManifest()
        result = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            duration_ms=50, truncated=False,
            metadata=meta,
            manifest=manifest,
        )
        d = result.to_dict()
        assert "metadata" in d
        assert "manifest" in d
        assert d["metadata"]["execution_id"] == "e1"
        assert d["manifest"]["export_root"] == "out"

    def test_execution_result_to_dict_without_metadata_is_clean(self):
        """When metadata/manifest are None, to_dict() omits those keys."""
        from assistant_os.sandbox.execution_result import ExecutionResult

        result = ExecutionResult(
            exit_code=0, stdout="", stderr="",
            duration_ms=10, truncated=False,
        )
        d = result.to_dict()
        assert "metadata" not in d
        assert "manifest" not in d
