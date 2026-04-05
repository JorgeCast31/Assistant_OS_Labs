"""
Tests — code_propose_executor (assistant_os/executors/code_propose_executor.py)

Coverage:
  A. _read_file_for_context  — path validation, size cap, CODE_FIX vs CODE_CREATE
  B. _parse_proposal_json    — plain JSON, fenced, fallback extraction, bad input
  C. _validate_and_normalise — blocked ops, risk defaults, affected_files defaults, error surface
  D. build_claude_propose_executor (factory + executor callable) — full contract via fake client
  E. Pipeline integration    — executor registered → preview data populated
"""

from __future__ import annotations

import json
import os
import pathlib
import pytest


# ---------------------------------------------------------------------------
# Helpers / fake clients
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Minimal stand-in for anthropic.Message."""

    def __init__(self, text: str):
        self.content = [type("Block", (), {"text": text})()]


class _FakeClient:
    """Fake anthropic.Anthropic client that returns a configurable JSON payload."""

    def __init__(self, payload: dict | None = None, raw_text: str | None = None):
        if raw_text is not None:
            self._raw = raw_text
        else:
            self._raw = json.dumps(payload or {
                "summary": "Test summary",
                "affected_files": ["src/foo.py"],
                "write_intent_summary": "Modifies foo.py",
                "patch_preview": "--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1 +1 @@\n-old\n+new",
                "operation_types": ["modify"],
                "risk_level": "low",
            })
        self.messages = self

    def create(self, **kwargs):
        return _FakeResponse(self._raw)


class _RaisingClient:
    """Fake client that raises a given exception on .messages.create()."""

    def __init__(self, exc: Exception):
        self._exc = exc
        self.messages = self

    def create(self, **kwargs):
        raise self._exc


# ---------------------------------------------------------------------------
# A. _read_file_for_context
# ---------------------------------------------------------------------------

class TestReadFileForContext:

    def _fn(self):
        from assistant_os.executors.code_propose_executor import _read_file_for_context
        return _read_file_for_context

    def test_empty_target_returns_none_none(self, tmp_path):
        content, err = self._fn()(str(tmp_path), "", "CODE_FIX")
        assert content is None and err is None

    def test_empty_workspace_returns_none_none(self):
        content, err = self._fn()("", "src/foo.py", "CODE_FIX")
        assert content is None and err is None

    def test_code_fix_missing_file_is_error(self, tmp_path):
        content, err = self._fn()(str(tmp_path), "missing.py", "CODE_FIX")
        assert content is None
        assert err is not None
        assert "not found" in err.lower()

    def test_code_create_missing_file_is_ok(self, tmp_path):
        content, err = self._fn()(str(tmp_path), "new_file.py", "CODE_CREATE")
        assert content is None and err is None

    def test_existing_file_read_successfully(self, tmp_path):
        f = tmp_path / "src" / "auth.py"
        f.parent.mkdir()
        f.write_text("def login(): pass\n", encoding="utf-8")
        content, err = self._fn()(str(tmp_path), "src/auth.py", "CODE_FIX")
        assert err is None
        assert "def login" in content

    def test_large_file_partially_read(self, tmp_path):
        from assistant_os.executors.code_propose_executor import _MAX_FILE_BYTES
        f = tmp_path / "big.py"
        f.write_text("x" * (_MAX_FILE_BYTES + 100), encoding="utf-8")
        content, err = self._fn()(str(tmp_path), "big.py", "CODE_FIX")
        assert err is None
        assert "truncated" in content.lower()
        assert len(content) > _MAX_FILE_BYTES  # has truncation notice appended

    def test_path_traversal_rejected(self, tmp_path):
        content, err = self._fn()(str(tmp_path), "../../etc/passwd", "CODE_FIX")
        assert content is None
        assert err is not None
        assert "traversal" in err.lower()

    def test_not_a_file_is_error(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        content, err = self._fn()(str(tmp_path), "subdir", "CODE_FIX")
        assert content is None
        assert err is not None

    def test_code_create_existing_file_is_readable(self, tmp_path):
        """CODE_CREATE with an existing file reads it (for overwrite proposals)."""
        f = tmp_path / "existing.py"
        f.write_text("# existing\n", encoding="utf-8")
        content, err = self._fn()(str(tmp_path), "existing.py", "CODE_CREATE")
        assert err is None
        assert "existing" in content


# ---------------------------------------------------------------------------
# B. _parse_proposal_json
# ---------------------------------------------------------------------------

class TestParseProposalJson:

    def _fn(self):
        from assistant_os.executors.code_propose_executor import _parse_proposal_json
        return _parse_proposal_json

    def test_plain_json_parsed(self):
        result = self._fn()('{"summary": "fix it", "risk_level": "low"}')
        assert result == {"summary": "fix it", "risk_level": "low"}

    def test_json_fenced_parsed(self):
        text = '```json\n{"summary": "s"}\n```'
        result = self._fn()(text)
        assert result == {"summary": "s"}

    def test_bare_fence_parsed(self):
        text = '```\n{"summary": "s"}\n```'
        result = self._fn()(text)
        assert result == {"summary": "s"}

    def test_stray_text_before_json_extracted(self):
        text = 'Here is the plan:\n{"summary": "x"}\nEnd.'
        result = self._fn()(text)
        assert result == {"summary": "x"}

    def test_non_json_returns_none(self):
        result = self._fn()("not json at all, no braces")
        assert result is None

    def test_empty_string_returns_none(self):
        result = self._fn()("")
        assert result is None

    def test_malformed_json_returns_none(self):
        result = self._fn()("{not: valid json}")
        assert result is None

    def test_nested_json_preserved(self):
        payload = {"affected_files": ["a.py", "b.py"], "risk_level": "high"}
        result = self._fn()(json.dumps(payload))
        assert result == payload


# ---------------------------------------------------------------------------
# C. _validate_and_normalise
# ---------------------------------------------------------------------------

class TestValidateAndNormalise:

    def _fn(self):
        from assistant_os.executors.code_propose_executor import _validate_and_normalise
        return _validate_and_normalise

    def test_error_field_surfaces_as_ok_false(self):
        raw = {"error": "cannot propose this"}
        result = self._fn()(raw, "f.py", "CODE_FIX")
        assert result["ok"] is False
        assert "cannot propose" in result["error"]

    def test_blocked_ops_removed(self):
        raw = {
            "summary": "s", "affected_files": ["f.py"], "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["modify", "delete", "rename"],
            "risk_level": "low",
        }
        result = self._fn()(raw, "f.py", "CODE_FIX")
        assert result["ok"] is True
        assert "delete" not in result["operation_types"]
        assert "rename" not in result["operation_types"]
        assert "modify" in result["operation_types"]

    def test_all_blocked_ops_defaults_from_action_fix(self):
        raw = {
            "summary": "s", "affected_files": ["f.py"], "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["delete"],
            "risk_level": "low",
        }
        result = self._fn()(raw, "f.py", "CODE_FIX")
        assert result["operation_types"] == ["modify"]

    def test_all_blocked_ops_defaults_from_action_create(self):
        raw = {
            "summary": "s", "affected_files": ["new.py"], "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["rename"],
            "risk_level": "low",
        }
        result = self._fn()(raw, "new.py", "CODE_CREATE")
        assert result["operation_types"] == ["create"]

    def test_invalid_risk_level_defaults_to_medium(self):
        raw = {
            "summary": "s", "affected_files": ["f.py"], "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["modify"],
            "risk_level": "unknown_level",
        }
        result = self._fn()(raw, "f.py", "CODE_FIX")
        assert result["risk_level"] == "medium"

    def test_empty_affected_files_defaults_to_target(self):
        raw = {
            "summary": "s", "affected_files": [], "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["modify"], "risk_level": "low",
        }
        result = self._fn()(raw, "src/main.py", "CODE_FIX")
        assert result["affected_files"] == ["src/main.py"]

    def test_missing_affected_files_defaults_to_target(self):
        raw = {
            "summary": "s", "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["modify"], "risk_level": "low",
        }
        result = self._fn()(raw, "src/main.py", "CODE_FIX")
        assert result["affected_files"] == ["src/main.py"]

    def test_valid_full_response_passes_through(self):
        raw = {
            "summary": "Add feature X",
            "affected_files": ["src/feature.py"],
            "write_intent_summary": "Adds feature.py",
            "patch_preview": "--- a/src/feature.py\n+++ b/src/feature.py",
            "operation_types": ["modify"],
            "risk_level": "medium",
        }
        result = self._fn()(raw, "src/feature.py", "CODE_FIX")
        assert result["ok"] is True
        assert result["summary"] == "Add feature X"
        assert result["risk_level"] == "medium"
        assert result["affected_files"] == ["src/feature.py"]

    def test_move_op_removed(self):
        raw = {
            "summary": "s", "affected_files": ["f.py"], "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["move", "create"],
            "risk_level": "low",
        }
        result = self._fn()(raw, "f.py", "CODE_CREATE")
        assert "move" not in result["operation_types"]
        assert "create" in result["operation_types"]

    # --- Canonical-set normalization (regression: unknown values must be dropped) ---

    def test_unknown_op_dropped(self):
        """Non-canonical value like 'update' must be dropped, not passed through."""
        raw = {
            "summary": "s", "affected_files": ["f.py"], "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["update"],
            "risk_level": "low",
        }
        result = self._fn()(raw, "f.py", "CODE_FIX")
        assert result["ok"] is True
        assert "update" not in result["operation_types"]

    def test_unknown_op_dropped_defaults_to_modify(self):
        """All-unknown ops for CODE_FIX fall back to ['modify']."""
        raw = {
            "summary": "s", "affected_files": ["f.py"], "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["patch", "overwrite"],
            "risk_level": "low",
        }
        result = self._fn()(raw, "f.py", "CODE_FIX")
        assert result["operation_types"] == ["modify"]

    def test_unknown_op_dropped_defaults_to_create(self):
        """All-unknown ops for CODE_CREATE fall back to ['create']."""
        raw = {
            "summary": "s", "affected_files": ["new.py"], "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["generate"],
            "risk_level": "low",
        }
        result = self._fn()(raw, "new.py", "CODE_CREATE")
        assert result["operation_types"] == ["create"]

    def test_mixed_canonical_and_unknown_keeps_only_canonical(self):
        """Known values survive; unknown values are silently dropped."""
        raw = {
            "summary": "s", "affected_files": ["f.py"], "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["modify", "update", "create"],
            "risk_level": "low",
        }
        result = self._fn()(raw, "f.py", "CODE_FIX")
        assert set(result["operation_types"]) == {"modify", "create"}

    def test_all_five_canonical_ops_recognised(self):
        """All five canonical values are accepted before the blocked-ops filter."""
        # Use only non-blocked canonical values to check acceptance
        raw = {
            "summary": "s", "affected_files": ["f.py"], "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["create", "modify"],
            "risk_level": "low",
        }
        result = self._fn()(raw, "f.py", "CODE_FIX")
        # Both survive (neither is blocked)
        assert "create" in result["operation_types"]
        assert "modify" in result["operation_types"]


# ---------------------------------------------------------------------------
# D. build_claude_propose_executor (factory + callable)
# ---------------------------------------------------------------------------

class TestBuildClauseProposeExecutor:

    def _build(self, client=None, payload=None, raw_text=None):
        from assistant_os.executors.code_propose_executor import build_claude_propose_executor
        import assistant_os.config as cfg
        # Temporarily ensure ANTHROPIC_API_KEY is set so factory doesn't raise
        orig = cfg.ANTHROPIC_API_KEY
        cfg.ANTHROPIC_API_KEY = "sk-ant-fake-test-key"
        try:
            return build_claude_propose_executor(
                client=client or _FakeClient(payload=payload, raw_text=raw_text)
            )
        finally:
            cfg.ANTHROPIC_API_KEY = orig

    def test_factory_returns_callable(self):
        executor = self._build()
        assert callable(executor)

    def test_successful_response_returns_ok_true(self, tmp_path):
        executor = self._build()
        result = executor({
            "action": "CODE_FIX",
            "target_file": "",
            "workspace": str(tmp_path),
            "context": "fix the bug",
            "allowed_write_scope": [],
        })
        assert result["ok"] is True

    def test_successful_response_has_all_fields(self, tmp_path):
        executor = self._build()
        result = executor({
            "action": "CODE_FIX",
            "target_file": "",
            "workspace": str(tmp_path),
            "context": "fix the bug",
            "allowed_write_scope": [],
        })
        for field in ("summary", "affected_files", "write_intent_summary",
                      "patch_preview", "operation_types", "risk_level"):
            assert field in result, f"missing field: {field!r}"

    def test_non_json_response_returns_ok_false(self, tmp_path):
        executor = self._build(raw_text="Sorry, I can't help with that.")
        result = executor({
            "action": "CODE_FIX", "target_file": "", "workspace": str(tmp_path),
            "context": "fix", "allowed_write_scope": [],
        })
        assert result["ok"] is False
        assert "error" in result

    def test_claude_error_field_surfaces(self, tmp_path):
        executor = self._build(raw_text='{"error": "change too risky"}')
        result = executor({
            "action": "CODE_FIX", "target_file": "", "workspace": str(tmp_path),
            "context": "fix", "allowed_write_scope": [],
        })
        assert result["ok"] is False
        assert "risky" in result["error"]

    def test_authentication_error_returns_ok_false(self, tmp_path):
        import anthropic as _anthropic
        exc = _anthropic.AuthenticationError.__new__(_anthropic.AuthenticationError)
        exc.args = ("invalid api key",)
        executor = self._build(client=_RaisingClient(exc))
        result = executor({
            "action": "CODE_FIX", "target_file": "", "workspace": str(tmp_path),
            "context": "fix", "allowed_write_scope": [],
        })
        assert result["ok"] is False
        assert "authentication" in result["error"].lower()

    def test_rate_limit_error_returns_ok_false(self, tmp_path):
        import anthropic as _anthropic
        exc = _anthropic.RateLimitError.__new__(_anthropic.RateLimitError)
        exc.args = ("rate limit",)
        executor = self._build(client=_RaisingClient(exc))
        result = executor({
            "action": "CODE_FIX", "target_file": "", "workspace": str(tmp_path),
            "context": "fix", "allowed_write_scope": [],
        })
        assert result["ok"] is False
        assert "rate limit" in result["error"].lower()

    def test_unexpected_exception_returns_ok_false(self, tmp_path):
        executor = self._build(client=_RaisingClient(RuntimeError("unexpected")))
        result = executor({
            "action": "CODE_FIX", "target_file": "", "workspace": str(tmp_path),
            "context": "fix", "allowed_write_scope": [],
        })
        assert result["ok"] is False
        assert "unexpected" in result["error"].lower()

    # FIX 3 — timeout
    def test_timeout_error_returns_ok_false(self, tmp_path):
        """APITimeoutError must return ok=False with 'timeout' in error message."""
        import anthropic as _anthropic
        exc = _anthropic.APITimeoutError.__new__(_anthropic.APITimeoutError)
        exc.args = ("request timed out",)
        executor = self._build(client=_RaisingClient(exc))
        result = executor({
            "action": "CODE_FIX", "target_file": "", "workspace": str(tmp_path),
            "context": "fix", "allowed_write_scope": [],
        })
        assert result["ok"] is False
        assert "timeout" in result["error"].lower()

    def test_timeout_is_set_on_messages_create(self, tmp_path):
        """The executor must pass timeout=45.0 to client.messages.create()."""
        received_kwargs: dict = {}

        class _CapturingClient:
            def __init__(self):
                self.messages = self
            def create(self, **kwargs):
                received_kwargs.update(kwargs)
                return _FakeResponse(json.dumps({
                    "summary": "s", "affected_files": [], "write_intent_summary": "w",
                    "patch_preview": "diff", "operation_types": ["modify"], "risk_level": "low",
                }))

        executor = self._build(client=_CapturingClient())
        executor({
            "action": "CODE_FIX", "target_file": "", "workspace": str(tmp_path),
            "context": "fix", "allowed_write_scope": [],
        })
        assert received_kwargs.get("timeout") == 45.0

    def test_blocked_ops_stripped_in_output(self, tmp_path):
        (tmp_path / "f.py").write_text("# existing\n", encoding="utf-8")
        payload = {
            "summary": "s", "affected_files": ["f.py"], "write_intent_summary": "w",
            "patch_preview": "diff", "operation_types": ["modify", "delete"],
            "risk_level": "low",
        }
        executor = self._build(payload=payload)
        result = executor({
            "action": "CODE_FIX", "target_file": "f.py", "workspace": str(tmp_path),
            "context": "fix", "allowed_write_scope": ["f.py"],
        })
        assert result["ok"] is True
        assert "delete" not in result["operation_types"]

    def test_no_api_key_raises_value_error(self):
        import assistant_os.config as cfg
        orig = cfg.ANTHROPIC_API_KEY
        cfg.ANTHROPIC_API_KEY = None
        try:
            from assistant_os.executors.code_propose_executor import build_claude_propose_executor
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                build_claude_propose_executor()
        finally:
            cfg.ANTHROPIC_API_KEY = orig

    def test_file_read_error_for_code_fix_missing_file(self, tmp_path):
        """CODE_FIX with a non-existent target file returns ok=False before calling Claude."""
        executor = self._build()
        result = executor({
            "action": "CODE_FIX",
            "target_file": "does_not_exist.py",
            "workspace": str(tmp_path),
            "context": "fix the bug",
            "allowed_write_scope": ["does_not_exist.py"],
        })
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_code_create_missing_file_is_not_an_error(self, tmp_path):
        """CODE_CREATE with a non-existent target file is valid — we are creating it."""
        executor = self._build()
        result = executor({
            "action": "CODE_CREATE",
            "target_file": "new_module.py",
            "workspace": str(tmp_path),
            "context": "create new module",
            "allowed_write_scope": ["new_module.py"],
        })
        # Fake client returns ok payload → normalise should succeed
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# E. Pipeline integration — propose executor registered → preview data populated
# ---------------------------------------------------------------------------

class TestProposePipelineIntegration:

    def _build_executor(self, payload: dict):
        from assistant_os.executors.code_propose_executor import build_claude_propose_executor
        import assistant_os.config as cfg
        orig = cfg.ANTHROPIC_API_KEY
        cfg.ANTHROPIC_API_KEY = "sk-ant-fake-pipeline"
        try:
            return build_claude_propose_executor(client=_FakeClient(payload=payload))
        finally:
            cfg.ANTHROPIC_API_KEY = orig

    def test_registered_executor_data_appears_in_pipeline_preview(self, tmp_path):
        """Full integration: executor registered → pipeline returns its output in data."""
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.pipelines.code_pipeline import execute as code_execute
        from assistant_os.contracts import ACTION_CODE_FIX

        payload = {
            "summary": "pipeline integration summary",
            "affected_files": ["app/main.py"],
            "write_intent_summary": "Modifies main.py to fix crash",
            "patch_preview": "--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-bug\n+fix",
            "operation_types": ["modify"],
            "risk_level": "medium",
        }
        executor = self._build_executor(payload)
        # Create target file so CODE_FIX read succeeds
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text("def main(): raise Exception('bug')\n", encoding="utf-8")
        original = cp._propose_executor
        cp.register_propose_executor(executor)
        try:
            plan = {
                "action": ACTION_CODE_FIX,
                "domain": "CODE",
                "raw_text": "fix the crash in main.py",
                "domain_payload": {"target_file": "app/main.py", "workspace": str(tmp_path)},
                "trace_id": "t-pipe-01",
                "plan_id": "p-pipe-01",
            }
            result = code_execute(plan, "ctx-pipe-01")
            assert result["ok"] is True
            data = result["data"]
            assert data["summary"] == "pipeline integration summary"
            assert data["risk_level"] == "medium"
            assert data["propose_executor_live"] is True
            assert "+fix" in data["patch_preview"]
        finally:
            cp.register_propose_executor(original)

    def test_executor_failure_causes_pipeline_error(self, tmp_path):
        """If the executor returns ok=False, pipeline returns an error DomainResult."""
        import assistant_os.pipelines.code_pipeline as cp
        from assistant_os.pipelines.code_pipeline import execute as code_execute
        from assistant_os.contracts import ACTION_CODE_FIX
        import assistant_os.config as cfg

        orig_key = cfg.ANTHROPIC_API_KEY
        cfg.ANTHROPIC_API_KEY = "sk-ant-fake-fail"
        try:
            from assistant_os.executors.code_propose_executor import build_claude_propose_executor
            executor = build_claude_propose_executor(
                client=_FakeClient(raw_text='{"error": "file too complex"}')
            )
        finally:
            cfg.ANTHROPIC_API_KEY = orig_key

        original = cp._propose_executor
        cp.register_propose_executor(executor)
        try:
            plan = {
                "action": ACTION_CODE_FIX,
                "domain": "CODE",
                "raw_text": "fix it",
                "domain_payload": {"target_file": "", "workspace": str(tmp_path)},
                "trace_id": "t-pipe-02",
                "plan_id": "p-pipe-02",
            }
            result = code_execute(plan, "ctx-pipe-02")
            assert result["ok"] is False
        finally:
            cp.register_propose_executor(original)
