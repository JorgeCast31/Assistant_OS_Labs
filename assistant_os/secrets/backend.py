"""
SecretBackend — abstract interface for secret resolution backends.

Abstraction
-----------
The rest of the system depends on this interface, not on any concrete
backend (os.environ, Vault, cloud secrets manager, etc.).  The initial
backend is LocalEnvBackend; future backends slot in without touching
SecretInjector or the Runner.

Interface
---------
    resolve_ref(ref_token)  — resolve a ref_token to its raw string value
    is_available(ref_token) — probe availability without raising

Only SecretInjector calls these methods.  No other component should
depend on SecretBackend directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SecretNotFoundError(Exception):
    """Raised when a ref_token cannot be resolved by the backend."""


class SecretBackend(ABC):
    """Abstract interface for secret resolution backends."""

    @abstractmethod
    def resolve_ref(self, ref_token: str) -> str:
        """
        Resolve a ref_token to its raw string value.

        Parameters
        ----------
        ref_token : opaque backend reference (e.g. "env:ANTHROPIC_API_KEY").

        Returns
        -------
        str — the secret value.

        Raises
        ------
        SecretNotFoundError — if the ref cannot be resolved.
        ValueError          — if the ref_token format is unrecognised.
        """
        ...

    @abstractmethod
    def is_available(self, ref_token: str) -> bool:
        """
        Return True if resolve_ref(ref_token) would succeed.

        Never raises — availability check only.
        """
        ...
