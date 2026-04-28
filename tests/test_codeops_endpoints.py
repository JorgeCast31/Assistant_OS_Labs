"""
Tests for CodeOps webhook endpoints.

Tests:
- POST /codeops/plan
- POST /codeops/pr

Uses http.client (stdlib) for requests like other webhook tests.
"""
import http.client
import json
import time
import unittest
from unittest.mock import patch

from assistant_os.webhook_server import start_server_thread, WebhookHTTPServer
from assistant_os.config import WEBHOOK_TOKEN, CODEOPS_MAX_BYTES


class TestCodeOpsEndpoints(unittest.TestCase):
    """Tests for /codeops/* endpoints."""
    
    server: WebhookHTTPServer
    port: int
    
    @classmethod
    def setUpClass(cls) -> None:
        """Start server in background thread."""
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)
    
    @classmethod
    def tearDownClass(cls) -> None:
        """Shutdown server."""
        cls.server.shutdown()
        cls.server.server_close()
    
    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict | None = None,
    ) -> tuple[int, dict]:
        """Make HTTP request and return (status_code, json_response)."""
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
    
    def _post_codeops(
        self,
        endpoint: str,
        data: dict,
        token: str | None = WEBHOOK_TOKEN,
    ) -> tuple[int, dict]:
        """Helper to POST to /codeops/* with proper headers."""
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-Assistant-Token"] = token
        
        body = json.dumps(data).encode("utf-8")
        return self._request("POST", endpoint, body, headers)
    
    # -------------------------------------------------------------------------
    # Authentication Tests
    # -------------------------------------------------------------------------
    
    def test_codeops_plan_401_missing_token(self):
        """POST /codeops/plan without token should return 401."""
        headers = {"Content-Type": "application/json"}
        body = json.dumps({"repo": "owner/repo", "goal": "Test"}).encode("utf-8")
        
        status, data = self._request("POST", "/codeops/plan", body, headers)
        
        self.assertEqual(status, 401)
    
    def test_codeops_pr_401_missing_token(self):
        """POST /codeops/pr without token should return 401."""
        headers = {"Content-Type": "application/json"}
        body = json.dumps({"repo": "owner/repo", "goal": "Test"}).encode("utf-8")
        
        status, data = self._request("POST", "/codeops/pr", body, headers)
        
        self.assertEqual(status, 401)
    
    def test_codeops_plan_401_invalid_token(self):
        """POST /codeops/plan with invalid token should return 401."""
        status, data = self._post_codeops(
            "/codeops/plan",
            {"repo": "owner/repo", "goal": "Test"},
            token="invalid_token"
        )
        
        self.assertEqual(status, 401)
    
    # -------------------------------------------------------------------------
    # /codeops/plan Tests
    # -------------------------------------------------------------------------
    
    def test_codeops_plan_valid_request(self):
        """POST /codeops/plan with valid TaskSpec should return 200."""
        status, data = self._post_codeops(
            "/codeops/plan",
            {"repo": "owner/repo", "goal": "Add unit tests for auth module"}
        )
        
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("steps", data)
        self.assertIn("files_to_touch", data)
        self.assertIn("warnings", data)
    
    def test_codeops_plan_returns_steps(self):
        """POST /codeops/plan should return execution steps."""
        status, data = self._post_codeops(
            "/codeops/plan",
            {"repo": "owner/repo", "goal": "Fix bug in utils"}
        )
        
        self.assertEqual(status, 200)
        self.assertTrue(len(data["steps"]) > 0)
        
        # Each step should have required fields
        for step in data["steps"]:
            self.assertIn("order", step)
            self.assertIn("action", step)
            self.assertIn("target", step)
            self.assertIn("description", step)
    
    def test_codeops_plan_with_full_spec(self):
        """POST /codeops/plan with all optional fields should work."""
        status, data = self._post_codeops(
            "/codeops/plan",
            {
                "repo": "owner/repo",
                "goal": "Refactor auth module",
                "base_branch": "develop",
                "module_scope": "src/auth",
                "acceptance": "All tests pass, coverage > 80%"
            }
        )
        
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
    
    def test_codeops_plan_missing_repo(self):
        """POST /codeops/plan without repo should return 400."""
        status, data = self._post_codeops(
            "/codeops/plan",
            {"goal": "Add tests"}
        )
        
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])
        self.assertIsNotNone(data["error"])
        self.assertIn("repo", data["error"].lower())
    
    def test_codeops_plan_missing_goal(self):
        """POST /codeops/plan without goal should return 400."""
        status, data = self._post_codeops(
            "/codeops/plan",
            {"repo": "owner/repo"}
        )
        
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])
        self.assertIn("goal", data["error"].lower())
    
    def test_codeops_plan_invalid_repo_format(self):
        """POST /codeops/plan with invalid repo format should return 400."""
        status, data = self._post_codeops(
            "/codeops/plan",
            {"repo": "invalid-repo-format", "goal": "Test"}
        )
        
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])
        self.assertIn("owner/repo", data["error"].lower())
    
    def test_codeops_plan_invalid_json(self):
        """POST /codeops/plan with invalid JSON should return 400."""
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = b"this is not valid json"
        
        status, data = self._request("POST", "/codeops/plan", body, headers)
        
        self.assertEqual(status, 400)
    
    def test_codeops_plan_warns_about_missing_github(self):
        """POST /codeops/plan should warn if GitHub token not configured."""
        # Note: In test environment, GITHUB_TOKEN might not be set
        status, data = self._post_codeops(
            "/codeops/plan",
            {"repo": "owner/repo", "goal": "Test"}
        )
        
        self.assertEqual(status, 200)
        # Should have at least one warning about GitHub
        has_github_warning = any("github" in w.lower() for w in data.get("warnings", []))
        self.assertTrue(has_github_warning)
    
    # -------------------------------------------------------------------------
    # /codeops/pr Tests
    # -------------------------------------------------------------------------
    
    def test_codeops_pr_valid_request(self):
        """POST /codeops/pr with valid TaskSpec returns 200 + stub envelope.

        ALFA invariant — when CODEOPS_LIVE_MODE is disabled (the default in
        tests), the endpoint MUST NOT claim a PR was created. The wire
        response must carry ok=False, pr_number=None, pr_url=None, and
        execution_status="stub".
        """
        status, data = self._post_codeops(
            "/codeops/pr",
            {"repo": "owner/repo", "goal": "Add unit tests"}
        )

        self.assertEqual(status, 200)
        # Contract keys
        self.assertIn("ok", data)
        self.assertIn("pr_number", data)
        self.assertIn("pr_url", data)
        self.assertIn("branch", data)
        self.assertIn("error", data)
        # Truthfulness
        self.assertFalse(data["ok"], "fake success leak: ok should be False in stub mode")
        self.assertIsNone(data["pr_number"])
        self.assertIsNone(data["pr_url"])
        self.assertEqual(data.get("execution_status"), "stub")
        self.assertIsNotNone(data["error"])

    def test_codeops_pr_returns_branch_name(self):
        """POST /codeops/pr returns the planned branch name (stub envelope)."""
        status, data = self._post_codeops(
            "/codeops/pr",
            {"repo": "owner/repo", "goal": "Fix authentication bug"}
        )

        self.assertEqual(status, 200)
        # Even in stub mode, the planned branch is exposed for transparency.
        self.assertFalse(data["ok"])
        self.assertEqual(data.get("execution_status"), "stub")
        self.assertIsNotNone(data["branch"])
        self.assertTrue(data["branch"].startswith("codeops/"))
    
    def test_codeops_pr_missing_repo(self):
        """POST /codeops/pr without repo should return 400."""
        status, data = self._post_codeops(
            "/codeops/pr",
            {"goal": "Add tests"}
        )
        
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])
    
    def test_codeops_pr_missing_goal(self):
        """POST /codeops/pr without goal should return 400."""
        status, data = self._post_codeops(
            "/codeops/pr",
            {"repo": "owner/repo"}
        )
        
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])
    
    # -------------------------------------------------------------------------
    # Guardrails Tests
    # -------------------------------------------------------------------------
    
    @patch("assistant_os.webhook_server.is_repo_allowed")
    def test_codeops_plan_repo_not_allowed(self, mock_is_allowed):
        """POST /codeops/plan with disallowed repo should return 403."""
        mock_is_allowed.return_value = False
        
        status, data = self._post_codeops(
            "/codeops/plan",
            {"repo": "blocked/repo", "goal": "Test"}
        )
        
        self.assertEqual(status, 403)
        self.assertFalse(data["ok"])
        self.assertIn("allowed", data["error"].lower())
    
    @patch("assistant_os.webhook_server.is_repo_allowed")
    def test_codeops_pr_repo_not_allowed(self, mock_is_allowed):
        """POST /codeops/pr with disallowed repo should return 403."""
        mock_is_allowed.return_value = False
        
        status, data = self._post_codeops(
            "/codeops/pr",
            {"repo": "blocked/repo", "goal": "Test"}
        )
        
        self.assertEqual(status, 403)
        self.assertFalse(data["ok"])
    
    def test_codeops_plan_module_scope_relative(self):
        """POST /codeops/plan with relative module_scope should work."""
        status, data = self._post_codeops(
            "/codeops/plan",
            {
                "repo": "owner/repo",
                "goal": "Refactor",
                "module_scope": "src/auth"
            }
        )
        
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
    
    @patch("assistant_os.webhook_server.is_path_in_workspace")
    def test_codeops_plan_module_scope_outside_workspace(self, mock_is_in_workspace):
        """POST /codeops/plan with absolute path outside workspace should return 400."""
        mock_is_in_workspace.return_value = False
        
        # Use Windows-style absolute path to ensure is_absolute() returns True
        import sys
        if sys.platform == "win32":
            bad_path = "C:\\Windows\\System32\\config"
        else:
            bad_path = "/etc/passwd"
        
        status, data = self._post_codeops(
            "/codeops/plan",
            {
                "repo": "owner/repo",
                "goal": "Test",
                "module_scope": bad_path
            }
        )
        
        self.assertEqual(status, 400)
        self.assertFalse(data["ok"])
        self.assertIn("workspace", data["error"].lower())


