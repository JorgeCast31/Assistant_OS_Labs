"""
Tests — Executor startup wiring (assistant_os/executors/startup.py)

Covers:
  A. setup_code_read_executor() — returns correct status and wires/unwires
  B. get_code_executor_status()  — reads current state without side effects
  C. Idempotency and error resilience
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _isolate(fn):
    """
    Decorator that saves and restores _review_executor around a test so that
    startup wiring calls in one test don't pollute another.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        import assistant_os.pipelines.code_pipeline as cp
        original = cp._review_executor
        try:
            return fn(*args, **kwargs)
        finally:
            cp.register_review_executor(original)

    return wrapper


# ---------------------------------------------------------------------------
# A. setup_code_read_executor
# ---------------------------------------------------------------------------

class TestSetupCodeReadExecutor:

    @_isolate
    def test_no_api_key_returns_live_false(self, monkeypatch):
        """With no ANTHROPIC_API_KEY, setup returns live=False and stubs executor."""
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", None)

        from assistant_os.executors.startup import setup_code_read_executor
        status = setup_code_read_executor()

        assert status["live"] is False
        assert status["model"] is None
        assert "ANTHROPIC_API_KEY" in status["note"]

    @_isolate
    def test_no_api_key_stubs_pipeline_executor(self, monkeypatch):
        """With no key, the pipeline executor is None (stub active)."""
        import assistant_os.config as cfg
        import assistant_os.pipelines.code_pipeline as cp
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", None)

        from assistant_os.executors.startup import setup_code_read_executor
        setup_code_read_executor()

        assert cp._review_executor is None

    @_isolate
    def test_api_key_present_returns_live_true(self, monkeypatch):
        """With ANTHROPIC_API_KEY set and a fake client, returns live=True."""
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-ant-fake-key-for-test")

        # Patch build_claude_review_executor to avoid real API construction
        import assistant_os.executors.code_review_executor as cre
        fake_executor = lambda inp: {"ok": True, "analysis": "test"}
        monkeypatch.setattr(cre, "build_claude_review_executor",
                            lambda **kw: fake_executor)

        from assistant_os.executors.startup import setup_code_read_executor
        status = setup_code_read_executor()

        assert status["live"] is True
        assert status["model"] is not None
        assert status["note"] == ""

    @_isolate
    def test_api_key_present_registers_executor(self, monkeypatch):
        """With key set, the pipeline's _review_executor is not None after setup."""
        import assistant_os.config as cfg
        import assistant_os.pipelines.code_pipeline as cp
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-ant-fake-key-for-test")

        import assistant_os.executors.code_review_executor as cre
        fake_executor = lambda inp: {"ok": True, "analysis": "test"}
        monkeypatch.setattr(cre, "build_claude_review_executor",
                            lambda **kw: fake_executor)

        from assistant_os.executors.startup import setup_code_read_executor
        setup_code_read_executor()

        assert cp._review_executor is not None

    @_isolate
    def test_build_exception_falls_back_to_stub(self, monkeypatch):
        """If executor construction raises, setup returns live=False without crashing."""
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-ant-fake-key-for-test")

        import assistant_os.executors.code_review_executor as cre

        def _boom(**kw):
            raise RuntimeError("simulated build failure")

        monkeypatch.setattr(cre, "build_claude_review_executor", _boom)

        from assistant_os.executors.startup import setup_code_read_executor
        status = setup_code_read_executor()

        assert status["live"] is False
        assert "setup failed" in status["note"]

    @_isolate
    def test_build_exception_stubs_pipeline(self, monkeypatch):
        """Executor construction failure leaves pipeline executor as None (stub)."""
        import assistant_os.config as cfg
        import assistant_os.pipelines.code_pipeline as cp
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-ant-fake-key-for-test")

        import assistant_os.executors.code_review_executor as cre
        monkeypatch.setattr(cre, "build_claude_review_executor",
                            lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))

        from assistant_os.executors.startup import setup_code_read_executor
        setup_code_read_executor()

        assert cp._review_executor is None

    @_isolate
    def test_idempotent_with_key(self, monkeypatch):
        """Calling setup twice with a key active has the same result as once."""
        import assistant_os.config as cfg
        import assistant_os.pipelines.code_pipeline as cp
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-ant-fake-key-for-test")

        import assistant_os.executors.code_review_executor as cre
        fake_executor = lambda inp: {"ok": True, "analysis": "x"}
        monkeypatch.setattr(cre, "build_claude_review_executor",
                            lambda **kw: fake_executor)

        from assistant_os.executors.startup import setup_code_read_executor
        s1 = setup_code_read_executor()
        s2 = setup_code_read_executor()

        assert s1["live"] == s2["live"] == True
        assert cp._review_executor is not None

    @_isolate
    def test_idempotent_without_key(self, monkeypatch):
        """Calling setup twice without a key leaves executor as None both times."""
        import assistant_os.config as cfg
        import assistant_os.pipelines.code_pipeline as cp
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", None)

        from assistant_os.executors.startup import setup_code_read_executor
        setup_code_read_executor()
        setup_code_read_executor()

        assert cp._review_executor is None


