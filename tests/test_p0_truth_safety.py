"""
P0 — Alpha 1 Truth & Safety tests.

P0-1: CODE sin ANTHROPIC_API_KEY debe fallar visible.
P0-2: CODE apply debe validar repo_path contra allowlist fail-closed.

These tests validate the invariants defined in the Alpha 1 sprint:
  - No silent stubs that return fake analysis.
  - No writes to unauthorized repo paths.
  - Path traversal must be blocked.
  - .git writes must be blocked.
  - REVIEW/EXPLAIN must not be broken by P0-2 (no-write path unaffected).
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(action: str, *, raw_text: str = "test", domain_payload: dict | None = None) -> dict:
    return {
        "action": action,
        "domain": "CODE",
        "raw_text": raw_text,
        "domain_payload": domain_payload or {},
        "trace_id": "p0-trace",
        "plan_id": "p0-plan",
    }


def _isolate(fn):
    """Decorator: reset pipeline executor state before/after each test."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        import assistant_os.pipelines.code_pipeline as cp
        orig_review = cp._review_executor
        orig_propose = cp._propose_executor
        try:
            return fn(*args, **kwargs)
        finally:
            cp._review_executor = orig_review
            cp._propose_executor = orig_propose

    return wrapper


# ===========================================================================
# P0-1 — CODE sin ANTHROPIC_API_KEY debe fallar visible
# ===========================================================================

class TestP01ExecutorUnavailable:
    """P0-1: When ANTHROPIC_API_KEY is absent, CODE must return an explicit
    executor_unavailable error — never a silent stub with fake analysis."""

    @_isolate
    def test_code_explain_no_api_key_returns_ok_false(self, monkeypatch):
        """CODE_EXPLAIN without API key must return ok=False."""
        import assistant_os.pipelines.code_pipeline as cp
        cp._review_executor = None  # simulate no key / no setup

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(_make_plan("CODE_EXPLAIN"), "ctx-p01-01")

        assert result["ok"] is False, "Expected ok=False when no executor is registered"

    @_isolate
    def test_code_explain_no_api_key_type_is_executor_unavailable(self, monkeypatch):
        """CODE_EXPLAIN result type must be executor_unavailable (not stub analysis)."""
        import assistant_os.pipelines.code_pipeline as cp
        cp._review_executor = None

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(_make_plan("CODE_EXPLAIN"), "ctx-p01-02")

        assert result["data"]["type"] == "executor_unavailable"

    @_isolate
    def test_code_explain_no_api_key_analysis_performed_is_false(self):
        """CODE_EXPLAIN must explicitly report no analysis was performed."""
        import assistant_os.pipelines.code_pipeline as cp
        cp._review_executor = None

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(_make_plan("CODE_EXPLAIN"), "ctx-p01-03")

        assert result["data"]["analysis_performed"] is False

    @_isolate
    def test_code_explain_no_api_key_executor_live_is_false(self):
        """CODE_EXPLAIN must report executor_live=False when no key is configured."""
        import assistant_os.pipelines.code_pipeline as cp
        cp._review_executor = None

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(_make_plan("CODE_EXPLAIN"), "ctx-p01-04")

        assert result["data"]["executor_live"] is False

    @_isolate
    def test_code_explain_no_api_key_message_is_informative(self):
        """CODE_EXPLAIN error message must mention the missing configuration."""
        import assistant_os.pipelines.code_pipeline as cp
        cp._review_executor = None

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(_make_plan("CODE_EXPLAIN"), "ctx-p01-05")

        msg = result.get("message", "").lower()
        assert "anthropic_api_key" in msg or "executor" in msg or "configurada" in msg, (
            f"Expected informative message, got: {result.get('message')!r}"
        )

    @_isolate
    def test_code_review_no_api_key_returns_ok_false(self):
        """CODE_REVIEW without API key must return ok=False."""
        import assistant_os.pipelines.code_pipeline as cp
        cp._review_executor = None

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(_make_plan("CODE_REVIEW"), "ctx-p01-06")

        assert result["ok"] is False
        assert result["data"]["type"] == "executor_unavailable"

    @_isolate
    def test_code_fix_preview_no_api_key_returns_ok_false(self, tmp_path):
        """CODE_FIX preview without API key must return ok=False — not a stub proposal."""
        import assistant_os.pipelines.code_pipeline as cp
        cp._propose_executor = None

        (tmp_path / "target.py").write_text("x = 1\n")

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(
            _make_plan(
                "CODE_FIX",
                raw_text="fix the function",
                domain_payload={"workspace": str(tmp_path), "target_file": "target.py"},
            ),
            "ctx-p01-07",
        )

        assert result["ok"] is False
        assert result["data"]["type"] == "executor_unavailable"
        assert result["data"]["analysis_performed"] is False

    @_isolate
    def test_code_create_preview_no_api_key_returns_ok_false(self, tmp_path):
        """CODE_CREATE preview without API key must return ok=False."""
        import assistant_os.pipelines.code_pipeline as cp
        cp._propose_executor = None

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(
            _make_plan(
                "CODE_CREATE",
                raw_text="create a new module",
                domain_payload={"workspace": str(tmp_path), "target_file": "new.py"},
            ),
            "ctx-p01-08",
        )

        assert result["ok"] is False
        assert result["data"]["type"] == "executor_unavailable"

    @_isolate
    def test_code_explain_with_real_executor_returns_ok_true(self):
        """CODE_EXPLAIN with a registered executor must return ok=True."""
        import assistant_os.pipelines.code_pipeline as cp

        fake_executor = lambda inp: {"ok": True, "analysis": "real analysis content"}
        cp._review_executor = fake_executor

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(_make_plan("CODE_EXPLAIN"), "ctx-p01-09")

        assert result["ok"] is True
        assert result["data"]["executor_live"] is True
        assert "[stub]" not in result["data"].get("analysis", "")

    @_isolate
    def test_no_stub_analysis_returned_when_no_key(self):
        """Result must NOT contain a '[stub]' prefixed analysis when no key is set.

        This is the core invariant: fake analysis is not acceptable.
        """
        import assistant_os.pipelines.code_pipeline as cp
        cp._review_executor = None

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(_make_plan("CODE_EXPLAIN"), "ctx-p01-10")

        assert result["ok"] is False
        # There must be no analysis field with stub content
        data = result.get("data", {})
        analysis = data.get("analysis", "")
        assert "[stub]" not in analysis, (
            "Stub analysis was returned silently — P0-1 violated"
        )


