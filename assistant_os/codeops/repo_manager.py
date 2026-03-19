"""
Local Git Repository Manager for CodeOps.

Provides functions for local git operations: cloning, branching,
applying patches, committing, and pushing changes.

Note: This module interacts with the local filesystem and git CLI.
All operations are designed to fail safely without leaving partial state.
"""
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from ..config import WORKSPACE_ROOT


class GitError(Exception):
    """Base exception for git operation errors."""
    pass


class CloneError(GitError):
    """Raised when repository cloning fails."""
    pass


class BranchError(GitError):
    """Raised when branch operations fail."""
    pass


class PatchError(GitError):
    """Raised when patch application fails."""
    pass


class CommitError(GitError):
    """Raised when commit or push operations fail."""
    pass


# Default directory for cloned repositories (inside workspace)
DEFAULT_REPOS_DIR = WORKSPACE_ROOT / "codeops_repos"


def clone_repo(
    repo_url: str,
    dest_dir: Optional[str | Path] = None,
    branch: Optional[str] = None,
    depth: int = 1
) -> Path:
    """
    Clone a git repository to a local directory.
    
    Args:
        repo_url: HTTPS or SSH URL of the repository
        dest_dir: Destination directory path. If None, uses DEFAULT_REPOS_DIR/<repo_name>
        branch: Specific branch to clone. If None, clones default branch.
        depth: Clone depth (default 1 for shallow clone). Use 0 for full clone.
    
    Returns:
        Path to the cloned repository directory
    
    Raises:
        CloneError: If cloning fails
        ValueError: If repo_url is invalid
    
    TODO: Implement actual git clone operation
    """
    if not repo_url:
        raise ValueError("Repository URL is required")
    
    # Extract repo name from URL
    # Handles: https://github.com/owner/repo.git, git@github.com:owner/repo.git
    repo_name = repo_url.rstrip("/").rstrip(".git").split("/")[-1]
    if ":" in repo_name:
        repo_name = repo_name.split(":")[-1]
    
    if not repo_name:
        raise ValueError(f"Could not extract repository name from URL: {repo_url}")
    
    # Determine destination
    if dest_dir is None:
        DEFAULT_REPOS_DIR.mkdir(parents=True, exist_ok=True)
        dest_path = DEFAULT_REPOS_DIR / repo_name
    else:
        dest_path = Path(dest_dir)
    
    # Check if already exists
    if dest_path.exists():
        raise CloneError(f"Destination already exists: {dest_path}")
    
    # TODO: Implement actual git clone
    # cmd = ["git", "clone"]
    # if depth > 0:
    #     cmd.extend(["--depth", str(depth)])
    # if branch:
    #     cmd.extend(["--branch", branch])
    # cmd.extend([repo_url, str(dest_path)])
    # 
    # result = subprocess.run(cmd, capture_output=True, text=True)
    # if result.returncode != 0:
    #     raise CloneError(f"git clone failed: {result.stderr}")
    
    raise NotImplementedError("clone_repo not yet implemented - git operations disabled")


def checkout_branch(
    repo_dir: str | Path,
    base: str,
    new_branch: str,
    create: bool = True
) -> str:
    """
    Checkout or create a branch in a local repository.
    
    Args:
        repo_dir: Path to the git repository
        base: Base branch to start from
        new_branch: Branch name to checkout/create
        create: If True, create the branch. If False, just checkout existing.
    
    Returns:
        Name of the checked out branch
    
    Raises:
        BranchError: If checkout fails
        ValueError: If parameters are invalid
        FileNotFoundError: If repo_dir doesn't exist
    
    TODO: Implement actual git checkout operation
    """
    repo_path = Path(repo_dir)
    
    if not repo_path.exists():
        raise FileNotFoundError(f"Repository directory not found: {repo_path}")
    
    if not (repo_path / ".git").exists():
        raise ValueError(f"Not a git repository: {repo_path}")
    
    if not base:
        raise ValueError("Base branch is required")
    
    if not new_branch:
        raise ValueError("New branch name is required")
    
    # Check for invalid characters
    invalid_chars = [" ", "~", "^", ":", "\\", "?", "*", "["]
    for char in invalid_chars:
        if char in new_branch:
            raise ValueError(f"Invalid character '{char}' in branch name: {new_branch}")
    
    # TODO: Implement actual git checkout
    # if create:
    #     cmd = ["git", "checkout", "-b", new_branch, base]
    # else:
    #     cmd = ["git", "checkout", new_branch]
    # 
    # result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
    # if result.returncode != 0:
    #     raise BranchError(f"git checkout failed: {result.stderr}")
    
    raise NotImplementedError("checkout_branch not yet implemented - git operations disabled")