# ---------------------------------------------------------------------------
# B. get_code_executor_status
# ---------------------------------------------------------------------------

class TestGetCodeExecutorStatus:

    @_isolate
    def test_returns_live_false_when_no_executor(self):
        """When _review_executor is None, status is live=False."""
        import assistant_os.pipelines.code_pipeline as cp
        cp.register_review_executor(None)

        from assistant_os.executors.startup import get_code_executor_status
        status = get_code_executor_status()

        assert status["live"] is False
        assert status["model"] is None

    @_isolate
    def test_returns_live_true_when_executor_registered(self):
        """When a real executor is registered, status is live=True with model."""
        import assistant_os.pipelines.code_pipeline as cp
        cp.register_review_executor(lambda inp: {"ok": True, "analysis": "x"})

        from assistant_os.executors.startup import get_code_executor_status
        status = get_code_executor_status()

        assert status["live"] is True
        assert status["model"] is not None

    @_isolate
    def test_does_not_change_pipeline_state(self):
        """get_code_executor_status is purely read-only."""
        import assistant_os.pipelines.code_pipeline as cp
        cp.register_review_executor(None)

        from assistant_os.executors.startup import get_code_executor_status
        get_code_executor_status()
        get_code_executor_status()

        assert cp._review_executor is None


# ---------------------------------------------------------------------------
# C. End-to-end: startup wiring → pipeline execution
# ---------------------------------------------------------------------------

class TestStartupToExecution:

    @_isolate
    def test_live_executor_produces_real_analysis_after_setup(self, monkeypatch):
        """After wiring via setup, CODE_EXPLAIN calls the registered executor."""
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", "sk-ant-fake")

        import assistant_os.executors.code_review_executor as cre
        monkeypatch.setattr(
            cre, "build_claude_review_executor",
            lambda **kw: (lambda inp: {"ok": True, "analysis": "startup-wired analysis"}),
        )

        from assistant_os.executors.startup import setup_code_read_executor
        setup_code_read_executor()

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        plan = {
            "action": "CODE_EXPLAIN",
            "domain": "CODE",
            "raw_text": "explícame este archivo",
            "domain_payload": {},
            "trace_id": "t1",
            "plan_id": "p1",
        }
        result = code_execute(plan, "ctx-startup-01")
        assert result["ok"] is True
        assert result["data"]["analysis"] == "startup-wired analysis"
        assert result["data"]["executor_live"] is True

    @_isolate
    def test_stub_used_when_no_key(self, monkeypatch):
        """With no API key, CODE_EXPLAIN returns stub analysis (contains '[stub]')."""
        import assistant_os.config as cfg
        monkeypatch.setattr(cfg, "ANTHROPIC_API_KEY", None)

        from assistant_os.executors.startup import setup_code_read_executor
        setup_code_read_executor()

        from assistant_os.pipelines.code_pipeline import execute as code_execute
        plan = {
            "action": "CODE_EXPLAIN",
            "domain": "CODE",
            "raw_text": "test",
            "domain_payload": {},
            "trace_id": "t2",
            "plan_id": "p2",
        }
        result = code_execute(plan, "ctx-startup-02")
        assert result["ok"] is True
        assert "[stub]" in result["data"]["analysis"]
        assert result["data"]["executor_live"] is False
