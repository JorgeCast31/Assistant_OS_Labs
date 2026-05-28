# Mission Control Outcome Trace Alpha Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the Outcome / Authority Trace space so it surfaces real confirm_pending items from the queue, an honest outcome status, and meaningful stage evidence refs — without adding any execution path.

**Architecture:** Evolve three existing functions in `assistant_os/mso/mission_control_status.py` and the authority trace webhook handler (`assistant_os/webhook_server.py`) to return richer read-model data. Add `build_authority_trace_stage_list()` helper to `mission_control_status.py` so stage-mapping logic is testable without a server. Update TypeScript types, API fallback constants, and the `OutcomeTraceSpace` / `OrchestrationViewSpace` UI components to consume the richer data. No new backend endpoints.

**Tech Stack:** Python 3.11, custom HTTP handler (`webhook_server.py`), Next.js 14 App Router, TypeScript, Vitest, pytest, `ConfirmablePreparedActionQueueEntry`, `build_outcome_status()`, `build_authority_trace_snapshot()`

---

## File Structure

**Modified (backend):**
- `assistant_os/mso/mission_control_status.py` — add `build_authority_trace_stage_list()`, populate `confirm_pending` in `build_orchestration_snapshot()`, enrich `outcome` section in `build_mission_control_status()`
- `assistant_os/webhook_server.py` — use `build_authority_trace_stage_list()` in `_handle_mso_authority_trace_snapshot_get()`

**Modified (tests):**
- `tests/test_mso_mission_control_truth_contracts.py` — add test classes for confirm_pending, outcome section, and stage evidence refs

**Modified (frontend):**
- `ui/lib/types.ts` — add `MCConfirmPendingAction`, update `OrchestrationSnapshotResponse.confirm_pending`, update `MissionControlStatusResponse.outcome`
- `ui/lib/api.ts` — update `MC_STATUS_UNAVAILABLE.outcome` shape to match new type
- `ui/components/sovereign/MissionControlView.tsx` — update `OrchestrationViewSpace` (show confirm_pending from backend), update `OutcomeTraceSpace` (show outcome status, stage evidence refs)
- `ui/components/sovereign/__tests__/MissionControlView.test.tsx` — add tests for confirm_pending display, outcome status display, evidence ref visibility

---

## Invariants — never relax these

Every response touched by this sprint must preserve:
```
execution_allowed: false
used_execution: false
runner_reachable_from_ui: false
source: "backend_read_model"
live_execution: false
event_stream_connected: false
```
`confirm_pending` items always have `execution_allowed: False, can_execute_now: False`.
`outcome.execution_closed: True` always.
Never display `running`, `live`, or `authorized` unless backend explicitly provides evidence.

---

## Task 1: Populate confirm_pending in build_orchestration_snapshot()

**Files:**
- Modify: `assistant_os/mso/mission_control_status.py` (lines 211–266, the `build_orchestration_snapshot()` function)
- Modify: `tests/test_mso_mission_control_truth_contracts.py` (add to `TestBuildOrchestrationSnapshot` class)

