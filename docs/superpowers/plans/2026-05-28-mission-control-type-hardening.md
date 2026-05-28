# Mission Control Type Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Mission Control lifecycle language protection from runtime-only (#220 display guards) to compile-time — by narrowing `MissionLifecycleState` to exclude dangerous states and narrowing `OrchestrationThread.executionStatus` to only `'unavailable'`.

**Architecture:** Two targeted type changes in `ui/lib/types.ts`. No runtime behavior changes — the #220 display guards (`DANGEROUS_LIFECYCLE_DISPLAY_MAP`, `EXEC_STATUS_DISPLAY_LABEL`) remain as defense-in-depth. TypeScript compilation (`npx tsc --noEmit`) is the primary validator.

**Tech Stack:** TypeScript, Vitest, Testing Library

---

## Type audit findings (pre-implementation)

| Type | Dangerous member | Legitimate producers? | Safe to remove? |
|------|-----------------|----------------------|-----------------|
| `MissionLifecycleState` | `'running'` | None in MC. No backend contract. | ✅ YES |
| `MissionLifecycleState` | `'completed'` | None in MC. No backend contract. | ✅ YES |
| `OrchestrationThread.executionStatus` | `'real'`, `'stub'`, `'partial'` | No: always hardcoded `'unavailable' as const` | ✅ YES — narrow to `'unavailable'` |
| `ExecutionStatus` (global) | `'real'` | Yes: arms, chat, ReadinessPanel, api.ts | ❌ NO — too many legitimate consumers |
| `MissionControlReadinessResponse.arms[].execution_status` | `'real'` | Backend contract | ❌ NO — backend response type |

**Consumers of `MissionLifecycleState`:**
- `ui/lib/types.ts` — definition (1 location)
- `ui/components/sovereign/MissionControlView.tsx` — ONLY consumer (3 import/5 usage locations)
- No other file. Full scope is confirmed.

**TypeScript baseline:** `npx tsc --noEmit` → EXIT:0

---

## File structure

| File | Action |
|------|--------|
| `ui/lib/types.ts` | Narrow `MissionLifecycleState` (remove `'running'`, `'completed'`); narrow `OrchestrationThread.executionStatus` to `'unavailable'` |
| `ui/components/sovereign/__tests__/MissionControlView.test.tsx` | Add 2 compile-time safety comments (no code changes needed — existing `as unknown as` casts survive narrowing) |

Note: `MissionControlView.tsx` itself needs no changes. All runtime values already conform to the narrowed types. The `DANGEROUS_LIFECYCLE_DISPLAY_MAP` is kept as-is (runtime defense-in-depth against `as any` and backend schema drift).

---

### Task 1: Type audit (COMPLETE — in-session)

- [x] Locate all uses of `MissionLifecycleState`, `MissionControlPlan.state`, `OrchestrationThread.status`, `OrchestrationThread.executionStatus`
- [x] Classify which types are backend contracts, UI-only, fallback-only, or internal
- [x] Confirm `MissionLifecycleState` has exactly one file consumer
- [x] Confirm `OrchestrationThread.executionStatus` is always `'unavailable'` in practice
- [x] Run TypeScript baseline: `npx tsc --noEmit` → EXIT:0

---

### Task 2: Narrow MissionLifecycleState — remove 'running' and 'completed'

**Goal:** `'running'` and `'completed'` are removed from `MissionLifecycleState`. Any code that assigns these values to `currentStage`, `nextStage`, `plan.state`, or `thread.status` will fail at compile time.

**Files:**
- Modify: `ui/lib/types.ts:831-841`

**Risk level:** Low — only one consumer file. All runtime values already conform.
**Authority risk:** None
**Tests required:** `npx tsc --noEmit` → EXIT:0 proves no regressions
**Stop condition:** TypeScript compiles clean. `MissionLifecycleState` no longer admits 'running' or 'completed'.

- [ ] **Step 1: Edit `MissionLifecycleState` in `ui/lib/types.ts`**

