> [!WARNING]
> **Historical / Frozen Contract Reference**
> This document belongs to a frozen/historical contract set. It is useful for traceability, but it may not reflect current runtime behavior.
> Current implementation source of truth must be verified in code before use.

<!-- agent:do-not-treat-as-source-of-truth -->

---

# Kill-Switch Assumption (Line F)

- Kill-switch enforcement is delegated to SovereignStateStore.
- Backend OpenClaw executes sovereign enforcement before runtime dispatch.
- If SovereignStateStore returns blocked, runtime execution is not permitted.
- Current kill-switch semantics are provisional and remain subject to finalization in Line D.
