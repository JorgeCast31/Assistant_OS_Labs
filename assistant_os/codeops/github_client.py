"""
GitHub API Client for CodeOps.

Provides authenticated access to GitHub API for repository operations,
branch management, and pull request creation.

Requires:
    - GITHUB_TOKEN environment variable with appropriate scopes:
      - repo (for private repos)
      - public_repo (for public repos only)
"""
import os
from typing import Optional

from .contracts import RepoInfo, BranchInfo, PRInfo


class GitHubClientError(Exception):
    """Base exception for GitHub client errors."""
    pass


class GitHubAuthError(GitHubClientError):
    """Raised when GitHub authentication fails or token is missing."""
    pass


class GitHubAPIError(GitHubClientError):
    """Raised when GitHub API returns an error."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class GitHubClient:
    """
    GitHub API client with authentication and common operations.
    
    Usage:
        client = GitHubClient()  # Uses GITHUB_TOKEN from environment
        repo = client.get_repo("owner/repo")
        client.create_branch(repo, "main", "feature/new-feature")
        pr = client.create_pr(repo, "Add feature", "Description", "feature/new-feature", "main")
    
    Environment:
        GITHUB_TOKEN: Personal access token or GitHub App token with repo access
    """
    
    API_BASE_URL = "https://api.github.com"
    
    def __init__(self, token: Optional[str] = None):
        """
        Initialize GitHub client.
        
        Args:
            token: GitHub token. If not provided, reads from GITHUB_TOKEN env var.
        
        Raises:
            GitHubAuthError: If no token is provided and GITHUB_TOKEN is not set.
        """
        self._token = token or os.environ.get("GITHUB_TOKEN")
        
        if not self._token:
            raise GitHubAuthError(
                "GitHub token is required. Set GITHUB_TOKEN environment variable "
                "or pass token to GitHubClient constructor."
            )
        
        # Token preview for debugging (first 8 chars only)
        self._token_preview = self._token[:8] + "..." if len(self._token) > 8 else "***"
        self._initialized = True
    
    @property
    def is_authenticated(self) -> bool:
        """Check if client has a token configured."""
        return bool(self._token)
    
    def get_repo(self, full_name: str) -> RepoInfo:
        """
        Get repository information.
        
        Args:
            full_name: Repository in "owner/repo" format
        
        Returns:
            RepoInfo with repository details
        
        Raises:
            GitHubAPIError: If repository not found or API error
            ValueError: If full_name format is invalid
        
        TODO: Implement actual GitHub API call
        """
        # Validate format
        if "/" not in full_name:
            raise ValueError(f"Repository must be in 'owner/repo' format, got: {full_name}")
        
        parts = full_name.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Invalid repository format: {full_name}")
        
        # TODO: Implement actual API call
        # Endpoint: GET /repos/{owner}/{repo}
        # Headers: Authorization: Bearer {token}
        
        # Placeholder response for now
        return RepoInfo(
            full_name=full_name,
            default_branch="main",
            private=False,
            clone_url=f"https://github.com/{full_name}.git"
        )
    
    def create_branch(
        self,
        repo: str | RepoInfo,
        base: str,
        new_branch: str
    ) -> BranchInfo:
        """
        Create a new branch from an existing branch.
        
        Args:
            repo: Repository name or RepoInfo object
            base: Base branch name to branch from
            new_branch: Name for the new branch
        
        Returns:
            BranchInfo for the newly created branch
        
        Raises:
            GitHubAPIError: If branch creation fails
            ValueError: If branch names are invalid
        
        TODO: Implement actual GitHub API call
        """
        # Normalize repo to string
        repo_name = repo["full_name"] if isinstance(repo, dict) else repo
        
        # Validate branch names
        if not base or not isinstance(base, str):
            raise ValueError("Base branch name is required")
        
        if not new_branch or not isinstance(new_branch, str):
            raise ValueError("New branch name is required")
        
        # Check for invalid characters in branch name
        invalid_chars = [" ", "~", "^", ":", "\\", "?", "*", "["]
        for char in invalid_chars:
            if char in new_branch:
                raise ValueError(f"Invalid character '{char}' in branch name: {new_branch}")
        
        # TODO: Implement actual API calls
        # 1. GET /repos/{owner}/{repo}/git/refs/heads/{base} - get base SHA
        # 2. POST /repos/{owner}/{repo}/git/refs - create new ref
        
        # Placeholder response
        return BranchInfo(
            name=new_branch,
            sha="placeholder_sha_" + new_branch[:8],
            protected=False
        )
    
    def create_pr(
        self,
        repo: str | RepoInfo,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool = False
    ) -> PRInfo:
        """
        Create a pull request.
        
        Args:
            repo: Repository name or RepoInfo object
            title: PR title
            body: PR description (supports markdown)
            head: Source branch (the branch with changes)
            base: Target branch (the branch to merge into)
            draft: Whether to create as draft PR
        
        Returns:
            PRInfo for the created pull request
        
        Raises:
            GitHubAPIError: If PR creation fails
            ValueError: If parameters are invalid
        
        TODO: Implement actual GitHub API call
        """
        # Normalize repo to string
        repo_name = repo["full_name"] if isinstance(repo, dict) else repo
        
        # Validate required fields
        if not title or not isinstance(title, str):
            raise ValueError("PR title is required")
        
        if not head or not isinstance(head, str):
            raise ValueError("Head branch is required")
        
        if not base or not isinstance(base, str):
            raise ValueError("Base branch is required")
        
        if head == base:
            raise ValueError("Head and base branches cannot be the same")
        
        # TODO: Implement actual API call
        # Endpoint: POST /repos/{owner}/{repo}/pulls
        # Body: { "title": title, "body": body, "head": head, "base": base, "draft": draft }
        
        # Placeholder response
        owner, repo_short = repo_name.split("/")
        return PRInfo(
            number=1,  # Placeholder
            title=title,
            state="open",
            head_branch=head,
            base_branch=base,
            url=f"https://github.com/{repo_name}/pull/1"
        )
    
    def list_prs(
        self,
        repo: str | RepoInfo,
        state: str = "open"
    ) -> list[PRInfo]:
        """
        List pull requests for a repository.
        
        Args:
            repo: Repository name or RepoInfo object
            state: Filter by state: "open", "closed", "all"
        
        Returns:
            List of PRInfo objects
        
        Raises:
            GitHubAPIError: If listing fails
            ValueError: If state is invalid
        
        TODO: Implement actual GitHub API call
        """
        # Normalize repo to string
        repo_name = repo["full_name"] if isinstance(repo, dict) else repo
        
        # Validate state
        valid_states = ["open", "closed", "all"]
        if state not in valid_states:
            raise ValueError(f"Invalid state '{state}'. Must be one of: {valid_states}")
        
        # TODO: Implement actual API call
        # Endpoint: GET /repos/{owner}/{repo}/pulls?state={state}
        
        # Placeholder: return empty list
        return []
    
    def get_branch(self, repo: str | RepoInfo, branch: str) -> BranchInfo:
        """
        Get information about a specific branch.
        
        Args:
            repo: Repository name or RepoInfo object
            branch: Branch name
        
        Returns:
            BranchInfo for the branch
        
        Raises:
            GitHubAPIError: If branch not found
        
        TODO: Implement actual GitHub API call
        """
        repo_name = repo["full_name"] if isinstance(repo, dict) else repo
        
        if not branch:
            raise ValueError("Branch name is required")
        
        # TODO: Implement actual API call
        # Endpoint: GET /repos/{owner}/{repo}/branches/{branch}
        
        # Placeholder response
        return BranchInfo(
            name=branch,
            sha="placeholder_sha",
            protected=branch in ["main", "master"]
        )
    
    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None
    ) -> dict:
        """
        Make an authenticated request to GitHub API.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            endpoint: API endpoint (without base URL)
            data: Optional JSON body for POST/PUT/PATCH
        
        Returns:
            JSON response as dictionary
        
        Raises:
            GitHubAPIError: If request fails
        
        TODO: Implement actual HTTP request using httpx or requests
        """
        # TODO: Implement actual HTTP request
        # url = f"{self.API_BASE_URL}{endpoint}"
        # headers = {
        #     "Authorization": f"Bearer {self._token}",
        #     "Accept": "application/vnd.github+json",
        #     "X-GitHub-Api-Version": "2022-11-28"
        # }
        
        raise NotImplementedError("_request method not yet implemented")
