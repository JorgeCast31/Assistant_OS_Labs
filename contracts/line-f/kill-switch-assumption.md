# Kill-Switch Assumption (Line F)

- Kill-switch enforcement is delegated to SovereignStateStore.
- Backend OpenClaw executes sovereign enforcement before runtime dispatch.
- If SovereignStateStore returns blocked, runtime execution is not permitted.
- Current kill-switch semantics are provisional and remain subject to finalization in Line D.
