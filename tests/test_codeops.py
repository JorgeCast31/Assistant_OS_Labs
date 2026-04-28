"""
Tests for CodeOps module.

Tests contracts validation, GitHub client initialization,
and handler functionality WITHOUT making external calls.
"""
import os
import unittest
from unittest.mock import patch, MagicMock

from assistant_os.codeops import (
    # Contracts
    TaskSpec,
    PlanResponse,
    PRResponse,
    validate_task_spec,
    # GitHub Client
    GitHubClient,
    GitHubAuthError,
    # Handler
    CodeOpsHandler,
)


# =============================================================================
# Contract Validation Tests
# =============================================================================

class TestTaskSpecValidation(unittest.TestCase):
    """Tests for TaskSpec validation."""
    
    def test_valid_minimal_spec(self):
        """Minimal valid spec with repo and goal."""
        spec = {"repo": "owner/repo", "goal": "Add tests"}
        is_valid, error = validate_task_spec(spec)
        self.assertTrue(is_valid)
        self.assertEqual(error, "")
    
    def test_valid_full_spec(self):
        """Full spec with all optional fields."""
        spec: TaskSpec = {
            "repo": "owner/repo",
            "goal": "Refactor auth module",
            "base_branch": "develop",
            "module_scope": "src/auth",
            "acceptance": "All tests pass"
        }
        is_valid, error = validate_task_spec(spec)
        self.assertTrue(is_valid)
        self.assertEqual(error, "")
    
    def test_missing_repo(self):
        """Missing repo field should fail."""
        spec = {"goal": "Add tests"}
        is_valid, error = validate_task_spec(spec)
        self.assertFalse(is_valid)
        self.assertIn("repo", error.lower())
    
    def test_missing_goal(self):
        """Missing goal field should fail."""
        spec = {"repo": "owner/repo"}
        is_valid, error = validate_task_spec(spec)
        self.assertFalse(is_valid)
        self.assertIn("goal", error.lower())
    
    def test_invalid_repo_format_no_slash(self):
        """Repo without slash should fail."""
        spec = {"repo": "just-repo-name", "goal": "Fix bug"}
        is_valid, error = validate_task_spec(spec)
        self.assertFalse(is_valid)
        self.assertIn("owner/repo", error.lower())
    
    def test_invalid_repo_format_empty_owner(self):
        """Repo with empty owner should fail."""
        spec = {"repo": "/repo", "goal": "Fix bug"}
        is_valid, error = validate_task_spec(spec)
        self.assertFalse(is_valid)
        self.assertIn("owner/repo", error.lower())
    
    def test_invalid_repo_format_empty_repo(self):
        """Repo with empty repo name should fail."""
        spec = {"repo": "owner/", "goal": "Fix bug"}
        is_valid, error = validate_task_spec(spec)
        self.assertFalse(is_valid)
        self.assertIn("owner/repo", error.lower())
    
    def test_empty_goal(self):
        """Empty goal string should fail."""
        spec = {"repo": "owner/repo", "goal": ""}
        is_valid, error = validate_task_spec(spec)
        self.assertFalse(is_valid)
        self.assertIn("goal", error.lower())
    
    def test_whitespace_only_goal(self):
        """Whitespace-only goal should fail."""
        spec = {"repo": "owner/repo", "goal": "   "}
        is_valid, error = validate_task_spec(spec)
        self.assertFalse(is_valid)
        self.assertIn("goal", error.lower())
    
    def test_not_a_dict(self):
        """Non-dict input should fail."""
        is_valid, error = validate_task_spec("not a dict")
        self.assertFalse(is_valid)
        self.assertIn("dictionary", error.lower())
    
    def test_none_input(self):
        """None input should fail."""
        is_valid, error = validate_task_spec(None)
        self.assertFalse(is_valid)


# =============================================================================
# GitHub Client Tests
# =============================================================================

