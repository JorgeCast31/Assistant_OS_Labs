"""Tests for Sprint S-AUTHORITY-SECRET-HARDENING-01.

These tests document the REQUIRED behavior after hardening:
  - No secret + no dev mode  → RuntimeError (currently FAILS — falls back silently)
  - ASSISTANT_OS_DEV_MODE=1  → allowed (dev default returned with warning)
  - Explicit env secret       → used directly
  - Explicit arg secret       → used directly

Tests marked with "currently FAILS" drive the implementation.
"""
import os
import warnings

import pytest

from assistant_os.authority.artifact import (
    AUTHORITY_ARTIFACT_SECRET_ENV_VAR,
    _DEFAULT_AUTHORITY_ARTIFACT_SECRET,
    resolve_authority_artifact_secret,
    sign_authority_artifact,
)

_DEV_MODE_ENV_VAR = "ASSISTANT_OS_DEV_MODE"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_env(monkeypatch):
    """Strip both secret and dev-mode vars so the function starts from scratch."""
    monkeypatch.delenv(AUTHORITY_ARTIFACT_SECRET_ENV_VAR, raising=False)
    monkeypatch.delenv(_DEV_MODE_ENV_VAR, raising=False)


# ---------------------------------------------------------------------------
# RED tests — these must FAIL on the current (unfixed) implementation
# ---------------------------------------------------------------------------


def test_raises_runtime_error_when_no_secret_and_no_dev_mode(monkeypatch):
    """resolve_authority_artifact_secret() must raise when no secret is configured
    and ASSISTANT_OS_DEV_MODE is not 1.  Currently it silently returns the dev
    default, which is the forgery vector we are eliminating."""
    _clean_env(monkeypatch)

    with pytest.raises(RuntimeError):
        resolve_authority_artifact_secret()


def test_error_message_names_the_required_env_var(monkeypatch):
    """The RuntimeError message must tell the operator exactly which env var to set."""
    _clean_env(monkeypatch)

    with pytest.raises(RuntimeError, match=AUTHORITY_ARTIFACT_SECRET_ENV_VAR):
        resolve_authority_artifact_secret()


def test_sign_raises_when_no_secret_and_no_dev_mode(monkeypatch):
    """sign_authority_artifact() must propagate the RuntimeError; it must not
    silently produce an artifact signed with the dev key in production."""
    _clean_env(monkeypatch)

    minimal_payload = {
        "artifact_version": "2",
        "execution_id": "exec-test",
        "plan_id": "plan-test",
        "authorized_plan_hash": "abc123",
        "policy_id": "pol-test",
        "policy_decision_ref": "pol-decision-test",
        "governance_ref": "gov-test",
        "approval_id": "approval-test",
        "execution_mode": "test",
        "capability_scope": ["test.read"],
        "runtime_profile": "test",
        "authority_source": "mso",
        "authority_class": "sovereign",
        "delegated_seat_ref": "",
        "signature": "",
    }

    with pytest.raises(RuntimeError):
        sign_authority_artifact(minimal_payload)


# ---------------------------------------------------------------------------
# GREEN confirmation tests — these must pass both before AND after the fix
# ---------------------------------------------------------------------------


def test_dev_mode_one_allows_dev_default(monkeypatch):
    """ASSISTANT_OS_DEV_MODE=1 must return the dev default (for tests and local dev)."""
    _clean_env(monkeypatch)
    monkeypatch.setenv(_DEV_MODE_ENV_VAR, "1")

    result = resolve_authority_artifact_secret()

    assert result == _DEFAULT_AUTHORITY_ARTIFACT_SECRET


def test_dev_mode_other_values_do_not_allow_dev_default(monkeypatch):
    """Only the exact string '1' enables dev mode; other truthy values must not."""
    _clean_env(monkeypatch)
    monkeypatch.setenv(_DEV_MODE_ENV_VAR, "true")  # 'true' ≠ '1'

    with pytest.raises(RuntimeError):
        resolve_authority_artifact_secret()


def test_explicit_env_secret_is_used(monkeypatch):
    """When ASSISTANT_OS_AUTHORITY_ARTIFACT_SECRET is set, it is used regardless of dev mode."""
    _clean_env(monkeypatch)
    monkeypatch.setenv(AUTHORITY_ARTIFACT_SECRET_ENV_VAR, "my-production-secret")

    result = resolve_authority_artifact_secret()

    assert result == "my-production-secret"


def test_explicit_arg_secret_takes_precedence_over_env(monkeypatch):
    """An explicit secret argument takes precedence over the env var."""
    _clean_env(monkeypatch)
    monkeypatch.setenv(AUTHORITY_ARTIFACT_SECRET_ENV_VAR, "env-secret")

    result = resolve_authority_artifact_secret(secret="arg-secret")

    assert result == "arg-secret"


def test_explicit_arg_secret_works_without_any_env(monkeypatch):
    """An explicit secret argument works even with no env vars set."""
    _clean_env(monkeypatch)

    result = resolve_authority_artifact_secret(secret="standalone-secret")

    assert result == "standalone-secret"


def test_dev_mode_issues_no_exception(monkeypatch):
    """Using dev mode must not raise; it may warn but must not crash."""
    _clean_env(monkeypatch)
    monkeypatch.setenv(_DEV_MODE_ENV_VAR, "1")

    # Must not raise
    result = resolve_authority_artifact_secret()
    assert isinstance(result, str) and result
