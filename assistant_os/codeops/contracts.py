"""
CodeOps Contracts - TypedDict definitions for CodeOps module.

These contracts define the data structures used throughout the CodeOps module
for task specification, responses, and internal communication.
"""
from typing import TypedDict, Optional


class TaskSpec(TypedDict, total=False):
    """
    Specification for a code task to be executed by CodeOps.
    
    Required fields:
        repo: Full repository name (e.g., "owner/repo")
        goal: Description of what needs to be accomplished
    
    Optional fields:
        base_branch: Branch to base work on (default: "main")
        module_scope: Specific module/directory to focus on
        acceptance: Acceptance criteria for the task
    """
    repo: str                    # Required: "owner/repo" format
    goal: str                    # Required: task description
    base_branch: str             # Optional: default "main"
    module_scope: Optional[str]  # Optional: specific module path
    acceptance: Optional[str]    # Optional: acceptance criteria


class PlanStep(TypedDict):
    """A single step in a code operation plan."""
    order: int           # Step number (1-based)
    action: str          # Action type: "analyze", "modify", "create", "delete", "test"
    target: str          # File or module being affected
    description: str     # Human-readable description of what will be done


class PlanResponse(TypedDict):
    """
    Response from CodeOpsHandler.plan_task().
    
    Contains the execution plan for a code task, including
    the ordered steps, files that will be touched, and any warnings.
    """
    ok: bool                    # Whether planning succeeded
    steps: list[PlanStep]       # Ordered list of steps to execute
    files_to_touch: list[str]   # List of file paths that will be modified
    warnings: list[str]         # Potential issues or risks identified
    error: Optional[str]        # Error message if ok=False


class PRResponse(TypedDict):
    """
    Response from CodeOpsHandler.create_pr().
    
    Contains the result of attempting to create a pull request.
    """
    ok: bool                    # Whether PR creation succeeded
    pr_number: Optional[int]    # PR number if created
    pr_url: Optional[str]       # URL to the PR if created
    branch: Optional[str]       # Branch name created
    error: Optional[str]        # Error message if ok=False


class RepoInfo(TypedDict):
    """Information about a GitHub repository."""
    full_name: str              # "owner/repo"
    default_branch: str         # Usually "main" or "master"
    private: bool               # Whether repo is private
    clone_url: str              # HTTPS clone URL


class BranchInfo(TypedDict):
    """Information about a Git branch."""
    name: str                   # Branch name
    sha: str                    # Latest commit SHA
    protected: bool             # Whether branch is protected


class PRInfo(TypedDict):
    """Information about a Pull Request."""
    number: int                 # PR number
    title: str                  # PR title
    state: str                  # "open", "closed", "merged"
    head_branch: str            # Source branch
    base_branch: str            # Target branch
    url: str                    # Web URL to PR


def validate_task_spec(spec: dict) -> tuple[bool, str]:
    """
    Validate that a TaskSpec has all required fields.
    
    Args:
        spec: Dictionary to validate as TaskSpec
    
    Returns:
        (is_valid, error_message) tuple
    """
    if not isinstance(spec, dict):
        return False, "TaskSpec must be a dictionary"
    
    # Required fields
    if "repo" not in spec:
        return False, "TaskSpec missing required field: 'repo'"
    
    if "goal" not in spec:
        return False, "TaskSpec missing required field: 'goal'"
    
    # Validate repo format (owner/repo)
    repo = spec.get("repo", "")
    if not isinstance(repo, str) or "/" not in repo:
        return False, "TaskSpec 'repo' must be in 'owner/repo' format"
    
    parts = repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return False, "TaskSpec 'repo' must be in 'owner/repo' format"
    
    # Validate goal is non-empty string
    goal = spec.get("goal", "")
    if not isinstance(goal, str) or not goal.strip():
        return False, "TaskSpec 'goal' must be a non-empty string"
    
    return True, ""