class TestGitHubClientAuth(unittest.TestCase):
    """Tests for GitHub client authentication."""
    
    def test_missing_token_raises_error(self):
        """Client without token should raise GitHubAuthError."""
        # Clear any existing GITHUB_TOKEN
        with patch.dict(os.environ, {}, clear=True):
            # Also remove GITHUB_TOKEN specifically
            env_without_token = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
            with patch.dict(os.environ, env_without_token, clear=True):
                with self.assertRaises(GitHubAuthError) as ctx:
                    GitHubClient()
                
                self.assertIn("GITHUB_TOKEN", str(ctx.exception))
    
    def test_explicit_token_accepted(self):
        """Client with explicit token should initialize."""
        client = GitHubClient(token="test_token_12345")
        self.assertTrue(client.is_authenticated)
    
    def test_env_token_accepted(self):
        """Client should read token from environment."""
        with patch.dict(os.environ, {"GITHUB_TOKEN": "env_token_67890"}):
            client = GitHubClient()
            self.assertTrue(client.is_authenticated)
    
    def test_explicit_token_overrides_env(self):
        """Explicit token should override environment."""
        with patch.dict(os.environ, {"GITHUB_TOKEN": "env_token"}):
            client = GitHubClient(token="explicit_token")
            # We can't directly check the token, but it should work
            self.assertTrue(client.is_authenticated)


class TestGitHubClientValidation(unittest.TestCase):
    """Tests for GitHub client parameter validation."""
    
    def setUp(self):
        """Create client with test token."""
        self.client = GitHubClient(token="test_token")
    
    def test_get_repo_invalid_format(self):
        """get_repo with invalid format should raise ValueError."""
        with self.assertRaises(ValueError):
            self.client.get_repo("not-valid-format")
    
    def test_get_repo_empty_owner(self):
        """get_repo with empty owner should raise ValueError."""
        with self.assertRaises(ValueError):
            self.client.get_repo("/repo")
    
    def test_create_branch_invalid_chars(self):
        """create_branch with invalid characters should raise ValueError."""
        invalid_names = ["branch name", "branch~name", "branch^name", "branch:name"]
        for name in invalid_names:
            with self.assertRaises(ValueError):
                self.client.create_branch("owner/repo", "main", name)
    
    def test_create_branch_empty_base(self):
        """create_branch with empty base should raise ValueError."""
        with self.assertRaises(ValueError):
            self.client.create_branch("owner/repo", "", "new-branch")
    
    def test_create_pr_same_branches(self):
        """create_pr with same head and base should raise ValueError."""
        with self.assertRaises(ValueError):
            self.client.create_pr("owner/repo", "Title", "Body", "main", "main")
    
    def test_create_pr_empty_title(self):
        """create_pr with empty title should raise ValueError."""
        with self.assertRaises(ValueError):
            self.client.create_pr("owner/repo", "", "Body", "feature", "main")
    
    def test_list_prs_invalid_state(self):
        """list_prs with invalid state should raise ValueError."""
        with self.assertRaises(ValueError):
            self.client.list_prs("owner/repo", state="invalid")
    
    def test_list_prs_valid_states(self):
        """list_prs should accept valid states."""
        for state in ["open", "closed", "all"]:
            # Should not raise
            result = self.client.list_prs("owner/repo", state=state)
            self.assertIsInstance(result, list)


# =============================================================================
# CodeOps Handler Tests
# =============================================================================

class TestCodeOpsHandlerInit(unittest.TestCase):
    """Tests for CodeOpsHandler initialization."""
    
    def test_init_without_token(self):
        """Handler should initialize even without GitHub token."""
        with patch.dict(os.environ, {}, clear=True):
            env_without_token = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
            with patch.dict(os.environ, env_without_token, clear=True):
                handler = CodeOpsHandler()
                self.assertFalse(handler.has_github_access)
    
    def test_init_with_token(self):
        """Handler with token should have GitHub access."""
        handler = CodeOpsHandler(github_token="test_token")
        self.assertTrue(handler.has_github_access)


