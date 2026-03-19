"""
CodeOps Module - Automated Code Operations for Assistant OS.

This module provides functionality for automated code changes via GitHub:
- Repository analysis and cloning
- Branch creation and management
- Code modifications and patches
- Pull request creation

Usage:
    from assistant_os.codeops import CodeOpsHandler
    
    handler = CodeOpsHandler()
    
    # Plan a task
    plan = handler.plan_task({
        "repo": "owner/repo",
        "goal": "Add unit tests for auth module"
    })
    
    # Create a PR (when fully implemented)
    result = handler.create_pr(task_spec)

Environment Variables:
    GITHUB_TOKEN: Required for GitHub API access (PR creation, repo info)
"""

from .contracts import (
    TaskSpec,
    PlanResponse,
    PlanStep,
    PRResponse,
    RepoInfo,
    BranchInfo,
    PRInfo,
    validate_task_spec,
)

from .github_client import (
    GitHubClient,
    GitHubClientError,
    GitHubAuthError,
    GitHubAPIError,
)

from .repo_manager import (
    GitError,
    CloneError,
    BranchError,
    PatchError,
    CommitError,
    clone_repo,
    checkout_branch,
    apply_patch,
    commit_and_push,
    cleanup_repo,
)

from .handler import (
    CodeOpsHandler,
    CodeOpsError,
    TaskValidationError,
)

__all__ = [
    # Contracts
    "TaskSpec",
    "PlanResponse",
    "PlanStep",
    "PRResponse",
    "RepoInfo",
    "BranchInfo",
    "PRInfo",
    "validate_task_spec",
    # GitHub Client
    "GitHubClient",
    "GitHubClientError",
    "GitHubAuthError",
    "GitHubAPIError",
    # Repo Manager
    "GitError",
    "CloneError",
    "BranchError",
    "PatchError",
    "CommitError",
    "clone_repo",
    "checkout_branch",
    "apply_patch",
    "commit_and_push",
    "cleanup_repo",
    # Handler
    "CodeOpsHandler",
    "CodeOpsError",
    "TaskValidationError",
]
