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
AUTHORITY_ARTIFACT_VERSION_V2 = "2"
AUTHORITY_ARTIFACT_SECRET_ENV_VAR = "ASSISTANT_OS_AUTHORITY_ARTIFACT_SECRET"
_AUTHORITY_ARTIFACT_DEV_MODE_ENV_VAR = "ASSISTANT_OS_DEV_MODE"
_DEFAULT_AUTHORITY_ARTIFACT_SECRET = "assistant_os.authority_artifact.dev_secret.v1"

# Valid authority source/class identifiers (V2).
AUTHORITY_SOURCE_MSO = "mso"
AUTHORITY_SOURCE_CODE_API = "code_api"
AUTHORITY_CLASS_SOVEREIGN = "sovereign"
AUTHORITY_CLASS_EXTERNAL_LOCAL = "external_local"

# Only these (source, class) combinations are valid.
_VALID_AUTHORITY_COMBOS: frozenset[tuple[str, str]] = frozenset({
    (AUTHORITY_SOURCE_MSO, AUTHORITY_CLASS_SOVEREIGN),
    (AUTHORITY_SOURCE_CODE_API, AUTHORITY_CLASS_EXTERNAL_LOCAL),
})

# Fields that must not start with the external_local sentinel for sovereign artifacts.
_SOVEREIGN_GOVERNANCE_FIELDS: tuple[str, ...] = (
    "policy_decision_ref",
    "governance_ref",
    "approval_id",
    "execution_mode",
)

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
    "authority_source",
    "authority_class",
)
_OPTIONAL_STRING_FIELDS: tuple[str, ...] = ("delegated_seat_ref",)
_REQUIRED_FIELDS: tuple[str, ...] = _STRING_FIELDS + ("capability_scope",)


@dataclass(frozen=True)
class AuthorityArtifact:
    """Canonical signed authority artifact (V2)."""

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
    authority_source: str
    authority_class: str
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
            "authority_source": self.authority_source,
            "authority_class": self.authority_class,
            "delegated_seat_ref": self.delegated_seat_ref,
            "signature": self.signature,
        }


def resolve_authority_artifact_secret(secret: str | None = None) -> str:
    """Resolve the authority artifact signing secret.

    Resolution order:
      1. Explicit ``secret`` argument (if non-empty string).
      2. ``ASSISTANT_OS_AUTHORITY_ARTIFACT_SECRET`` environment variable.
      3. Development default — only if ``ASSISTANT_OS_DEV_MODE=1`` is set.
      4. Otherwise: raise RuntimeError.  No silent fallback in production.

    Raises:
        RuntimeError: When no secret is configured and
            ``ASSISTANT_OS_DEV_MODE`` is not exactly ``"1"``.
    """
    if isinstance(secret, str) and secret.strip():
        return secret
    env_value = os.environ.get(AUTHORITY_ARTIFACT_SECRET_ENV_VAR, "").strip()
    if env_value:
        return env_value
    if os.environ.get(_AUTHORITY_ARTIFACT_DEV_MODE_ENV_VAR, "").strip() == "1":
        import warnings
        warnings.warn(
            f"[AUTHORITY] Using development artifact secret. "
            f"Set {AUTHORITY_ARTIFACT_SECRET_ENV_VAR} for production deployments.",
            stacklevel=3,
        )
        return _DEFAULT_AUTHORITY_ARTIFACT_SECRET
    raise RuntimeError(
        f"Authority artifact secret is not configured and "
        f"{_AUTHORITY_ARTIFACT_DEV_MODE_ENV_VAR} is not set to '1'. "
        f"Set the {AUTHORITY_ARTIFACT_SECRET_ENV_VAR} environment variable "
        f"before signing or verifying authority artifacts. "
        f"For local development only, set {_AUTHORITY_ARTIFACT_DEV_MODE_ENV_VAR}=1."
    )


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

    if normalized["artifact_version"] != AUTHORITY_ARTIFACT_VERSION_V2:
        raise ValueError(
            f"Unsupported authority artifact version {normalized['artifact_version']!r}. "
            f"Expected V2 ({AUTHORITY_ARTIFACT_VERSION_V2!r})."
        )

    source = normalized["authority_source"]
    cls = normalized["authority_class"]
    if (source, cls) not in _VALID_AUTHORITY_COMBOS:
        raise ValueError(
            f"Invalid authority combination: authority_source={source!r}, "
            f"authority_class={cls!r}. "
            f"Valid combinations: {sorted(_VALID_AUTHORITY_COMBOS)}."
        )

    if cls == AUTHORITY_CLASS_SOVEREIGN:
        for gov_field in _SOVEREIGN_GOVERNANCE_FIELDS:
            val = normalized.get(gov_field, "")
            if val.startswith("external_local"):
                raise ValueError(
                    f"Sovereign artifact field {gov_field!r} must not use the "
                    f"external_local sentinel. Got: {val!r}."
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