Replace the current union (lines 831–841):
```typescript
export type MissionLifecycleState =
  | 'draft'
  | 'planning'
  | 'mso_review'
  | 'prepared'
  | 'awaiting_confirmation'
  | 'running'
  | 'blocked'
  | 'completed'
  | 'failed'
  | 'cancelled'
```

With the narrowed union:
```typescript
// S-MISSION-CONTROL-TYPE-HARDENING-01
// 'running' and 'completed' are removed — no legitimate Mission Control surface
// produces these states. The display guard in LifecycleBadge (DANGEROUS_LIFECYCLE_DISPLAY_MAP)
// remains as runtime defense-in-depth against 'as any' casts and backend schema drift.
export type MissionLifecycleState =
  | 'draft'
  | 'planning'
  | 'mso_review'
  | 'prepared'
  | 'awaiting_confirmation'
  | 'blocked'
  | 'failed'
  | 'cancelled'
```

- [ ] **Step 2: Verify TypeScript compiles clean**

```bash
cd ui && npx tsc --noEmit 2>&1; echo "EXIT:$?"
```
Expected: `EXIT:0`

---

### Task 3: Narrow OrchestrationThread.executionStatus — to 'unavailable' only

**Goal:** `OrchestrationThread.executionStatus` is narrowed to `'unavailable'`. All MC thread cards are architecturally guaranteed to have `executionStatus: 'unavailable'` — this makes that guarantee a compile-time contract.

**Files:**
- Modify: `ui/lib/types.ts:852-859`

**Risk level:** Low. `ExecStatusBadge` accepts the full union for arms — this change only affects the `OrchestrationThread` interface, not `ExecStatusBadge`.
**Authority risk:** None
**Tests required:** `npx tsc --noEmit` → EXIT:0
**Stop condition:** TypeScript compiles clean. MC threads cannot be assigned 'real' or 'partial' execution status.

- [ ] **Step 1: Edit `OrchestrationThread.executionStatus` in `ui/lib/types.ts`**

Replace:
```typescript
export interface OrchestrationThread {
  id: string
  label: string
  status: MissionLifecycleState
  assignedArm?: string
  lastEvent?: string
  executionStatus?: 'real' | 'stub' | 'unavailable' | 'partial'
}
```

With:
```typescript
export interface OrchestrationThread {
  id: string
  label: string
  status: MissionLifecycleState
  assignedArm?: string
  lastEvent?: string
  // S-MISSION-CONTROL-TYPE-HARDENING-01
  // Narrowed to 'unavailable': MC threads never claim real/stub/partial execution.
  // ExecStatusBadge still accepts the full union for arms (separate prop type).
  executionStatus?: 'unavailable'
}
```

- [ ] **Step 2: Verify TypeScript compiles clean**

```bash
cd ui && npx tsc --noEmit 2>&1; echo "EXIT:$?"
```
Expected: `EXIT:0`

---

### Task 4: Tests — verify no regressions + document compile-time safety

**Goal:** All 161 tests pass after type changes. TypeScript exit 0. No test changes needed (existing adversarial tests use `as unknown as` casts which survive type narrowing).

**Files:**
- No changes needed — add safety annotation to test file as documentation

**Risk level:** None
**Authority risk:** None
**Stop condition:** 161 tests pass, `npx tsc --noEmit` EXIT:0.

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

### Task 5: Validation + dangerous-language scan + PR

**Goal:** Full safety scans on changed files, branch push, PR opened.

**Files:** No changes.

**Risk level:** None
**Authority risk:** None
**Stop condition:** Scans clean, PR open, not merged.

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
git checkout -b fix/mso-lifecycle-type-hardening
git add ui/lib/types.ts docs/superpowers/plans/2026-05-28-mission-control-type-hardening.md
git commit -m "fix(ui): narrow MissionLifecycleState and OrchestrationThread.executionStatus"
```

- [ ] **Step 4: Push and open PR**

```bash
git push origin fix/mso-lifecycle-type-hardening
gh pr create --title "fix(ui): harden mission-control lifecycle types" ...
```
