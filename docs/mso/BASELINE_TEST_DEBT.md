# Baseline Test Debt

> Documented as part of S-MISSION-CONTROL-TRUTH-CONTRACTS-ALPHA-01.
> Last verified: 2026-05-26

## Pre-existing failures (do not fix in this sprint)

The following failures are pre-existing and pre-date this sprint. They are not
regression blockers for the Mission Control truth contracts work.

| Test | File | Status |
|---|---|---|
| `test_runtime_delegates_cognitive_request_and_persists_artifacts` | `tests/test_mso_runtime.py` | pre-existing |
| `test_runtime_diagnostics_surface_reports_recent_cognitive_activity` | `tests/test_mso_runtime.py` | pre-existing |

## Observed baseline — actual test suite state (2026-05-26)

After fixing the Windows `UnicodeDecodeError` collection failure (via `PYTHONUTF8=1`),
the full suite reveals a **variable baseline** of pre-existing failures. The failure
count varies between runs due to environment-dependent tests and shared state.

Observed failure range across multiple local runs on Windows (Python 3.11, `PYTHONUTF8=1`):

- **Minimum observed**: 7 failures
- **Maximum observed**: 21 failures

The failures span multiple test files including:
- `tests/test_mso_runtime.py` (3 consistent failures)
- `tests/test_operator_admin_api.py`
- `tests/test_mso_restrictions.py`
- `tests/test_token_rotation.py`
- `tests/test_cognitive_worker_runner.py`
- `tests/test_admin_api_auth.py`
- `tests/test_s02_admin_token_hardening.py`
- `tests/test_sprint_alfa.py`
- and others

These failures are all pre-existing and unrelated to this sprint's scope.

## Note on sprint plan expectation

The sprint plan expected "exactly 2 failures" after the encoding fix. The actual
baseline is larger. This discrepancy is recorded here for traceability. The 2
specifically-named failures do appear consistently in every run.
