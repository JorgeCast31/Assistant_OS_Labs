# Mission Control Queue Truth Consistency

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two compounding bugs that cause Mission Control's backend to misreport queue state:
1. `_get_queue_counts_for_lifecycle()` filters by `status="prepared"/"awaiting_confirmation"` but real queue items have `status="pending_review"` → always returns (0, 0) → lifecycle snapshot always says "planning"
2. `build_mission_control_status().queues.confirm_pending_count` is hardcoded to 0 → header confirm badge is always 0

**Architecture:** Both bugs share a root cause: the semantic separation of "prepared" vs "awaiting_confirmation" at the queue entry level. In the current model, all items in the queue are simultaneously prepared actions (drafted) and pending confirmation (human review required). The fix is to return `(N, N)` from `_get_queue_counts_for_lifecycle()` where N = total queue size, and to use that helper in `build_mission_control_status()` for both counts.

**Tech Stack:** Python, TypeScript/React (Next.js), pytest, Vitest

**Branch:** New branch off clean main: `fix/mso-queue-truth-consistency`

**Sprint:** S-MISSION-CONTROL-QUEUE-TRUTH-01

---

## Dangerous language policy

Never use: `running · executing · authorized · ready to run · live · real execution · runner ready · completed · successfully executed`

---

## Invariants (never relaxed)

- `execution_allowed = False` everywhere
- `used_execution = False` everywhere
- `source = "backend_read_model"` everywhere
- `current_stage` ∈ `{'planning', 'prepared', 'awaiting_confirmation'}` — never 'running'

---

## Root cause analysis

**`_get_queue_counts_for_lifecycle()`** (mission_control_status.py lines 437–452):

```python
# BROKEN: filters by status that raw queue items never have
prepared = sum(1 for i in items if i.get("status") == "prepared")
confirm  = sum(1 for i in items if i.get("status") == "awaiting_confirmation")
return prepared, confirm  # always (0, 0) — raw items have status="pending_review"
```

**Why items have `status="pending_review"`:**
`ConfirmablePreparedActionQueueEntry.status` is always `"pending_review"` (dataclass default).
The strings `"prepared"` and `"awaiting_confirmation"` are assigned ONLY in `build_orchestration_snapshot()` when constructing the API response — they are NOT stored in the queue.

**Correct behavior:** All `pending_review` items are simultaneously:
- prepared (they were prepared/drafted as actions for review)
- awaiting_confirmation (they cannot execute without human confirmation)
Therefore `_get_queue_counts_for_lifecycle()` should return `(N, N)` where N = total queue size.

**Impact of the bug:**
- `build_lifecycle_snapshot().current_stage` always = `"planning"` (N items → should be "awaiting_confirmation")
- `build_lifecycle_snapshot().queues_at_snapshot` always = `{prepared: 0, confirm: 0}`
- `MSOEscalationSpace.preparedCount` = 0 from backend (should be N)
- `MSOEscalationSpace.confirmCount` = 0 from backend (should be N)
- `MSOEscalationSpace.currentStage` = "planning" from backend (should be "awaiting_confirmation")
- `mcStatus.queues.confirm_pending_count` = 0 (hardcoded, separate issue)

---

## File Map

| Action | Path |
|---|---|
| Modify | `assistant_os/mso/mission_control_status.py` |
| Modify | `tests/test_mso_mission_control_truth_contracts.py` |

**No UI changes required.** The UI already has correct wiring — it reads from `lifecycleData.queues_at_snapshot` and `mcStatus.queues`. Once the backend returns correct data, the UI reflects it automatically.

**No new routes, no new proxies, no new types, no TypeScript changes required.**

---

## Task 1: Fix _get_queue_counts_for_lifecycle() and build_mission_control_status().queues

**Goal:** Replace the always-zero status-based filtering with total-queue-count. Wire mcStatus.queues.confirm_pending_count to use the real count.

**Files:**
- Modify: `assistant_os/mso/mission_control_status.py`
  - `_get_queue_counts_for_lifecycle()` (~line 437)
  - `build_mission_control_status()` (~line 34, queues section ~line 151)

**Risk level:** Low — read-only, same queue function already called
**Authority risk:** None — no execution, no new state, no new endpoints

- [ ] **Step 1: Write failing tests first**

Add to `tests/test_mso_mission_control_truth_contracts.py`, in `TestBuildLifecycleSnapshot` class (or a new `TestGetQueueCountsForLifecycle` class), after existing tests:

