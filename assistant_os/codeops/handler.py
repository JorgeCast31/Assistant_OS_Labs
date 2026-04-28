"""
CodeOps Handler - Main orchestrator for code operations.

This handler coordinates between the GitHub client and local repo manager
to execute code tasks: planning, executing changes, and creating PRs.
"""
import os
from typing import Optional

from .contracts import (
    TaskSpec,
    PlanResponse,
    PlanStep,
    PRResponse,
    validate_task_spec,
)
from .github_client import GitHubClient, GitHubAuthError


class CodeOpsError(Exception):
    """Base exception for CodeOps handler errors."""
    pass


class TaskValidationError(CodeOpsError):
    """Raised when task specification is invalid."""
    pass


class CodeOpsHandler:
    """
    Main handler for code operations.

    Orchestrates the full workflow:
    1. Parse and validate task specification
    2. Create execution plan
    3. Clone repository and create branch
    4. Apply changes
    5. Commit, push, and create PR

    Usage:
        handler = CodeOpsHandler()

        # Plan a task
        plan = handler.plan_task({
            "repo": "owner/repo",
            "goal": "Add unit tests for auth module"
        })

        # Execute and create PR
        if plan["ok"]:
            result = handler.create_pr(task_spec)
    """

    def __init__(self, github_token: Optional[str] = None):
        """
        Initialize CodeOps handler.

        Args:
            github_token: GitHub token for API access.
                         If not provided, uses GITHUB_TOKEN env var.

        Note:
            Some operations (planning) can work without GitHub token.
            PR creation requires valid authentication.
        """
        self._github_token = github_token or os.environ.get("GITHUB_TOKEN")
        self._github_client: Optional[GitHubClient] = None

        # Lazy initialization of GitHub client
        if self._github_token:
            try:
                self._github_client = GitHubClient(self._github_token)
            except GitHubAuthError:
                pass  # Will fail later if GitHub operations needed

    @property
    def has_github_access(self) -> bool:
        """Check if GitHub API access is available."""
        return self._github_client is not None

    def plan_task(self, task_spec: TaskSpec | dict) -> PlanResponse:
        """
        Create an execution plan for a code task.

        This method analyzes the task specification and creates a detailed
        plan of steps to execute, including files to touch and potential risks.

        Args:
            task_spec: Task specification with repo, goal, and optional fields

        Returns:
            PlanResponse with steps, files_to_touch, and warnings

        Note:
            This method does NOT require GitHub access - it only analyzes
            the task and creates a local plan.
        """
        # Validate task spec
        is_valid, error = validate_task_spec(task_spec)
        if not is_valid:
            return PlanResponse(
                ok=False,
                steps=[],
                files_to_touch=[],
                warnings=[],
                error=error
            )

        # Extract fields with defaults
        repo = task_spec["repo"]
        goal = task_spec["goal"]
        base_branch = task_spec.get("base_branch", "main")
        module_scope = task_spec.get("module_scope")
        acceptance = task_spec.get("acceptance")

        # Build execution plan
        steps: list[PlanStep] = []
        files_to_touch: list[str] = []
        warnings: list[str] = []

        # Step 1: Analyze repository structure
        steps.append(PlanStep(
            order=1,
            action="analyze",
            target=repo,
            description=f"Clone and analyze repository structure of {repo}"
        ))

        # Step 2: Identify affected files based on goal
        if module_scope:
            target_path = module_scope
            steps.append(PlanStep(
                order=2,
                action="analyze",
                target=module_scope,
                description=f"Identify files to modify in {module_scope}"
            ))
            files_to_touch.append(f"{module_scope}/*")
        else:
            target_path = repo
            steps.append(PlanStep(
                order=2,
                action="analyze",
                target=repo,
                description="Identify files to modify based on goal analysis"
            ))

        # Step 3: Create branch
        branch_name = self._generate_branch_name(goal)
        steps.append(PlanStep(
            order=3,
            action="create",
            target=f"branch:{branch_name}",
            description=f"Create feature branch '{branch_name}' from '{base_branch}'"
        ))

        # Step 4: Modify/create files based on goal keywords
        if "test" in goal.lower():
            steps.append(PlanStep(
                order=4,
                action="create",
                target="tests/",
                description="Create or update test files"
            ))
            files_to_touch.append("tests/test_*.py")

        if "refactor" in goal.lower():
            warnings.append("Refactoring may affect multiple files - review carefully")
            steps.append(PlanStep(
                order=4,
                action="modify",
                target=target_path,
                description="Refactor existing code"
            ))

        if "fix" in goal.lower() or "bug" in goal.lower():
            steps.append(PlanStep(
                order=4,
                action="modify",
                target=target_path,
                description="Apply bug fix"
            ))
            warnings.append("Bug fixes should include regression tests")

        if "add" in goal.lower() or "create" in goal.lower() or "implement" in goal.lower():
            steps.append(PlanStep(
                order=4,
                action="create",
                target=target_path,
                description="Create new code/files"
            ))

        # If no specific action identified, add generic modify step
        if len(steps) == 3:  # Only analyze + analyze + branch
            steps.append(PlanStep(
                order=4,
                action="modify",
                target=target_path,
                description=f"Apply changes for: {goal[:50]}..."
            ))

        # Step 5: Run tests if applicable
        steps.append(PlanStep(
            order=len(steps) + 1,
            action="test",
            target="tests/",
            description="Run test suite to verify changes"
        ))

        # Step 6: Commit and push
        steps.append(PlanStep(
            order=len(steps) + 1,
            action="modify",
            target=f"branch:{branch_name}",
            description="Commit changes and push to remote"
        ))

        # Step 7: Create PR
        steps.append(PlanStep(
            order=len(steps) + 1,
            action="create",
            target="pull_request",
            description=f"Create pull request to merge '{branch_name}' into '{base_branch}'"
        ))

        # Add warnings based on analysis
        if not self.has_github_access:
            warnings.append("GitHub token not configured - PR creation will fail")

        if not acceptance:
            warnings.append("No acceptance criteria specified - consider adding for clarity")

        return PlanResponse(
            ok=True,
            steps=steps,
            files_to_touch=files_to_touch,
            warnings=warnings,
            error=None
        )

    def create_pr(self, task_spec: TaskSpec | dict) -> PRResponse:
        """
        Execute a task and create a pull request.

        ALFA invariant — NO fake success.
        Real PR execution is not yet implemented at this layer. This method
        validates the input, performs guardrail checks, and then returns a
        truthful stub response (`ok=False`) with the planned branch name as
        informational data only. No remote operation is performed.

        The HTTP layer (webhook_server._handle_codeops_pr) is responsible for
        stamping `execution_status` on the wire response so the UI never
        renders fake success.

        Args:
            task_spec: Task specification with repo, goal, and optional fields

        Returns:
            PRResponse with `ok=False`, `pr_number=None`, `pr_url=None`,
            `branch=<planned_branch>`, and an explanatory `error` message.
        """
        # Validate task spec
        is_valid, error = validate_task_spec(task_spec)
        if not is_valid:
            return PRResponse(
                ok=False,
                pr_number=None,
                pr_url=None,
                branch=None,
                error=error
            )

        # Check GitHub access
        if not self.has_github_access:
            return PRResponse(
                ok=False,
                pr_number=None,
                pr_url=None,
                branch=None,
                error="GitHub token not configured. Set GITHUB_TOKEN environment variable."
            )

        # Extract fields
        repo = task_spec["repo"]
        goal = task_spec["goal"]
        base_branch = task_spec.get("base_branch", "main")

        # Generate branch name (informational only — no branch is actually created)
        branch_name = self._generate_branch_name(goal)

        # ALFA invariant — return truthful stub.
        return PRResponse(
            ok=False,
            pr_number=None,
            pr_url=None,
            branch=branch_name,
            error=(
                "CodeOps create_pr not implemented — real PR execution is "
                "not yet wired (stub). The planned branch name is returned "
                "for transparency only; no remote operation was performed."
            ),
        )

    def _generate_branch_name(self, goal: str) -> str:
        """
        Generate a branch name from a goal description.

        Args:
            goal: Task goal description

        Returns:
            Valid git branch name
        """
        # Extract keywords and create slug
        words = goal.lower().split()[:5]  # First 5 words

        # Remove common filler words
        stop_words = {"the", "a", "an", "to", "for", "in", "on", "of", "and", "or"}
        words = [w for w in words if w not in stop_words]

        # Clean each word
        clean_words = []
        for word in words:
            # Keep only alphanumeric
            clean = "".join(c for c in word if c.isalnum())
            if clean:
                clean_words.append(clean)

        # Build branch name
        if clean_words:
            slug = "-".join(clean_words[:4])
        else:
            slug = "codeops-task"

        return f"codeops/{slug}"
