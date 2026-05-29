'use client'

/**
 * PlanStateBadge — sovereign Plan state indicator.
 *
 * Design contract:
 *   - Renders ONLY the 3 permitted Plan states: draft | planning | mso_review.
 *   - Never renders: running, executing, completed, approved, authorized,
 *     cancelled, blocked, prepared, or any execution-adjacent state.
 *   - Does NOT inherit from or reuse LifecycleBadge.
 *   - Does NOT use ExecutionState from lib/sovereign/types.ts (legacy type).
 *   - Does NOT imply execution, authorization, or preparation.
 *
 * mso_review display note (D-11):
 *   When state is 'mso_review', the badge shows "MSO Review" with a neutral
 *   color — NOT green/success. Visibility does not imply MSO acceptance,
 *   authorization, preparation, or execution.
 *
 * Sprint: #228 — Draft Persistence Implementation, no prepare.
 */

import type { PlanDraftState } from '@/lib/types'

// ── Permitted state configuration ─────────────────────────────────────────────

const PLAN_STATE_CONFIG: Record<
  PlanDraftState,
  { label: string; bg: string; border: string; text: string; dot: string }
> = {
  draft: {
    label: 'Draft',
    bg: 'bg-slate-500/10',
    border: 'border-slate-500/30',
    text: 'text-slate-400',
    dot: 'bg-slate-500',
  },
  planning: {
    label: 'Planning',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    text: 'text-amber-400',
    dot: 'bg-amber-500',
  },
  mso_review: {
    label: 'MSO Review',
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/30',
    text: 'text-blue-400',
    dot: 'bg-blue-500',
  },
}

// States that must NEVER appear on this badge — defense-in-depth guard.
// If somehow an execution-adjacent state reaches the badge, render an error pill.
const FORBIDDEN_STATES = new Set([
  'running', 'executing', 'completed', 'approved', 'authorized',
  'cancelled', 'blocked', 'prepared', 'awaiting_confirmation',
  'failed', 'live',
])

// ── Props ─────────────────────────────────────────────────────────────────────

interface PlanStateBadgeProps {
  state: PlanDraftState
  /** Show a compact version (dot only, no label). Default: false. */
  compact?: boolean
  /** Additional CSS classes. */
  className?: string
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PlanStateBadge({ state, compact = false, className = '' }: PlanStateBadgeProps) {
  // Defense-in-depth: if an execution-adjacent state somehow reaches here,
  // render a clear error pill rather than silently displaying bad semantics.
  if (FORBIDDEN_STATES.has(state as string)) {
    console.warn(
      `[PlanStateBadge] Received forbidden state: "${state}". ` +
      'Plan badges must only show draft/planning/mso_review. ' +
      'This indicates a backend schema drift or incorrect type usage.',
    )
    return (
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-mono bg-red-500/10 border-red-500/30 text-red-400 ${className}`}>
        ⊘ Unknown State
      </span>
    )
  }

  const config = PLAN_STATE_CONFIG[state]
  if (!config) {
    // Unknown non-forbidden state — also render error pill
    console.warn(`[PlanStateBadge] Unknown Plan state: "${state}"`)
    return (
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-mono bg-red-500/10 border-red-500/30 text-red-400 ${className}`}>
        ⊘ Unknown State
      </span>
    )
  }

  if (compact) {
    return (
      <span
        className={`inline-block w-2 h-2 rounded-full ${config.dot} ${className}`}
        title={config.label}
        aria-label={`Plan state: ${config.label}`}
      />
    )
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-mono ${config.bg} ${config.border} ${config.text} ${className}`}
      aria-label={`Plan state: ${config.label}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot} flex-shrink-0`} />
      {config.label}
    </span>
  )
}
