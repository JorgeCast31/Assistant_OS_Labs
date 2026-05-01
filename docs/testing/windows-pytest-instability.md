# Windows Local Pytest Instability and Admin Token Audit Notes

## Scope

This note records local Windows test behavior and an admin token audit endpoint clarification.

It documents investigation findings only. It is not a product behavior change, not a test or pytest configuration change, and not a CI failure report.

## Symptoms Observed

On a local Windows environment, a full pytest run sometimes crashed with:

```text
Windows fatal exception: access violation
```

The crash appeared during pytest traceback or report generation. The apparent nearby test was:

```text
tests/test_sprint_a1_5_hardening.py::TestNoSyntheticIdentity::test_2a_no_synthetic_subject_state_active_in_policy_context
```

The full-suite behavior was intermittent. Later runs also showed an intermittent admin token audit signal around:

```text
tests/test_admin_api_auth.py::TestAdminApiAuth::test_admin_can_audit_tokens_without_leaking_raw_secret
```

The originally reported admin signal was HTTP 401. That was not reproduced during the follow-up investigation. A later transient local signal returned HTTP 200 but had `data["count"] == 1` instead of the expected `>= 2`.

## What Was Verified

The suspicious sprint hardening test passed when run alone.

The full suspicious file passed:

```text
tests/test_sprint_a1_5_hardening.py
15 passed
```

A large targeted subset later passed:

```text
702 passed, 14 skipped, 87 subtests passed
```

The full suite later passed:

```text
4057 passed, 14 skipped
```

The investigation did not establish a deterministic failing test, a deterministic file range, or a confirmed product regression. CI/main remained green where applicable during this investigation.

## Admin Endpoint Clarification

`/admin/tokens` belongs to:

```text
assistant_os.control_plane.admin_server
```

It does not hit:

```text
assistant_os.webhook_server
```

The control plane `/admin/tokens` endpoint expects:

```text
Authorization: Bearer <operator-token>
```

The bearer token must authenticate to an operator context with admin role.

The endpoint does not use these webhook headers:

```text
X-Assistant-Token
X-Assistant-Admin-Token
```

Those headers belong to webhook, schema, and governance paths. Do not "fix" `/admin/tokens` by adding `X-Assistant-Token` or `X-Assistant-Admin-Token` to this control plane test unless the control plane contract is intentionally changed and covered by tests.

## Current Diagnosis

The Windows access violation is currently diagnosed as non-reproducible local environment instability, likely involving Windows, pytest, traceback or report generation, ordering, or environment-specific behavior.

The admin token audit signal is also not confirmed as a production regression. The observed `data["count"]` mismatch may involve shared state, audit/token fixture order, or local run contamination. No confirmed auth contract bug was found.

No production fix was applied because changing production code or tests based on the transient signal would be speculative.

## What Not To Do

Do not weaken authentication.

Do not change the `/admin/tokens` contract to use webhook headers.

Do not skip or xfail tests without a reproducible failure.

Do not patch production based only on the transient HTTP 401 report.

Do not mark CI green as invalid because one local Windows full-suite run crashed.

Do not treat `X-Assistant-Token` or `X-Assistant-Admin-Token` as required headers for `assistant_os.control_plane.admin_server` unless code and tests prove a deliberate contract change.

## Recommended Diagnostics If It Recurs

Start by checking collection and the isolated suspect tests:

```bash
python -m pytest --collect-only -q
python -m pytest tests/test_admin_api_auth.py -q
python -m pytest tests/test_admin_api_auth.py::TestAdminApiAuth::test_admin_can_audit_tokens_without_leaking_raw_secret -vv
python -m pytest tests/test_sprint_a1_5_hardening.py -vv
python -m pytest -x -vv --tb=short
```

If a crash or failure recurs, record the last printed test and run narrowed file groups around that point. Prefer serial runs. Avoid parallel full-suite runs because shared filesystem or runtime state can contaminate diagnostics.

Useful narrowed follow-ups include:

```bash
python -m pytest tests/test_admin_api_auth.py::TestAdminApiAuth::test_admin_can_audit_tokens_without_leaking_raw_secret -vv --tb=short
python -m pytest tests/test_admin_api_auth.py -q
python -m pytest tests/test_sprint_a1_5_hardening.py -vv --tb=short
```

## Escalation Criteria

Open a real fix sprint only if at least one of these is true:

- The same failure reproduces twice in a row.
- CI fails.
- The isolated suspicious test fails.
- The admin token count mismatch is reproducible.
- An auth contract mismatch is proven by code and tests.

## Status

- Documented.
- No code change.
- No test change.
- No pytest configuration change.
- No authentication behavior change.
