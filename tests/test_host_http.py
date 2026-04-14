"""
Tests — Phase 4B: HOST HTTP Layer Hardening + API Contract

API contract (Phase 4B)
-----------------------
POST /host/action  body: { "action": str, "payload": dict }
POST /host/confirm body: { "plan_id": str }

Response shape (ALL cases):
  {
    "ok":          bool,
    "domain":      "HOST",
    "result_type": str,
    "data":        dict,
    "error":       { "type": str, "message": str, "code": str } | null
  }

HTTP status mapping (definitive):
  200  action executed (ok=True)
  202  plan_confirmation_required
  400  invalid/missing fields, unknown action
  401  auth missing/invalid
  404  plan_id not found / expired
  409  control_plane_blocked
  500  unexpected error

Coverage
--------
A.  Auth: 401 on missing/invalid token (both endpoints)
B.  /host/action: 400 on missing action, missing payload, bad JSON, unknown action
C.  /host/action: RISK_LOW auto-executes → 200
D.  /host/action: RISK_MEDIUM → 202 with plan_id in data
E.  /host/confirm: 400 on missing/invalid plan_id
F.  /host/confirm: 404 on unknown plan_id
G.  Full two-pass flow: /host/action → /host/confirm → 200
H.  /host/confirm: 409 CONTROL_PLANE_BLOCKED (agent quarantined between passes)
I.  /host/action RISK_LOW: agent not active → 409
J.  No bypass: both handlers call handle_request (orchestrator)
K.  CONTRACT SHAPE: every response has ok/domain/result_type/data/error
L.  CONTRACT SHAPE: error always null or {type, message, code}
M.  CONTRACT SHAPE: no extra legacy fields (no "status", "agent", "message", "ts")
N.  Idempotence: second confirm of same plan_id → 404
O.  Error codes: errors include structured code field
"""

from __future__ import annotations

import http.client
import json
import time
import unittest
from unittest.mock import MagicMock, patch

from assistant_os.webhook_server import start_server_thread, WebhookHTTPServer
from assistant_os.config import WEBHOOK_TOKEN
from assistant_os.agents.host_agent import (
    ALLOWED_DIRECTORIES,
    HOST_AGENT_ID,
    _reset_host_agent_state_for_tests,
)
from assistant_os.agents.host_audit import HOST_AUDIT_LOG
from assistant_os.context_store import clear_store
from assistant_os.core.control_plane import (
    _reset_state_for_tests,
    activate_agent,
    quarantine_agent,
)


_ALLOWED_DIR = ALLOWED_DIRECTORIES[0]

_REQUIRED_RESPONSE_KEYS = {"ok", "domain", "result_type", "data", "error"}
_FORBIDDEN_RESPONSE_KEYS = {"status", "agent", "message", "ts", "context_id"}


def _scandir_cm(entries):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=iter(entries))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


