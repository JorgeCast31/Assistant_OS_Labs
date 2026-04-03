"""
SecretInjector — secret delivery service for AssistantOS.

Responsibilities
----------------
1. Resolve SecretRefs to SecretHandles (via SecretBackend).
2. Build an EnvBundle from a list of SecretRefs for one execution.
3. Provision an ephemeral env file from a bundle (for --env-file Docker flag).
4. Destroy the env file and invalidate the bundle after execution.

What SecretInjector does NOT do
--------------------------------
- Does not decide policy (policy is in AuthorizedPlan / ArtifactPolicy).
- Does not move into the Kernel.
- Does not hand raw secret strings through normal payload fields.
- Does not persist secret values to workspace, artifacts, DB, or logs.

Redaction discipline
--------------------
- provision_env_file() writes to a tempfile in the OS temp dir — NOT workspace.
- The temp file is deleted unconditionally in cleanup_provision() / finally blocks.
- SecretHandle.__value is name-mangled and wiped on invalidate().
- No secret value ever appears in SecretResolutionError messages.

Ephemeral env file format
--------------------------
Standard Docker --env-file format:
    NAME=VALUE
    NAME2=VALUE2
Newlines within values are escaped to \\n.
"""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from typing import Optional

from .backend import SecretBackend, SecretNotFoundError
from .secret_ref import EnvBundle, SecretHandle, SecretRef

# Default handle TTL.  Short-lived by design — must survive one execution only.
_DEFAULT_TTL_SECONDS: float = 300.0  # 5 minutes


class SecretResolutionError(Exception):
    """
    Raised when SecretInjector cannot resolve a secret or validate context.

    Message must NEVER include a secret value.
    """