```python
class TestGetQueueCountsForLifecycle:
    """_get_queue_counts_for_lifecycle() — real queue integration."""

    def test_returns_tuple_of_two_ints(self):
        from assistant_os.mso.mission_control_status import _get_queue_counts_for_lifecycle
        result = _get_queue_counts_for_lifecycle()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(isinstance(v, int) for v in result)

    def test_both_counts_equal(self):
        """Prepared and confirm counts must be equal — same items in both views."""
        from assistant_os.mso.mission_control_status import _get_queue_counts_for_lifecycle
        prepared, confirm = _get_queue_counts_for_lifecycle()
        assert prepared == confirm, (
            f"prepared={prepared} != confirm={confirm}: "
            "all queue items are simultaneously prepared and awaiting confirmation"
        )

    def test_counts_reflect_real_queue_size(self):
        """After enqueueing N items, both counts should equal N."""
        from assistant_os.mso.confirmable_prepared_action import ConfirmablePreparedAction
        from assistant_os.mso.prepared_action_queue import enqueue_confirmable_prepared_action
        from assistant_os.mso.mission_control_status import _get_queue_counts_for_lifecycle
        for i in range(3):
            action = ConfirmablePreparedAction(
                preparation_id=f"prep-queue-count-{i}",
                proposal_id=f"prop-queue-count-{i}",
                user_intent=f"queue count test intent {i}",
                domain="CODE",
                requested_action=f"queue_count_test_{i}",
                capability_name="code_execution",
            )
            enqueue_confirmable_prepared_action(action)
        prepared, confirm = _get_queue_counts_for_lifecycle()
        assert prepared >= 3, f"prepared_count={prepared} expected >= 3 after enqueueing 3 items"
        assert confirm >= 3, f"confirm_count={confirm} expected >= 3 after enqueueing 3 items"


class TestMCStatusQueuesConsistency:
    """build_mission_control_status().queues — both counts must be consistent."""

    def test_confirm_pending_count_is_not_hardcoded_zero(self, monkeypatch):
        """confirm_pending_count must not always be 0 when queue has items."""
        from assistant_os.mso import mission_control_status
        monkeypatch.setattr(
            mission_control_status,
            "_get_queue_counts_for_lifecycle",
            lambda: (5, 5),  # simulate 5 items in queue
        )
        from assistant_os.mso.mission_control_status import build_mission_control_status
        result = build_mission_control_status()
        assert result["queues"]["confirm_pending_count"] == 5, (
            f"confirm_pending_count={result['queues']['confirm_pending_count']} "
            "expected 5 — not hardcoded 0"
        )

    def test_prepared_actions_count_matches_confirm_pending_count(self, monkeypatch):
        """Both queue counts must be equal — they reflect the same queue items."""
        from assistant_os.mso import mission_control_status
        monkeypatch.setattr(
            mission_control_status,
            "_get_queue_counts_for_lifecycle",
            lambda: (3, 3),
        )
        from assistant_os.mso.mission_control_status import build_mission_control_status
        result = build_mission_control_status()
        assert result["queues"]["prepared_actions_count"] == result["queues"]["confirm_pending_count"]

    def test_lifecycle_stage_is_awaiting_confirmation_with_real_items(self, monkeypatch):
        """lifecycle snapshot should show awaiting_confirmation when queue has items."""
        from assistant_os.mso import mission_control_status
        monkeypatch.setattr(
            mission_control_status,
            "_get_queue_counts_for_lifecycle",
            lambda: (2, 2),  # simulate 2 items in queue
        )
        from assistant_os.mso.mission_control_status import build_lifecycle_snapshot
        result = build_lifecycle_snapshot()
        assert result["current_stage"] == "awaiting_confirmation", (
            f"current_stage={result['current_stage']!r} expected 'awaiting_confirmation' "
            "when queue has items"
        )
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd "C:\Users\Jorge\Assistant_OS_Labs"
set PYTHONUTF8=1 && python -m pytest tests/test_mso_mission_control_truth_contracts.py::TestGetQueueCountsForLifecycle tests/test_mso_mission_control_truth_contracts.py::TestMCStatusQueuesConsistency -v 2>&1 | tail -20
```

