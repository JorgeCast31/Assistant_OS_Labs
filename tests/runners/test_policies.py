"""Tests for runner policies — Slice 1 (hardened)."""

import os
from pathlib import Path

import pytest

from assistant_os.runners.errors import PolicyViolationError
from assistant_os.runners.policies import is_path_allowed, validate_repo_path


# ---------------------------------------------------------------------------
# is_path_allowed — basic cases
# ---------------------------------------------------------------------------


def test_is_path_allowed_normal_path(tmp_path):
    assert is_path_allowed(str(tmp_path)) is True


def test_is_path_allowed_denies_git_path(tmp_path):
    git_path = tmp_path / ".git"
    git_path.mkdir()
    assert is_path_allowed(str(git_path)) is False


def test_is_path_allowed_custom_deny_list(tmp_path):
    subdir = tmp_path / "forbidden"
    subdir.mkdir()
    assert is_path_allowed(str(subdir), deny_paths={"forbidden"}) is False


def test_is_path_allowed_with_allow_list(tmp_path):
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    other_dir = tmp_path / "other"
    other_dir.mkdir()

    assert is_path_allowed(str(allowed_dir), allow_paths=[str(allowed_dir)]) is True
    assert is_path_allowed(str(other_dir), allow_paths=[str(allowed_dir)]) is False


def test_is_path_allowed_secrets_denied(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    assert is_path_allowed(str(secrets_dir)) is False


# ---------------------------------------------------------------------------
# is_path_allowed — hardening: no substring false-positives
# ---------------------------------------------------------------------------


def test_is_path_allowed_no_false_positive_on_etc_substring(tmp_path):
    """A directory named 'etcetera' must NOT be denied just because it contains 'etc'."""
    etcetera = tmp_path / "etcetera"
    etcetera.mkdir()
    assert is_path_allowed(str(etcetera)) is True


def test_is_path_allowed_no_false_positive_on_secrets_substring(tmp_path):
    """A directory named 'my_secrets_backup' must NOT be denied by the segment rule.

    The segment rule matches full path components, not substrings of them.
    """
    # "my_secrets_backup" as a full component does NOT equal "secrets"
    d = tmp_path / "my_secrets_backup"
    d.mkdir()
    assert is_path_allowed(str(d)) is True


def test_is_path_allowed_allow_list_no_false_positive_on_prefix(tmp_path):
    """'/tmp/foo' must not accidentally allow '/tmp/foobar'."""
    foo = tmp_path / "foo"
    foo.mkdir()
    foobar = tmp_path / "foobar"
    foobar.mkdir()

    assert is_path_allowed(str(foo), allow_paths=[str(foo)]) is True
    assert is_path_allowed(str(foobar), allow_paths=[str(foo)]) is False


def test_is_path_allowed_child_of_denied_prefix_also_denied(tmp_path):
    """A path inside a denied parent directory must also be denied."""
    parent = tmp_path / "restricted"
    parent.mkdir()
    child = parent / "config"
    child.mkdir()
    # Deny the parent — child should also be denied
    assert is_path_allowed(str(child), deny_paths={str(parent)}) is False


def test_is_path_allowed_sibling_of_denied_prefix_is_allowed(tmp_path):
    """A sibling directory must not be denied when only its sibling is in the deny list."""
    denied_dir = tmp_path / "denied"
    denied_dir.mkdir()
    sibling_dir = tmp_path / "allowed_sibling"
    sibling_dir.mkdir()
    assert is_path_allowed(str(sibling_dir), deny_paths={str(denied_dir)}) is True


def test_is_path_allowed_nested_git_segment_is_denied(tmp_path):
    """A .git directory nested inside a project path is denied."""
    nested = tmp_path / "project" / ".git"
    nested.mkdir(parents=True)
    assert is_path_allowed(str(nested)) is False


# ---------------------------------------------------------------------------
# validate_repo_path — basic cases
# ---------------------------------------------------------------------------


def test_validate_repo_path_valid(tmp_path):
    validate_repo_path(str(tmp_path))


def test_validate_repo_path_empty_string():
    with pytest.raises(PolicyViolationError, match="must not be empty"):
        validate_repo_path("")


def test_validate_repo_path_whitespace_only():
    with pytest.raises(PolicyViolationError, match="must not be empty"):
        validate_repo_path("   ")


def test_validate_repo_path_nonexistent():
    with pytest.raises(PolicyViolationError, match="does not exist"):
        validate_repo_path("/this/path/does/not/exist/at/all")


def test_validate_repo_path_file_not_dir(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("hello")
    with pytest.raises(PolicyViolationError, match="not a directory"):
        validate_repo_path(str(f))


def test_validate_repo_path_denied_git(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    with pytest.raises(PolicyViolationError, match="denied by policy"):
        validate_repo_path(str(git_dir))


# ---------------------------------------------------------------------------
# validate_repo_path — hardening
# ---------------------------------------------------------------------------


def test_validate_repo_path_resolves_traversal(tmp_path):
    """Path traversal using ../ must resolve to the real path and be validated."""
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    traversal = str(subdir) + "/../subdir"
    # Should succeed — resolves back to subdir which is valid
    validate_repo_path(traversal)


def test_validate_repo_path_traversal_into_denied(tmp_path):
    """Traversal that resolves into a denied path must be rejected."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    safe_dir = tmp_path / "safe"
    safe_dir.mkdir()
    # Traverse from safe into .git
    traversal = str(safe_dir) + "/../.git"
    with pytest.raises(PolicyViolationError, match="denied by policy"):
        validate_repo_path(traversal)