class SecretInjector:
    """
    Secret delivery service.

    Parameters
    ----------
    backend     : SecretBackend to use for resolving ref_tokens.
    ttl_seconds : TTL for issued handles and bundles (seconds).
    """

    def __init__(
        self,
        backend: SecretBackend,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._backend = backend
        self._ttl = ttl_seconds

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(
        self,
        secret_ref: SecretRef,
        plan_id: str,
        execution_id: str = "",
    ) -> SecretHandle:
        """
        Resolve a SecretRef to a SecretHandle.

        Parameters
        ----------
        secret_ref   : The opaque reference to resolve.
        plan_id      : Plan that authorized the resolution — must be non-empty.
        execution_id : Execution being served (optional at resolve time).

        Returns
        -------
        SecretHandle with the value set internally.

        Raises
        ------
        SecretResolutionError — missing context, unavailable secret (if required).
        """
        if not plan_id or not plan_id.strip():
            raise SecretResolutionError(
                "plan_id is required for secret resolution — "
                "resolution without authorization context is not allowed"
            )

        try:
            raw_value = self._backend.resolve_ref(secret_ref.ref_token)
        except SecretNotFoundError as exc:
            if secret_ref.required:
                # Do NOT include the ref_token value in the message if it could
                # contain sensitive path information.  The name is safe.
                raise SecretResolutionError(
                    f"Required secret {secret_ref.name!r} could not be resolved: {exc}"
                ) from exc
            # Not required — return an already-invalidated handle (empty value).
            return self._make_handle(
                secret_ref=secret_ref,
                plan_id=plan_id,
                execution_id=execution_id,
                value="",
                pre_invalidate=True,
            )
        except ValueError as exc:
            raise SecretResolutionError(
                f"Invalid ref_token for secret {secret_ref.name!r}: {exc}"
            ) from exc

        return self._make_handle(
            secret_ref=secret_ref,
            plan_id=plan_id,
            execution_id=execution_id,
            value=raw_value,
        )

    def build_env_bundle(
        self,
        secret_refs: list[SecretRef],
        plan_id: str,
        execution_id: str,
    ) -> EnvBundle:
        """
        Resolve all SecretRefs and package handles into an EnvBundle.

        Parameters
        ----------
        secret_refs  : list of SecretRefs the execution declared.
        plan_id      : authorizing plan ID.
        execution_id : execution ID being served.

        Returns
        -------
        EnvBundle with all handles resolved and value-loaded.

        Raises
        ------
        SecretResolutionError — if any required ref cannot be resolved.
        """
        if not execution_id or not execution_id.strip():
            raise SecretResolutionError(
                "execution_id is required for build_env_bundle — "
                "bundle scope cannot be established without it"
            )

        now = time.time()
        handles: list[SecretHandle] = []
        for ref in secret_refs:
            handle = self.resolve(ref, plan_id=plan_id, execution_id=execution_id)
            handles.append(handle)

        return EnvBundle(
            bundle_id=f"bnd-{uuid.uuid4().hex[:16]}",
            execution_id=execution_id,
            plan_id=plan_id,
            handles=handles,
            issued_at=now,
            expires_at=now + self._ttl,
        )

    # ------------------------------------------------------------------
    # Provisioning
    # ------------------------------------------------------------------

    def provision_env_file(self, bundle: EnvBundle) -> str:
        """
        Materialize the bundle's secrets into an ephemeral Docker env file.

        The file is written to the OS temp directory — NOT to any workspace
        or artifact path.  The caller MUST call cleanup_provision() in a
        finally block to delete the file and invalidate the bundle.

        File format: Docker --env-file (NAME=VALUE, one per line).

        Parameters
        ----------
        bundle : An active EnvBundle from build_env_bundle().

        Returns
        -------
        str — absolute path to the temp env file.

        Raises
        ------
        SecretResolutionError — if bundle is invalid or expired.
        """
        if not bundle.is_valid():
            raise SecretResolutionError(
                f"EnvBundle {bundle.bundle_id!r} is invalid or expired — "
                "cannot provision env file"
            )

        lines: list[str] = []
        for handle in bundle.handles:
            if not handle.is_valid():
                continue
            # Consume value — this is the single moment the raw value is accessed.
            value = handle._consume_value()
            # Escape embedded newlines so Docker env-file parsing stays correct.
            safe_value = value.replace("\n", "\\n")
            lines.append(f"{handle.name}={safe_value}\n")

        # Write to temp file in OS temp dir, not workspace.
        # mode=0o600 → readable only by the current user.
        fd, path = tempfile.mkstemp(prefix="aos-run-", suffix=".env")
        try:
            os.chmod(path, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fobj:
                fobj.writelines(lines)
        except Exception:
            # Clean up the fd/file if writing failed.
            try:
                os.unlink(path)
            except OSError:
                pass
            raise

        return path

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_provision(self, env_file_path: str, bundle: EnvBundle) -> None:
        """
        Delete the ephemeral env file and invalidate the bundle.

        Must be called in a finally block after container execution, even if
        execution failed or raised.  Never raises itself.

        Parameters
        ----------
        env_file_path : path returned by provision_env_file().
        bundle        : the bundle that was provisioned.
        """
        # Delete env file first so the window where it exists is minimised.
        _safe_unlink(env_file_path)
        bundle.invalidate()

    def cleanup(self, bundle: EnvBundle) -> None:
        """
        Invalidate a bundle when no env file was provisioned.

        Use this when build_env_bundle was called but provision_env_file
        was not (e.g. in stub mode).
        """
        bundle.invalidate()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_handle(
        self,
        secret_ref: SecretRef,
        plan_id: str,
        execution_id: str,
        value: str,
        pre_invalidate: bool = False,
    ) -> SecretHandle:
        now = time.time()
        handle = SecretHandle(
            handle_id=f"hdl-{uuid.uuid4().hex[:16]}",
            ref_token=secret_ref.ref_token,
            name=secret_ref.name,
            plan_id=plan_id,
            execution_id=execution_id,
            domain=secret_ref.domain,
            issued_at=now,
            expires_at=now + self._ttl,
        )
        handle._set_value(value)
        if pre_invalidate:
            handle.invalidate()
        return handle


# ---------------------------------------------------------------------------
# Module-level utility
# ---------------------------------------------------------------------------


def _safe_unlink(path: str) -> None:
    """Delete a file.  Never raises."""
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass
