"""
Tests — Code Review Executor (real read-only executor)

Covers:
  A. File reading (_read_target_file)
  B. Prompt building (_build_user_prompt)
  C. Executor factory (build_claude_review_executor) using a fake Claude client
  D. Integration with code_pipeline via register_review_executor
"""

from __future__ import annotations

import os
import pytest

from assistant_os.executors.code_review_executor import (
    _read_target_file,
    _build_user_prompt,
    build_claude_review_executor,
    _MAX_FILE_BYTES,
)


# ---------------------------------------------------------------------------
# Fake Claude client — simulates anthropic.Anthropic without network
# ---------------------------------------------------------------------------

class _FakeContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeContent(text)]


class _FakeClient:
    """Minimal fake that mimics anthropic.Anthropic().messages.create(...)."""

    def __init__(self, response_text: str = "fake analysis") -> None:
        self._response_text = response_text
        self.last_call: dict = {}

    class _Messages:
        def __init__(self, parent: "_FakeClient") -> None:
            self._parent = parent

        def create(self, **kwargs) -> _FakeMessage:
            self._parent.last_call = kwargs
            return _FakeMessage(self._parent._response_text)

    @property
    def messages(self) -> "_FakeClient._Messages":
        return self._Messages(self)


class _RaisingClient:
    """Fake client that raises a given exception on messages.create."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    class _Messages:
        def __init__(self, exc):
            self._exc = exc

        def create(self, **kwargs):
            raise self._exc

    @property
    def messages(self):
        return self._Messages(self._exc)


# ---------------------------------------------------------------------------
# A. _read_target_file
# ---------------------------------------------------------------------------

class TestReadTargetFile:

    def test_empty_target_file_returns_none_none(self, tmp_path):
        content, error, _start_line = _read_target_file(str(tmp_path), "")
        assert content is None
        assert error is None

    def test_empty_workspace_returns_none_none(self, tmp_path):
        content, error, _start_line = _read_target_file("", "src/foo.py")
        assert content is None
        assert error is None

    def test_reads_existing_file(self, tmp_path):
        f = tmp_path / "foo.py"
        f.write_text("def hello(): pass\n")
        content, error, _start_line = _read_target_file(str(tmp_path), "foo.py")
        assert error is None
        assert "def hello" in content

    def test_nested_path_reads_correctly(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "bar.py").write_text("x = 1\n")
        content, error, _start_line = _read_target_file(str(tmp_path), "src/bar.py")
        assert error is None
        assert "x = 1" in content

    def test_nonexistent_file_returns_error(self, tmp_path):
        content, error, _start_line = _read_target_file(str(tmp_path), "does_not_exist.py")
        assert content is None
        assert "not found" in error.lower()

    def test_directory_path_returns_error(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        content, error, _start_line = _read_target_file(str(tmp_path), "subdir")
        assert content is None
        assert error is not None

    def test_file_too_large_returns_error(self, tmp_path):
        big = tmp_path / "big.py"
        big.write_bytes(b"x" * (_MAX_FILE_BYTES + 1))
        content, error, _start_line = _read_target_file(str(tmp_path), "big.py")
        assert content is None
        assert "too large" in error.lower()

    def test_file_exactly_at_limit_is_accepted(self, tmp_path):
        ok_file = tmp_path / "ok.py"
        ok_file.write_bytes(b"a" * _MAX_FILE_BYTES)
        content, error, _start_line = _read_target_file(str(tmp_path), "ok.py")
        assert error is None
        assert content is not None

    def test_path_traversal_rejected(self, tmp_path):
        content, error, _start_line = _read_target_file(str(tmp_path), "../outside.py")
        assert content is None
        assert "traversal" in error.lower()

    def test_utf8_file_read_correctly(self, tmp_path):
        f = tmp_path / "unicode.py"
        f.write_text("# café y ñoño\npass\n", encoding="utf-8")
        content, error, _start_line = _read_target_file(str(tmp_path), "unicode.py")
        assert error is None
        assert "café" in content


# ---------------------------------------------------------------------------
# B. _build_user_prompt
# ---------------------------------------------------------------------------

class TestBuildUserPrompt:

    def test_explain_action_directive(self):
        prompt = _build_user_prompt("CODE_EXPLAIN", "", None, "")
        assert "explain" in prompt.lower()

    def test_review_action_directive(self):
        prompt = _build_user_prompt("CODE_REVIEW", "", None, "")
        assert "review" in prompt.lower()

    def test_target_file_included(self):
        prompt = _build_user_prompt("CODE_EXPLAIN", "src/auth.py", None, "")
        assert "src/auth.py" in prompt

    def test_file_content_in_fenced_block(self):
        prompt = _build_user_prompt("CODE_EXPLAIN", "foo.py", "def f(): pass", "")
        assert "```" in prompt
        assert "def f(): pass" in prompt

    def test_no_file_content_shows_notice(self):
        prompt = _build_user_prompt("CODE_EXPLAIN", "foo.py", None, "")
        assert "No file content" in prompt

    def test_user_context_included(self):
        prompt = _build_user_prompt("CODE_REVIEW", "", None, "What does this do?")
        assert "What does this do?" in prompt

    def test_python_fence_language_from_extension(self):
        prompt = _build_user_prompt("CODE_EXPLAIN", "foo.py", "x=1", "")
        assert "```py" in prompt

    def test_unknown_extension_uses_empty_fence(self):
        prompt = _build_user_prompt("CODE_EXPLAIN", "Makefile", "all:", "")
        assert "```\n" in prompt or "```" in prompt


# ---------------------------------------------------------------------------
# C. build_claude_review_executor (fake client)
# ---------------------------------------------------------------------------

class TestBuildClaudeReviewExecutor:

    def _make_executor(self, response: str = "analysis result"):
        return build_claude_review_executor(client=_FakeClient(response))

    def test_explain_returns_ok_and_analysis(self, tmp_path):
        (tmp_path / "foo.py").write_text("def f(): pass")
        executor = self._make_executor("This function does nothing.")
        result = executor({
            "action": "CODE_EXPLAIN",
            "target_file": "foo.py",
            "workspace": str(tmp_path),
            "context": "",
        })
        assert result["ok"] is True
        assert result["analysis"] == "This function does nothing."

    def test_review_returns_ok_and_analysis(self, tmp_path):
        (tmp_path / "foo.py").write_text("x = eval(input())")
        executor = self._make_executor("Dangerous: eval of user input.")
        result = executor({
            "action": "CODE_REVIEW",
            "target_file": "foo.py",
            "workspace": str(tmp_path),
            "context": "",
        })
        assert result["ok"] is True
        assert "Dangerous" in result["analysis"]

    def test_missing_file_returns_error(self, tmp_path):
        executor = self._make_executor()
        result = executor({
            "action": "CODE_EXPLAIN",
            "target_file": "no_such_file.py",
            "workspace": str(tmp_path),
            "context": "",
        })
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_file_too_large_returns_error(self, tmp_path):
        big = tmp_path / "big.py"
        big.write_bytes(b"x" * (_MAX_FILE_BYTES + 1))
        executor = self._make_executor()
        result = executor({
            "action": "CODE_REVIEW",
            "target_file": "big.py",
            "workspace": str(tmp_path),
            "context": "",
        })
        assert result["ok"] is False
        assert "too large" in result["error"].lower()

    def test_empty_target_file_context_only_succeeds(self):
        """No file provided — executor responds from context alone (no error)."""
        executor = self._make_executor("context-only analysis")
        result = executor({
            "action": "CODE_EXPLAIN",
            "target_file": "",
            "workspace": "",
            "context": "What is a generator?",
        })
        assert result["ok"] is True
        assert result["analysis"] == "context-only analysis"

    def test_claude_call_receives_correct_model(self, tmp_path):
        fake = _FakeClient("ok")
        executor = build_claude_review_executor(client=fake, model="claude-test-model")
        executor({"action": "CODE_EXPLAIN", "target_file": "", "workspace": "", "context": "hi"})
        assert fake.last_call["model"] == "claude-test-model"

    def test_claude_call_receives_correct_max_tokens(self, tmp_path):
        fake = _FakeClient("ok")
        executor = build_claude_review_executor(client=fake, max_tokens=512)
        executor({"action": "CODE_EXPLAIN", "target_file": "", "workspace": "", "context": "hi"})
        assert fake.last_call["max_tokens"] == 512

    def test_claude_call_uses_system_prompt(self):
        fake = _FakeClient("ok")
        executor = build_claude_review_executor(client=fake)
        executor({"action": "CODE_REVIEW", "target_file": "", "workspace": "", "context": "x"})
        assert "system" in fake.last_call
        assert len(fake.last_call["system"]) > 0

    def test_api_exception_returns_clean_error(self):
        executor = build_claude_review_executor(
            client=_RaisingClient(RuntimeError("network timeout")),
        )
        result = executor({
            "action": "CODE_EXPLAIN",
            "target_file": "",
            "workspace": "",
            "context": "what?",
        })
        assert result["ok"] is False
        assert "network timeout" in result["error"] or "Unexpected" in result["error"]

    def test_path_traversal_rejected_by_executor(self, tmp_path):
        executor = self._make_executor()
        result = executor({
            "action": "CODE_EXPLAIN",
            "target_file": "../escape.py",
            "workspace": str(tmp_path),
            "context": "",
        })
        assert result["ok"] is False
        assert "traversal" in result["error"].lower()


# ---------------------------------------------------------------------------
# D. Integration with code_pipeline.register_review_executor
# ---------------------------------------------------------------------------

class TestExecutorPipelineIntegration:
    """
    Full round-trip: build_claude_review_executor → register_review_executor →
    code_pipeline.execute → DomainResult with real analysis.
    """

    def _make_plan(self, action: str, payload: dict | None = None) -> dict:
        return {
            "action": action,
            "domain": "CODE",
            "raw_text": "test",
            "domain_payload": payload or {},
            "trace_id": "test_trace",
            "plan_id": "test_plan",
        }

    def test_registered_executor_produces_real_analysis(self, tmp_path):
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.contracts import RESULT_TYPE_CODE_EXPLAIN

        (tmp_path / "foo.py").write_text("def greet(): return 'hello'")
        fake_client = _FakeClient("greet returns a greeting string")
        executor = build_claude_review_executor(client=fake_client)

        original = cp._review_executor
        cp.register_review_executor(executor)
        try:
            plan = self._make_plan("CODE_EXPLAIN", {
                "target_file": "foo.py",
                "workspace": str(tmp_path),
            })
            from assistant_os.pipelines.code_pipeline import execute as code_execute
            result = code_execute(plan, "ctx-integ-01")
            assert result["ok"] is True
            assert result["result_type"] == RESULT_TYPE_CODE_EXPLAIN
            assert "greet returns" in result["data"]["analysis"]
            assert result["data"]["executor_live"] is True
        finally:
            cp.register_review_executor(original)

    def test_registered_executor_file_error_propagates(self, tmp_path):
        """File read failures from the real executor surface as DomainResult errors."""
        import assistant_os.pipelines.code_pipeline as cp

        fake_client = _FakeClient("should not be called")
        executor = build_claude_review_executor(client=fake_client)

        original = cp._review_executor
        cp.register_review_executor(executor)
        try:
            plan = self._make_plan("CODE_REVIEW", {
                "target_file": "nonexistent.py",
                "workspace": str(tmp_path),
            })
            from assistant_os.pipelines.code_pipeline import execute as code_execute
            result = code_execute(plan, "ctx-integ-02")
            assert result["ok"] is False
            assert result["error"]["type"] == "ReviewFailed"
        finally:
            cp.register_review_executor(original)

    def test_executor_live_false_when_unregistered(self):
        """P0-1: when executor is None, pipeline must return ok=False (executor_unavailable).

        Silent stubs are not acceptable — the caller must know no real analysis occurred.
        """
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.pipelines.code_pipeline import execute as code_execute

        original = cp._review_executor
        cp.register_review_executor(None)
        try:
            plan = self._make_plan("CODE_EXPLAIN")
            result = code_execute(plan, "ctx-integ-03")
            # P0-1: must fail visible — not ok=True with stub analysis
            assert result["ok"] is False
            assert result["data"]["executor_live"] is False
            assert result["data"]["type"] == "executor_unavailable"
        finally:
            cp.register_review_executor(original)
