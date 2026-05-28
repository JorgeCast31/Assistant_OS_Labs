# Mission Control Thread State Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Narrow `OrchestrationThread.status` from the broad `MissionLifecycleState` union (8 members) to a dedicated `OrchestrationThreadStatus = 'prepared'` literal type — the only value an MC thread card can ever display. This eliminates 7 unreachable states at compile time and removes the defensive `as MissionLifecycleState` casts.

**Architecture:** One new type alias and one interface field change in `ui/lib/types.ts`. One cast cleanup in `MissionControlView.tsx` (remove `as MissionLifecycleState` on lines 773 and 780). No runtime behavior changes. TypeScript compilation is the primary validator.

**Tech Stack:** TypeScript, Vitest

---

## Type audit findings (pre-implementation)

| Location | Value assigned to `OrchestrationThread.status` | Path |
|----------|------------------------------------------------|------|
| `MissionControlView.tsx:773` | `'prepared' as MissionLifecycleState` | Backend snapshot path |
| `MissionControlView.tsx:780` | `'prepared' as MissionLifecycleState` | Zustand fallback path |

**Values that can NEVER appear on `OrchestrationThread.status`:**
- `'draft'`, `'planning'`, `'mso_review'` — plan states, not thread states
- `'awaiting_confirmation'` — never assigned
- `'blocked'`, `'failed'`, `'cancelled'` — never assigned

**Only consumer files:** `ui/lib/types.ts` (definition) + `ui/components/sovereign/MissionControlView.tsx` (only consumer). Confirmed via filesystem grep.

**TypeScript baseline:** `npx tsc --noEmit` → EXIT:0

---

## Capability map

```
What Mission Control can do now:
- Display prepared action queue items as read-only thread cards
- Show lifecycle badges (no running/completed/executing — hardened in #220/#221)
- Show plan status (draft/planning/mso_review — hardened in #222)
- Show arm registry (registered/unavailable labels)
- Escalate plan drafts to MSO (local state + redirect only)
- Display authority trace + outcome status (read-only)

What backend truth exists:
- GET /api/mso/mission-control/status
- GET /api/mso/mission-control/orchestration-snapshot
- GET /api/mso/mission-control/lifecycle-snapshot
- GET /api/mso/mission-control/authority-trace

What thread-state type risks remain after this sprint:
- None: OrchestrationThread.status fully narrowed to 'prepared'
```

---

## File structure

| File | Action |
|------|--------|
| `ui/lib/types.ts` | Add `OrchestrationThreadStatus` type alias; narrow `OrchestrationThread.status` |
| `ui/components/sovereign/MissionControlView.tsx` | Remove `as MissionLifecycleState` casts on lines 773 and 780 |

---

### Task 1: Type audit (COMPLETE — in-session)

- [x] Locate all `OrchestrationThread.status` assignments in the codebase
- [x] Confirm both assignments are `'prepared'` (lines 773 and 780 of MissionControlView.tsx)
- [x] Confirm only 2 consumer files: `types.ts` + `MissionControlView.tsx`
- [x] Confirm no test file constructs `OrchestrationThread` directly
- [x] Run TypeScript baseline: `npx tsc --noEmit` → EXIT:0

---

### Task 2: Add OrchestrationThreadStatus and narrow OrchestrationThread.status

**Goal:** `OrchestrationThread.status` is narrowed to `OrchestrationThreadStatus = 'prepared'`. Any future code assigning `'running'`, `'blocked'`, `'completed'`, etc. to a thread's status will fail at compile time.

**Files:**
- Modify: `ui/lib/types.ts` — `OrchestrationThread` interface
- Modify: `ui/components/sovereign/MissionControlView.tsx` — remove `as MissionLifecycleState` casts

**Risk level:** Low — single consumer file, all runtime values conform.
**Authority risk:** None — type-level only.
**Tests required:** `npx tsc --noEmit` → EXIT:0
**Stop condition:** TypeScript compiles clean. `OrchestrationThread.status` cannot be assigned any execution-adjacent state.

- [ ] **Step 1: Add `OrchestrationThreadStatus` type alias in `ui/lib/types.ts`**

Insert before the `OrchestrationThread` interface (currently around line 866):

```typescript
// S-MISSION-CONTROL-THREAD-STATE-HARDENING-01
// OrchestrationThread represents a read-only UI projection of a prepared action.
// It is not a runtime execution thread. The only reachable status is 'prepared'.
// Narrowing prevents execution-adjacent states (running, blocked, failed, etc.)
// from ever appearing on a thread card at compile time.
export type OrchestrationThreadStatus = 'prepared'
```

- [ ] **Step 2: Update `OrchestrationThread.status` field type**

