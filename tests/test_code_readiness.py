"""Tests for assistant_os.codeops.readiness.

Verifies the CODE readiness producer:
1. get_code_readiness() returns a structured summary dict.
2. Probes are read-only and fail-soft (never raise).
3. Docker daemon is NEVER probed when APPLY_EXECUTION_MODE != "real".
4. Docker probe is daemon-ping only — never instantiates a container.
5. Code API probe uses a tight timeout and never raises.
6. CODE capabilities are filtered from the registry, not invented.
7. Counts (allowed / confirm_only / blocked) are derived, not hard-coded.
8. Producer is read-only — never mutates state, never calls pipelines/agents.
9. Producer never claims authority — no execution_mode, no GovernanceVerdict.
10. Output is JSON-serializable.

INVARIANTS this module enforces (architectural):
  - readiness producer is a passive observer; no apply, no execute.
  - Docker probe must use `docker info`/`docker version` (CLI), never `docker run`.
  - Default APPLY_EXECUTION_MODE is "stub", so by default no Docker probe runs.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Shape / contract tests
# ---------------------------------------------------------------------------

class TestGetCodeReadinessReturnsDict(unittest.TestCase):
    """get_code_readiness() returns a dict with the documented schema."""

    def test_returns_dict(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        result = get_code_readiness()
        self.assertIsInstance(result, dict)

    def test_has_identity_fields(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        result = get_code_readiness()
        self.assertEqual(result["domain"], "CODE")
        self.assertIs(result["feature_enabled"], True)
        self.assertIsInstance(result["last_health_check"], str)
        self.assertGreater(len(result["last_health_check"]), 0)
        self.assertIsInstance(result["note"], str)
        self.assertIn("authority", result["note"].lower())

    def test_has_code_api_fields(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        result = get_code_readiness()
        self.assertIn("code_api_reachable", result)
        self.assertIsInstance(result["code_api_reachable"], bool)
        self.assertIn("code_api_url", result)
        self.assertIsInstance(result["code_api_url"], str)
        self.assertIn("code_api_latency_ms", result)
        self.assertIsInstance(result["code_api_latency_ms"], int)
        self.assertGreaterEqual(result["code_api_latency_ms"], 0)

    def test_has_apply_mode_fields(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        result = get_code_readiness()
        self.assertIn("apply_execution_mode", result)
        self.assertIn(result["apply_execution_mode"], ("stub", "real"))
        self.assertIsInstance(result["apply_real_enabled"], bool)

    def test_has_runner_backend_fields(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        result = get_code_readiness()
        self.assertIn("runner_backend_probed", result)
        self.assertIsInstance(result["runner_backend_probed"], bool)
        self.assertIn("runner_backend_available", result)
        # available may be bool or None
        self.assertIn(result["runner_backend_available"], (True, False, None))

    def test_has_runner_config_fields(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        result = get_code_readiness()
        self.assertIsInstance(result["runner_timeout_seconds"], int)
        self.assertIsInstance(result["runner_memory_limit"], str)
        self.assertIsInstance(result["runner_cpu_limit"], str)
        self.assertIsInstance(result["runner_base_image"], str)

    def test_has_capability_fields(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        result = get_code_readiness()
        self.assertIsInstance(result["code_capabilities"], list)
        self.assertIsInstance(result["code_capability_allowed_count"], int)
        self.assertIsInstance(result["code_capability_confirm_only_count"], int)
        self.assertIsInstance(result["code_capability_blocked_count"], int)

    def test_output_is_json_serializable(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        result = get_code_readiness()
        # Should not raise.
        encoded = json.dumps(result)
        self.assertIsInstance(encoded, str)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["domain"], "CODE")


# ---------------------------------------------------------------------------
# Apply-mode behavior
# ---------------------------------------------------------------------------

class TestApplyModeStub(unittest.TestCase):
    """When APPLY_EXECUTION_MODE is 'stub' (default), Docker is NEVER probed."""

    def test_stub_mode_skips_docker_probe(self) -> None:
        from assistant_os.codeops import readiness
        with patch.object(readiness, "_get_apply_mode", return_value="stub"):
            with patch.object(readiness, "_probe_runner_backend") as probe:
                result = readiness.get_code_readiness()
                # Probe MUST NOT be called when stub.
                probe.assert_not_called()
        self.assertFalse(result["runner_backend_probed"])
        self.assertIsNone(result["runner_backend_available"])
        self.assertFalse(result["apply_real_enabled"])
        self.assertEqual(result["apply_execution_mode"], "stub")

    def test_stub_mode_runner_backend_error_is_explanatory(self) -> None:
        from assistant_os.codeops import readiness
        with patch.object(readiness, "_get_apply_mode", return_value="stub"):
            result = readiness.get_code_readiness()
        self.assertIn("stub", (result.get("runner_backend_error") or "").lower())


class TestApplyModeReal(unittest.TestCase):
    """When APPLY_EXECUTION_MODE is 'real', Docker daemon IS probed (ping-only)."""

    def test_real_mode_calls_runner_probe(self) -> None:
        from assistant_os.codeops import readiness
        with patch.object(readiness, "_get_apply_mode", return_value="real"):
            with patch.object(readiness, "_probe_runner_backend") as probe:
                probe.return_value = (True, 12, None)
                result = readiness.get_code_readiness()
                probe.assert_called_once()
        self.assertTrue(result["runner_backend_probed"])
        self.assertTrue(result["runner_backend_available"])
        self.assertEqual(result["runner_backend_latency_ms"], 12)
        self.assertTrue(result["apply_real_enabled"])

    def test_real_mode_probe_failure_is_fail_soft(self) -> None:
        from assistant_os.codeops import readiness
        with patch.object(readiness, "_get_apply_mode", return_value="real"):
            with patch.object(readiness, "_probe_runner_backend") as probe:
                probe.return_value = (False, 0, "docker daemon unreachable")
                result = readiness.get_code_readiness()
        self.assertTrue(result["runner_backend_probed"])
        self.assertFalse(result["runner_backend_available"])
        self.assertEqual(result["runner_backend_error"], "docker daemon unreachable")


class TestRunnerProbeNeverCreatesContainer(unittest.TestCase):
    """Hard invariant — the docker probe must use info/version, never run."""

    def test_probe_uses_info_or_version_only(self) -> None:
        from assistant_os.codeops import readiness
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="Server Version: 24.0.7\n", stderr="")
            available, latency, err = readiness._probe_runner_backend()
            run.assert_called_once()
            args = run.call_args[0][0]
            # First arg is `docker`, second must be a non-mutating subcommand.
            self.assertEqual(args[0], "docker")
            self.assertIn(args[1], ("info", "version"))
            # Must NOT contain "run", "exec", "create", "start" anywhere.
            forbidden = {"run", "exec", "create", "start", "rm", "kill"}
            for tok in args:
                self.assertNotIn(tok, forbidden, f"Forbidden token in probe args: {args}")
        self.assertTrue(available)
        self.assertGreaterEqual(latency, 0)
        self.assertIsNone(err)

    def test_probe_returns_unavailable_on_subprocess_error(self) -> None:
        from assistant_os.codeops import readiness
        with patch("subprocess.run", side_effect=FileNotFoundError("docker not found")):
            available, latency, err = readiness._probe_runner_backend()
        self.assertFalse(available)
        self.assertEqual(latency, 0)
        self.assertIsNotNone(err)
        self.assertIn("docker", err.lower())

    def test_probe_returns_unavailable_on_nonzero_exit(self) -> None:
        from assistant_os.codeops import readiness
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=1, stdout="", stderr="cannot connect to daemon")
            available, latency, err = readiness._probe_runner_backend()
        self.assertFalse(available)
        self.assertIsNotNone(err)

    def test_probe_returns_unavailable_on_timeout(self) -> None:
        from assistant_os.codeops import readiness
        import subprocess as _sp
        with patch("subprocess.run", side_effect=_sp.TimeoutExpired(cmd="docker info", timeout=1.0)):
            available, latency, err = readiness._probe_runner_backend()
        self.assertFalse(available)
        self.assertIsNotNone(err)
        self.assertIn("timeout", err.lower())


# ---------------------------------------------------------------------------
# Code API probe behavior
# ---------------------------------------------------------------------------

class TestCodeApiProbe(unittest.TestCase):
    """Code API probe must be read-only and fail-soft."""

    def test_probe_success(self) -> None:
        from assistant_os.codeops import readiness
        fake_resp = MagicMock()
        fake_resp.status = 200
        fake_resp.read.return_value = b'{"status":"ok","service":"code_api"}'
        fake_resp.__enter__ = lambda self_: self_
        fake_resp.__exit__ = lambda *a, **k: False
        with patch.object(readiness, "_open_url", return_value=fake_resp):
            reachable, latency, err = readiness._probe_code_api()
        self.assertTrue(reachable)
        self.assertGreaterEqual(latency, 0)
        self.assertIsNone(err)

    def test_probe_handles_url_error(self) -> None:
        from assistant_os.codeops import readiness
        from urllib.error import URLError
        with patch.object(readiness, "_open_url", side_effect=URLError("connection refused")):
            reachable, latency, err = readiness._probe_code_api()
        self.assertFalse(reachable)
        self.assertEqual(latency, 0)
        self.assertIsNotNone(err)

    def test_probe_handles_arbitrary_exception(self) -> None:
        from assistant_os.codeops import readiness
        with patch.object(readiness, "_open_url", side_effect=RuntimeError("boom")):
            reachable, latency, err = readiness._probe_code_api()
        self.assertFalse(reachable)
        self.assertIsNotNone(err)


# ---------------------------------------------------------------------------
# Capability summary tests — derived, never invented.
# ---------------------------------------------------------------------------

class TestCodeCapabilitiesSummary(unittest.TestCase):
    """code_capabilities reflect the registry exactly — no inventions."""

    def setUp(self) -> None:
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        reset_dynamic_capabilities()

    def test_only_code_domain_listed(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        result = get_code_readiness()
        for cap in result["code_capabilities"]:
            self.assertEqual(cap["domain"], "CODE",
                             f"Non-CODE capability leaked into summary: {cap}")

    def test_summary_contains_known_code_actions(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        from assistant_os.contracts import (
            ACTION_CODE_EXPLAIN, ACTION_CODE_REVIEW,
            ACTION_CODE_FIX, ACTION_CODE_CREATE,
        )
        result = get_code_readiness()
        actions = {cap["action"] for cap in result["code_capabilities"]}
        for expected in (ACTION_CODE_EXPLAIN, ACTION_CODE_REVIEW,
                         ACTION_CODE_FIX, ACTION_CODE_CREATE):
            self.assertIn(expected, actions,
                          f"Expected CODE action {expected} not present.")

    def test_counts_match_listed_capabilities(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        result = get_code_readiness()
        caps = result["code_capabilities"]
        allowed = sum(1 for c in caps if c["mode"] == "allow" and c.get("allowed", True))
        confirm = sum(1 for c in caps if c["mode"] == "confirm_only")
        blocked = sum(1 for c in caps if (c["mode"] == "deny") or not c.get("allowed", True))
        self.assertEqual(result["code_capability_allowed_count"], allowed)
        self.assertEqual(result["code_capability_confirm_only_count"], confirm)
        self.assertEqual(result["code_capability_blocked_count"], blocked)

    def test_each_capability_has_required_fields(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        result = get_code_readiness()
        for cap in result["code_capabilities"]:
            self.assertIn("action", cap)
            self.assertIn("domain", cap)
            self.assertIn("mode", cap)
            self.assertIn("allowed", cap)
            self.assertIn(cap["mode"], ("allow", "confirm_only", "plan_only", "deny"))


# ---------------------------------------------------------------------------
# Negative / invariant tests — readiness must NOT touch authority surfaces.
# ---------------------------------------------------------------------------

class TestReadinessIsReadOnly(unittest.TestCase):
    """Hard invariants — readiness must never call execution / authority paths."""

    def test_does_not_call_kernel_router(self) -> None:
        # Defensive: import surface should not pull kernel/router execution paths
        # at call time. We assert by patching common entrypoints and verifying
        # they were never invoked.
        from assistant_os.codeops import readiness
        try:
            from assistant_os import router as _router
        except ImportError:
            self.skipTest("router not importable in this layout")
            return
        with patch.object(_router, "handle_request", create=True) as kernel_handle:
            readiness.get_code_readiness()
            kernel_handle.assert_not_called()

    def test_does_not_call_code_pipeline(self) -> None:
        from assistant_os.codeops import readiness
        try:
            from assistant_os.pipelines import code_pipeline as _cp
        except ImportError:
            self.skipTest("code_pipeline not importable in this layout")
            return
        # Patch any obvious entrypoint; if absent, this test simply asserts
        # the import does not crash readiness.
        for name in ("run_pipeline", "execute", "handle"):
            if hasattr(_cp, name):
                with patch.object(_cp, name) as fn:
                    readiness.get_code_readiness()
                    fn.assert_not_called()

    def test_does_not_write_to_audit_store(self) -> None:
        from assistant_os.codeops import readiness
        try:
            from assistant_os.sandbox import audit_store as _audit
        except ImportError:
            self.skipTest("audit_store not importable in this layout")
            return
        # Any function that looks like a writer should not be called.
        for writer_name in ("append", "write", "record", "save"):
            if hasattr(_audit, writer_name):
                with patch.object(_audit, writer_name) as fn:
                    readiness.get_code_readiness()
                    fn.assert_not_called()

    def test_does_not_produce_execution_mode_or_verdict(self) -> None:
        from assistant_os.codeops.readiness import get_code_readiness
        result = get_code_readiness()
        # Forbidden authority fields must not appear.
        for forbidden in ("execution_mode", "effective_execution_mode",
                          "governance_verdict", "policy_decision",
                          "authorized", "approved"):
            self.assertNotIn(forbidden, result,
                             f"Readiness leaked authority field: {forbidden}")

    def test_function_never_raises(self) -> None:
        """Even with all probes broken, get_code_readiness() returns a dict."""
        from assistant_os.codeops import readiness
        with patch.object(readiness, "_probe_code_api",
                          side_effect=RuntimeError("api boom")):
            with patch.object(readiness, "_probe_runner_backend",
                              side_effect=RuntimeError("docker boom")):
                with patch.object(readiness, "_summarize_code_capabilities",
                                  side_effect=RuntimeError("registry boom")):
                    result = readiness.get_code_readiness()
        self.assertIsInstance(result, dict)
        self.assertEqual(result["domain"], "CODE")
        # Must surface that something failed without raising.
        self.assertFalse(result["code_api_reachable"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
