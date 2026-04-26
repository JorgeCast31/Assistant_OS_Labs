"""
S-02 Admin Token Hardening — Security Tests

Validates that:
1. validate_startup_config() raises RuntimeError when WEBHOOK_TOKEN is absent.
2. /admin/governance/mode returns 403 when WEBHOOK_ADMIN_TOKEN is absent.
3. /admin/governance/mode returns 403 when the admin token is wrong.
4. /admin/governance/mode is reachable (not 403) with correct tokens.
5. _check_auth() returns 503 when WEBHOOK_TOKEN is None (fail-closed).
6. _check_auth() returns 401 (not 503) when WEBHOOK_TOKEN is set but token is wrong.
7. No insecure fallback token exists in config.
"""
from __future__ import annotations

import http.client
import json
import time
import unittest
from unittest.mock import patch

# conftest.py sets WEBHOOK_TOKEN and WEBHOOK_ADMIN_TOKEN as stubs before import.
# Tests that need to simulate absent tokens patch the module-level variable.

_STUB_WEBHOOK_TOKEN = "test-stub-webhook-token"
_STUB_ADMIN_TOKEN   = "test-stub-admin-token"


# ---------------------------------------------------------------------------
# Test 1 — validate_startup_config() raises when WEBHOOK_TOKEN is None
# ---------------------------------------------------------------------------

class TestValidateStartupConfig(unittest.TestCase):

    def test_raises_when_webhook_token_is_none(self):
        """validate_startup_config() must raise RuntimeError when WEBHOOK_TOKEN is None."""
        from assistant_os.config import validate_startup_config
        with patch("assistant_os.config.WEBHOOK_TOKEN", None):
            with self.assertRaises(RuntimeError) as ctx:
                validate_startup_config()
        msg = str(ctx.exception)
        self.assertIn("WEBHOOK_TOKEN", msg)
        self.assertIn("STARTUP BLOCKED", msg)

    def test_does_not_raise_when_webhook_token_is_set(self):
        """validate_startup_config() must not raise when WEBHOOK_TOKEN is set."""
        from assistant_os.config import validate_startup_config
        with patch("assistant_os.config.WEBHOOK_TOKEN", "some-valid-token"):
            try:
                validate_startup_config()
            except RuntimeError as exc:
                self.fail(f"validate_startup_config raised unexpectedly: {exc}")

    def test_no_insecure_fallback_in_config(self):
        """The string 'TEST_TOKEN_NOT_FOR_PRODUCTION_USE' must not exist in config source."""
        import inspect
        import assistant_os.config as _cfg
        source = inspect.getsource(_cfg)
        self.assertNotIn(
            "TEST_TOKEN_NOT_FOR_PRODUCTION_USE",
            source,
            "Insecure fallback token found in config.py — remove it.",
        )


# ---------------------------------------------------------------------------
# Test 2–4 — /admin/governance/mode endpoint token enforcement
# ---------------------------------------------------------------------------