Replace:
```typescript
export interface OrchestrationThread {
  id: string
  label: string
  status: MissionLifecycleState
  assignedArm?: string
  lastEvent?: string
  // S-MISSION-CONTROL-TYPE-HARDENING-01
  // Narrowed to 'unavailable': MC threads never claim real/stub/partial execution.
  // ExecStatusBadge still accepts the full ExecutionStatus union for arms — separate prop type.
  executionStatus?: 'unavailable'
}
```

With:
```typescript
export interface OrchestrationThread {
  id: string
  label: string
  // S-MISSION-CONTROL-THREAD-STATE-HARDENING-01
  // Narrowed from MissionLifecycleState: thread cards only ever show 'prepared'.
  // OrchestrationThread is a read-only UI projection of a PreparedAction, not a
  // runtime execution thread. Execution-adjacent states are unreachable.
  status: OrchestrationThreadStatus
  assignedArm?: string
  lastEvent?: string
  // S-MISSION-CONTROL-TYPE-HARDENING-01
  // Narrowed to 'unavailable': MC threads never claim real/stub/partial execution.
  // ExecStatusBadge still accepts the full ExecutionStatus union for arms — separate prop type.
  executionStatus?: 'unavailable'
}
```

- [ ] **Step 3: Remove `as MissionLifecycleState` casts in `MissionControlView.tsx`**

Replace in the backend snapshot path (line 773):
```typescript
        status:        'prepared' as MissionLifecycleState,
```
With:
```typescript
        status:        'prepared',
```

Replace in the Zustand fallback path (line 780):
```typescript
        status:        'prepared' as MissionLifecycleState,
```
With:
```typescript
        status:        'prepared',
```

- [ ] **Step 4: Update import in `MissionControlView.tsx`**

The import `MissionLifecycleState` may still be needed for `LifecycleBadge`'s prop type. Verify it remains referenced. If not referenced elsewhere, remove it. If still referenced, leave unchanged.

Verify with:
```bash
grep -n "MissionLifecycleState" ui/components/sovereign/MissionControlView.tsx
```

- [ ] **Step 5: Verify TypeScript compiles clean**

```bash
cd ui && npx tsc --noEmit 2>&1; echo "EXIT:$?"
```
Expected: `EXIT:0`

---

### Task 3: Validation

**Goal:** All 161 tests pass. TypeScript clean. Build compiles.

**Risk level:** None
**Authority risk:** None
**Stop condition:** All green.

- [ ] **Step 1: Run full UI test suite**

```bash
cd ui && npm run test -- --run
```
Expected: 161 passed, 0 failed.

- [ ] **Step 2: Run TypeScript check**

```bash
cd ui && npx tsc --noEmit 2>&1; echo "EXIT:$?"
```
Expected: `EXIT:0`

- [ ] **Step 3: Run Next.js build**

```bash
cd ui && npm run build 2>&1 | tail -5
```
Expected: Compiled successfully.

---

### Task 4: Safety scan + PR

**Goal:** Dangerous-language and forbidden-path scans on changed files. Branch push. PR opened.

**Risk level:** None
**Authority risk:** None
**Stop condition:** Scans clean, PR open, not merged.

- [ ] **Step 1: Dangerous-language scan on changed files**

```bash
grep -n "running\|executing\|authorized\|ready to run\|live execution\|runner ready\|completed\|successfully executed\|real" \
  ui/lib/types.ts ui/components/sovereign/MissionControlView.tsx \
  | grep -v "//\|not\|NEVER\|DANGEROUS\|closed\|unavailable\|blocked\|EXEC_STATUS\|LIFECYCLE"
```

Classify every hit.

- [ ] **Step 2: Forbidden-path scan on changed files**

```bash
grep -n "handle_request\|issue_token\|AuthorityArtifact\|fabricat\|fake.*run\|Police.*bypass" \
  ui/lib/types.ts ui/components/sovereign/MissionControlView.tsx
```

- [ ] **Step 3: Create branch and commit**

```bash
git checkout -b fix/mso-thread-status-narrowing
git add ui/lib/types.ts ui/components/sovereign/MissionControlView.tsx \
  docs/superpowers/plans/2026-05-28-mission-control-thread-state-hardening.md
git commit -m "fix(ui): narrow OrchestrationThread.status to OrchestrationThreadStatus"
```

- [ ] **Step 4: Push and open PR**

```bash
git push origin fix/mso-thread-status-narrowing
gh pr create --repo JorgeCast31/Assistant_OS_Labs \
  --head fix/mso-thread-status-narrowing \
  --base main \
  --title "fix(ui): narrow mission-control thread state" \
  --body "..."
```