class TestCodeOpsResponseStructure(unittest.TestCase):
    """Tests for consistent response structure."""
    
    server: WebhookHTTPServer
    port: int
    
    @classmethod
    def setUpClass(cls) -> None:
        """Start server in background thread."""
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)
    
    @classmethod
    def tearDownClass(cls) -> None:
        """Shutdown server."""
        cls.server.shutdown()
        cls.server.server_close()
    
    def _post(self, path: str, data: dict) -> tuple[int, dict]:
        """POST with auth and return response."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {
            "Content-Type": "application/json",
            "X-Assistant-Token": WEBHOOK_TOKEN,
        }
        body = json.dumps(data).encode("utf-8")
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        status = response.status
        data = json.loads(response.read().decode("utf-8"))
        conn.close()
        return status, data
    
    def test_plan_response_has_all_fields(self):
        """PlanResponse should have ok, steps, files_to_touch, warnings, error."""
        _, data = self._post("/codeops/plan", {
            "repo": "owner/repo",
            "goal": "Test"
        })
        
        self.assertIn("ok", data)
        self.assertIn("steps", data)
        self.assertIn("files_to_touch", data)
        self.assertIn("warnings", data)
        self.assertIn("error", data)
    
    def test_pr_response_has_all_fields(self):
        """PRResponse should have ok, pr_number, pr_url, branch, error."""
        _, data = self._post("/codeops/pr", {
            "repo": "owner/repo",
            "goal": "Test"
        })

        self.assertIn("ok", data)
        self.assertIn("pr_number", data)
        self.assertIn("pr_url", data)
        self.assertIn("branch", data)
        self.assertIn("error", data)

    def test_plan_error_response_structure(self):
        """Error response should have same structure with ok=False."""
        _, data = self._post("/codeops/plan", {
            "repo": "invalid",  # Invalid format
            "goal": "Test"
        })

        self.assertFalse(data["ok"])
        self.assertEqual(data["steps"], [])
        self.assertEqual(data["files_to_touch"], [])
        self.assertIsNotNone(data["error"])


if __name__ == "__main__":
    unittest.main()