# ===========================================================================
# P0-2 — CODE apply debe validar repo_path contra allowlist fail-closed
# ===========================================================================

class TestP02ApplyAllowlist:
    """P0-2: CODE apply must validate repo_path against an explicit allowlist.

    Fail-closed: no allowlist configured → deny all writes.
    """

    def _make_apply_plan(self, workspace: str, proposal_id: str = "prop-test-01") -> dict:
        proposal = {
            "proposal_id": proposal_id,
            "affected_files": ["main.py"],
            "patch_preview": "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-old\n+new\n",
            "operation_types": ["modify"],
            "risk_level": "low",
            "patch_preview_truncated": False,
        }
        return _make_plan(
            "CODE_FIX",
            domain_payload={
                "workspace": workspace,
                "target_file": "main.py",
                "phase": "apply",
                "proposal": proposal,
            },
        )

    def test_apply_no_allowlist_configured_fails_closed(self, tmp_path, monkeypatch):
        """P0-2 invariant: if CODE_APPLY_ALLOWED_REPO_PATHS is empty, apply must be denied."""
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "CODE_APPLY_ALLOWED_REPO_PATHS", [])

        from assistant_os.pipelines.code_pipeline import _validate_apply_repo_path
        error = _validate_apply_repo_path(str(tmp_path))

        assert error is not None, "Expected error when no allowlist is configured"
        assert "CODE_APPLY_ALLOWED_REPO_PATHS" in error or "bloqueado" in error.lower()

    def test_apply_workspace_outside_allowlist_is_blocked(self, tmp_path, monkeypatch):
        """P0-2: workspace outside the allowlist must be blocked."""
        import assistant_os.config as cfg
        authorized_dir = tmp_path / "authorized"
        authorized_dir.mkdir()
        other_dir = tmp_path / "other"
        other_dir.mkdir()

        monkeypatch.setattr(cfg, "CODE_APPLY_ALLOWED_REPO_PATHS", [str(authorized_dir)])

        from assistant_os.pipelines.code_pipeline import _validate_apply_repo_path
        error = _validate_apply_repo_path(str(other_dir))

        assert error is not None, "Expected error for workspace outside allowlist"

    def test_apply_workspace_inside_allowlist_is_authorized(self, tmp_path, monkeypatch):
        """P0-2: workspace inside the allowlist must pass validation."""
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "CODE_APPLY_ALLOWED_REPO_PATHS", [str(tmp_path)])

        from assistant_os.pipelines.code_pipeline import _validate_apply_repo_path
        error = _validate_apply_repo_path(str(tmp_path))

        assert error is None, f"Expected None (authorized) but got: {error!r}"

    def test_apply_path_traversal_is_blocked(self, tmp_path, monkeypatch):
        """P0-2: path traversal using ../ must be blocked after canonical resolution."""
        import assistant_os.config as cfg
        authorized_dir = tmp_path / "safe"
        authorized_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()

        monkeypatch.setattr(cfg, "CODE_APPLY_ALLOWED_REPO_PATHS", [str(authorized_dir)])

        # Traversal: safe/../outside → resolves to outside_dir (not authorized)
        traversal_path = str(authorized_dir) + "/../outside"

        from assistant_os.pipelines.code_pipeline import _validate_apply_repo_path
        error = _validate_apply_repo_path(traversal_path)

        assert error is not None, (
            "Path traversal that escapes allowlist must be blocked. "
            f"Traversal path: {traversal_path!r}"
        )

    def test_apply_git_dir_is_blocked(self, tmp_path, monkeypatch):
        """P0-2: writes inside .git must be explicitly blocked."""
        import assistant_os.config as cfg
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Even if .git is somehow in the allowlist, it must be blocked
        monkeypatch.setattr(cfg, "CODE_APPLY_ALLOWED_REPO_PATHS", [str(tmp_path)])

        from assistant_os.pipelines.code_pipeline import _validate_apply_repo_path
        error = _validate_apply_repo_path(str(git_dir))

        assert error is not None, "Writes inside .git must be blocked"
        assert ".git" in error or "git" in error.lower()

    def test_apply_subdirectory_inside_authorized_root_is_allowed(self, tmp_path, monkeypatch):
        """P0-2: subdirectory inside authorized root must be allowed."""
        import assistant_os.config as cfg
        subdir = tmp_path / "src" / "module"
        subdir.mkdir(parents=True)

        monkeypatch.setattr(cfg, "CODE_APPLY_ALLOWED_REPO_PATHS", [str(tmp_path)])

        from assistant_os.pipelines.code_pipeline import _validate_apply_repo_path
        error = _validate_apply_repo_path(str(subdir))

        assert error is None, f"Subdirectory inside authorized root should be allowed: {error!r}"

    def test_apply_pipeline_blocks_when_no_allowlist(self, tmp_path, monkeypatch):
        """P0-2 end-to-end: pipeline apply returns ok=False with RepoPathNotAuthorized."""
        import assistant_os.config as cfg
        import assistant_os.pipelines.code_pipeline as cp
        monkeypatch.setattr(cfg, "CODE_APPLY_ALLOWED_REPO_PATHS", [])

        (tmp_path / "main.py").write_text("old = 1\n")

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(self._make_apply_plan(str(tmp_path)), "ctx-p02-pipeline")

        assert result["ok"] is False
        error_type = result.get("error", {}).get("type", "")
        assert error_type == "RepoPathNotAuthorized", (
            f"Expected RepoPathNotAuthorized, got: {error_type!r}"
        )
        assert result["data"]["guard_failure"] == "RepoPathNotAuthorized"

    def test_apply_pipeline_authorized_path_passes_guard(self, tmp_path, monkeypatch):
        """P0-2 end-to-end: apply with authorized path reaches the next guard (not allowlist blocked)."""
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "CODE_APPLY_ALLOWED_REPO_PATHS", [str(tmp_path)])

        (tmp_path / "main.py").write_text("old = 1\n")

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        # A duplicate proposal_id ensures we hit Guard 1 (single-use) instead of Guard 0.5
        # This proves the allowlist guard was passed.
        import assistant_os.pipelines.code_pipeline as cp
        cp._applied_proposals.add("prop-already-applied")

        result = code_execute(
            self._make_apply_plan(str(tmp_path), proposal_id="prop-already-applied"),
            "ctx-p02-authorized",
        )

        # If we reach Guard 1, the allowlist was not the blocker
        error_type = result.get("error", {}).get("type", "")
        assert error_type != "RepoPathNotAuthorized", (
            "Allowlist guard should have passed for authorized path, "
            f"but got: {error_type!r}"
        )
        # Clean up
        cp._applied_proposals.discard("prop-already-applied")


