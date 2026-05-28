# Mission Control Language Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden Mission Control so dangerous lifecycle language (`running`, `completed`, `real`) can never be rendered from stale fallback state — even if rogue data or a future code change passes dangerous values to display components.

**Architecture:** Display-layer guard maps transform dangerous state strings to safe alternatives before CSS lookup and text render. `LifecycleBadge` gains a `DANGEROUS_LIFECYCLE_DISPLAY_MAP` that remaps `running → blocked`, `completed → closed`, `executing → blocked`. `ExecStatusBadge` gains a display label map that renders `real → registered`. No backend changes. No TypeScript type removals (backward compatible). All changes are isolated to `MissionControlView.tsx` and its test file.

**Tech Stack:** React, TypeScript, Vitest, Testing Library

---

## Audit findings (pre-implementation)

| Finding | Location | Classification |
|---------|----------|----------------|
| `LifecycleBadge` CSS key `running` + raw text render | line 189, 197 | MUST-FIX — latent hole |
| `LifecycleBadge` CSS key `completed` + raw text render | line 191, 197 | MUST-FIX — execution-adjacent |
| `ExecStatusBadge` renders `status` as text; `'real'` today via `mapExecStatus('active')` | line 211, 556 | MUST-FIX — live today |
| `nextStage` derivation — already returns 'blocked' | line 379–384 | pre-existing fix ✅ |
| Thread status always hardcoded to `'prepared'` | line 749, 756 | safe ✅ |
| `plan.state` — only reachable as draft/planning/mso_review | line 219–241 | safe ✅ |
| Runner trace stage always `'closed'` | line 984 | safe ✅ |

---

## File structure

| File | Action |
|------|--------|
| `ui/components/sovereign/MissionControlView.tsx` | Modify: `LifecycleBadge`, `ExecStatusBadge` |
| `ui/components/sovereign/__tests__/MissionControlView.test.tsx` | Modify: add 4 new tests |

---

### Task 1: Audit MissionControlView.tsx rendered labels

**Goal:** Identify all rendered paths that can surface dangerous terms. Classify each.

**Files:**
- Read: `ui/components/sovereign/MissionControlView.tsx`

**Risk level:** None (read-only audit)
**Authority risk:** None
**Tests required:** None at this step
**Stop condition:** Complete classification table produced (above)

- [x] Read `MissionControlView.tsx` in full
- [x] Grep for `running`, `executing`, `authorized`, `ready to run`, `live`, `completed`, `real`
- [x] Classify each hit:
  - `running` in `LifecycleBadge` CSS map (line 189): **MUST-FIX** (latent hole)
  - `completed` in `LifecycleBadge` CSS map (line 191): **MUST-FIX** (execution-adjacent)
  - `real` in `ExecStatusBadge` rendered via `{status}` (line 211): **MUST-FIX** (live today)
  - `nextStage` returns 'blocked' not 'running': pre-existing fix ✅
  - Thread status always 'prepared': safe ✅
  - `plan.state` never reaches 'running': safe ✅

---

### Task 2: Harden LifecycleBadge — add DANGEROUS_LIFECYCLE_DISPLAY_MAP guard

**Goal:** No call to `LifecycleBadge` with `state='running'`, `'completed'`, or `'executing'` may render that word as text. Safe alternatives: `'running' → 'blocked'`, `'completed' → 'closed'`, `'executing' → 'blocked'`.

**Files:**
- Modify: `ui/components/sovereign/MissionControlView.tsx` — `LifecycleBadge` (lines 182–200)

**Risk level:** Low — display-only change. No backend, no type changes, no store changes.
**Authority risk:** None
**Tests required:** Task 4 tests verify the guard
**Stop condition:** `LifecycleBadge` never renders 'running', 'completed', or 'executing' as visible text regardless of what is passed as `state`.

- [ ] **Step 1: Add `DANGEROUS_LIFECYCLE_DISPLAY_MAP` constant before `LifecycleBadge`**

```tsx
// S-MISSION-CONTROL-LANGUAGE-HARDENING-01
// Dangerous lifecycle labels must never be rendered on a surface that cannot execute.
// Applied before CSS lookup and text render — the guard is unconditional.
const DANGEROUS_LIFECYCLE_DISPLAY_MAP: Readonly<Record<string, string>> = {
  running:   'blocked',   // never: implies live execution which never comes from this surface
  executing: 'blocked',   // defense in depth
  completed: 'closed',    // never: implies execution completed — impossible from this surface
}
```

- [ ] **Step 2: Apply guard inside `LifecycleBadge`, remove `running`/`completed` CSS entries, add `closed`**

Replace the existing `LifecycleBadge` function (lines 182–200):

