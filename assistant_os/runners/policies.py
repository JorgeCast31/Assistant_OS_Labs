"""
Runner policies — Slice 1 (hardened).

Path validation uses two distinct matching strategies:
  - Absolute prefix match: for system paths like /etc, C:/Windows
  - Segment match: for dangerous directory names like .git, .ssh, secrets

This prevents substring false-positives (e.g. "etc" matching "/home/etcetera").
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Collection, List, Optional

from .errors import PolicyViolationError

# Absolute path prefixes that are always denied.
# Matched as path prefix: denied if resolved path == prefix OR starts with prefix + "/".
_DENY_ABSOLUTE_PREFIXES: frozenset[str] = frozenset(
    {
        # Unix system directories
        "/root",
        "/etc",
        "/bin",
        "/sbin",
        "/usr",
        "/proc",
        "/sys",
        "/boot",
        "/dev",
        # Windows system directories (forward-slash normalised, lower-case)
        "c:/windows",
        "c:/program files",
        "c:/program files (x86)",
    }
)

# Path segment names that are always denied.
# Matched against individual components of the resolved path.
_DENY_SEGMENTS: frozenset[str] = frozenset(
    {
        ".git",
        ".ssh",
        "secrets",
    }
)

# Union exported for external use and tests.
DENY_PATHS: frozenset[str] = _DENY_ABSOLUTE_PREFIXES | _DENY_SEGMENTS

# Maximum allowed execution timeout in seconds.
MAX_TIMEOUT: int = 300

# Default timeout used when test_spec does not provide one.
DEFAULT_TEST_TIMEOUT: int = 120

# Allowed executable basenames for the first token in a test command.
# Full paths are accepted; only the basename is checked.
_ALLOWED_TEST_EXECUTABLES: frozenset[str] = frozenset({"pytest", "python", "python3"})

# Shell metacharacters that must never appear in any command token.
# Backslash is intentionally excluded: Windows paths use it and shell=False
# makes it safe. The check is defense-in-depth against confused callers, not
# a substitute for shell=False.
_SHELL_META_RE = re.compile(r"[|;&<>$`]")


def is_path_allowed(
    path: str,
    allow_paths: Optional[Collection[str]] = None,
    deny_paths: Optional[Collection[str]] = None,
) -> bool:
    """Return True if *path* is permitted under the given policy sets.

    Matching strategy (deny-list takes priority over allow-list):
    - Entries that look like absolute paths ("/etc", "c:/windows") are checked
      as path prefixes using Path semantics — no substring false-positives.
    - Entries without a leading slash or drive letter are treated as path
      segment names and matched against individual components of the path.

    If *deny_paths* is None the module-level DENY_PATHS constant is used.
    """
    effective_deny = deny_paths if deny_paths is not None else DENY_PATHS

    resolved = Path(path).resolve()
    resolved_posix = resolved.as_posix().lower()
    resolved_parts_lower = {p.lower() for p in resolved.parts}

    for denied in effective_deny:
        # Normalise to forward-slash posix form for consistent cross-platform comparison.
        d = denied.replace("\\", "/").lower()

        # Detect absolute path: starts with "/" or Windows drive ("c:/")
        is_absolute = d.startswith("/") or (len(d) >= 3 and d[1] == ":" and d[2] == "/")

        if is_absolute:
            # Prefix match — avoid empty-string edge case from stripping "/"
            prefix = d.rstrip("/")
            if not prefix:
                continue  # bare "/" is handled separately in validate_repo_path
            if resolved_posix == prefix or resolved_posix.startswith(prefix + "/"):
                return False
        else:
            # Segment match — any path component equals the denied name
            segment = d.strip("/")
            if segment and segment in resolved_parts_lower:
                return False

    # If an allow-list is provided the path must match at least one entry.
    if allow_paths is not None:
        for allowed in allow_paths:
            allowed_norm = Path(allowed).resolve().as_posix().lower()
            if resolved_posix == allowed_norm or resolved_posix.startswith(allowed_norm + "/"):
                return True
        return False

    return True


def validate_repo_path(repo_path: str) -> None:
    """Validate that *repo_path* is a safe, existing directory.

    Checks (in order):
        1. Non-empty string.
        2. Resolves to an existing path (handles ../ traversal automatically).
        3. Is a directory, not a file.
        4. Is not the filesystem root.
        5. Is not denied by policy.

    Raises:
        PolicyViolationError: if any check fails.
    """
    if not repo_path or not repo_path.strip():
        raise PolicyViolationError("repo_path must not be empty.")

    # resolve() expands symlinks and eliminates ../ traversal
    resolved = Path(repo_path).resolve()

    if not resolved.exists():
        raise PolicyViolationError(f"repo_path does not exist: {repo_path!r}")

    if not resolved.is_dir():
        raise PolicyViolationError(f"repo_path is not a directory: {repo_path!r}")

    # Reject filesystem root (e.g. "/" on Unix, "C:\" on Windows)
    if resolved == Path(resolved.anchor):
        raise PolicyViolationError(
            f"repo_path is the filesystem root, denied: {repo_path!r}"
        )

    if not is_path_allowed(str(resolved)):
        raise PolicyViolationError(f"repo_path is denied by policy: {repo_path!r}")


# ---------------------------------------------------------------------------
# Test execution policies (Slice 3)
# ---------------------------------------------------------------------------


def is_test_command_allowed(command: List[str]) -> bool:
    """Return True if *command* is a permitted test invocation.

    Rules:
      - Must be a non-empty list (no shell strings).
      - First token's basename must be "pytest", "python", or "python3".
      - If the executable is python/python3, the command must be
        ["<python>", "-m", "pytest", ...].
      - No token may contain shell metacharacters.

    Using basename allows full paths like /usr/bin/python3 or
    C:/Python/python.exe without needing an exhaustive path list.
    """
    if not isinstance(command, list) or not command:
        return False

    for token in command:
        if _SHELL_META_RE.search(str(token)):
            return False

    executable = Path(command[0]).name.lower()
    if executable.endswith(".exe"):
        executable = executable[:-4]

    if executable == "pytest":
        return True

    if executable in ("python", "python3"):
        # Must be: <python> -m pytest [extra args...]
        return len(command) >= 3 and command[1] == "-m" and command[2] == "pytest"

    return False


def validate_test_spec(test_spec: object) -> None:
    """Validate test_spec structure and policy compliance.

    Raises:
        PolicyViolationError: if the spec is missing, malformed, or unsafe.
    """
    if not isinstance(test_spec, dict):
        raise PolicyViolationError("test_spec must be a dict.")

    command = test_spec.get("command")
    if not command:
        raise PolicyViolationError("test_spec must have a non-empty 'command'.")

    if isinstance(command, str):
        raise PolicyViolationError(
            "test_spec 'command' must be a list, not a string — shell strings are not allowed."
        )

    if not isinstance(command, list):
        raise PolicyViolationError("test_spec 'command' must be a list.")

    if not is_test_command_allowed(command):
        raise PolicyViolationError(
            f"test_spec command is not allowed: {command!r}. "
            "Only pytest-based commands are permitted."
        )

    timeout_sec = test_spec.get("timeout_sec")
    if timeout_sec is not None:
        if not isinstance(timeout_sec, (int, float)) or timeout_sec <= 0:
            raise PolicyViolationError("test_spec 'timeout_sec' must be a positive number.")
        if timeout_sec > MAX_TIMEOUT:
            raise PolicyViolationError(
                f"test_spec 'timeout_sec' ({timeout_sec}) exceeds MAX_TIMEOUT ({MAX_TIMEOUT})."
            )
