"""
S-01 Freeze System Real — Integration Tests

Validates end-to-end freeze behavior through the live webhook server:

1. POST /admin/governance/mode {mode: FROZEN} → sets system to FROZEN.
2. GET /mso/state reflects FROZEN after freeze is applied.
3. POST /chat/process is blocked (503) while system is FROZEN.
4. POST /admin/governance/mode {mode: NORMAL} → clears FROZEN, restores operation.
5. POST /chat/process succeeds (not 503) after NORMAL is restored.
6. Freeze endpoint requires correct admin token (fail-closed).
7. Freeze endpoint requires correct webhook token.
"""
from __future__ import annotations

import http.client
import json
import time
import unittest

# Read the effective tokens from config — same values the server loaded at startup.
# Never hardcode stubs: if CI sets WEBHOOK_TOKEN to a real value, conftest.py's
# setdefault has no effect, and the server holds the real token. Reading from
# config ensures tests always send the token that _check_auth() expects.
from assistant_os.config import WEBHOOK_TOKEN as _STUB_WEBHOOK_TOKEN
from assistant_os.config import WEBHOOK_ADMIN_TOKEN as _STUB_ADMIN_TOKEN


def _post_governance_mode(
    port: int,
    mode: str,
    reason: str = "test_freeze",
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
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/admin/governance/mode", body=body, headers=headers)
    resp = conn.getresponse()
    status = resp.status
    data = json.loads(resp.read().decode("utf-8"))
    conn.close()
    return status, data


def _get_mso_state(port: int) -> tuple[int, dict]:
    headers = {"X-Assistant-Token": _STUB_WEBHOOK_TOKEN}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/mso/state", headers=headers)
    resp = conn.getresponse()
    status = resp.status
    data = json.loads(resp.read().decode("utf-8"))
    conn.close()
    return status, data


def _post_chat_process(port: int) -> tuple[int, dict]:
    headers = {
        "Content-Type": "application/json",
        "X-Assistant-Token": _STUB_WEBHOOK_TOKEN,
    }
    body = json.dumps({"text": "hello"}).encode("utf-8")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/chat/process", body=body, headers=headers)
    resp = conn.getresponse()
    status = resp.status
    try:
        data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        data = {}
    conn.close()
    return status, data


class TestFreezeSystemEndToEnd(unittest.TestCase):
    """
    Full freeze/unfreeze cycle verified against a live server.
    Tests run sequentially — order matters.
    """

    from assistant_os.webhook_server import WebhookHTTPServer
    server: "WebhookHTTPServer"
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        from assistant_os.webhook_server import start_server_thread
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)
        # Ensure we start in NORMAL mode
        _post_governance_mode(cls.port, "NORMAL", reason="test_setup")

    @classmethod
    def tearDownClass(cls) -> None:
        # Always restore NORMAL before shutdown so other test classes are unaffected
        _post_governance_mode(cls.port, "NORMAL", reason="test_teardown")
        cls.server.shutdown()
        cls.server.server_close()

    # Test 1 — Freeze sets mode to FROZEN
    def test_01_freeze_sets_frozen_mode(self):
        """POST /admin/governance/mode {mode: FROZEN} must return ok=true and mode=FROZEN."""
        status, data = _post_governance_mode(self.port, "FROZEN", reason="s01_freeze_test")
        self.assertEqual(status, 200, f"Expected 200, got {status}: {data}")
        self.assertTrue(data.get("ok"), f"Expected ok=true: {data}")
        self.assertEqual(data.get("mode"), "FROZEN", f"Expected mode=FROZEN: {data}")

    # Test 2 — /mso/state reflects FROZEN
    def test_02_mso_state_reflects_frozen(self):
        """GET /mso/state must return operational_mode=FROZEN after freeze."""
        # Ensure FROZEN is active (depends on test_01 having run, but set it explicitly)
        _post_governance_mode(self.port, "FROZEN", reason="s01_state_check")
        status, data = _get_mso_state(self.port)
        self.assertEqual(status, 200, f"Expected 200 from /mso/state, got {status}: {data}")
        mode = data.get("operational_mode") or data.get("mode")
        self.assertEqual(mode, "FROZEN", f"Expected operational_mode=FROZEN: {data}")

    # Test 3 — /chat/process blocked while FROZEN
    def test_03_chat_process_blocked_while_frozen(self):
        """POST /chat/process must be blocked (503) while system is FROZEN."""
        _post_governance_mode(self.port, "FROZEN", reason="s01_block_test")
        status, data = _post_chat_process(self.port)
        self.assertEqual(
            status, 503,
            f"Expected 503 (frozen block), got {status}: {data}",
        )

    # Test 4 — Restore NORMAL clears FROZEN
    def test_04_restore_normal_clears_frozen(self):
        """POST /admin/governance/mode {mode: NORMAL} must return ok=true."""
        _post_governance_mode(self.port, "FROZEN", reason="s01_restore_pre")
        status, data = _post_governance_mode(self.port, "NORMAL", reason="s01_restore_test")
        self.assertEqual(status, 200, f"Expected 200, got {status}: {data}")
        self.assertTrue(data.get("ok"), f"Expected ok=true: {data}")

    # Test 5 — /chat/process succeeds after NORMAL restored
    def test_05_chat_process_not_blocked_after_normal(self):
        """POST /chat/process must not return 503 after NORMAL is restored."""
        _post_governance_mode(self.port, "NORMAL", reason="s01_unblock_verify")
        status, _data = _post_chat_process(self.port)
        self.assertNotEqual(
            status, 503,
            f"Got 503 after restoring NORMAL — freeze not cleared.",
        )

    # Test 6 — Wrong admin token → 403 (fail-closed)
    def test_06_freeze_requires_correct_admin_token(self):
        """Freeze endpoint must return 403 with wrong admin token (fail-closed)."""
        status, data = _post_governance_mode(
            self.port, "FROZEN", admin_token="wrong-admin-token"
        )
        self.assertEqual(status, 403, f"Expected 403 with wrong admin token: {data}")

    # Test 7 — Wrong webhook token → 401
    def test_07_freeze_requires_correct_webhook_token(self):
        """Freeze endpoint must return 401 with wrong webhook token."""
        status, data = _post_governance_mode(
            self.port, "FROZEN", webhook_token="wrong-webhook-token"
        )
        self.assertEqual(status, 401, f"Expected 401 with wrong webhook token: {data}")
