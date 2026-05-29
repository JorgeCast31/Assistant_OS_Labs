# Mission Control ALFA Gap Consolidation

> Sprint #224 — 2026-05-28
> Principle: MSO is the only source of executable authority.
> Truth before power. Order before speed. MSO before execution.

---

## 1. Estado actual

| Area | Status |
|---|---|
| Repo health (Linux/POSIX) | GREEN — 6946 passed / 0 failures |
| Mission Control truth contracts | 114 passed |
| UI vitest | 161 passed |
| next build | success |
| tsc --noEmit | 0 errors |
| Windows baseline | DEBT — 7–21 pre-existing env failures (see BASELINE_TEST_DEBT.md) |
| Mission Control mode | **Read-model observational** — no execution path |
| Backend truth contracts | Present and passing — webhook_server, mission_control_status, authority_trace |
| Planner | **Local/informal** — no formal Planner object, no POST /plans |
| Prepare contract | **Does not exist** — no POST /prepare, no prepare-only governed contract |
| Authority trace | **Snapshot mode** — architectural, not per-mission |
| Outcome visibility | Partial — confirms pending visible, execution outcome not live-tracked |
| Runner | **Closed from Mission Control** — no reachable execution path from UI |

---

## 2. Qué existe

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Mission Control read UI | Exists | `ui/components/sovereign/MissionControlView.tsx` | Observational, no execution triggers |
| Authority trace snapshot | Exists | `assistant_os/mso/authority_trace.py`, `AUTHORITY_CHAIN` (9 stages) | Architectural snapshot, not per-mission |
| Authority trace stage list | Exists | `assistant_os/mso/mission_control_status.py::build_authority_trace_stage_list()` | Returns 9 stages, passes 114 contracts |
| Confirm queue visibility | Exists | `/api/mso/prepared-actions/pending` | Reads prepared actions for manual review |
| Orchestration snapshot | Exists | `build_orchestration_snapshot()` | Returns read-model, no mutation |
| Mission Control status API | Exists | `webhook_server._handle_mso_authority_trace_snapshot_get()` | Read-only endpoint |
| Police gate | Exists | `assistant_os/mso/police/` | Gates all execution, not bypassed |
| MSO kernel | Exists | `assistant_os/mso/` | Sole source of executable authority |
| Execution proposal (cognitive-only) | Exists | `assistant_os/mso/execution_proposal.py` | `execution_allowed=False` invariant |
| Machine Operator lane | Exists | Separate lane | Has `policy_decision_ref: auto:` — isolated, not connected to Mission Control |
| BASELINE_TEST_DEBT documentation | Updated | `docs/mso/BASELINE_TEST_DEBT.md` | Linux green / Windows debt distinguished |

---

## 3. Qué NO existe todavía

| Missing Capability | Relevant Sprint | Notes |
|---|---|---|
| Planner formal | #225 (design only) | No formal Planner object, no structured plan lifecycle |
| Draft persistence | #225+ | No draft state stored anywhere |
| POST /plans | #225+ | Endpoint does not exist |
| Prepare-only governed contract | #226+ | No prepare-only authority boundary defined |
| POST /prepare | #226+ | Endpoint does not exist |
| Mission-correlated authority trace | #226+ | Trace is architectural snapshot, not linked to a mission ID |
| Execution from Mission Control | Intentionally deferred | Mission Control is read-model; execution requires Runner, which is closed from UI |
| Live execution state in Mission Control | Intentionally deferred | No running/completed/executing/live states wired |
| Multi-agent dispatch from Mission Control | Intentionally deferred | Not in scope |
| WebSocket/SSE push from Mission Control | Intentionally deferred | Not in scope |

---

## 4. Fronteras de autoridad

```
MSO kernel
  └── governs all authority
        ├── Police gates execution
        │     └── Runner is closed from Mission Control
        ├── Mission Control
        │     └── observes / surfaces prepared actions visually
        │     └── DOES NOT execute
        │     └── DOES NOT emit tokens
        │     └── DOES NOT create AuthorityArtifacts
        ├── Machine Operator lane
        │     └── SEPARATE execution lane
        │     └── policy_decision_ref: auto: (contained to that lane)
        │     └── MUST NOT be connected to Mission Control
        └── WORK handler
              └── uses core.orchestrator.handle_request directly
              └── conceptual bypass of authority chain (external debt, not this sprint)
```

**Invariants that hold today:**

- Mission Control does not execute.
- Runner is not reachable from Mission Control.
- No tokens are emitted from the UI.
- No AuthorityArtifact is created from the UI.
- POST /plans does not exist.
- POST /prepare does not exist.
- Police is not bypassed.
- Machine Operator is not connected to Mission Control.

---

## 5. Riesgos residuales

| Risk | Severity | Notes |
|---|---|---|
| Machine Operator lane confundible con Mission Control | Medium | Both visible in UI — must not be confused; MO is an execution lane, MC is read-model |
| `policy_decision_ref: auto:` in machine_operator | Medium | Contained to MO lane, but pattern must not propagate to Mission Control or new routes |
| WORK handler direct orchestrator bypass | High | `core.orchestrator.handle_request` called directly — bypasses formal authority chain; documented as external debt |
| Baseline debt Windows-specific | Low | 7–21 pre-existing failures on Windows; does not affect Linux baseline; see BASELINE_TEST_DEBT.md |
| Authority trace is snapshot, not per-mission | Medium | Trace cannot be correlated to a specific mission ID until Planner formal exists |
| Draft state implicitly in memory | Medium | No persistence; process restart loses any draft context |
| Readiness ~72% | — | Remaining ~28% requires Planner formal, prepare contract, and mission-correlated trace (sprints #225–#228) |

---

## 6. Próximo sprint recomendado

```
Next recommended sprint:
#225 — Planner Formal DESIGN ONLY
```

**No implementation of /plans or /prepare should occur before design approval.**

Design deliverables for #225:
- Formal definition of what a "Plan" is (schema, lifecycle, persistence contract)
- Decision: where does Plan state live? (MSO? separate service? DB?)
- Decision: what is the authority boundary for plan creation vs. execution approval?
- ADR: Planner formal vs. current local planner
- No code changes to MSO, Police, Runner, or auth

**Readiness gate:** Sprint #225 design must be reviewed and approved before any implementation sprint (#226+) begins.

---

## Appendix — AUTHORITY_CHAIN (canonical, 9 stages)

```python
AUTHORITY_CHAIN = [
    "mso_kernel",
    "intent_contract",
    "policy",
    "governance",
    "capability_token",
    "police_gate",
    "authority_artifact",
    "runner",
    "outcome",
]
```

Source: `assistant_os/mso/authority_trace.py:30`
Test coverage: `tests/test_mso_mission_control_truth_contracts.py` (114 contracts)
