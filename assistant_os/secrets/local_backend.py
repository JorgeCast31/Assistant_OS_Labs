"""
LocalEnvBackend — local-process secret backend for AssistantOS v0.

This is NOT a production secret store.
It is the initial backend implementation that allows the rest of the system
to use the SecretBackend abstraction without yet integrating Vault or a
cloud secret manager.

Supported ref_token protocols
------------------------------
    "env:<VAR_NAME>"   — resolve from the process environment (os.environ).
                         Example: "env:ANTHROPIC_API_KEY"

    "mem:<KEY>"        — resolve from an in-memory dict passed at construction.
                         Used in tests and for secrets that are already in memory
                         (e.g. decrypted at startup from a local keyfile).
                         Example: "mem:test_api_key"

Security properties (v0)
-------------------------
- Values come from the process environment or an injected in-memory store —
  no network calls, no disk I/O.
- The backend never logs or prints values.
- Callers (SecretInjector only) are responsible for erasing values after use.

Limitations
-----------
- Reads from os.environ at resolve_ref() call time — no caching.
- In-memory store is not encrypted in process memory.
- No rotation, no versioning, no audit trail of reads.
  (All of these are deferred to the next backend implementation.)
"""

from __future__ import annotations

import os
from typing import Optional

from .backend import SecretBackend, SecretNotFoundError

# Recognised ref_token protocol prefixes.
_PROTOCOL_ENV = "env:"
_PROTOCOL_MEM = "mem:"


class LocalEnvBackend(SecretBackend):
    """
    Backend that resolves secrets from the process environment or an
    injected in-memory store.

    Parameters
    ----------
    memory_store : optional dict mapping key → value for "mem:<KEY>" tokens.
                   Useful in tests to inject secrets without touching os.environ.
    """

    def __init__(
        self,
        memory_store: Optional[dict[str, str]] = None,
    ) -> None:
        # Defensive copy so callers cannot mutate the store after construction.
        self._memory: dict[str, str] = dict(memory_store) if memory_store else {}

    def resolve_ref(self, ref_token: str) -> str:
        """
        Resolve ref_token to its raw string value.

        Raises SecretNotFoundError if the referenced var/key is absent.
        Raises ValueError for unrecognised protocol prefixes.
        """
        if ref_token.startswith(_PROTOCOL_ENV):
            var_name = ref_token[len(_PROTOCOL_ENV):]
            if not var_name:
                raise ValueError(
                    f"Empty env var name in ref_token: {ref_token!r}"
                )
            value = os.environ.get(var_name)
            if value is None:
                raise SecretNotFoundError(
                    f"Environment variable {var_name!r} is not set"
                )
            return value

        if ref_token.startswith(_PROTOCOL_MEM):
            key = ref_token[len(_PROTOCOL_MEM):]
            if not key:
                raise ValueError(
                    f"Empty mem key in ref_token: {ref_token!r}"
                )
            if key not in self._memory:
                raise SecretNotFoundError(
                    f"Memory store key {key!r} not found"
                )
            return self._memory[key]

        raise ValueError(
            f"Unrecognised ref_token protocol: {ref_token!r}. "
            f"Supported: {_PROTOCOL_ENV!r}, {_PROTOCOL_MEM!r}"
        )

    def is_available(self, ref_token: str) -> bool:
        """Return True if resolve_ref would succeed; never raises."""
        try:
            self.resolve_ref(ref_token)
            return True
        except (SecretNotFoundError, ValueError):
            return False
