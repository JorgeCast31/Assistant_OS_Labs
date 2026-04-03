"""
Secret contracts — SecretRef, SecretHandle, EnvBundle.

These types embody the architectural model:
  SecretRef    = opaque reference, not value
  SecretHandle = scoped, ephemeral handle, not value
  EnvBundle    = execution-scoped provisioning bundle, not values

Redaction discipline
--------------------
- SecretHandle stores the secret value under a name-mangled private attribute
  (_SecretHandle__value).  It is never exposed by __repr__, __str__,
  to_audit_dict(), or any serialization method.
- EnvBundle carries handles but never materializes their values into normal
  Python dicts or log-friendly representations.
- to_audit_dict() methods on all three types are safe to write to logs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# SecretRef — opaque reference, no value
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecretRef:
    """
    An opaque reference to a secret that an execution may need.

    SecretRef does NOT contain the secret value.  It is safe to include
    in plans, proposals, and control-plane payloads.

    Fields
    ------
    name      : env var name that will be injected into the container
                (e.g. "API_KEY" → available as os.environ["API_KEY"]).
    ref_token : opaque backend token that the SecretBackend uses to locate
                the secret (e.g. "env:ANTHROPIC_API_KEY", "mem:test_key").
    domain    : domain scope that authorized this reference
                (e.g. "code", "fin", "*").
    required  : if True, execution fails when the secret cannot be resolved.
    """

    name: str
    ref_token: str
    domain: str
    required: bool = True

    def to_dict(self) -> dict:
        """Safe to log — contains no secret value."""
        return {
            "name": self.name,
            "ref_token": self.ref_token,
            "domain": self.domain,
            "required": self.required,
        }


# ---------------------------------------------------------------------------
# SecretHandle — scoped ephemeral handle, value is pseudo-private
# ---------------------------------------------------------------------------


class SecretHandle:
    """
    A scoped, ephemeral handle for a resolved secret.

    The secret value is stored under the name-mangled attribute
    _SecretHandle__value so that naive attribute enumeration and
    repr printing do not expose it.  Value access is intentionally
    limited to SecretInjector internals via _set_value() and _consume_value().

    NEVER call _consume_value() outside of SecretInjector.provision_env_file().
    """

    __slots__ = (
        "handle_id",
        "ref_token",
        "name",
        "plan_id",
        "execution_id",
        "domain",
        "issued_at",
        "expires_at",
        "invalidated",
        "_SecretHandle__value",  # explicit slot for name-mangled attribute
    )

    def __init__(
        self,
        handle_id: str,
        ref_token: str,
        name: str,
        plan_id: str,
        execution_id: str,
        domain: str,
        issued_at: float,
        expires_at: float,
    ) -> None:
        self.handle_id = handle_id
        self.ref_token = ref_token
        self.name = name
        self.plan_id = plan_id
        self.execution_id = execution_id
        self.domain = domain
        self.issued_at = issued_at
        self.expires_at = expires_at
        self.invalidated = False
        self.__value: str = ""  # name-mangled: _SecretHandle__value

    # ------------------------------------------------------------------
    # Value access — restricted to injector internals
    # ------------------------------------------------------------------

    def _set_value(self, value: str) -> None:
        """Called once by SecretInjector after resolving from backend."""
        if self.invalidated:
            raise RuntimeError(
                f"Cannot set value on invalidated handle {self.handle_id!r}"
            )
        self.__value = value

    def _consume_value(self) -> str:
        """
        Return the secret value.

        ONLY call this inside SecretInjector.provision_env_file().
        Raises RuntimeError if handle is invalid or expired.
        """
        if not self.is_valid():
            raise RuntimeError(
                f"Cannot consume value from invalid/expired handle {self.handle_id!r}"
            )
        return self.__value

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def is_valid(self) -> bool:
        """True iff handle is not invalidated and has not expired."""
        return not self.invalidated and time.time() < self.expires_at

    def invalidate(self) -> None:
        """Wipe the value and mark the handle as consumed/expired."""
        self.__value = ""
        self.invalidated = True

    # ------------------------------------------------------------------
    # Repr / serialization — never expose value
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"SecretHandle(handle_id={self.handle_id!r}, "
            f"name={self.name!r}, "
            f"domain={self.domain!r}, "
            f"valid={self.is_valid()}, "
            f"[VALUE REDACTED])"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def to_audit_dict(self) -> dict:
        """
        Safe for audit logs and metadata.  Never includes the secret value.
        """
        return {
            "handle_id": self.handle_id,
            "ref_token": self.ref_token,   # opaque ref — safe
            "name": self.name,
            "plan_id": self.plan_id,
            "execution_id": self.execution_id,
            "domain": self.domain,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "invalidated": self.invalidated,
            # value: NEVER included
        }


# ---------------------------------------------------------------------------
# EnvBundle — execution-scoped provisioning bundle
# ---------------------------------------------------------------------------


class EnvBundle:
    """
    A collection of SecretHandles bound to a specific execution.

    EnvBundle is created by SecretInjector just before container launch and
    invalidated immediately after — in the same finally block that destroys
    the ephemeral env file.

    NEVER serialize the handles' values.  to_audit_dict() is always safe.
    """

    __slots__ = (
        "bundle_id",
        "execution_id",
        "plan_id",
        "handles",
        "issued_at",
        "expires_at",
        "invalidated",
    )

    def __init__(
        self,
        bundle_id: str,
        execution_id: str,
        plan_id: str,
        handles: list,
        issued_at: float,
        expires_at: float,
    ) -> None:
        self.bundle_id = bundle_id
        self.execution_id = execution_id
        self.plan_id = plan_id
        self.handles: list[SecretHandle] = handles
        self.issued_at = issued_at
        self.expires_at = expires_at
        self.invalidated = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def is_valid(self) -> bool:
        """True iff bundle is not invalidated and has not expired."""
        return not self.invalidated and time.time() < self.expires_at

    def invalidate(self) -> None:
        """Cascade invalidation to all handles, then mark bundle as consumed."""
        for handle in self.handles:
            handle.invalidate()
        self.invalidated = True

    # ------------------------------------------------------------------
    # Repr / serialization — never expose values
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"EnvBundle(bundle_id={self.bundle_id!r}, "
            f"execution_id={self.execution_id!r}, "
            f"plan_id={self.plan_id!r}, "
            f"secrets={len(self.handles)}, "
            f"[VALUES REDACTED])"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def to_audit_dict(self) -> dict:
        """
        Safe for audit logs and ExecutionMetadata.  Never includes secret values.
        """
        return {
            "bundle_id": self.bundle_id,
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "secret_count": len(self.handles),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "invalidated": self.invalidated,
            "handles": [h.to_audit_dict() for h in self.handles],
            # values: NEVER included
        }
