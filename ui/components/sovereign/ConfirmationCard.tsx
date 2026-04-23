'use client'

import { useState } from 'react'
import type { MSOPlanItem, GovernanceTrace } from '@/lib/sovereign/types'
import { AuthorityBadge } from './AuthorityBadge'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ConfirmationCardProps {
  message: string
  plan?: MSOPlanItem[]
  governanceTrace?: GovernanceTrace
  onConfirm: () => void
  onCancel: () => void
  disabled?: boolean
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ConfirmationCard({
  message,
  plan,
  governanceTrace,
  onConfirm,
  onCancel,
  disabled = false,
}: ConfirmationCardProps) {
  const [choice, setChoice] = useState<'confirm' | 'cancel' | null>(null)
  const isHandled = choice !== null

  const handleConfirm = () => {
    if (isHandled || disabled) return
    setChoice('confirm')
    onConfirm()
  }

  const handleCancel = () => {
    if (isHandled || disabled) return
    setChoice('cancel')
    onCancel()
  }

  return (
    <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-amber-500/20 bg-amber-500/10">
        <div className="flex items-center gap-2">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-amber-400">
            <path d="M8 2L14 5V11L8 14L2 11V5L8 2Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
            <path d="M8 6V8.5M8 10V10.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span className="text-sm font-mono font-semibold text-amber-400">
            Authorization Required
          </span>
        </div>
      </div>

      {/* Content */}
      <div className="px-4 py-4 space-y-4">
        <p className="text-sm font-mono text-tx-primary leading-relaxed">
          {message}
        </p>

        {/* Plan Summary */}
        {plan && plan.length > 0 && (
          <div className="space-y-2">
            <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">
              Planned Actions
            </p>
            <div className="space-y-1">
              {plan.map((item, i) => (
                <div key={item.id} className="flex items-center gap-2 px-3 py-2 rounded bg-os-elevated border border-os-border">
                  <span className="text-[10px] font-mono text-amber-400 w-4">
                    {i + 1}.
                  </span>
                  <span className="text-xs font-mono text-tx-secondary flex-1">
                    {item.action}
                  </span>
                  {item.requiresAuth && (
                    <span className="px-1.5 py-0.5 text-[8px] font-mono bg-amber-500/20 text-amber-400 rounded uppercase">
                      Auth
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Governance Trace */}
        {governanceTrace && <AuthorityBadge trace={governanceTrace} />}

        {/* Actions */}
        <div className="flex gap-3 pt-2">
          <button
            onClick={handleConfirm}
            disabled={isHandled || disabled}
            className={`
              flex-1 px-4 py-2.5 rounded-lg text-sm font-mono font-medium
              transition-all duration-150
              ${choice === 'confirm'
                ? 'bg-amber-500/30 border border-amber-500/50 text-amber-300 cursor-default'
                : 'bg-amber-500/15 border border-amber-500/30 text-amber-400 hover:bg-amber-500/25 hover:border-amber-500/40'
              }
              disabled:opacity-40 disabled:cursor-not-allowed
            `}
          >
            {choice === 'confirm' ? 'Authorized' : 'Authorize Execution'}
          </button>
          <button
            onClick={handleCancel}
            disabled={isHandled || disabled}
            className={`
              px-4 py-2.5 rounded-lg text-sm font-mono
              transition-all duration-150
              ${choice === 'cancel'
                ? 'bg-red-500/20 border border-red-500/40 text-red-400 cursor-default'
                : 'bg-os-elevated border border-os-border text-tx-secondary hover:border-os-border-hi hover:text-tx-primary'
              }
              disabled:opacity-40 disabled:cursor-not-allowed
            `}
          >
            {choice === 'cancel' ? 'Cancelled' : 'Cancel'}
          </button>
        </div>
      </div>

      {/* Footer Warning */}
      <div className="px-4 py-2 border-t border-amber-500/20 bg-amber-500/5">
        <p className="text-[9px] font-mono text-amber-400/60 text-center">
          MSO is the sole authority - this action will execute on confirmation
        </p>
      </div>
    </div>
  )
}
