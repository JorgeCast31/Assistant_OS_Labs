from __future__ import annotations

import pytest

from assistant_os.authority import (
    AUTHORITY_ARTIFACT_VERSION_V1,
    canonicalize_authority_artifact,
    sign_authority_artifact,
    verify_authority_artifact,
)


def _artifact(**overrides):
    artifact = {
        "artifact_version": AUTHORITY_ARTIFACT_VERSION_V1,
        "execution_id": "exec-001",
        "plan_id": "plan-001",
        "authorized_plan_hash": "hash-001",
        "policy_id": "default",
        "policy_decision_ref": "decision:plan-001",
        "governance_ref": "gov-001",
        "approval_id": "approval-001",
        "execution_mode": "confirm",
        "capability_scope": ["code_fix", "code_create"],
        "runtime_profile": "python3.11",
    }
    artifact.update(overrides)
    return artifact


class TestAuthorityArtifact:
    SECRET = "authority-artifact-test-secret"

    def test_same_artifact_yields_same_canonical_form(self):
        left = canonicalize_authority_artifact(_artifact())
        right = canonicalize_authority_artifact(
            _artifact(capability_scope=["code_create", "code_fix", "code_fix"])
        )

        assert left == right

    def test_changing_signed_field_breaks_verification(self):
        artifact = sign_authority_artifact(_artifact(), secret=self.SECRET).to_dict()
        artifact["execution_mode"] = "blocked"

        assert verify_authority_artifact(artifact, secret=self.SECRET) is False

    def test_missing_required_field_fails(self):
        artifact = _artifact()
        del artifact["approval_id"]

        with pytest.raises(ValueError, match="missing required fields"):
            canonicalize_authority_artifact(artifact)

    def test_unsupported_artifact_version_fails(self):
        artifact = _artifact(artifact_version="999")

        with pytest.raises(ValueError, match="Unsupported authority artifact version"):
            sign_authority_artifact(artifact, secret=self.SECRET)

    def test_invalid_signature_fails(self):
        artifact = sign_authority_artifact(_artifact(), secret=self.SECRET).to_dict()
        artifact["signature"] = "not-a-real-signature"

        assert verify_authority_artifact(artifact, secret=self.SECRET) is False
