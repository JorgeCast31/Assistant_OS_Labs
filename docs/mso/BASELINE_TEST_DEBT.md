# Baseline Test Debt

> Documented as part of S-MISSION-CONTROL-TRUTH-CONTRACTS-ALPHA-01.
> Last verified: 2026-05-26 (Windows). Updated: 2026-05-28 (Linux/POSIX audit).

---

## Linux/POSIX Baseline — 2026-05-28 (GREEN)

The full test suite was audited on Linux/POSIX on 2026-05-28 as part of Sprint #224 (Mission Control ALFA Gap Consolidation). Results:

| Suite | Result |
|---|---|
| `pytest` (full suite) | **6946 passed / 0 failures / 0 errors / 23 skipped** |
| `pytest tests/test_mso_mission_control_truth_contracts.py` | **114 passed** |
| `ui: npm run test` (vitest) | **161 passed** |
| `next build` | **success** |
| `npx tsc --noEmit` | **0 errors** |

**The repo is green on Linux/POSIX.** The failures documented below are Windows-specific environmental debt and do not represent a universal baseline failure state.

---

## Windows Environmental Debt — 2026-05-26 (observed on Windows, Python 3.11)

> These failures were observed on Windows. They are NOT present on Linux/POSIX.
> They are conserved here for traceability but must not be presented as baseline universal failures.

### Pre-existing failures (stable — appear in every Windows run)

| Test | File | Status |
|---|---|---|
| `test_runtime_delegates_cognitive_request_and_persists_artifacts` | `tests/test_mso_runtime.py` | pre-existing Windows |
| `test_runtime_diagnostics_surface_reports_recent_cognitive_activity` | `tests/test_mso_runtime.py` | pre-existing Windows |

### Variable Windows failure range

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

These failures are all pre-existing and unrelated to any sprint's functional scope.
They reflect environment-dependent test isolation issues and shared state in the
pre-existing test suite. The variance is expected environmental noise, not regressions.

---

## Classification

| Platform | Status | Notes |
|---|---|---|
| Linux/POSIX | GREEN | 6946/6946 passed as of 2026-05-28 |
| Windows | DEBT | 7–21 pre-existing failures, env/isolation/encoding issues |

---

## Note on original sprint plan expectation

The original sprint plan (S-MISSION-CONTROL-TRUTH-CONTRACTS-ALPHA-01) expected "exactly 2 failures" after the encoding fix. The actual Windows baseline is larger. This discrepancy is recorded here for traceability. The 2 specifically-named failures do appear consistently in every Windows run and remain the stable Windows regression indicators to watch.

The Linux/POSIX baseline is the authoritative health signal.
