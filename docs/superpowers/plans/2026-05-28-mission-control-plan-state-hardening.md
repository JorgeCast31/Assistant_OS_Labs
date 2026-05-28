# Mission Control Plan State Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Narrow `MissionControlPlan.state` from the broad `MissionLifecycleState` union to a dedicated `MissionControlPlanState = 'draft' | 'planning' | 'mso_review'` — the only values a local plan can ever hold. This eliminates 5 unreachable states (`prepared`, `awaiting_confirmation`, `blocked`, `failed`, `cancelled`) at compile time.

**Architecture:** One new type alias and one interface field change in `ui/lib/types.ts`. No runtime behavior changes. `MissionControlView.tsx` needs no code changes — all runtime values already conform to the narrowed type. TypeScript compilation (`npx tsc --noEmit`) is the primary validator.

**Tech Stack:** TypeScript, Vitest

---

## Type audit findings (pre-implementation)

| Type | Current field type | Values actually used | Safe to narrow? |
|------|-------------------|---------------------|-----------------|
| `MissionControlPlan.state` | `MissionLifecycleState` | `'draft'`, `'planning'`, `'mso_review'` only | ✅ YES |
| `MissionLifecycleState` | (global union) | Used broadly elsewhere | ❌ NO — do not touch |

**Consumers of `MissionControlPlan`:**
- `ui/lib/types.ts` — definition (1 location)
- `ui/components/sovereign/MissionControlView.tsx` — ONLY consumer (import + `useState<MissionControlPlan>`)
- No other file. Full scope confirmed.

**Values used in `MissionControlView.tsx`:**
- `state: 'draft'` — initial value (line 246)
- `state: 'planning'` — set during edit (line 264)
- `state: 'mso_review'` — set on escalate (line 256)
- `state: 'draft'` — reset after clear (line 337)
- Comparisons: `plan.state === 'mso_review'`, `p.state === 'draft'`, `p.state === 'planning'`

**Values that can NEVER appear:** `prepared`, `awaiting_confirmation`, `blocked`, `failed`, `cancelled`

**TypeScript baseline:** `npx tsc --noEmit` → EXIT:0

---

## File structure

| File | Action |
|------|--------|
| `ui/lib/types.ts` | Add `MissionControlPlanState` type alias; narrow `MissionControlPlan.state` |
| `ui/components/sovereign/MissionControlView.tsx` | No changes needed — all runtime values already conform |

---

### Task 1: Type audit (COMPLETE — in-session)

- [x] Locate all uses of `MissionControlPlan`, `MissionControlPlan.state` in the codebase
- [x] Confirm only 2 files: `types.ts` (definition) and `MissionControlView.tsx` (consumer)
- [x] Confirm all values assigned to `plan.state` are in `{ 'draft', 'planning', 'mso_review' }`
- [x] Confirm `MissionControlView.tsx` needs no code changes
- [x] Run TypeScript baseline: `npx tsc --noEmit` → EXIT:0

---

### Task 2: Add MissionControlPlanState and narrow MissionControlPlan.state

**Goal:** `MissionControlPlan.state` is narrowed to `MissionControlPlanState`. Any code that assigns `prepared`, `awaiting_confirmation`, `blocked`, `failed`, or `cancelled` to a plan's state will fail at compile time.

**Files:**
- Modify: `ui/lib/types.ts:844-852`

**Risk level:** Low — single consumer file, all runtime values conform.
**Authority risk:** None
**Tests required:** `npx tsc --noEmit` → EXIT:0 proves no regressions
**Stop condition:** TypeScript compiles clean. `MissionControlPlan.state` no longer admits execution-adjacent states.

- [ ] **Step 1: Add `MissionControlPlanState` type alias in `ui/lib/types.ts`**

Insert after line 843 (after `MissionLifecycleState`, before `MissionControlPlan`):

```typescript
// S-MISSION-CONTROL-PLAN-STATE-HARDENING-01
// PlannerSpace is a local, non-executing surface. Plans can only ever be in
// draft, planning, or mso_review. Narrowing prevents execution-adjacent states
// (prepared, blocked, failed, etc.) from ever appearing on plan.state at
// compile time.
export type MissionControlPlanState =
  | 'draft'
  | 'planning'
  | 'mso_review'
```

- [ ] **Step 2: Update `MissionControlPlan.state` field type**

Replace:
```typescript
export interface MissionControlPlan {
  id?: string
  title: string
  body: string
  state: MissionLifecycleState
  createdAt?: string
  updatedAt?: string
}
```

With:
```typescript
export interface MissionControlPlan {
  id?: string
  title: string
  body: string
  // S-MISSION-CONTROL-PLAN-STATE-HARDENING-01
  // Narrowed from MissionLifecycleState: plans never reach execution-adjacent states.
  state: MissionControlPlanState
  createdAt?: string
  updatedAt?: string
}
```

- [ ] **Step 3: Verify TypeScript compiles clean**

```bash
cd ui && npx tsc --noEmit 2>&1; echo "EXIT:$?"
```
Expected: `EXIT:0`

---

### Task 3: Validation

**Goal:** All 161 tests pass. TypeScript clean. Build compiles.

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

### Task 4: Validation + dangerous-language scan + PR

**Goal:** Safety scans on changed file, branch push, PR opened.

- [ ] **Step 1: Dangerous-language scan on changed file**

```bash
grep -n "running\|executing\|authorized\|ready to run\|live execution\|runner ready\|completed\|successfully executed\|real" \
  ui/lib/types.ts | grep -v "//\|not\|NEVER\|DANGEROUS\|closed\|unavailable\|blocked"
```

- [ ] **Step 2: Forbidden-path scan on changed file**

```bash
grep -n "handle_request\|issue_token\|AuthorityArtifact\|fabricat\|fake.*run\|Police.*bypass" \
  ui/lib/types.ts
```

- [ ] **Step 3: Create branch and commit**

```bash
git checkout -b fix/mso-plan-state-narrowing
git add ui/lib/types.ts docs/superpowers/plans/2026-05-28-mission-control-plan-state-hardening.md
git commit -m "fix(ui): narrow MissionControlPlan.state to MissionControlPlanState"
```

- [ ] **Step 4: Push and open PR**

```bash
git push origin fix/mso-plan-state-narrowing
gh pr create --repo JorgeCast31/Assistant_OS_Labs \
  --head fix/mso-plan-state-narrowing \
  --base main \
  --title "fix(ui): narrow mission-control plan state" \
  --body "..."
```