class TestAdminGovernanceModeTokenEnforcement(unittest.TestCase):
    """
    Starts a real webhook server with stub tokens.
    Tests that admin token enforcement is fail-closed.
    """

    from assistant_os.webhook_server import WebhookHTTPServer
    server: "WebhookHTTPServer"
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        from assistant_os.webhook_server import start_server_thread
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def _post_governance_mode(
        self,
        mode: str,
        reason: str = "test reason",
        *,
        webhook_token: str | None = _STUB_WEBHOOK_TOKEN,
        admin_token: str | None = _STUB_ADMIN_TOKEN,
    ) -> tuple[int, dict]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if webhook_token is not None:
            headers["X-Assistant-Token"] = webhook_token
        if admin_token is not None:
            headers["X-Assistant-Admin-Token"] = admin_token
        body = json.dumps({"mode": mode, "reason": reason}).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/admin/governance/mode", body=body, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return status, data

    # Test 2 — WEBHOOK_ADMIN_TOKEN absent → 403 (fail-closed)
    def test_403_when_admin_token_not_configured(self):
        """Admin endpoint must return 403 when WEBHOOK_ADMIN_TOKEN is None."""
        with patch("assistant_os.config.WEBHOOK_ADMIN_TOKEN", None):
            status, data = self._post_governance_mode("FROZEN")
        self.assertEqual(status, 403, data)
        self.assertEqual(data.get("error", {}).get("type"), "Forbidden")

    # Test 3 — Wrong admin token → 403
    def test_403_with_wrong_admin_token(self):
        """Admin endpoint must return 403 when admin token is incorrect."""
        status, data = self._post_governance_mode("FROZEN", admin_token="wrong-admin-token")
        self.assertEqual(status, 403, data)
        self.assertEqual(data.get("error", {}).get("type"), "Forbidden")

    # Test 4 — Correct tokens → not 403 (endpoint is reachable)
    def test_success_with_correct_tokens(self):
        """Admin endpoint must not return 403 when both tokens are correct."""
        status, data = self._post_governance_mode("NORMAL")
        self.assertNotEqual(status, 403, f"Got 403 with correct tokens: {data}")
        self.assertIn("ok", data)

    # Extra: empty admin token → 403
    def test_403_with_empty_admin_token(self):
        """Admin endpoint must return 403 when admin token header is empty string."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Assistant-Token": _STUB_WEBHOOK_TOKEN,
            "X-Assistant-Admin-Token": "",
        }
        body = json.dumps({"mode": "NORMAL"}).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/admin/governance/mode", body=body, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        self.assertEqual(status, 403, data)


# ---------------------------------------------------------------------------
# Test 5–6 — _check_auth() fail-closed behavior
# ---------------------------------------------------------------------------

class TestCheckAuthFailClosed(unittest.TestCase):
    """
    Tests _check_auth() behavior when WEBHOOK_TOKEN is None or wrong.
    Uses a live server to exercise the full path.
    """

    from assistant_os.webhook_server import WebhookHTTPServer
    server: "WebhookHTTPServer"
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        from assistant_os.webhook_server import start_server_thread
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def _get_health(self, token: str | None = None) -> tuple[int, dict]:
        headers: dict[str, str] = {}
        if token is not None:
            headers["X-Assistant-Token"] = token
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/health", headers=headers)
        resp = conn.getresponse()
        status = resp.status
        try:
            data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            data = {}
        conn.close()
        return status, data

    def _post_command(self, token: str | None = None) -> tuple[int, dict]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-Assistant-Token"] = token
        body = json.dumps({"text": "test"}).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/command", body=body, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        try:
            data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            data = {}
        conn.close()
        return status, data

    # Test 5 — WEBHOOK_TOKEN None → 503 on authenticated endpoint
    def test_503_when_webhook_token_not_configured(self):
        """_check_auth() must return 503 when WEBHOOK_TOKEN is None (fail-closed)."""
        with patch("assistant_os.webhook_server.WEBHOOK_TOKEN", None):
            status, data = self._post_command(token="any-token")
        self.assertEqual(status, 503, data)
        self.assertEqual(data.get("error", {}).get("type"), "ServiceUnavailable")

    # Test 6 — WEBHOOK_TOKEN set but wrong token → 401 (not 503)
    def test_401_with_wrong_token_when_configured(self):
        """_check_auth() must return 401 (not 503) when token is wrong but WEBHOOK_TOKEN is set."""
        status, data = self._post_command(token="definitely-wrong-token")
        self.assertEqual(status, 401, data)
        self.assertEqual(data.get("error", {}).get("type"), "Unauthorized")

    # Test 7 — No token header → 401
    def test_401_with_missing_token_header(self):
        """_check_auth() must return 401 when no token header is sent."""
        status, data = self._post_command(token=None)
        self.assertEqual(status, 401, data)
        self.assertEqual(data.get("error", {}).get("type"), "Unauthorized")

    # Test 8 — Correct token → 200 (end-to-end auth success)
    def test_200_with_correct_token(self):
        """Correct WEBHOOK_TOKEN must result in authenticated access (not 401/503)."""
        status, data = self._post_command(token=_STUB_WEBHOOK_TOKEN)
        self.assertNotIn(status, (401, 503), f"Got auth error with correct token: {status} {data}")