class TestHostHTTP(unittest.TestCase):
    """Integration tests for POST /host/action and POST /host/confirm."""

    server: WebhookHTTPServer
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        _reset_state_for_tests()
        _reset_host_agent_state_for_tests()
        HOST_AUDIT_LOG.clear()
        clear_store()

    def tearDown(self) -> None:
        _reset_state_for_tests()
        _reset_host_agent_state_for_tests()
        HOST_AUDIT_LOG.clear()
        clear_store()

    # -------------------------------------------------------------------------
    # HTTP helpers
    # -------------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict | None = None,
    ) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = headers or {}
        if body is not None:
            conn.request(method, path, body=body, headers=headers)
        else:
            conn.request(method, path, headers=headers)
        response = conn.getresponse()
        status = response.status
        data = response.read().decode("utf-8")
        conn.close()
        try:
            return status, json.loads(data)
        except json.JSONDecodeError:
            return status, {"_raw": data}

    def _post(self, path: str, data: dict, token: str | None = WEBHOOK_TOKEN) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-Assistant-Token"] = token
        body = json.dumps(data).encode("utf-8")
        return self._request("POST", path, body, headers)

    def _post_action(self, data: dict, token: str | None = WEBHOOK_TOKEN) -> tuple[int, dict]:
        return self._post("/host/action", data, token)

    def _post_confirm(self, data: dict, token: str | None = WEBHOOK_TOKEN) -> tuple[int, dict]:
        return self._post("/host/confirm", data, token)

    def _list_dir_payload(self) -> dict:
        return {"action": "list_directory", "path": _ALLOWED_DIR, "confirmed": True}

    def _open_app_payload(self) -> dict:
        return {"action": "open_app", "app_name": "notepad", "confirmed": True}

    # -------------------------------------------------------------------------
    # Shape validator helper
    # -------------------------------------------------------------------------

    def _assert_host_contract(self, data: dict, context: str = "") -> None:
        """Assert the response follows the HOST API contract shape."""
        prefix = f"[{context}] " if context else ""
        # Required keys
        for key in _REQUIRED_RESPONSE_KEYS:
            self.assertIn(key, data, f"{prefix}Response missing required key '{key}'")
        # domain is always HOST
        self.assertEqual(data["domain"], "HOST", f"{prefix}domain must be 'HOST'")
        # data is always a dict
        self.assertIsInstance(data["data"], dict, f"{prefix}data must be a dict")
        # error is null or structured dict
        error = data["error"]
        if error is not None:
            self.assertIsInstance(error, dict, f"{prefix}error must be dict or null")
            for k in ("type", "message", "code"):
                self.assertIn(k, error, f"{prefix}error missing field '{k}'")
        # No legacy fields
        for key in _FORBIDDEN_RESPONSE_KEYS:
            self.assertNotIn(key, data, f"{prefix}Response must not contain legacy field '{key}'")

    # =========================================================================
    # A. Auth
    # =========================================================================

    def test_action_401_missing_token(self):
        """POST /host/action without token → 401."""
        headers = {"Content-Type": "application/json"}
        body = json.dumps({"action": "list_directory", "payload": self._list_dir_payload()}).encode()
        status, _ = self._request("POST", "/host/action", body, headers)
        self.assertEqual(status, 401)

    def test_confirm_401_missing_token(self):
        """POST /host/confirm without token → 401."""
        headers = {"Content-Type": "application/json"}
        body = json.dumps({"plan_id": "00000000-0000-0000-0000-000000000000"}).encode()
        status, _ = self._request("POST", "/host/confirm", body, headers)
        self.assertEqual(status, 401)

    def test_action_401_invalid_token(self):
        """POST /host/action with wrong token → 401."""
        status, data = self._post_action(
            {"action": "list_directory", "payload": self._list_dir_payload()},
            token="bad-token",
        )
        self.assertEqual(status, 401)
        self._assert_host_contract(data, "action_401_invalid_token")
        error = data["error"]
        self.assertEqual(error["code"], "UNAUTHORIZED")

    def test_confirm_401_invalid_token(self):
        """POST /host/confirm with wrong token → 401."""
        status, data = self._post_confirm(
            {"plan_id": "00000000-0000-0000-0000-000000000000"},
            token="bad-token",
        )
        self.assertEqual(status, 401)
        self._assert_host_contract(data, "confirm_401_invalid_token")
        error = data["error"]
        self.assertEqual(error["code"], "UNAUTHORIZED")

    # =========================================================================
    # B. /host/action input validation
    # =========================================================================

    def test_action_400_missing_action(self):
        """POST /host/action without 'action' field → 400."""
        status, data = self._post_action({"payload": self._list_dir_payload()})
        self.assertEqual(status, 400)
        self._assert_host_contract(data, "400_missing_action")

    def test_action_400_missing_payload(self):
        """POST /host/action without 'payload' field → 400."""
        status, data = self._post_action({"action": "list_directory"})
        self.assertEqual(status, 400)
        self._assert_host_contract(data, "400_missing_payload")

    def test_action_400_payload_not_dict(self):
        """POST /host/action with payload as string → 400."""
        status, data = self._post_action({"action": "list_directory", "payload": "bad"})
        self.assertEqual(status, 400)
        self._assert_host_contract(data, "400_payload_not_dict")

    def test_action_400_bad_json(self):
        """POST /host/action with non-JSON body → 400."""
        headers = {"Content-Type": "application/json", "X-Assistant-Token": WEBHOOK_TOKEN}
        status, data = self._request("POST", "/host/action", b"not-json{{{", headers)
        self.assertEqual(status, 400)
        self._assert_host_contract(data, "400_bad_json")

    def test_action_400_unknown_action(self):
        """POST /host/action with unrecognized action name → 400."""
        status, data = self._post_action({"action": "nuke_everything", "payload": {}})
        self.assertEqual(status, 400)
        self._assert_host_contract(data, "400_unknown_action")
        self.assertIsNotNone(data["error"])
        self.assertEqual(data["error"]["code"], "BAD_REQUEST")

    def test_action_400_canonical_name_rejected(self):
        """POST /host/action with canonical 'HOST_LIST_DIRECTORY' is rejected.

        The HTTP API only accepts short names. No aliases.
        """
        status, data = self._post_action({
            "action": "HOST_LIST_DIRECTORY",
            "payload": self._list_dir_payload(),
        })
        self.assertEqual(status, 400)
        self._assert_host_contract(data, "400_canonical_name_rejected")

    def test_action_400_empty_body(self):
        """POST /host/action with empty body → 400."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
            "Content-Length": "0",
        }
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/host/action", body=b"", headers=headers)
        response = conn.getresponse()
        status = response.status
        conn.close()
        self.assertIn(status, (400, 422))

    # =========================================================================
    # C. /host/action RISK_LOW auto-executes → 200
    # =========================================================================

    def test_action_list_directory_200(self):
        """RISK_LOW list_directory auto-executes → 200 with ok=True."""
        activate_agent(HOST_AGENT_ID)
        mock_e = MagicMock()
        mock_e.name = "file.txt"
        mock_e.is_dir.return_value = False
        mock_e.stat.return_value = MagicMock(st_size=100)

        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm([mock_e])):
            status, data = self._post_action({
                "action": "list_directory",
                "payload": self._list_dir_payload(),
            })

        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("result_type"), "host_action")
        self._assert_host_contract(data, "list_directory_200")
        self.assertIsNone(data["error"])

    def test_action_list_directory_response_has_data(self):
        """list_directory 200 response includes 'data' with action info."""
        activate_agent(HOST_AGENT_ID)
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm([])):
            status, data = self._post_action({
                "action": "list_directory",
                "payload": self._list_dir_payload(),
            })

        self.assertEqual(status, 200)
        self._assert_host_contract(data, "list_directory_data")
        self.assertEqual(data["data"].get("action"), "list_directory")

    # =========================================================================
    # D. /host/action RISK_MEDIUM → 202 plan_confirmation_required
    # =========================================================================

    def test_action_open_app_returns_202(self):
        """RISK_MEDIUM open_app → 202 plan_confirmation_required."""
        status, data = self._post_action({
            "action": "open_app",
            "payload": self._open_app_payload(),
        })
        self.assertEqual(status, 202)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("result_type"), "plan_confirmation_required")
        self._assert_host_contract(data, "open_app_202")

    def test_action_open_app_202_plan_id_in_data(self):
        """202 response must include non-empty plan_id inside data dict."""
        status, data = self._post_action({
            "action": "open_app",
            "payload": self._open_app_payload(),
        })
        self.assertEqual(status, 202)
        self._assert_host_contract(data, "202_plan_id_in_data")
        plan_id = data["data"].get("plan_id")
        self.assertIsNotNone(plan_id, "plan_id must be in data")
        self.assertTrue(plan_id, "plan_id must be non-empty")

    # =========================================================================
    # E. /host/confirm input validation
    # =========================================================================

    def test_confirm_400_missing_plan_id(self):
        """POST /host/confirm without 'plan_id' → 400."""
        status, data = self._post_confirm({})
        self.assertEqual(status, 400)
        self._assert_host_contract(data, "confirm_400_missing")

    def test_confirm_400_plan_id_not_string(self):
        """POST /host/confirm with plan_id as number → 400."""
        status, data = self._post_confirm({"plan_id": 12345})
        self.assertEqual(status, 400)
        self._assert_host_contract(data, "confirm_400_not_string")

    def test_confirm_400_plan_id_empty_string(self):
        """POST /host/confirm with plan_id='' → 400."""
        status, data = self._post_confirm({"plan_id": ""})
        self.assertEqual(status, 400)
        self._assert_host_contract(data, "confirm_400_empty_string")

    # =========================================================================
    # F. /host/confirm: 404 plan not found
    # =========================================================================

    def test_confirm_404_nonexistent_plan_id(self):
        """Confirm with unknown plan_id → 404."""
        status, data = self._post_confirm({"plan_id": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual(status, 404)
        self.assertFalse(data.get("ok"))
        self._assert_host_contract(data, "confirm_404")
        error = data["error"]
        self.assertEqual(error.get("type"), "PlanNotFound")
        self.assertEqual(error.get("code"), "PLAN_NOT_FOUND")

    # =========================================================================
    # G. Full two-pass flow: /host/action → /host/confirm → 200
    # =========================================================================

    def test_full_two_pass_open_app(self):
        """Full flow: POST /host/action → 202, POST /host/confirm → 200."""
        activate_agent(HOST_AGENT_ID)

        # Pass 1
        status1, data1 = self._post_action({
            "action": "open_app",
            "payload": self._open_app_payload(),
        })
        self.assertEqual(status1, 202)
        plan_id = data1["data"]["plan_id"]

        # Pass 2
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        with patch("subprocess.Popen", return_value=mock_proc):
            status2, data2 = self._post_confirm({"plan_id": plan_id})

        self.assertEqual(status2, 200)
        self.assertTrue(data2.get("ok"))
        self.assertEqual(data2.get("result_type"), "host_action")
        self._assert_host_contract(data2, "two_pass_confirm")
        self.assertIsNone(data2["error"])

    def test_full_two_pass_execution_data(self):
        """Confirmed open_app must return pid and action in data."""
        activate_agent(HOST_AGENT_ID)

        status1, data1 = self._post_action({
            "action": "open_app",
            "payload": self._open_app_payload(),
        })
        plan_id = data1["data"]["plan_id"]

        mock_proc = MagicMock()
        mock_proc.pid = 4242
        with patch("subprocess.Popen", return_value=mock_proc):
            status2, data2 = self._post_confirm({"plan_id": plan_id})

        self.assertEqual(status2, 200)
        action_data = data2.get("data", {})
        self.assertEqual(action_data.get("action"), "open_app")
        self.assertEqual(action_data.get("pid"), 4242)

    # =========================================================================
    # H. /host/confirm: 409 CONTROL_PLANE_BLOCKED
    # =========================================================================

    def test_confirm_409_agent_quarantined_between_passes(self):
        """Agent quarantined between pass 1 and pass 2 → 409."""
        activate_agent(HOST_AGENT_ID)

        status1, data1 = self._post_action({
            "action": "open_app",
            "payload": self._open_app_payload(),
        })
        plan_id = data1["data"]["plan_id"]

        quarantine_agent(HOST_AGENT_ID)

        with patch("subprocess.Popen") as mock_popen:
            status2, data2 = self._post_confirm({"plan_id": plan_id})

        self.assertEqual(status2, 409)
        self.assertFalse(data2.get("ok"))
        self._assert_host_contract(data2, "confirm_409")
        self.assertEqual(data2["error"]["code"], "CONTROL_PLANE_BLOCKED")
        mock_popen.assert_not_called()

    # =========================================================================
    # I. /host/action RISK_LOW: agent not active → 409
    # =========================================================================

    def test_action_409_agent_not_active_risk_low(self):
        """RISK_LOW action with agent never activated → 409 control_plane_blocked."""
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm([])):
            status, data = self._post_action({
                "action": "list_directory",
                "payload": self._list_dir_payload(),
            })

        self.assertEqual(status, 409)
        self.assertFalse(data.get("ok"))
        self._assert_host_contract(data, "409_agent_not_active")
        self.assertEqual(data["error"]["code"], "CONTROL_PLANE_BLOCKED")

    # =========================================================================
    # J. No bypass: routing through orchestrator
    # =========================================================================

    def test_host_action_routes_through_orchestrator(self):
        """handle_request must be called by /host/action (no direct pipeline bypass)."""
        activate_agent(HOST_AGENT_ID)

        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm([])):
            with patch(
                "assistant_os.core.orchestrator.handle_request",
                wraps=__import__(
                    "assistant_os.core.orchestrator", fromlist=["handle_request"]
                ).handle_request,
            ) as mock_orch:
                self._post_action({
                    "action": "list_directory",
                    "payload": self._list_dir_payload(),
                })

        mock_orch.assert_called_once()

    def test_host_confirm_routes_through_orchestrator(self):
        """handle_request must be called by /host/confirm (no direct pipeline bypass)."""
        activate_agent(HOST_AGENT_ID)

        status1, data1 = self._post_action({
            "action": "open_app",
            "payload": self._open_app_payload(),
        })
        plan_id = data1["data"]["plan_id"]

        mock_proc = MagicMock()
        mock_proc.pid = 1
        with patch("subprocess.Popen", return_value=mock_proc), \
             patch(
                 "assistant_os.core.orchestrator.handle_request",
                 wraps=__import__(
                     "assistant_os.core.orchestrator", fromlist=["handle_request"]
                 ).handle_request,
             ) as mock_orch:
            self._post_confirm({"plan_id": plan_id})

        mock_orch.assert_called_once()

    # =========================================================================
    # K. CONTRACT: all responses have required keys
    # =========================================================================

    def test_contract_shape_200_has_required_keys(self):
        """200 response satisfies the HOST contract shape."""
        activate_agent(HOST_AGENT_ID)
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm([])):
            _, data = self._post_action({
                "action": "list_directory",
                "payload": self._list_dir_payload(),
            })
        self._assert_host_contract(data, "contract_200")

    def test_contract_shape_202_has_required_keys(self):
        """202 response satisfies the HOST contract shape."""
        _, data = self._post_action({
            "action": "open_app",
            "payload": self._open_app_payload(),
        })
        self._assert_host_contract(data, "contract_202")

    def test_contract_shape_400_has_required_keys(self):
        """400 response satisfies the HOST contract shape."""
        _, data = self._post_action({"payload": self._list_dir_payload()})
        self._assert_host_contract(data, "contract_400")

    def test_contract_shape_401_has_required_keys(self):
        """401 response satisfies the HOST contract shape."""
        _, data = self._post_action(
            {"action": "list_directory", "payload": self._list_dir_payload()},
            token="wrong",
        )
        self._assert_host_contract(data, "contract_401")

    def test_contract_shape_404_has_required_keys(self):
        """404 response satisfies the HOST contract shape."""
        _, data = self._post_confirm({"plan_id": "00000000-0000-0000-0000-000000000000"})
        self._assert_host_contract(data, "contract_404")

    def test_contract_shape_409_has_required_keys(self):
        """409 response satisfies the HOST contract shape."""
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm([])):
            _, data = self._post_action({
                "action": "list_directory",
                "payload": self._list_dir_payload(),
            })
        self._assert_host_contract(data, "contract_409")

    # =========================================================================
    # L. CONTRACT: error always null or {type, message, code}
    # =========================================================================

    def test_contract_error_null_on_success(self):
        """Successful response must have error=null."""
        activate_agent(HOST_AGENT_ID)
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm([])):
            _, data = self._post_action({
                "action": "list_directory",
                "payload": self._list_dir_payload(),
            })
        self.assertIsNone(data["error"])

    def test_contract_error_null_on_202(self):
        """202 plan_confirmation_required must have error=null."""
        _, data = self._post_action({
            "action": "open_app",
            "payload": self._open_app_payload(),
        })
        self.assertEqual(data.get("result_type"), "plan_confirmation_required")
        self.assertIsNone(data["error"])

    def test_contract_error_structured_on_400(self):
        """400 response must have error with type, message, code."""
        _, data = self._post_action({"action": "bad_action", "payload": {}})
        error = data["error"]
        self.assertIsNotNone(error)
        self.assertIn("type", error)
        self.assertIn("message", error)
        self.assertIn("code", error)
        self.assertTrue(error["type"])
        self.assertTrue(error["message"])
        self.assertTrue(error["code"])

    def test_contract_error_structured_on_404(self):
        """404 response must have error with type, message, code."""
        _, data = self._post_confirm({"plan_id": "00000000-0000-0000-0000-000000000000"})
        error = data["error"]
        self.assertIsNotNone(error)
        self.assertEqual(error.get("type"), "PlanNotFound")
        self.assertEqual(error.get("code"), "PLAN_NOT_FOUND")
        self.assertTrue(error.get("message"))

    # =========================================================================
    # M. CONTRACT: no legacy fields
    # =========================================================================

    def test_contract_no_legacy_fields_in_200(self):
        """200 response must not contain legacy fields."""
        activate_agent(HOST_AGENT_ID)
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm([])):
            _, data = self._post_action({
                "action": "list_directory",
                "payload": self._list_dir_payload(),
            })
        for key in _FORBIDDEN_RESPONSE_KEYS:
            self.assertNotIn(key, data, f"Legacy field '{key}' found in response")

    def test_contract_no_legacy_fields_in_202(self):
        """202 response must not contain legacy fields."""
        _, data = self._post_action({
            "action": "open_app",
            "payload": self._open_app_payload(),
        })
        for key in _FORBIDDEN_RESPONSE_KEYS:
            self.assertNotIn(key, data, f"Legacy field '{key}' found in response")

    def test_contract_no_legacy_fields_in_400(self):
        """400 response must not contain legacy fields."""
        _, data = self._post_action({"payload": {}})
        for key in _FORBIDDEN_RESPONSE_KEYS:
            self.assertNotIn(key, data, f"Legacy field '{key}' found in response")

    # =========================================================================
    # N. Idempotence: second confirm → 404
    # =========================================================================

    def test_single_use_second_confirm_returns_404(self):
        """plan_id is single-use: second /host/confirm → 404."""
        activate_agent(HOST_AGENT_ID)

        status1, data1 = self._post_action({
            "action": "open_app",
            "payload": self._open_app_payload(),
        })
        plan_id = data1["data"]["plan_id"]

        mock_proc = MagicMock()
        mock_proc.pid = 1
        with patch("subprocess.Popen", return_value=mock_proc):
            s1, _ = self._post_confirm({"plan_id": plan_id})
        self.assertEqual(s1, 200)

        s2, d2 = self._post_confirm({"plan_id": plan_id})
        self.assertEqual(s2, 404)
        self.assertFalse(d2["ok"])
        self._assert_host_contract(d2, "second_confirm_404")
        self.assertEqual(d2["error"]["code"], "PLAN_NOT_FOUND")

    # =========================================================================
    # O. Error codes
    # =========================================================================

    def test_error_code_unauthorized(self):
        """Auth error has code=UNAUTHORIZED."""
        _, data = self._post_action(
            {"action": "list_directory", "payload": self._list_dir_payload()},
            token="invalid",
        )
        self.assertEqual(data["error"]["code"], "UNAUTHORIZED")

    def test_error_code_bad_request_missing_action(self):
        """Missing action has code=BAD_REQUEST."""
        _, data = self._post_action({"payload": self._list_dir_payload()})
        self.assertEqual(data["error"]["code"], "BAD_REQUEST")

    def test_error_code_bad_request_missing_payload(self):
        """Missing payload has code=BAD_REQUEST."""
        _, data = self._post_action({"action": "list_directory"})
        self.assertEqual(data["error"]["code"], "BAD_REQUEST")

    def test_error_code_plan_not_found(self):
        """Nonexistent plan_id has code=PLAN_NOT_FOUND."""
        _, data = self._post_confirm({"plan_id": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual(data["error"]["code"], "PLAN_NOT_FOUND")

    def test_error_code_control_plane_blocked(self):
        """Inactive agent → code=CONTROL_PLANE_BLOCKED."""
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm([])):
            _, data = self._post_action({
                "action": "list_directory",
                "payload": self._list_dir_payload(),
            })
        self.assertEqual(data["error"]["code"], "CONTROL_PLANE_BLOCKED")


if __name__ == "__main__":
    unittest.main()
