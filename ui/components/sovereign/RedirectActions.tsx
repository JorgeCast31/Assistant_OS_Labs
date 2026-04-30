'use client'

/**
 * RedirectActions — ALFA-FLIGHT-02 §3
 *
 * Shared, reusable component every blocking surface uses to render the
 * canonical "next step" pills. The contract is intentionally narrow:
 *
 *   - Inputs: a list of redirect targets (mso / machine_operator) and the
 *     original operator text. Either may be empty/undefined.
 *   - Action: clicking a pill switches the sovereign-store activeView to
 *     the chosen target and stashes the original text in
 *     `pendingRedirectText` so the destination surface can pre-fill its
 *     composer. The destination surface is responsible for consuming the
 *     stash on mount or focus.
 *
 * There is NO authority decision here. The component does not validate
 * whether the redirect is safe — it merely navigates. Authority verdict
 * still happens at the backend (MSO / Police / Pipeline) once the operator
 * issues the redirected request from the destination surface.
 *
 * Rendering rule: when the targets list is empty, the component renders
 * nothing — never a hollow "no options" placeholder, which would itself
 * be a dead-end.
 */

import { useSovereignStore } from '@/stores/sovereign-store'
import type { RedirectOption, RedirectTarget } from '@/lib/api'

interface RedirectActionsProps {
  /** Concrete redirect options to render. From `redirectsForSurface()`. */
  options: RedirectOption[]
  /**
   * Original operator text. When provided, pre-loaded into the destination
   * surface's composer. Pass `undefined` if the redirect is intent-less
   * (e.g. fail-closed proxy 503 with no user input).
   */
  originalText?: string
  /**
   * Optional callback fired AFTER the store has been updated and the view
   * switched. Useful for surfaces that want to also clear their own
   * transient state (input field, loading flag).
   */
  onRedirect?: (target: RedirectTarget) => void
  /**
   * Visual density. "compact" for inline use under message bubbles;
   * "panel" for standalone callouts.
   */
  variant?: 'compact' | 'panel'
}

const TARGET_TONE: Record<RedirectTarget, { idle: string; hover: string; icon: string }> = {
  mso: {
    idle:  'bg-amber-500/10 border-amber-500/25 text-amber-300',
    hover: 'hover:bg-amber-500/20 hover:border-amber-500/40',
    icon:  '◆',
  },
  machine_operator: {
    idle:  'bg-slate-500/10 border-slate-500/25 text-slate-300',
    hover: 'hover:bg-slate-500/20 hover:border-slate-500/40',
    icon:  '▶',
  },
}

/**
 * Map a logical RedirectTarget to the sovereign-store activeView and
 * activeAgent state mutations. Centralized here so individual buttons
 * never know about store internals.
 */
function applyRedirect(target: RedirectTarget, text: string | undefined): void {
  const store = useSovereignStore.getState()

  // Stash the operator's original text before navigating, so the
  // destination surface can read it on mount via consumePendingRedirectText.
  if (typeof text === 'string' && text.trim().length > 0) {
    store.setPendingRedirectText(text.trim())
  }

  if (target === 'mso') {
    store.setActiveAgent(null)
    store.setActiveView('mso')
    return
  }
  if (target === 'machine_operator') {
    // setActiveAgent already flips activeView to 'agents' when the agent is
    // non-null, so we don't need to set both.
    store.setActiveAgent('machine_operator')
    return
  }
}

export function RedirectActions({
  options,
  originalText,
  onRedirect,
  variant = 'compact',
}: RedirectActionsProps) {
  if (!options || options.length === 0) return null

  const wrapperClass = variant === 'panel'
    ? 'mt-3 rounded-lg border border-os-border bg-os-elevated p-3 space-y-2'
    : 'mt-2 flex flex-wrap items-center gap-2'

  const headerClass = variant === 'panel'
    ? 'text-[10px] font-mono text-tx-muted uppercase tracking-wider'
    : 'text-[10px] font-mono text-tx-muted'

  return (
    <div className={wrapperClass}>
      <span className={headerClass}>
        {variant === 'panel' ? 'Next step' : 'Suggested next step:'}
      </span>
      <div className={variant === 'panel' ? 'flex flex-wrap gap-2' : 'flex flex-wrap gap-2'}>
        {options.map(opt => {
          const tone = TARGET_TONE[opt.target]
          return (
            <button
              key={opt.target}
              onClick={() => {
                applyRedirect(opt.target, originalText)
                onRedirect?.(opt.target)
              }}
              title={opt.hint}
              className={`
                inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border
                text-[11px] font-mono transition-colors
                ${tone.idle} ${tone.hover}
              `}
            >
              <span aria-hidden className="text-xs">{tone.icon}</span>
              <span>{opt.label}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