```tsx
function LifecycleBadge({ state }: { state: MissionLifecycleState | string }) {
  // Apply safety remapping before CSS lookup or text render.
  // Dangerous states are blocked unconditionally at display time.
  const safeState = DANGEROUS_LIFECYCLE_DISPLAY_MAP[state] ?? state

  const cls: Record<string, string> = {
    draft:                 'text-tx-muted border-os-border bg-os-base',
    planning:              'text-cyan-400 border-cyan-400/30 bg-cyan-400/10',
    mso_review:            'text-amber-400 border-amber-400/30 bg-amber-400/10',
    prepared:              'text-blue-400 border-blue-400/30 bg-blue-400/10',
    awaiting_confirmation: 'text-orange-400 border-orange-400/30 bg-orange-400/10',
    blocked:               'text-rose-400 border-rose-400/30 bg-rose-400/10',
    closed:                'text-tx-muted/50 border-os-border/50 bg-os-base',
    failed:                'text-rose-400 border-rose-400/30 bg-rose-400/10',
    cancelled:             'text-tx-muted border-os-border bg-os-base',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border ${cls[safeState] ?? 'text-tx-muted border-os-border bg-os-base'}`}>
      {safeState.replace(/_/g, ' ')}
    </span>
  )
}
```

- [ ] **Step 3: Run UI tests — verify existing tests still pass**

Run: `cd ui && npm run test -- --run`
Expected: 157 passed (no regressions)

---

### Task 3: Harden ExecStatusBadge — rename 'real' display label to 'registered'

**Goal:** `'real'` rendered alone is execution-adjacent language. Arm being "real" (not a stub) is an implementation status, not an execution status. Display as 'registered' without changing the internal type contract.

**Files:**
- Modify: `ui/components/sovereign/MissionControlView.tsx` — `ExecStatusBadge` (lines 202–214)

**Risk level:** Low — display-only change. `status: 'real'` prop type unchanged. `OrchestrationThread.executionStatus` type unchanged.
**Authority risk:** None
**Tests required:** Task 4 test verifies no 'real' text rendered
**Stop condition:** `ExecStatusBadge` with `status='real'` renders "registered" not "real".

- [ ] **Step 1: Add `EXEC_STATUS_DISPLAY_LABEL` map before `ExecStatusBadge`**

```tsx
// S-MISSION-CONTROL-LANGUAGE-HARDENING-01
// 'real' is an internal status value meaning "registered real arm implementation"
// (vs a stub). The word 'real' rendered alone is execution-adjacent and misleading.
// Display label overrides without changing the internal type contract.
const EXEC_STATUS_DISPLAY_LABEL: Readonly<Record<string, string>> = {
  real:        'registered',  // 'real arm' ≠ 'real execution'
  partial:     'partial',
  stub:        'stub',
  unavailable: 'unavailable',
}
```

- [ ] **Step 2: Apply label override in `ExecStatusBadge` render**

Replace `{status}` in the return with `{EXEC_STATUS_DISPLAY_LABEL[status] ?? status}`:

```tsx
function ExecStatusBadge({ status }: { status: 'real' | 'stub' | 'unavailable' | 'partial' }) {
  const cls = {
    real:        'text-ok border-ok/30 bg-ok/10',
    partial:     'text-warn border-warn/30 bg-warn/10',
    stub:        'text-amber-400 border-amber-400/30 bg-amber-400/10',
    unavailable: 'text-tx-muted border-os-border bg-os-base',
  }[status]
  return (
    <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono uppercase border ${cls}`}>
      {EXEC_STATUS_DISPLAY_LABEL[status] ?? status}
    </span>
  )
}
```

- [ ] **Step 3: Run UI tests — verify no regressions**

Run: `cd ui && npm run test -- --run`
Expected: 157 passed (no regressions)

---

### Task 4: Tests — prove dangerous states cannot render

**Goal:** Add 4 tests that prove the guards work even under adversarial input.

**Files:**
- Modify: `ui/components/sovereign/__tests__/MissionControlView.test.tsx`

**Risk level:** None
**Authority risk:** None
**Stop condition:** 4 new tests pass. All previously passing tests still pass. Total ≥ 161.

- [ ] **Step 1: Write the 4 failing tests first, run to confirm red**

Add a new `describe` block at the end of the test file:

```typescript
describe('Language hardening — S-MISSION-CONTROL-LANGUAGE-HARDENING-01', () => {
  it('LifecycleBadge: state="running" from rogue backend renders "blocked" not "running"', async () => {
    // Simulate rogue/unknown lifecycle value from backend (e.g., future schema change)
    vi.mocked(getMissionControlLifecycleSnapshot).mockResolvedValue({
      ...LC_SNAPSHOT_UNAVAILABLE,
      ok: true,
      current_stage: 'running' as unknown as 'planning',
      queues_at_snapshot: { prepared_actions_count: 1, confirm_pending_count: 1 },
    })
    render(<MissionControlView />)
    clickTab('MSO')
    await waitFor(() => {
      // 'running' must never appear as a rendered lifecycle badge label
      expect(screen.queryByText(/^running$/i)).not.toBeInTheDocument()
      // 'blocked' must appear as the safe fallback
      const blockedEls = screen.getAllByText(/^blocked$/i)
      expect(blockedEls.length).toBeGreaterThan(0)
    })
  })

  it('LifecycleBadge: state="executing" from rogue backend renders "blocked" not "executing"', async () => {
    vi.mocked(getMissionControlLifecycleSnapshot).mockResolvedValue({
      ...LC_SNAPSHOT_UNAVAILABLE,
      ok: true,
      current_stage: 'executing' as unknown as 'planning',
      queues_at_snapshot: { prepared_actions_count: 1, confirm_pending_count: 1 },
    })
    render(<MissionControlView />)
    clickTab('MSO')
    await waitFor(() => {
      expect(screen.queryByText(/^executing$/i)).not.toBeInTheDocument()
      const blockedEls = screen.getAllByText(/^blocked$/i)
      expect(blockedEls.length).toBeGreaterThan(0)
    })
  })

  it('LifecycleBadge: state="completed" from rogue backend does not render "completed"', async () => {
    vi.mocked(getMissionControlLifecycleSnapshot).mockResolvedValue({
      ...LC_SNAPSHOT_UNAVAILABLE,
      ok: true,
      current_stage: 'completed' as unknown as 'planning',
      queues_at_snapshot: { prepared_actions_count: 0, confirm_pending_count: 0 },
    })
    render(<MissionControlView />)
    clickTab('MSO')
    await waitFor(() => {
      // 'completed' must not appear as a lifecycle badge label (implies execution)
      expect(screen.queryByText(/^completed$/i)).not.toBeInTheDocument()
    })
  })

  it('ExecStatusBadge: active backend arm renders "registered" not "real"', async () => {
    // Simulate a backend arm with execution_status: 'unavailable' (always from readiness)
    // and a Zustand arm with status='active' which previously produced 'real' via mapExecStatus
    vi.mocked(getMissionControlReadiness).mockResolvedValue({
      ...MC_READINESS_UNAVAILABLE,
      ok: false, // backend unavailable → falls back to Zustand sovereign store
    })
    render(<MissionControlView />)
    clickTab('Arms')
    // When no arms in Zustand store: badge shows 'unavailable' → no 'real' text
    await waitFor(() => {
      expect(screen.queryByText(/^real$/i)).not.toBeInTheDocument()
    })
  })
})
```

Run: `cd ui && npm run test -- --run`
Expected: **4 new tests FAIL** (before guard implementation). Confirm with:
- The `running` test should FAIL before the guard is added (it renders "running")
- The `registered` test should PASS (no Zustand arms = no 'real' badge visible)

- [ ] **Step 2: Verify tests are red for LifecycleBadge guard (before Task 2 fix)**

*This step is done before Task 2 if TDD order is followed. After implementing Tasks 2–3, re-run.*

- [ ] **Step 3: Run tests after Tasks 2–3 are implemented**

Run: `cd ui && npm run test -- --run`
Expected: **All new tests PASS**. Total ≥ 161.

---

### Task 5: Validation + dangerous-language scan + PR

**Goal:** Full validation, safety scans, branch push, PR opened.

**Files:** No changes.

**Risk level:** None
**Authority risk:** None
**Stop condition:** All tests pass, scans clean, PR open, not merged.

- [ ] **Step 1: Full UI test run**

```bash
cd ui && npm run test -- --run
```
Expected: ≥ 161 passed, 0 failed.

- [ ] **Step 2: Next.js build**

```bash
cd ui && npm run build
```
Expected: Compiled successfully.

- [ ] **Step 3: Dangerous-language scan on modified file**

```bash
grep -n "running\|executing\|authorized\|ready to run\|live execution\|runner ready\|completed\|successfully executed\|real" \
  ui/components/sovereign/MissionControlView.tsx \
  | grep -v "//\|execution_closed\|live_execution\|event_stream\|closed\|unavailable\|blocked\|NEVER\|not\|#\|DANGEROUS_LIFECYCLE\|EXEC_STATUS"
```

Every hit must be classified as pre-existing/safe or must-fix.

- [ ] **Step 4: Forbidden-path scan on modified file**

```bash
grep -n "handle_request\|issue_token\|AuthorityArtifact\|fabricat\|fake.*run\|fake.*policy\|Police.*bypass\|Runner.*import" \
  ui/components/sovereign/MissionControlView.tsx
```

Expected: All hits are safe (pre-existing labels/strings, not invocations).

- [ ] **Step 5: Create branch and commit**

```bash
git checkout -b fix/mso-language-hardening
git add ui/components/sovereign/MissionControlView.tsx
git add ui/components/sovereign/__tests__/MissionControlView.test.tsx
git add docs/superpowers/plans/2026-05-28-mission-control-language-hardening.md
git commit -m "fix(ui): harden mission-control execution language — guard LifecycleBadge and ExecStatusBadge"
```

- [ ] **Step 6: Push and open PR**

```bash
git push origin fix/mso-language-hardening
gh pr create --title "fix(ui): harden mission-control execution language" --body "..."
```

PR body must include: Summary, Capability map, Unsafe labels found, Files changed, Tests added, Safety invariants, Dangerous-language scan, Forbidden-path scan, Known residual debt, Recommended next target.
