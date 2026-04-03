"""
secrets — SecretInjector subsystem for AssistantOS.

This package implements the secret delivery contract:

    SecretRef → SecretHandle → EnvBundle

No secret value crosses a component boundary as a normal payload field.
The injector materializes values exactly once, just before container launch,
into an ephemeral env file that is destroyed in the same finally-block.

Public surface
--------------
    from assistant_os.secrets.secret_ref import SecretRef, SecretHandle, EnvBundle
    from assistant_os.secrets.backend import SecretBackend, SecretNotFoundError
    from assistant_os.secrets.local_backend import LocalEnvBackend
    from assistant_os.secrets.injector import SecretInjector, SecretResolutionError

Architectural invariants (closed decisions — do not reopen)
-----------------------------------------------------------
1.  SecretRef  = opaque reference. No value.
2.  SecretHandle = scoped ephemeral handle. Value is name-mangled (pseudo-private).
3.  EnvBundle = execution-scoped provisioning bundle. Values never serialized.
4.  SecretInjector resolves and provisions. It does not decide policy.
5.  to_dict() / to_audit_dict() / __repr__ on any secret type never expose values.
6.  Kernel does not resolve secrets.
7.  OpenClaw never sees secrets.
8.  ToolResult / DomainResult / transport payloads / audit logs: no secret values.
"""
