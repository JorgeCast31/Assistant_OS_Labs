"""Canonical signed authority artifact foundation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from typing import Any

AUTHORITY_ARTIFACT_VERSION_V1 = "1"
AUTHORITY_ARTIFACT_SECRET_ENV_VAR = "ASSISTANT_OS_AUTHORITY_ARTIFACT_SECRET"
_DEFAULT_AUTHORITY_ARTIFACT_SECRET = "assistant_os.authority_artifact.dev_secret.v1"

_STRING_FIELDS: tuple[str, ...] = (
    "artifact_version",
    "execution_id",
    "plan_id",
    "authorized_plan_hash",
    "policy_id",
    "policy_decision_ref",
    "governance_ref",
    "approval_id",
    "execution_mode",
    "runtime_profile",
)
_OPTIONAL_STRING_FIELDS: tuple[str, ...] = ("delegated_seat_ref",)
_REQUIRED_FIELDS: tuple[str, ...] = _STRING_FIELDS + ("capability_scope",)


@dataclass(frozen=True)
class AuthorityArtifact:
    """Canonical signed authority artifact."""

    artifact_version: str
    execution_id: str
    plan_id: str
    authorized_plan_hash: str
    policy_id: str
    policy_decision_ref: str
    governance_ref: str
    approval_id: str
    execution_mode: str
    capability_scope: list[str]
    runtime_profile: str
    delegated_seat_ref: str = ""
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_version": self.artifact_version,
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "authorized_plan_hash": self.authorized_plan_hash,
            "policy_id": self.policy_id,
            "policy_decision_ref": self.policy_decision_ref,
            "governance_ref": self.governance_ref,
            "approval_id": self.approval_id,
            "execution_mode": self.execution_mode,
            "capability_scope": list(self.capability_scope),
            "runtime_profile": self.runtime_profile,
            "delegated_seat_ref": self.delegated_seat_ref,
            "signature": self.signature,
        }


def resolve_authority_artifact_secret(secret: str | None = None) -> str:
    """Resolve the authority artifact signing secret."""
    if isinstance(secret, str) and secret.strip():
        return secret
    env_value = os.environ.get(AUTHORITY_ARTIFACT_SECRET_ENV_VAR, "").strip()
    if env_value:
        return env_value
    return _DEFAULT_AUTHORITY_ARTIFACT_SECRET


def _coerce_artifact_payload(artifact: AuthorityArtifact | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(artifact, AuthorityArtifact):
        return artifact.to_dict()
    if isinstance(artifact, Mapping):
        return dict(artifact)
    raise ValueError("Authority artifact must be an AuthorityArtifact or dict-like payload.")


def _normalized_scope(raw_scope: Any) -> list[str]:
    if not isinstance(raw_scope, (list, tuple)):
        raise ValueError("Authority artifact capability_scope must be a list of strings.")

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_scope:
        if not isinstance(item, str):
            raise ValueError("Authority artifact capability_scope entries must be strings.")
        value = item.strip()
        if not value:
            raise ValueError("Authority artifact capability_scope entries must be non-empty.")
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    if not normalized:
        raise ValueError("Authority artifact capability_scope must be non-empty.")
    normalized.sort()
    return normalized


def _normalized_unsigned_payload(artifact: AuthorityArtifact | Mapping[str, Any]) -> dict[str, Any]:
    payload = _coerce_artifact_payload(artifact)

    missing_fields = [field_name for field_name in _REQUIRED_FIELDS if field_name not in payload]
    if missing_fields:
        raise ValueError(
            f"Authority artifact is missing required fields: {', '.join(sorted(missing_fields))}."
        )

    normalized: dict[str, Any] = {}
    for field_name in _STRING_FIELDS:
        value = payload.get(field_name)
        if not isinstance(value, str):
            raise ValueError(f"Authority artifact field {field_name!r} must be a string.")
        normalized[field_name] = value.strip()
        if not normalized[field_name]:
            raise ValueError(f"Authority artifact field {field_name!r} must be non-empty.")

    if normalized["artifact_version"] != AUTHORITY_ARTIFACT_VERSION_V1:
        raise ValueError(
            f"Unsupported authority artifact version {normalized['artifact_version']!r}."
        )

    for field_name in _OPTIONAL_STRING_FIELDS:
        value = payload.get(field_name, "")
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"Authority artifact field {field_name!r} must be a string.")
        normalized_value = value.strip()
        if normalized_value:
            normalized[field_name] = normalized_value

    normalized["capability_scope"] = _normalized_scope(payload.get("capability_scope"))
    return normalized


def canonicalize_authority_artifact(artifact: AuthorityArtifact | Mapping[str, Any]) -> str:
    """Return the canonical JSON form used for signing."""
    payload = _normalized_unsigned_payload(artifact)
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _signature_hex(
    artifact: AuthorityArtifact | Mapping[str, Any],
    *,
    secret: str,
) -> str:
    canonical = canonicalize_authority_artifact(artifact).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def sign_authority_artifact(
    artifact: AuthorityArtifact | Mapping[str, Any],
    secret: str | None = None,
) -> AuthorityArtifact:
    """Sign and return a normalized canonical authority artifact."""
    normalized = _normalized_unsigned_payload(artifact)
    secret_value = resolve_authority_artifact_secret(secret)
    signature = _signature_hex(normalized, secret=secret_value)
    return AuthorityArtifact(signature=signature, **normalized)


def verify_authority_artifact(
    artifact: AuthorityArtifact | Mapping[str, Any],
    secret: str | None = None,
) -> bool:
    """Verify a canonical authority artifact."""
    try:
        payload = _coerce_artifact_payload(artifact)
        signature = payload.get("signature")
        if not isinstance(signature, str) or not signature.strip():
            return False
        expected = _signature_hex(payload, secret=resolve_authority_artifact_secret(secret))
        return hmac.compare_digest(signature.strip(), expected)
    except Exception:
        return False