**Context:** `build_orchestration_snapshot()` currently reads `list_pending_confirmable_action_dicts()` for `prepared_actions` but always returns `confirm_pending: []`. Queue entries have `human_confirmation_status: "pending"` and `status: "pending_review"`. Every queue entry IS awaiting confirmation, so the same loop can produce both lists. The `confirm_pending` items should have `status: "awaiting_confirmation"` (distinct from prepared_actions' `status: "prepared"`).

- [ ] **Step 1: Write failing tests**

Add these test methods inside the existing `TestBuildOrchestrationSnapshot` class in `tests/test_mso_mission_control_truth_contracts.py`, AFTER the existing `test_prepared_actions_intent_max_60_chars` method:

```python
    # ---- confirm_pending tests ----

    def test_confirm_pending_is_list(self):
        result = _snapshot()
        assert isinstance(result["confirm_pending"], list)

    def test_confirm_pending_empty_by_default(self):
        """Queue is empty by default → confirm_pending must be []."""
        result = _snapshot()
        assert result["confirm_pending"] == []

    def test_confirm_pending_populated_when_queue_has_entry(self):
        """When an action is enqueued, confirm_pending must reflect it."""
        from assistant_os.mso.confirmable_prepared_action import ConfirmablePreparedAction
        from assistant_os.mso.prepared_action_queue import enqueue_confirmable_prepared_action
        action = ConfirmablePreparedAction(
            preparation_id="prep-test-cp-1",
            proposal_id="prop-test-cp-1",
            user_intent="test confirm pending intent",
            domain="CODE",
            requested_action="write_test",
            capability_name="code_execution",
        )
        enqueue_confirmable_prepared_action(action)
        result = _snapshot()
        assert len(result["confirm_pending"]) == 1

    def test_confirm_pending_status_is_awaiting_confirmation(self):
        """Confirm pending items must carry status='awaiting_confirmation'."""
        from assistant_os.mso.confirmable_prepared_action import ConfirmablePreparedAction
        from assistant_os.mso.prepared_action_queue import enqueue_confirmable_prepared_action
        action = ConfirmablePreparedAction(
            preparation_id="prep-test-cp-2",
            proposal_id="prop-test-cp-2",
            user_intent="status check intent",
            domain="CODE",
            requested_action="check_status",
            capability_name="code_execution",
        )
        enqueue_confirmable_prepared_action(action)
        result = _snapshot()
        for item in result["confirm_pending"]:
            assert item["status"] == "awaiting_confirmation", (
                f"confirm_pending item has unexpected status={item.get('status')!r}"
            )

    def test_confirm_pending_execution_allowed_is_false(self):
        """Invariant: confirm_pending items must always have execution_allowed=False."""
        from assistant_os.mso.confirmable_prepared_action import ConfirmablePreparedAction
        from assistant_os.mso.prepared_action_queue import enqueue_confirmable_prepared_action
        action = ConfirmablePreparedAction(
            preparation_id="prep-test-cp-3",
            proposal_id="prop-test-cp-3",
            user_intent="exec check intent",
            domain="CODE",
            requested_action="exec_check",
            capability_name="code_execution",
        )
        enqueue_confirmable_prepared_action(action)
        result = _snapshot()
        for item in result["confirm_pending"]:
            assert item["execution_allowed"] is False, (
                "confirm_pending item must have execution_allowed=False"
            )

    def test_confirm_pending_can_execute_now_is_false(self):
        """Invariant: confirm_pending items must always have can_execute_now=False."""
        from assistant_os.mso.confirmable_prepared_action import ConfirmablePreparedAction
        from assistant_os.mso.prepared_action_queue import enqueue_confirmable_prepared_action
        action = ConfirmablePreparedAction(
            preparation_id="prep-test-cp-4",
            proposal_id="prop-test-cp-4",
            user_intent="can exec check",
            domain="CODE",
            requested_action="can_exec_check",
            capability_name="code_execution",
        )
        enqueue_confirmable_prepared_action(action)
        result = _snapshot()
        for item in result["confirm_pending"]:
            assert item["can_execute_now"] is False, (
                "confirm_pending item must have can_execute_now=False"
            )

    def test_confirm_pending_does_not_imply_execution(self):
        """Confirm pending != running. No confirm_pending item may have status='running'."""
        from assistant_os.mso.confirmable_prepared_action import ConfirmablePreparedAction
        from assistant_os.mso.prepared_action_queue import enqueue_confirmable_prepared_action
        action = ConfirmablePreparedAction(
            preparation_id="prep-test-cp-5",
            proposal_id="prop-test-cp-5",
            user_intent="no running check",
            domain="CODE",
            requested_action="no_running",
            capability_name="code_execution",
        )
        enqueue_confirmable_prepared_action(action)
        result = _snapshot()
        for item in result["confirm_pending"]:
            assert item.get("status") != "running", (
                "confirm_pending item must NEVER have status='running' — it is not executing"
            )

    def test_confirm_pending_has_required_keys(self):
        """Each confirm_pending item must have id, status, domain, intent, requested_action."""
        from assistant_os.mso.confirmable_prepared_action import ConfirmablePreparedAction
        from assistant_os.mso.prepared_action_queue import enqueue_confirmable_prepared_action
        action = ConfirmablePreparedAction(
            preparation_id="prep-test-cp-6",
            proposal_id="prop-test-cp-6",
            user_intent="keys check intent",
            domain="CODE",
            requested_action="write_keys_check",
            capability_name="code_execution",
        )
        enqueue_confirmable_prepared_action(action)
        result = _snapshot()
        for item in result["confirm_pending"]:
            for key in ("id", "status", "domain", "intent", "requested_action",
                        "execution_allowed", "can_execute_now"):
                assert key in item, (
                    f"confirm_pending item missing required key {key!r}"
                )

    def test_confirm_pending_count_matches_prepared_actions_count(self):
        """When queue has N entries, both prepared_actions and confirm_pending have N items."""
        from assistant_os.mso.confirmable_prepared_action import ConfirmablePreparedAction
        from assistant_os.mso.prepared_action_queue import enqueue_confirmable_prepared_action
        for i in range(2):
            action = ConfirmablePreparedAction(
                preparation_id=f"prep-cp-count-{i}",
                proposal_id=f"prop-cp-count-{i}",
                user_intent=f"count check intent {i}",
                domain="CODE",
                requested_action=f"count_check_{i}",
                capability_name="code_execution",
            )
            enqueue_confirmable_prepared_action(action)
        result = _snapshot()
        assert len(result["prepared_actions"]) == len(result["confirm_pending"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
python -m pytest tests/test_mso_mission_control_truth_contracts.py::TestBuildOrchestrationSnapshot::test_confirm_pending_populated_when_queue_has_entry tests/test_mso_mission_control_truth_contracts.py::TestBuildOrchestrationSnapshot::test_confirm_pending_status_is_awaiting_confirmation tests/test_mso_mission_control_truth_contracts.py::TestBuildOrchestrationSnapshot::test_confirm_pending_has_required_keys -v
```

Expected: FAIL — `confirm_pending` is `[]` even when queue has entries.

- [ ] **Step 3: Update build_orchestration_snapshot()**

Replace the entire `build_orchestration_snapshot()` function in `assistant_os/mso/mission_control_status.py` with:

```python
def build_orchestration_snapshot() -> dict[str, Any]:
    """
    Aggregate the prepared action queue into an orchestration snapshot dict.

    - runs and threads are always [] — there is no live execution
    - prepared_actions is derived from the queue (honest read-model)
    - confirm_pending reflects the same queue entries viewed as awaiting human confirmation
    - A run must NEVER have status: "running" — if nothing is running, return empty

    Returns
    -------
    dict
        Truth-contract dict. Never raises.
    """
    prepared_actions: list[dict[str, Any]] = []
    confirm_pending_items: list[dict[str, Any]] = []

    try:
        from .prepared_action_queue import list_pending_confirmable_action_dicts
        raw_entries = list_pending_confirmable_action_dicts()

        for entry in raw_entries:
            # Resolve a stable ID — prefer queue_entry_id, fall back to prepared_action_id
            entry_id = (
                entry.get("queue_entry_id")
                or entry.get("prepared_action_id")
                or "unknown"
            )

            # Truncate user_intent to first 60 chars for surface transport
            raw_intent: str | None = entry.get("user_intent") or None
            intent: str | None = raw_intent[:60] if raw_intent else None

            prepared_actions.append(
                {
                    "id": entry_id,
                    "status": "prepared",
                    "domain": entry.get("domain") or None,
                    "intent": intent,
                }
            )

            # Confirm pending: same entry viewed as awaiting human confirmation.
            # human_confirmation_status is always "pending" for queue entries.
            # execution_allowed and can_execute_now are always False (enforced by dataclass invariants).
            confirm_pending_items.append(
                {
                    "id": entry_id,
                    "status": "awaiting_confirmation",
                    "domain": entry.get("domain") or None,
                    "intent": intent,
                    "requested_action": entry.get("requested_action") or None,
                    "execution_allowed": False,   # ALWAYS False
                    "can_execute_now": False,      # ALWAYS False
                }
            )
    except Exception:
        prepared_actions = []
        confirm_pending_items = []

    return {
        "ok": True,
        "source": "backend_read_model",
        "execution_allowed": False,
        "used_execution": False,
        "runner_reachable_from_ui": False,
        "runs": [],        # no live runs — honest empty
        "threads": [],     # no live threads — honest empty
        "prepared_actions": prepared_actions,
        "confirm_pending": confirm_pending_items,
        "live_execution": False,
        "event_stream_connected": False,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
python -m pytest tests/test_mso_mission_control_truth_contracts.py::TestBuildOrchestrationSnapshot -v
```

Expected: All tests in `TestBuildOrchestrationSnapshot` pass.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
git add assistant_os/mso/mission_control_status.py tests/test_mso_mission_control_truth_contracts.py
git commit -m "feat(mso): populate confirm_pending in build_orchestration_snapshot"
```

---

## Task 2: Enrich outcome section in build_mission_control_status()

**Files:**
- Modify: `assistant_os/mso/mission_control_status.py` (lines 77–135, the `build_mission_control_status()` function, specifically the outcome section at end of return dict)
- Modify: `tests/test_mso_mission_control_truth_contracts.py` (add to `TestBuildMissionControlStatus` class)

**Context:** The `outcome` section in `build_mission_control_status()` is currently hardcoded as `{"status": "unavailable"}`. `outcome_status.py` has `build_outcome_status()` which queries task_registry, trace_aggregator, context_store, and runner metadata. With no IDs passed, it returns `{found: False, outcome: {status: "not_found"}}` immediately (all four `_find_*` functions return `None` immediately when IDs are empty). This is more honest than `"unavailable"`. The outcome section should also include `found`, `execution_closed: True`, and `sources_checked`.

- [ ] **Step 1: Write failing tests**

Add these test methods inside the existing `TestBuildMissionControlStatus` class in `tests/test_mso_mission_control_truth_contracts.py`, AFTER the existing `test_authority_counts_is_dict` method:

```python
    # ---- outcome section tests ----

    def test_outcome_found_is_false_with_no_query(self):
        """No query IDs → outcome.found must be False (honest: nothing was searched)."""
        result = _status()
        assert result["outcome"].get("found") is False

    def test_outcome_execution_closed_is_true(self):
        """Invariant: outcome.execution_closed must always be True."""
        result = _status()
        assert result["outcome"].get("execution_closed") is True

    def test_outcome_status_is_valid_state_word(self):
        """outcome.status must be a known honest state, not a fabricated success."""
        result = _status()
        valid_states = (
            "unavailable", "not_found", "unknown",
            "pending", "completed", "failed", "blocked",
        )
        assert result["outcome"]["status"] in valid_states, (
            f"outcome.status={result['outcome']['status']!r} is not a known honest state"
        )

    def test_outcome_status_is_not_running(self):
        """outcome.status must NEVER be 'running' — nothing is executing."""
        result = _status()
        assert result["outcome"]["status"] != "running"

    def test_outcome_sources_checked_is_list(self):
        """outcome.sources_checked must be present and be a list."""
        result = _status()
        assert isinstance(result["outcome"].get("sources_checked"), list)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
python -m pytest tests/test_mso_mission_control_truth_contracts.py::TestBuildMissionControlStatus::test_outcome_found_is_false_with_no_query tests/test_mso_mission_control_truth_contracts.py::TestBuildMissionControlStatus::test_outcome_execution_closed_is_true tests/test_mso_mission_control_truth_contracts.py::TestBuildMissionControlStatus::test_outcome_sources_checked_is_list -v
```

Expected: FAIL — `outcome` currently only has `{"status": "unavailable"}`, missing `found`, `execution_closed`, `sources_checked`.

- [ ] **Step 3: Update the outcome section in build_mission_control_status()**

In `assistant_os/mso/mission_control_status.py`, replace the comment and `"outcome"` key in `build_mission_control_status()`'s return dict. The current code at lines ~130–134 looks like:

```python
        "outcome": {
            "status": "unavailable",  # no live outcome data at this layer
        },
```

Replace the entire `"outcome"` entry (and add the outcome derivation logic before the return statement) so that the section before the `return` and the return value look like this. Find the existing `# -- Authority status` block and add the new outcome block AFTER it, before the `# -- Derive overall state` comment:

```python
    # -- Outcome status (read-only, fail-soft) -----------------------------------
    # build_outcome_status() with no IDs returns found=False, status="not_found"
    # immediately (all _find_* helpers return None when no IDs are supplied).
    # This is more honest than hardcoding "unavailable".
    outcome_info: dict[str, Any] = {
        "status": "unavailable",
        "found": False,
        "execution_closed": True,
        "sources_checked": [],
    }
    try:
        from .outcome_status import build_outcome_status
        raw_outcome = build_outcome_status()  # no IDs → not_found
        outcome_info = {
            "status": raw_outcome.get("outcome", {}).get("status", "unknown"),
            "found": bool(raw_outcome.get("found", False)),
            "execution_closed": True,  # ALWAYS True — no execution from UI
            "sources_checked": list(raw_outcome.get("sources", {}).keys()),
        }
    except Exception:
        outcome_info = {
            "status": "unavailable",
            "found": False,
            "execution_closed": True,
            "sources_checked": [],
        }
```

And update the return dict to use `outcome_info`:

```python
        "outcome": outcome_info,
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
python -m pytest tests/test_mso_mission_control_truth_contracts.py::TestBuildMissionControlStatus -v
```

Expected: All tests in `TestBuildMissionControlStatus` pass, including existing ones (`test_outcome_section_present` still passes because `outcome` is still present).

- [ ] **Step 5: Commit**

```bash
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
git add assistant_os/mso/mission_control_status.py tests/test_mso_mission_control_truth_contracts.py
git commit -m "feat(mso): enrich outcome section in build_mission_control_status with honest outcome_status"
```

---

## Task 3: Extract build_authority_trace_stage_list() + enrich evidence_refs

**Files:**
- Modify: `assistant_os/mso/mission_control_status.py` (add new function `build_authority_trace_stage_list()` at end of file)
- Modify: `assistant_os/webhook_server.py` (lines ~5534–5588, simplify `_handle_mso_authority_trace_snapshot_get()`)
- Modify: `tests/test_mso_mission_control_truth_contracts.py` (add new `TestBuildAuthorityTraceStageList` class)

**Context:** The stage-mapping logic that converts a `build_authority_trace_snapshot()` result to a UI-ready stages list currently lives inside `_handle_mso_authority_trace_snapshot_get()` in `webhook_server.py`. It is untestable without spinning up a server. This task extracts it into `build_authority_trace_stage_list(snapshot)` in `mission_control_status.py`, and enriches `evidence_ref` fields (currently all `None`) with honest metadata from the snapshot. The webhook handler is simplified to call this helper.

**Stage mapping rules (to implement):**
- `mso_kernel` → always `"available"` (MSO is always present). evidence: `"kernel_boundary:true · orchestrator_owned:true"`
- `intent_contract` → `"available"` if `snapshot["request"]["available"]` else `"architectural"`. evidence: `"execution_intent:false"` (always false at rest)
- `policy` → `"available"` if `snapshot["policy"]["available"]` else `"architectural"`. evidence: `None` (no policy_decision_ref at rest)
- `governance` → `"available"` if `snapshot["governance"]["available"]` else `"architectural"`. evidence: `None`
- `capability_token` → `"available"` if `snapshot["capability"]["available"]` else `"architectural"`. evidence: `None`
- `police_gate` → always `"available"` (wired into chain). evidence: `f"decision_visibility:{snapshot['police'].get('decision_visibility', 'not_persisted_yet')}"`
- `authority_artifact` → always `"available"` (wired into chain). evidence: `f"artifact_version:{snapshot['artifact'].get('artifact_version', 'unknown')} · authority_source:{snapshot['artifact'].get('authority_source', 'unknown')}"`
- `runner` → always `"architectural"` (architecturally closed from UI). evidence: `"fail_closed:true · executed:false · runner_reachable_from_ui:false"`
- `outcome` → `"available"` if `snapshot["outcome"]["available"]` else `"unavailable"`. evidence: `"execution_closed:true"`

- [ ] **Step 1: Write failing tests**

Add a new test class in `tests/test_mso_mission_control_truth_contracts.py`, AFTER the `TestBuildOrchestrationSnapshot` class and BEFORE `TestMissionControlRouteHandlers`:

```python
# ===========================================================================
# build_authority_trace_stage_list
# ===========================================================================


def _stage_list(snapshot=None):
    from assistant_os.mso.mission_control_status import build_authority_trace_stage_list
    if snapshot is None:
        from assistant_os.mso.authority_trace import build_authority_trace_snapshot
        snapshot = build_authority_trace_snapshot()
    return build_authority_trace_stage_list(snapshot)


class TestBuildAuthorityTraceStageList:

    def test_returns_list(self):
        stages = _stage_list()
        assert isinstance(stages, list)

    def test_returns_nine_stages(self):
        stages = _stage_list()
        assert len(stages) == 9

    def test_all_stages_have_required_keys(self):
        stages = _stage_list()
        for stage in stages:
            for key in ("id", "label", "state", "evidence_ref"):
                assert key in stage, f"Stage {stage.get('id')!r} missing key {key!r}"

    def test_stage_ids_match_authority_chain(self):
        from assistant_os.mso.authority_trace import AUTHORITY_CHAIN
        stages = _stage_list()
        stage_ids = [s["id"] for s in stages]
        assert stage_ids == list(AUTHORITY_CHAIN)

    def test_mso_kernel_is_always_available(self):
        """MSO kernel is always present — must show 'available'."""
        stages = _stage_list()
        mso = next(s for s in stages if s["id"] == "mso_kernel")
        assert mso["state"] == "available", (
            f"mso_kernel state={mso['state']!r} — MSO is always present"
        )

    def test_runner_is_not_available(self):
        """Runner is architecturally closed from UI — must NOT be 'available'."""
        stages = _stage_list()
        runner = next(s for s in stages if s["id"] == "runner")
        assert runner["state"] != "available", (
            "runner stage must never show 'available' — runner is closed from UI"
        )
        assert runner["state"] in ("architectural", "blocked", "unavailable", "pending")

    def test_runner_evidence_ref_contains_fail_closed(self):
        """Runner evidence_ref must include fail_closed:true."""
        stages = _stage_list()
        runner = next(s for s in stages if s["id"] == "runner")
        assert runner.get("evidence_ref") is not None
        assert "fail_closed:true" in runner["evidence_ref"]

    def test_police_gate_evidence_ref_contains_decision_visibility(self):
        """Police gate evidence_ref must contain decision_visibility."""
        stages = _stage_list()
        police = next(s for s in stages if s["id"] == "police_gate")
        assert police.get("evidence_ref") is not None
        assert "decision_visibility:" in police["evidence_ref"]

    def test_mso_kernel_evidence_ref_contains_kernel_boundary(self):
        """MSO kernel evidence_ref must document the architectural boundary."""
        stages = _stage_list()
        mso = next(s for s in stages if s["id"] == "mso_kernel")
        assert mso.get("evidence_ref") is not None
        assert "kernel_boundary:true" in mso["evidence_ref"]

    def test_runner_evidence_ref_contains_runner_reachable_false(self):
        """Runner evidence_ref must explicitly state runner_reachable_from_ui:false."""
        stages = _stage_list()
        runner = next(s for s in stages if s["id"] == "runner")
        assert "runner_reachable_from_ui:false" in runner["evidence_ref"]

    def test_outcome_state_is_not_available_without_context(self):
        """With no request context, outcome state must be 'unavailable'."""
        stages = _stage_list()
        outcome = next(s for s in stages if s["id"] == "outcome")
        assert outcome["state"] in ("unavailable", "architectural")

    def test_no_stage_state_is_running_or_live(self):
        """No stage may have state='running' or state='live' — not execution traces."""
        stages = _stage_list()
        for stage in stages:
            assert stage["state"] not in ("running", "live", "executing"), (
                f"Stage {stage['id']!r} has unsafe state={stage['state']!r}"
            )

    def test_does_not_raise_with_empty_snapshot(self):
        """Must not raise even if snapshot is empty dict."""
        stages = _stage_list({})
        assert isinstance(stages, list)
        assert len(stages) == 9

    def test_authority_artifact_evidence_ref_contains_artifact_version(self):
        stages = _stage_list()
        artifact = next(s for s in stages if s["id"] == "authority_artifact")
        assert artifact.get("evidence_ref") is not None
        assert "artifact_version:" in artifact["evidence_ref"]
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
python -m pytest tests/test_mso_mission_control_truth_contracts.py::TestBuildAuthorityTraceStageList -v
```

Expected: FAIL — `build_authority_trace_stage_list` does not exist yet.

- [ ] **Step 3: Add build_authority_trace_stage_list() to mission_control_status.py**

Append this function to the END of `assistant_os/mso/mission_control_status.py` (after `build_orchestration_snapshot()`):

```python
# ---------------------------------------------------------------------------
# 4. build_authority_trace_stage_list
# ---------------------------------------------------------------------------


def build_authority_trace_stage_list(
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Map a build_authority_trace_snapshot() result to a UI-ready stages list.

    Each stage gets:
      - id          : stage key from AUTHORITY_CHAIN
      - label       : human-readable name
      - state       : 'available' | 'architectural' | 'unavailable' | 'pending'
      - evidence_ref: honest metadata string where available, None otherwise

    State rules:
      - mso_kernel         → always "available" (MSO is always present)
      - intent_contract    → "available" if snapshot.request.available else "architectural"
      - policy             → "available" if snapshot.policy.available else "architectural"
      - governance         → "available" if snapshot.governance.available else "architectural"
      - capability_token   → "available" if snapshot.capability.available else "architectural"
      - police_gate        → always "available" (wired into chain)
      - authority_artifact → always "available" (wired into chain)
      - runner             → always "architectural" (closed from UI)
      - outcome            → "available" if snapshot.outcome.available else "unavailable"

    Evidence refs are populated honestly from snapshot data where present.
    Never fabricated. Returns a list even if snapshot is empty or malformed.

    Returns
    -------
    list[dict[str, Any]]
        9-element stages list. Never raises.
    """
    from .authority_trace import AUTHORITY_CHAIN

    # Safely extract nested stage data from snapshot
    def _stage(key: str) -> dict[str, Any]:
        val = snapshot.get(key, {})
        return val if isinstance(val, dict) else {}

    request_data    = _stage("request")
    policy_data     = _stage("policy")
    governance_data = _stage("governance")
    capability_data = _stage("capability")
    police_data     = _stage("police")
    artifact_data   = _stage("artifact")
    runner_data     = _stage("runner")
    outcome_data    = _stage("outcome")

    stage_specs: dict[str, tuple[str, str, str | None]] = {
        # id → (label, state, evidence_ref)
        "mso_kernel": (
            "MSO Kernel",
            "available",  # MSO is always present — never architectural
            "kernel_boundary:true · orchestrator_owned:true",
        ),
        "intent_contract": (
            "Intent Contract",
            "available" if request_data.get("available") else "architectural",
            "execution_intent:false",  # no execution intent at architectural rest
        ),
        "policy": (
            "PolicyDecision",
            "available" if policy_data.get("available") else "architectural",
            None,  # no policy_decision_ref at rest
        ),
        "governance": (
            "Governance",
            "available" if governance_data.get("available") else "architectural",
            None,  # no governance_ref at rest
        ),
        "capability_token": (
            "CapabilityToken",
            "available" if capability_data.get("available") else "architectural",
            None,  # no token_ref at rest
        ),
        "police_gate": (
            "Police Gate",
            "available",  # always wired into the authority chain
            f"decision_visibility:{police_data.get('decision_visibility', 'not_persisted_yet')}",
        ),
        "authority_artifact": (
            "AuthorityArtifact",
            "available",  # always wired into the authority chain
            (
                f"artifact_version:{artifact_data.get('artifact_version', 'unknown')}"
                f" · authority_source:{artifact_data.get('authority_source', 'unknown')}"
            ),
        ),
        "runner": (
            "Runner",
            "architectural",  # ALWAYS closed from UI
            "fail_closed:true · executed:false · runner_reachable_from_ui:false",
        ),
        "outcome": (
            "Outcome",
            "available" if outcome_data.get("available") else "unavailable",
            "execution_closed:true",
        ),
    }

    stages: list[dict[str, Any]] = []
    for stage_id in AUTHORITY_CHAIN:
        label, state, evidence_ref = stage_specs.get(
            stage_id,
            (stage_id, "architectural", None),
        )
        stages.append(
            {
                "id": stage_id,
                "label": label,
                "state": state,
                "evidence_ref": evidence_ref,
            }
        )
    return stages
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
python -m pytest tests/test_mso_mission_control_truth_contracts.py::TestBuildAuthorityTraceStageList -v
```

Expected: All `TestBuildAuthorityTraceStageList` tests pass.

- [ ] **Step 5: Simplify the webhook handler to use the helper**

In `assistant_os/webhook_server.py`, replace the body of `_handle_mso_authority_trace_snapshot_get()` (the try block starting at the `from .mso.authority_trace import ...` line) with:

```python
        try:
            from .mso.authority_trace import build_authority_trace_snapshot, AUTHORITY_CHAIN
            from .mso.mission_control_status import build_authority_trace_stage_list

            # Build snapshot with no per-request context → architectural/snapshot mode
            snapshot = build_authority_trace_snapshot()
            stages = build_authority_trace_stage_list(snapshot)

            self._send_json_response(
                200,
                {
                    "ok": True,
                    "source": "backend_read_model",
                    "trace_mode": "snapshot",
                    "execution_allowed": False,
                    "used_execution": False,
                    "runner_reachable_from_ui": False,
                    "stages": stages,
                    "chain": list(AUTHORITY_CHAIN),
                },
            )
```

Keep the existing `except Exception` handler below unchanged.

- [ ] **Step 6: Run all backend tests to verify nothing broke**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
python -m pytest tests/test_mso_mission_control_truth_contracts.py -v
```

Expected: All 63+ tests pass (existing 63 + new tests from Tasks 1, 2, 3).

- [ ] **Step 7: Commit**

```bash
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
git add assistant_os/mso/mission_control_status.py assistant_os/webhook_server.py tests/test_mso_mission_control_truth_contracts.py
git commit -m "feat(mso): extract build_authority_trace_stage_list with meaningful evidence refs"
```

---

## Task 4: Frontend types + UI updates

**Files:**
- Modify: `ui/lib/types.ts` — add `MCConfirmPendingAction`; update `OrchestrationSnapshotResponse.confirm_pending`; update `MissionControlStatusResponse.outcome`
- Modify: `ui/lib/api.ts` — update `MC_STATUS_UNAVAILABLE.outcome` shape
- Modify: `ui/components/sovereign/MissionControlView.tsx` — update `OrchestrationViewSpace` (show confirm_pending from backend), update `OutcomeTraceSpace` (outcome status, stage evidence refs)
- Modify: `ui/components/sovereign/__tests__/MissionControlView.test.tsx` — add tests

**Context:** `OrchestrationSnapshotResponse.confirm_pending` is currently typed as `never[]` — it must become `MCConfirmPendingAction[]` so the new confirm_pending items from backend can flow through. `MissionControlStatusResponse.outcome` currently only has `{status: 'unavailable'}` — it must accommodate the richer shape `{status, found, execution_closed, sources_checked}`. `OrchestrationViewSpace` currently shows confirm_pending count from a Zustand store — it should prefer the backend snapshot count when available. `OutcomeTraceSpace` currently only shows the authority trace chain — it should also show the outcome status from `mcStatus` and surface `evidence_ref` values next to each stage.

### 4a. Update types.ts

- [ ] **Step 1: Add MCConfirmPendingAction and update existing interfaces**

In `ui/lib/types.ts`, find the `MCPreparedAction` interface and add `MCConfirmPendingAction` immediately after it:

```typescript
export interface MCConfirmPendingAction {
  id: string
  status: 'awaiting_confirmation'
  domain: string | null
  intent: string | null
  requested_action: string | null
  execution_allowed: false
  can_execute_now: false
}
```

Then update `OrchestrationSnapshotResponse` — change the `confirm_pending` field type from `never[]` to `MCConfirmPendingAction[]`:

```typescript
export interface OrchestrationSnapshotResponse {
  ok: boolean
  source: 'backend_read_model'
  execution_allowed: false
  used_execution: false
  runner_reachable_from_ui: false
  runs: never[]
  threads: never[]
  prepared_actions: MCPreparedAction[]
  confirm_pending: MCConfirmPendingAction[]
  live_execution: false
  event_stream_connected: false
  status?: 'unavailable'
  error?: string
}
```

Then update `MissionControlStatusResponse` — change the `outcome` field:

```typescript
  outcome: {
    status: 'not_found' | 'unknown' | 'unavailable' | 'pending' | 'completed' | 'failed' | 'blocked'
    found: boolean
    execution_closed: true
    sources_checked?: string[]
  }
```

### 4b. Update api.ts fallback constants

- [ ] **Step 2: Update MC_STATUS_UNAVAILABLE.outcome in api.ts**

In `ui/lib/api.ts`, find the `MC_STATUS_UNAVAILABLE` constant and update its `outcome` field to match the new type:

```typescript
  outcome: { status: 'unavailable', found: false, execution_closed: true },
```

(Keep `sources_checked` optional — the fallback doesn't need to set it.)

Also find `MC_ORCHESTRATION_UNAVAILABLE` and verify `confirm_pending: []` is still valid (it is — `[]` is assignable to `MCConfirmPendingAction[]`). No change needed for this constant.

- [ ] **Step 3: Run TypeScript type check to confirm no type errors**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01\ui
npm run typecheck 2>&1 | head -30
```

If `typecheck` script does not exist, run:
```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01\ui
npx tsc --noEmit 2>&1 | head -30
```

Expected: No type errors related to the changed interfaces.

### 4c. Update MissionControlView.tsx

- [ ] **Step 4: Write failing UI tests for new behaviors**

Add the following test blocks in `ui/components/sovereign/__tests__/MissionControlView.test.tsx`. Find the existing `import` block at the top that imports the mock functions (`getMissionControlStatus`, `getMissionControlReadiness`, etc.) and also import `MCConfirmPendingAction` from `@/lib/types`.

Find the section that creates `MC_ORCHESTRATION_UNAVAILABLE` mock and add a helper for orchestration data that includes confirm_pending:

First, locate the existing `describe('OrchestrationViewSpace')` block and add these tests inside it (after the existing tests):

```typescript
  describe('confirm_pending from backend snapshot', () => {
    it('shows confirm_pending count from backend when ok:true', async () => {
      vi.mocked(getOrchestrationSnapshot).mockResolvedValue({
        ok: true,
        source: 'backend_read_model',
        execution_allowed: false,
        used_execution: false,
        runner_reachable_from_ui: false,
        runs: [],
        threads: [],
        prepared_actions: [],
        confirm_pending: [
          {
            id: 'cp-test-1',
            status: 'awaiting_confirmation',
            domain: 'CODE',
            intent: 'test intent awaiting confirmation',
            requested_action: 'write_test',
            execution_allowed: false,
            can_execute_now: false,
          },
        ],
        live_execution: false,
        event_stream_connected: false,
      })
      render(<MissionControlView />)
      // Switch to orchestration tab
      const tab = screen.getByRole('button', { name: /orchestration/i })
      await userEvent.click(tab)
      await waitFor(() => {
        // confirm_pending count should appear
        expect(screen.getByText('1')).toBeTruthy()
      })
    })

    it('confirm_pending items do not show running or executing', async () => {
      vi.mocked(getOrchestrationSnapshot).mockResolvedValue({
        ok: true,
        source: 'backend_read_model',
        execution_allowed: false,
        used_execution: false,
        runner_reachable_from_ui: false,
        runs: [],
        threads: [],
        prepared_actions: [],
        confirm_pending: [
          {
            id: 'cp-test-2',
            status: 'awaiting_confirmation',
            domain: 'CODE',
            intent: 'no running here',
            requested_action: 'check_no_running',
            execution_allowed: false,
            can_execute_now: false,
          },
        ],
        live_execution: false,
        event_stream_connected: false,
      })
      render(<MissionControlView />)
      const tab = screen.getByRole('button', { name: /orchestration/i })
      await userEvent.click(tab)
      await waitFor(() => {
        expect(screen.queryByText(/running/i)).toBeNull()
        expect(screen.queryByText(/executing/i)).toBeNull()
      })
    })
  })
```

Then add a new describe block for `OutcomeTraceSpace` backend outcome:

```typescript
  describe('OutcomeTraceSpace — outcome status and evidence refs', () => {
    it('shows outcome status from mc status when available', async () => {
      vi.mocked(getMissionControlStatus).mockResolvedValue({
        ok: true,
        source: 'backend_read_model',
        execution_allowed: false,
        used_execution: false,
        runner_reachable_from_ui: false,
        mission_control: {
          state: 'available',
          mode: 'read_model',
          execution_allowed: false,
          used_execution: false,
        },
        mso: { entity_status: 'available', seat_status: 'available', boundary: 'sovereign' },
        queues: { prepared_actions_count: 0, confirm_pending_count: 0 },
        authority: { status: 'available', counts: {} },
        outcome: {
          status: 'not_found',
          found: false,
          execution_closed: true,
          sources_checked: ['task_registry', 'trace_chain', 'context_store_pending', 'runner_metadata'],
        },
      })
      render(<MissionControlView />)
      const tab = screen.getByRole('button', { name: /outcome/i })
      await userEvent.click(tab)
      await waitFor(() => {
        expect(
          screen.getByTestId('outcome-status-label')
        ).toBeTruthy()
      })
    })

    it('never shows outcome status as running or live', async () => {
      vi.mocked(getMissionControlStatus).mockResolvedValue({
        ok: true,
        source: 'backend_read_model',
        execution_allowed: false,
        used_execution: false,
        runner_reachable_from_ui: false,
        mission_control: {
          state: 'available',
          mode: 'read_model',
          execution_allowed: false,
          used_execution: false,
        },
        mso: { entity_status: 'available', seat_status: 'available', boundary: 'sovereign' },
        queues: { prepared_actions_count: 0, confirm_pending_count: 0 },
        authority: { status: 'available', counts: {} },
        outcome: {
          status: 'not_found',
          found: false,
          execution_closed: true,
        },
      })
      render(<MissionControlView />)
      const tab = screen.getByRole('button', { name: /outcome/i })
      await userEvent.click(tab)
      await waitFor(() => {
        expect(screen.queryByText(/running/i)).toBeNull()
        expect(screen.queryByText(/live/i)).toBeNull()
      })
    })

    it('shows execution_closed:true in outcome', async () => {
      render(<MissionControlView />)
      const tab = screen.getByRole('button', { name: /outcome/i })
      await userEvent.click(tab)
      await waitFor(() => {
        expect(screen.getByTestId('outcome-execution-closed')).toBeTruthy()
      })
    })

    it('shows trace mode label', async () => {
      render(<MissionControlView />)
      const tab = screen.getByRole('button', { name: /outcome/i })
      await userEvent.click(tab)
      await waitFor(() => {
        expect(screen.getByTestId('trace-mode-label')).toBeTruthy()
      })
    })

    it('evidence refs visible when backend snapshot has mode=snapshot', async () => {
      vi.mocked(getAuthorityTraceSnapshot).mockResolvedValue({
        ok: true,
        source: 'backend_read_model',
        execution_allowed: false,
        used_execution: false,
        runner_reachable_from_ui: false,
        trace_mode: 'snapshot',
        stages: [
          {
            id: 'mso_kernel',
            label: 'MSO Kernel',
            state: 'available',
            evidence_ref: 'kernel_boundary:true · orchestrator_owned:true',
          },
          {
            id: 'runner',
            label: 'Runner',
            state: 'architectural',
            evidence_ref: 'fail_closed:true · executed:false · runner_reachable_from_ui:false',
          },
        ],
      })
      render(<MissionControlView />)
      const tab = screen.getByRole('button', { name: /outcome/i })
      await userEvent.click(tab)
      await waitFor(() => {
        expect(screen.getByText(/kernel_boundary:true/i)).toBeTruthy()
      })
    })
  })
```

- [ ] **Step 5: Run UI tests to verify they fail**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01\ui
npm run test -- --reporter=verbose 2>&1 | grep -E "FAIL|PASS|✓|✗|×" | head -40
```

Expected: New tests fail — `outcome-status-label` and `outcome-execution-closed` data-testids don't exist yet.

### 4d. Update MissionControlView.tsx component

- [ ] **Step 6: Update OrchestrationViewSpace to show confirm_pending from backend**

In `ui/components/sovereign/MissionControlView.tsx`, find `OrchestrationViewSpace()` (starts at line ~692). The current `Confirm Pending` tile at lines ~783-789 reads from `confirmPending` Zustand store. Update it to prefer backend `confirm_pending` count:

Find the block that defines `confirmCount`:
```typescript
  const confirmCount = confirmPending?.pending_count ?? 0
```

Replace with:
```typescript
  // Prefer backend snapshot confirm_pending count; fall back to Zustand
  const confirmCount = useBackendSnapshot
    ? orchestrationData!.confirm_pending.length
    : (confirmPending?.pending_count ?? 0)
```

- [ ] **Step 7: Update OutcomeTraceSpace to show outcome status + evidence_ref**

In `ui/components/sovereign/MissionControlView.tsx`, find `OutcomeTraceSpace()` (starts at line ~971). The function currently uses `traceData` from `useMCTraceQuery()` but does NOT use `mcStatus` from `useMCStatusQuery()`. Add `mcStatus`:

Add at the top of `OutcomeTraceSpace()` (after `const traceData = useMCTraceQuery()`):
```typescript
  const mcStatus = useMCStatusQuery()
  const outcomeInfo = mcStatus?.outcome ?? null
```

In the JSX, find the `{/* Outcome status */}` section (around line 1041–1045):
```tsx
      {/* Outcome status */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">Execution Outcome</p>
        <OutcomeStatusPanel />
      </section>
```

Replace with:
```tsx
      {/* Outcome status */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">Execution Outcome</p>
        {/* Honest outcome status from backend read model */}
        <div className="rounded-lg border border-os-border bg-os-surface p-3 mb-3">
          <div className="flex items-center justify-between">
            <span
              className="text-[10px] font-mono text-tx-muted"
              data-testid="outcome-status-label"
            >
              outcome.status: {outcomeInfo?.status ?? 'loading…'}
            </span>
            <span
              className="text-[9px] font-mono text-tx-muted/60"
              data-testid="outcome-execution-closed"
            >
              execution_closed: true
            </span>
          </div>
          {outcomeInfo && (
            <p className="text-[9px] font-mono text-tx-muted/60 mt-1">
              found: {String(outcomeInfo.found)} · runner_reachable_from_ui: false
            </p>
          )}
        </div>
        <OutcomeStatusPanel />
      </section>
```

Also, in the authority trace stage rendering, find the `AuthorityTraceStage` call that uses `stage.evidence_ref ?? ''` for `note`. This is already rendering evidence_ref correctly since it passes `stage.evidence_ref ?? ''` as the `note` prop. No change needed there.

- [ ] **Step 8: Run UI tests to verify they pass**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01\ui
npm run test -- --reporter=verbose 2>&1 | tail -15
```

Expected: All UI tests pass (146 existing + new tests). If any new test fails, check the `data-testid` values match exactly.

- [ ] **Step 9: Run Next.js build to verify no build errors**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01\ui
npm run build 2>&1 | tail -20
```

Expected: Build completes without errors.

- [ ] **Step 10: Commit**

```bash
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
git add ui/lib/types.ts ui/lib/api.ts ui/components/sovereign/MissionControlView.tsx ui/components/sovereign/__tests__/MissionControlView.test.tsx
git commit -m "feat(ui): update OutcomeTraceSpace and OrchestrationViewSpace with confirm_pending and outcome status"
```

---

## Task 5: Final validation

**Files:** No code changes — validation only.

- [ ] **Step 1: Run sprint backend tests**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
python -m pytest tests/test_mso_mission_control_truth_contracts.py -v
```

Expected: All tests pass. Count should be 63 (baseline) + new tests from Tasks 1–3.

- [ ] **Step 2: Run full UI tests**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01\ui
npm run test 2>&1 | tail -10
```

Expected: All tests pass. Count should be 146 (baseline) + new tests from Task 4.

- [ ] **Step 3: Run typecheck**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01\ui
npm run typecheck 2>&1 | head -30
```

If `typecheck` script not found:
```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01\ui
npx tsc --noEmit 2>&1 | head -30
```

Expected: No type errors.

- [ ] **Step 4: Run Next.js build**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01\ui
npm run build 2>&1 | tail -10
```

Expected: Build succeeds.

- [ ] **Step 5: Dangerous-language scan**

Search for unsafe language in sprint-modified files:

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
grep -rn "running\|executing\|authorized\|ready to run\|real execution\|runner ready\|live execution" \
  assistant_os/mso/mission_control_status.py \
  assistant_os/webhook_server.py \
  ui/components/sovereign/MissionControlView.tsx \
  ui/lib/types.ts \
  ui/lib/api.ts
```

Every hit must be either:
- A negative assertion (e.g. `!= "running"`)
- Pre-existing unrelated code
- Backed by explicit backend evidence

If any fabricated claim is found, replace with `awaiting_confirmation`, `snapshot`, `architectural`, `unavailable`, or `execution_closed`.

- [ ] **Step 6: Forbidden-path scan**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
grep -rn "from.*runner\|import.*runner\|Runner()\|RunnerClient\|AuthorityArtifact(" \
  ui/app/api/ ui/components/ ui/lib/ ui/hooks/ assistant_os/mso/mission_control_status.py

grep -rn "handle_request\|fabricate\|fake_run\|fake_authority\|fake_policy" \
  ui/app/api/ assistant_os/mso/mission_control_status.py
```

Expected: CLEAN — no Runner imports from UI, no fabrication.

- [ ] **Step 7: Final sprint test run**

```
cd C:\Users\Jorge\Assistant_OS_Labs\.claude\worktrees\outcome-trace-01
python -m pytest tests/test_mso_mission_control_truth_contracts.py --tb=short 2>&1 | tail -10
```

Expected: All sprint tests pass with 0 failures.

---

## Notes on existing baseline failures

The full `pytest` suite (excluding `test_sprint_a1_5_hardening.py` which crashes Python on Windows) has 7–21 pre-existing failures documented in `docs/mso/BASELINE_TEST_DEBT.md`. Do NOT fix those in this sprint. They are pre-existing and unrelated to Mission Control truth contracts.

---

## Future sprints (do NOT implement now)

- **Plan persistence / prepare contract** — `/mso/plans` endpoint for prepare-only read-model
- **Event stream / SSE** — real-time orchestration event channel (requires WebSocket/SSE infrastructure)
- **Live run trace** — authority trace with per-request context (requires execution correlation)
- **Outcome persistence** — durable outcome store backed by DB, not process-local
- **Retirement of Zustand fallbacks** — retire Arms, Orchestration, Trace Zustand fallbacks once backend coverage is validated in CI