Expected: failures on `test_both_counts_equal`, `test_counts_reflect_real_queue_size`, `test_confirm_pending_count_is_not_hardcoded_zero`, `test_prepared_actions_count_matches_confirm_pending_count`, `test_lifecycle_stage_is_awaiting_confirmation_with_real_items`.

- [ ] **Step 3: Fix _get_queue_counts_for_lifecycle()**

In `assistant_os/mso/mission_control_status.py`, find `_get_queue_counts_for_lifecycle()` (around line 437).

Replace:
```python
def _get_queue_counts_for_lifecycle() -> tuple[int, int]:
    """
    Return (prepared_actions_count, confirm_pending_count) from the queue.

    Separated so tests can monkeypatch without touching the real queue.
    Returns (0, 0) on any failure — fail-soft.
    """
    try:
        from .prepared_action_queue import list_pending_confirmable_action_dicts

        items = list_pending_confirmable_action_dicts()
        prepared = sum(1 for i in items if i.get("status") == "prepared")
        confirm = sum(1 for i in items if i.get("status") == "awaiting_confirmation")
        return prepared, confirm
    except Exception:  # noqa: BLE001
        return 0, 0
```

With:
```python
def _get_queue_counts_for_lifecycle() -> tuple[int, int]:
    """
    Return (prepared_actions_count, confirm_pending_count) from the queue.

    Separated so tests can monkeypatch without touching the real queue.
    Returns (0, 0) on any failure — fail-soft.

    Semantic note
    -------------
    All items in the prepared-action queue have queue-level status="pending_review".
    The strings "prepared" and "awaiting_confirmation" are semantic views applied
    at the read-model layer (build_orchestration_snapshot), NOT stored on the entry.

    Every pending-review item is simultaneously:
    - a prepared action (it has been drafted for review)
    - awaiting human confirmation (it cannot execute without explicit confirmation)

    Therefore both counts equal the total queue size. There is no sub-state of
    "prepared but not awaiting confirmation" in the current queue model.
    """
    try:
        from .prepared_action_queue import list_pending_confirmable_action_dicts

        total = len(list_pending_confirmable_action_dicts())
        return total, total  # both counts = N: all items are prepared and awaiting confirmation
    except Exception:  # noqa: BLE001
        return 0, 0
```

- [ ] **Step 4: Fix build_mission_control_status() to use the helper**

Find the `prepared_actions_count` section in `build_mission_control_status()` (around line 76):

Replace:
```python
    # -- Prepared action queue count -----------------------------------------
    prepared_actions_count = 0
    try:
        from .prepared_action_queue import list_pending_confirmable_action_dicts
        prepared_actions_count = len(list_pending_confirmable_action_dicts())
    except Exception:
        prepared_actions_count = 0
```

With:
```python
    # -- Queue counts (prepared actions and confirm pending share the same items) -
    # Use _get_queue_counts_for_lifecycle() as the single source for queue counts.
    # Both prepared_actions_count and confirm_pending_count reflect the total queue
    # size — all items are simultaneously prepared and awaiting confirmation.
    _prepared_count, _confirm_pending_count = _get_queue_counts_for_lifecycle()
    prepared_actions_count = _prepared_count
```

Then in the `"queues"` section of the return dict, replace:
```python
        "queues": {
            "prepared_actions_count": prepared_actions_count,
            "confirm_pending_count": 0,  # confirm queue not separate at this layer
        },
```

With:
```python
        "queues": {
            "prepared_actions_count": prepared_actions_count,
            "confirm_pending_count": _confirm_pending_count,
        },
```

- [ ] **Step 5: Run new tests to confirm they pass**

```bash
set PYTHONUTF8=1 && python -m pytest tests/test_mso_mission_control_truth_contracts.py::TestGetQueueCountsForLifecycle tests/test_mso_mission_control_truth_contracts.py::TestMCStatusQueuesConsistency -v 2>&1 | tail -20
```

Expected: all new tests pass.

- [ ] **Step 6: Run full Python truth suite**

```bash
set PYTHONUTF8=1 && python -m pytest tests/test_mso_mission_control_truth_contracts.py 2>&1 | tail -5
```

Expected: all tests pass (107 pre-existing + new tests).

- [ ] **Step 7: Commit**

```bash
git add assistant_os/mso/mission_control_status.py tests/test_mso_mission_control_truth_contracts.py
git commit -m "fix(mso): align queue counts — confirm_pending_count was hardcoded 0, lifecycle always returned planning"
```

---

