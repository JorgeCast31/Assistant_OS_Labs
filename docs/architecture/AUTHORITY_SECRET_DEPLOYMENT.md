# Authority Artifact Secret — Deployment Guide

## Overview

`resolve_authority_artifact_secret()` is the single gateway for obtaining the
HMAC-SHA256 secret used to sign and verify all authority artifacts.  As of
Sprint `S-AUTHORITY-SECRET-HARDENING-01`, the function is **fail-closed**: it
raises `RuntimeError` if no secret is configured and the system is not
explicitly in development mode.  There is no silent fallback in production.

---

## Resolution order

| Priority | Condition | Result |
|----------|-----------|--------|
| 1 | `secret` argument is a non-empty string | Use the argument directly |
| 2 | `ASSISTANT_OS_AUTHORITY_ARTIFACT_SECRET` env var is set and non-empty | Use the env var value |
| 3 | `ASSISTANT_OS_DEV_MODE` env var equals exactly `"1"` | Use the dev-default key (with `UserWarning`) |
| 4 | None of the above | **`RuntimeError`** — fail closed |

---

## Production deployment

1. Generate a secret (minimum 32 bytes of entropy):
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Set the environment variable in your deployment environment (systemd unit,
   Docker secret, Kubernetes secret, etc.):
   ```
   ASSISTANT_OS_AUTHORITY_ARTIFACT_SECRET=<generated-value>
   ```

3. **Do not** set `ASSISTANT_OS_DEV_MODE` in production.  If it is set and
   `ASSISTANT_OS_AUTHORITY_ARTIFACT_SECRET` is absent, the system will still
   fall back to the dev default — but it will emit a `UserWarning` loud enough
   to be visible in any structured log aggregator.  Treat that warning as a
   misconfiguration alarm.

4. Rotate the secret by updating the env var and restarting the service.
   All authority artifacts signed under the old secret will fail verification
   immediately (HMAC is not backward-compatible on key rotation by design).

---

## Local development / CI

Set `ASSISTANT_OS_DEV_MODE=1` in your local `.env` (never commit it) or in
your CI environment variables.  Do **not** set
`ASSISTANT_OS_AUTHORITY_ARTIFACT_SECRET` in local dev unless you are
specifically testing production-secret paths.

The test suite sets `ASSISTANT_OS_DEV_MODE=1` automatically via
`tests/conftest.py` (`os.environ.setdefault`).  Individual tests that need to
exercise the production-hardened path use `monkeypatch.delenv()` to clear it
for the duration of that test.

---

## Security invariants

- **No silent forgery vector.** A misconfigured production deployment that
  omits `ASSISTANT_OS_AUTHORITY_ARTIFACT_SECRET` cannot silently accept
  artifacts signed with the dev key.  The process fails closed.
- **Strict dev-mode gate.** Only the exact string `"1"` enables dev mode.
  Values like `"true"`, `"yes"`, `"on"`, or `"True"` are rejected.
- **Constant-time comparison.** Verification uses `hmac.compare_digest` to
  prevent timing-based signature oracle attacks.

---

## Relevant code

| File | Symbol |
|------|--------|
| `assistant_os/authority/artifact.py` | `resolve_authority_artifact_secret()` |
| `assistant_os/authority/artifact.py` | `AUTHORITY_ARTIFACT_SECRET_ENV_VAR` |
| `assistant_os/authority/artifact.py` | `_AUTHORITY_ARTIFACT_DEV_MODE_ENV_VAR` |
| `tests/test_authority_artifact_secret_hardening.py` | Sprint acceptance tests |
| `tests/conftest.py` | Session-wide `ASSISTANT_OS_DEV_MODE=1` default |
| `.env.example` | Template with placeholder value |