class TestCodeOpsHandlerPlanTask(unittest.TestCase):
    """Tests for CodeOpsHandler.plan_task()."""
    
    def setUp(self):
        """Create handler without GitHub token (planning doesn't need it)."""
        with patch.dict(os.environ, {}, clear=True):
            env_without_token = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
            with patch.dict(os.environ, env_without_token, clear=True):
                self.handler = CodeOpsHandler()
    
    def test_plan_returns_valid_structure(self):
        """plan_task should return PlanResponse with all fields."""
        spec = {"repo": "owner/repo", "goal": "Add unit tests"}
        result = self.handler.plan_task(spec)
        
        # Check all required fields
        self.assertIn("ok", result)
        self.assertIn("steps", result)
        self.assertIn("files_to_touch", result)
        self.assertIn("warnings", result)
        self.assertIn("error", result)
    
    def test_plan_valid_spec_returns_ok(self):
        """plan_task with valid spec should return ok=True."""
        spec = {"repo": "owner/repo", "goal": "Refactor module"}
        result = self.handler.plan_task(spec)
        
        self.assertTrue(result["ok"])
        self.assertIsNone(result["error"])
    
    def test_plan_invalid_spec_returns_error(self):
        """plan_task with invalid spec should return ok=False."""
        spec = {"goal": "Missing repo"}  # No repo
        result = self.handler.plan_task(spec)
        
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["steps"], [])
    
    def test_plan_has_steps(self):
        """plan_task should generate execution steps."""
        spec = {"repo": "owner/repo", "goal": "Add feature"}
        result = self.handler.plan_task(spec)
        
        self.assertTrue(len(result["steps"]) > 0)
    
    def test_plan_steps_have_required_fields(self):
        """Each step should have order, action, target, description."""
        spec = {"repo": "owner/repo", "goal": "Fix bug"}
        result = self.handler.plan_task(spec)
        
        for step in result["steps"]:
            self.assertIn("order", step)
            self.assertIn("action", step)
            self.assertIn("target", step)
            self.assertIn("description", step)
    
    def test_plan_test_goal_includes_test_step(self):
        """Goal mentioning 'test' should include test-related steps."""
        spec = {"repo": "owner/repo", "goal": "Add unit tests for auth"}
        result = self.handler.plan_task(spec)
        
        # Should have files_to_touch with test files
        has_test_reference = any("test" in f.lower() for f in result["files_to_touch"])
        self.assertTrue(has_test_reference)
    
    def test_plan_warns_about_missing_github(self):
        """Plan without GitHub access should warn about PR creation."""
        spec = {"repo": "owner/repo", "goal": "Some task"}
        result = self.handler.plan_task(spec)
        
        has_github_warning = any("github" in w.lower() for w in result["warnings"])
        self.assertTrue(has_github_warning)
    
    def test_plan_warns_about_missing_acceptance(self):
        """Plan without acceptance criteria should include warning."""
        spec = {"repo": "owner/repo", "goal": "Some task"}
        result = self.handler.plan_task(spec)
        
        has_acceptance_warning = any("acceptance" in w.lower() for w in result["warnings"])
        self.assertTrue(has_acceptance_warning)
    
    def test_plan_with_acceptance_no_warning(self):
        """Plan with acceptance criteria should not warn about it."""
        spec = {
            "repo": "owner/repo",
            "goal": "Some task",
            "acceptance": "All tests pass"
        }
        result = self.handler.plan_task(spec)
        
        has_acceptance_warning = any("acceptance" in w.lower() for w in result["warnings"])
        self.assertFalse(has_acceptance_warning)
    
    def test_plan_with_module_scope(self):
        """Plan with module_scope should focus on that module."""
        spec = {
            "repo": "owner/repo",
            "goal": "Refactor",
            "module_scope": "src/auth"
        }
        result = self.handler.plan_task(spec)
        
        # Check that module scope appears in steps or files
        has_scope_reference = any(
            "src/auth" in step["target"] or "src/auth" in step["description"]
            for step in result["steps"]
        )
        self.assertTrue(has_scope_reference)