# ===========================================================================
# Smoke tests — REVIEW and EXPLAIN not broken by P0-2 (no-write paths)
# ===========================================================================

class TestP0SmokeNonWritePaths:
    """REVIEW and EXPLAIN must not be affected by the P0-2 allowlist guard.

    These paths never write files, so allowlist validation is irrelevant.
    """

    @_isolate
    def test_code_explain_with_executor_not_blocked_by_allowlist(self, monkeypatch):
        """CODE_EXPLAIN (read-only) is not subject to the P0-2 allowlist guard."""
        import assistant_os.pipelines.code_pipeline as cp
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "CODE_APPLY_ALLOWED_REPO_PATHS", [])  # empty allowlist

        # Register a real executor so P0-1 doesn't trigger
        cp._review_executor = lambda inp: {"ok": True, "analysis": "ok analysis"}

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(_make_plan("CODE_EXPLAIN"), "ctx-smoke-01")

        assert result["ok"] is True, (
            "CODE_EXPLAIN must not be blocked by P0-2 allowlist (it does not write files)"
        )

    @_isolate
    def test_code_review_with_executor_not_blocked_by_allowlist(self, monkeypatch):
        """CODE_REVIEW (read-only) is not subject to the P0-2 allowlist guard."""
        import assistant_os.pipelines.code_pipeline as cp
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "CODE_APPLY_ALLOWED_REPO_PATHS", [])

        cp._review_executor = lambda inp: {"ok": True, "analysis": "ok review"}

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        result = code_execute(_make_plan("CODE_REVIEW"), "ctx-smoke-02")

        assert result["ok"] is True, (
            "CODE_REVIEW must not be blocked by P0-2 allowlist (it does not write files)"
        )