## Task 2: Safety scans + validation + PR

**Goal:** Confirm all suites pass, scans clean, open PR.

**Files:** None changed — validation and PR only

- [ ] **Step 1: Full Python suite**

```bash
set PYTHONUTF8=1 && python -m pytest tests/test_mso_mission_control_truth_contracts.py 2>&1 | tail -5
```

- [ ] **Step 2: Full UI suite + TypeScript + build**

No UI changes in this sprint, but validate baseline holds:

```bash
cd ui
npx vitest run 2>&1 | tail -5
npx tsc --noEmit 2>&1; echo "EXIT:$?"
npx next build 2>&1 | grep -E "compiled|Error" | tail -5
```

Expected: 157 UI tests pass, TypeScript EXIT:0, build compiled.

- [ ] **Step 3: Dangerous-language scan**

```bash
grep -rn "running\|executing\|authorized\|ready to run\|live execution\|runner ready\|successfully executed" \
  assistant_os/mso/mission_control_status.py \
  | grep -v "//\|execution_allowed\|used_execution\|liveExecution\|live_execution\|event_stream\|closed\|unavailable\|awaiting_confirmation\|runner_reachable\|block\|NEVER\|not\|#"
```

Expected: zero hits in new code.

- [ ] **Step 4: Forbidden-path scan**

```bash
grep -rn "handle_request\|issue_token\|AuthorityArtifact\|fabricat\|fake.*run\|fake.*policy\|Police.*bypass" \
  assistant_os/mso/mission_control_status.py
```

Expected: zero hits (only pre-existing "Never fabricated" comments).

- [ ] **Step 5: Push and open PR**

```bash
git push origin fix/mso-queue-truth-consistency
gh pr create --title "fix(mso): align mission-control queue counts with backend truth" --body "..."
```

PR body template:

```markdown
## Summary
Fix two compounding bugs that cause Mission Control to misreport queue state:
1. `_get_queue_counts_for_lifecycle()` filtered by `status="prepared"/"awaiting_confirmation"` but real queue entries have `status="pending_review"` → always returned (0,0) → lifecycle snapshot always reported "planning"
2. `build_mission_control_status().queues.confirm_pending_count` was hardcoded to 0 → header confirm badge always showed 0

## Capability map delta
**Before:** lifecycle always says "planning" · mcStatus.queues.confirm_pending_count always 0
**After:** lifecycle reflects real queue state · confirm_pending_count = real count

## Files changed
- `assistant_os/mso/mission_control_status.py` — fix _get_queue_counts_for_lifecycle(), wire build_mission_control_status()
- `tests/test_mso_mission_control_truth_contracts.py` — new test classes

## Contracts changed
- `build_mission_control_status().queues.confirm_pending_count`: was 0 hardcoded, now = real queue size
- `_get_queue_counts_for_lifecycle()`: was (0, 0) always (status filter bug), now = (N, N)
- `build_lifecycle_snapshot().current_stage`: was always "planning", now = "awaiting_confirmation" when N > 0
- `build_lifecycle_snapshot().queues_at_snapshot`: was always {0, 0}, now {N, N}

## Tests
- Python truth contracts: all pass
- UI: 157 pass (no UI changes)
- TypeScript: EXIT:0
- Build: compiled

## Safety invariants
- execution_allowed: false (unchanged)
- used_execution: false (unchanged)
- runner_reachable_from_ui: false (unchanged)
- Runner: not called
- Police: not bypassed
- AuthorityArtifact: not created
- Tokens: not issued

## Dangerous-language scan: clean (zero hits in new code)
## Forbidden-path scan: clean (zero hits)

## Known residual debt
- 'running' still in MissionLifecycleState union type (backward compat)
- No Planner draft persistence (separate sprint, requires explicit approval for write surface)

## Recommended next target
TypeScript literal safety — remove 'running' from MissionLifecycleState or
document its valid backend-evidence-only semantics.

Do not merge without explicit human approval.
```

---

## Risk Summary

| Task | Authority Risk | Complexity | Rollback |
|---|---|---|---|
| Task 1: Fix queue counts | None | Low — 2 small edits + tests | Revert 2 code sections |
| Task 2: Validation + PR | None | None | N/A |

## Out of scope

- POST /plans, POST /prepare
- WebSocket/SSE
- Token issuance
- Runner invocation
- 'running' removal from TypeScript type
- Any execution surface