class TestCodeOpsHandlerCreatePR(unittest.TestCase):
    """Tests for CodeOpsHandler.create_pr()."""
    
    def test_create_pr_without_github_fails(self):
        """create_pr without GitHub access should return error."""
        with patch.dict(os.environ, {}, clear=True):
            env_without_token = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
            with patch.dict(os.environ, env_without_token, clear=True):
                handler = CodeOpsHandler()
                
                spec = {"repo": "owner/repo", "goal": "Add tests"}
                result = handler.create_pr(spec)
                
                self.assertFalse(result["ok"])
                self.assertIn("GITHUB_TOKEN", result["error"])
    
    def test_create_pr_invalid_spec_fails(self):
        """create_pr with invalid spec should return error."""
        handler = CodeOpsHandler(github_token="test_token")
        
        spec = {"goal": "Missing repo"}
        result = handler.create_pr(spec)
        
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])
    
    def test_create_pr_valid_spec_returns_structure(self):
        """create_pr with valid spec returns the full PRResponse structure.

        ALFA invariant: the handler is currently a stub — real PR execution
        is not wired. The response must therefore be honest (`ok=False`) but
        still expose every key in the contract so callers/UI can render it.
        """
        handler = CodeOpsHandler(github_token="test_token")

        spec = {"repo": "owner/repo", "goal": "Add tests"}
        result = handler.create_pr(spec)

        # Structure
        self.assertIn("ok", result)
        self.assertIn("pr_number", result)
        self.assertIn("pr_url", result)
        self.assertIn("branch", result)
        self.assertIn("error", result)
        # Truthfulness — no fake success.
        self.assertFalse(result["ok"])
        self.assertIsNone(result["pr_number"])
        self.assertIsNone(result["pr_url"])
        self.assertIsNotNone(result["error"])

    def test_create_pr_generates_branch_name(self):
        """create_pr returns the planned branch name even though no PR runs.

        The stub layer must surface the deterministic branch slug so the UI
        can show 'planned branch: codeops/...' without lying about execution.
        """
        handler = CodeOpsHandler(github_token="test_token")

        spec = {"repo": "owner/repo", "goal": "Add unit tests for auth"}
        result = handler.create_pr(spec)

        # ALFA invariant — stub must NOT claim ok=True.
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["branch"])
        self.assertTrue(result["branch"].startswith("codeops/"))


class TestBranchNameGeneration(unittest.TestCase):
    """Tests for branch name generation from goals."""
    
    def setUp(self):
        """Create handler with token."""
        self.handler = CodeOpsHandler(github_token="test_token")
    
    def test_branch_name_lowercase(self):
        """Branch name should be lowercase."""
        spec = {"repo": "owner/repo", "goal": "ADD FEATURE"}
        result = self.handler.create_pr(spec)
        
        self.assertEqual(result["branch"], result["branch"].lower())
    
    def test_branch_name_has_prefix(self):
        """Branch name should have codeops/ prefix."""
        spec = {"repo": "owner/repo", "goal": "Fix bug"}
        result = self.handler.create_pr(spec)

        self.assertTrue(result["branch"].startswith("codeops/"))

    def test_branch_name_removes_stop_words(self):
        """Branch name should remove common stop words."""
        spec = {"repo": "owner/repo", "goal": "Add the feature to the module"}
        result = self.handler.create_pr(spec)

        # 'the' and 'to' should be removed
        self.assertNotIn("-the-", result["branch"])
        self.assertNotIn("-to-", result["branch"])


if __name__ == "__main__":
    unittest.main()
