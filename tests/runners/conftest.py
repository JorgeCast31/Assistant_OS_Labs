"""Shared test utilities for runner tests."""
from __future__ import annotations

import hashlib
import json

import pytest

from assistant_os.authority import (
    AUTHORITY_ARTIFACT_SECRET_ENV_VAR,
    AUTHORITY_ARTIFACT_VERSION_V2,
    AUTHORITY_CLASS_EXTERNAL_LOCAL,
    AUTHORITY_SOURCE_CODE_API,
    sign_authority_artifact,
)
from assistant_os.sandbox.authorized_plan import AuthorizedPlan


@pytest.fixture(autouse=True)
def _artifact_secret(monkeypatch):
    monkeypatch.setenv(
        AUTHORITY_ARTIFACT_SECRET_ENV_VAR,
        "runner-tests-shared-secret",
    )


def make_authorized_plan(
    execution_id: str,
    *,
    capability_scope: list[str] | None = None,
) -> AuthorizedPlan:
    """Build a minimal valid V2 external_local AuthorizedPlan for runner tests.

    Runner tests focus on apply/test/report behavior, not authority chain.
    An external_local artifact is the minimal honest authority that satisfies
    Runner's fail-closed check without implying MSO/Police governance.
    """
    scope = capability_scope or ["code_execute"]
    plan_id = execution_id

    plan_content = {
        "execution_id": execution_id,
        "plan_id": plan_id,
        "policy_id": "default",
        "capability_scope": sorted(scope),
    }
    authorized_plan_hash = hashlib.sha256(
        json.dumps(plan_content, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    artifact_payload = {
        "artifact_version": AUTHORITY_ARTIFACT_VERSION_V2,
        "execution_id": execution_id,
        "plan_id": plan_id,
        "authorized_plan_hash": authorized_plan_hash,
        "policy_id": "default",
        "policy_decision_ref": f"external_local:code_api:{execution_id}",
        "governance_ref": f"external_local:code_api:{execution_id}",
        "approval_id": f"external_local:code_api:{execution_id}",
        "execution_mode": "external_local",
        "capability_scope": scope,
        "runtime_profile": "python3.11",
        "authority_source": AUTHORITY_SOURCE_CODE_API,
        "authority_class": AUTHORITY_CLASS_EXTERNAL_LOCAL,
    }
    authority_artifact = sign_authority_artifact(artifact_payload)

    return AuthorizedPlan(
        execution_id=execution_id,
        plan_id=plan_id,
        authorized_plan_hash=authorized_plan_hash,
        policy_id="default",
        capability_scope=scope,
        runtime_profile="python3.11",
        authority_artifact=authority_artifact,
    )
