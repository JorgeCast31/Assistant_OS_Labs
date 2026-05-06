# Truthfulness Observability Gap Report

## 1. Executive Summary

This document serves as an architectural blueprint outlining the current state and known gaps in the system's operational truthfulness observability. The goal is to standardize how the system reports technical readiness across all domains without interfering with sovereign policy execution authority.

## 2. Current Coverage

The system successfully enforces several passive surface contracts, primarily observed in the UI:
- UI components strictly avoid fabricating "healthy" states when backends are "unknown" or "unavailable".
- MSO State (local) is never misrepresented as authoritative backend truth (no fabricated "MSO ACTIVE").
- Proxy endpoints (`/api/code/readiness`, `/api/mso/governance/status`) are securely implemented as GET-only, utilizing server-side tokens and avoiding client-side exposure.
- `PolicyDecision.execution_mode` is isolated and remains pure; technical observability errors (e.g., "connection refused") are successfully kept out of governance audit reasons.

## 3. Known Gaps

Despite the strong UI contracts, the backend currently exhibits the following gaps:

- **Fragmented Readiness Shapes:** Different operational domains (CODE, FIN, HOST) do not share a consistent response shape, hindering standardized UI rendering.
- **Configured vs. Healthy Confusion:** The system may report a component (like `machine_operator`) as "active" or "healthy" simply because it is configured, even if no live probe has verified it is reachable.
- **Centralized Truthfulness Gate Not Implemented:** Truthfulness gating logic is currently fragmented across multiple modules, lacking a unified middleware mechanism to evaluate intent readiness before execution.
- **Missing `audit.truthfulness` Metadata:** Technical failure signals are not consistently propagated to the observational metadata `audit["truthfulness"]`.
- **Outcome Endpoint Observability Gap:** As noted in the Sovereign Observability Checkpoint, the Outcome HTTP endpoint and corresponding UI panel are not yet available.

## 4. Target Readiness Vocabulary & Shape

To resolve the fragmented readiness shapes, the backend must adopt the following standardized JSON structure for all domain readiness probes:

```json
{
  "domain": "CODE",
  "status": "unavailable",
  "last_check": "2026-05-06T00:00:00Z",
  "error": "connection refused"
}
```

### Standardized Status Vocabulary
The `status` field must strictly differentiate between capability states:
- **`configured`**: The feature exists in the registry but has not been verified. (Does NOT imply healthy).
- **`reachable`**: The transport/network path is open, but the service health is unverified.
- **`healthy`**: The service responded positively to a health probe.
- **`operational`**: The service is fully healthy and ready for active execution.
- **`unavailable`**: The service is known to be down or failing probes.
- **`unknown`**: The system cannot determine the status.
- **`stub`**: The service is running in a mock/bypass mode.

## 5. Explicit Authority Rule

**Truthfulness signals do not grant authority and must not mutate `PolicyDecision.execution_mode`.**

Technical observability is strictly passive. If an execution fails a truthfulness check (e.g., status is `unavailable`), the orchestrator must block the action and report the failure in the `audit` metadata. It must *never* alter the MSO's sovereign execution decision.

## 6. Future Implementation Strategy

The future implementation sprint must address the gaps by:
1. Creating a centralized `assistant_os/middleware/truthfulness.py` (or equivalent) to handle all operational gating.
2. Refactoring `assistant_os/codeops/readiness.py` and other domains to return the target readiness shape.
3. Ensuring `assistant_os/surface_behavior.py` and other UI-adjacent layers correctly apply the standardized status vocabulary (never conflating "configured" with "healthy").
4. Piping the truthfulness payload into the system's `audit.truthfulness` metadata on every request.

## 7. Executable Debt Markers

The tests located in `tests/test_unified_truthfulness_observability.py` contain `@pytest.mark.xfail` markers that perfectly capture these gaps. These tests serve as executable debt markers. The ultimate goal of the implementation sprint is to safely remove these `xfail` markers, turning them into standard passing assertions, thus proving the gaps are closed.