def apply_patch(
    repo_dir: str | Path,
    unified_diff: str,
    check_only: bool = False
) -> bool:
    """
    Apply a unified diff patch to a repository.
    
    Args:
        repo_dir: Path to the git repository
        unified_diff: The unified diff content to apply
        check_only: If True, only check if patch would apply cleanly
    
    Returns:
        True if patch was applied (or would apply) successfully
    
    Raises:
        PatchError: If patch application fails
        ValueError: If parameters are invalid
        FileNotFoundError: If repo_dir doesn't exist
    
    TODO: Implement actual patch application
    """
    repo_path = Path(repo_dir)
    
    if not repo_path.exists():
        raise FileNotFoundError(f"Repository directory not found: {repo_path}")
    
    if not unified_diff or not isinstance(unified_diff, str):
        raise ValueError("Unified diff content is required")
    
    # Basic validation of diff format
    if not unified_diff.strip().startswith(("---", "diff ")):
        raise ValueError("Invalid unified diff format: must start with '---' or 'diff'")
    
    # TODO: Implement actual patch application
    # if check_only:
    #     cmd = ["git", "apply", "--check", "-"]
    # else:
    #     cmd = ["git", "apply", "-"]
    # 
    # result = subprocess.run(
    #     cmd,
    #     cwd=repo_path,
    #     input=unified_diff,
    #     capture_output=True,
    #     text=True
    # )
    # if result.returncode != 0:
    #     raise PatchError(f"Patch application failed: {result.stderr}")
    
    raise NotImplementedError("apply_patch not yet implemented - git operations disabled")


def commit_and_push(
    repo_dir: str | Path,
    message: str,
    remote: str = "origin",
    branch: Optional[str] = None
) -> tuple[str, bool]:
    """
    Stage all changes, commit, and push to remote.
    
    Args:
        repo_dir: Path to the git repository
        message: Commit message
        remote: Remote name (default: "origin")
        branch: Branch to push. If None, pushes current branch.
    
    Returns:
        Tuple of (commit_sha, push_success)
    
    Raises:
        CommitError: If commit or push fails
        ValueError: If parameters are invalid
        FileNotFoundError: If repo_dir doesn't exist
    
    TODO: Implement actual git commit and push
    """
    repo_path = Path(repo_dir)
    
    if not repo_path.exists():
        raise FileNotFoundError(f"Repository directory not found: {repo_path}")
    
    if not (repo_path / ".git").exists():
        raise ValueError(f"Not a git repository: {repo_path}")
    
    if not message or not isinstance(message, str):
        raise ValueError("Commit message is required")
    
    if not message.strip():
        raise ValueError("Commit message cannot be empty")
    
    # TODO: Implement actual git commit and push
    # # Stage all changes
    # subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
    # 
    # # Commit
    # result = subprocess.run(
    #     ["git", "commit", "-m", message],
    #     cwd=repo_path,
    #     capture_output=True,
    #     text=True
    # )
    # if result.returncode != 0:
    #     raise CommitError(f"git commit failed: {result.stderr}")
    # 
    # # Get commit SHA
    # sha_result = subprocess.run(
    #     ["git", "rev-parse", "HEAD"],
    #     cwd=repo_path,
    #     capture_output=True,
    #     text=True
    # )
    # commit_sha = sha_result.stdout.strip()
    # 
    # # Push
    # push_cmd = ["git", "push", remote]
    # if branch:
    #     push_cmd.append(branch)
    # push_result = subprocess.run(push_cmd, cwd=repo_path, capture_output=True, text=True)
    # 
    # return commit_sha, push_result.returncode == 0
    
    raise NotImplementedError("commit_and_push not yet implemented - git operations disabled")


def get_current_branch(repo_dir: str | Path) -> str:
    """
    Get the current branch name of a repository.
    
    Args:
        repo_dir: Path to the git repository
    
    Returns:
        Current branch name
    
    Raises:
        GitError: If operation fails
    
    TODO: Implement actual git branch detection
    """
    repo_path = Path(repo_dir)
    
    if not repo_path.exists():
        raise FileNotFoundError(f"Repository directory not found: {repo_path}")
    
    if not (repo_path / ".git").exists():
        raise ValueError(f"Not a git repository: {repo_path}")
    
    # TODO: Implement actual git command
    # result = subprocess.run(
    #     ["git", "branch", "--show-current"],
    #     cwd=repo_path,
    #     capture_output=True,
    #     text=True
    # )
    # if result.returncode != 0:
    #     raise GitError(f"Could not get current branch: {result.stderr}")
    # return result.stdout.strip()
    
    raise NotImplementedError("get_current_branch not yet implemented")


def has_uncommitted_changes(repo_dir: str | Path) -> bool:
    """
    Check if repository has uncommitted changes.
    
    Args:
        repo_dir: Path to the git repository
    
    Returns:
        True if there are uncommitted changes
    
    TODO: Implement actual git status check
    """
    repo_path = Path(repo_dir)
    
    if not repo_path.exists():
        raise FileNotFoundError(f"Repository directory not found: {repo_path}")
    
    # TODO: Implement actual git status check
    # result = subprocess.run(
    #     ["git", "status", "--porcelain"],
    #     cwd=repo_path,
    #     capture_output=True,
    #     text=True
    # )
    # return bool(result.stdout.strip())
    
    raise NotImplementedError("has_uncommitted_changes not yet implemented")


def cleanup_repo(repo_dir: str | Path) -> bool:
    """
    Remove a cloned repository directory.
    
    Args:
        repo_dir: Path to the repository to remove
    
    Returns:
        True if successfully removed
    
    Raises:
        GitError: If removal fails
    """
    repo_path = Path(repo_dir)
    
    if not repo_path.exists():
        return True  # Already gone
    
    # Safety check: only remove from our repos directory
    try:
        repo_path.resolve().relative_to(DEFAULT_REPOS_DIR.resolve())
    except ValueError:
        raise GitError(
            f"Refusing to delete repository outside of {DEFAULT_REPOS_DIR}: {repo_path}"
        )
    
    try:
        shutil.rmtree(repo_path)
        return True
    except Exception as e:
        raise GitError(f"Failed to remove repository {repo_path}: {e}")
