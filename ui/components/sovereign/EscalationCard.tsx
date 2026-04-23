'use client'

import type { EscalationRequest } from '@/lib/sovereign/types'

// ── Risk Level Styles ─────────────────────────────────────────────────────────

const RISK_STYLES: Record<EscalationRequest['riskLevel'], { bg: string; border: string; text: string }> = {
  low:      { bg: 'bg-slate-500/10',   border: 'border-slate-500/20', text: 'text-slate-400' },
  medium:   { bg: 'bg-amber-500/10',   border: 'border-amber-500/20', text: 'text-amber-400' },
  high:     { bg: 'bg-orange-500/10',  border: 'border-orange-500/20', text: 'text-orange-400' },
  critical: { bg: 'bg-red-500/10',     border: 'border-red-500/20',   text: 'text-red-400' },
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface EscalationCardProps {
  escalation: EscalationRequest
  onSendToMSO: (command: string) => void
  onDismiss: () => void
}

// ── Component ─────────────────────────────────────────────────────────────────

export function EscalationCard({ escalation, onSendToMSO, onDismiss }: EscalationCardProps) {
  const riskStyle = RISK_STYLES[escalation.riskLevel] ?? RISK_STYLES.medium

  return (
    <div className={`rounded-xl overflow-hidden ${riskStyle.bg} ${riskStyle.border} border`}>
      {/* Header */}
      <div className={`px-4 py-3 border-b ${riskStyle.border} flex items-center gap-3`}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className={riskStyle.text}>
          <path d="M8 1L15 13H1L8 1Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
          <path d="M8 6V9M8 11V11.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        <span className={`text-sm font-mono font-semibold ${riskStyle.text}`}>
          Authorization Required
        </span>
        <span className={`ml-auto px-2 py-0.5 text-[9px] font-mono uppercase rounded ${riskStyle.bg} ${riskStyle.text} border ${riskStyle.border}`}>
          {escalation.riskLevel}
        </span>
      </div>

      {/* Content */}
      <div className="px-4 py-4 space-y-4">
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-1">
            Reason
          </p>
          <p className="text-sm font-mono text-tx-primary">
            {escalation.reason}
          </p>
        </div>

        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-1">
            Suggested MSO Command
          </p>
          <div className="px-3 py-2 rounded-lg bg-os-base border border-os-border font-mono text-xs text-amber-400 break-all">
            {escalation.suggestedCommand}
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-3 pt-2">
          <button
            onClick={() => onSendToMSO(escalation.suggestedCommand)}
            className={`
              flex-1 px-4 py-2.5 rounded-lg text-sm font-mono font-medium
              bg-amber-500/15 border border-amber-500/30 text-amber-400
              hover:bg-amber-500/25 hover:border-amber-500/40
              transition-all duration-150
            `}
          >
            Send to MSO
          </button>
          <button
            onClick={onDismiss}
            className="
              px-4 py-2.5 rounded-lg text-sm font-mono
              bg-os-elevated border border-os-border text-tx-secondary
              hover:border-os-border-hi hover:text-tx-primary
              transition-all duration-150
            "
          >
            Dismiss
          </button>
        </div>
      </div>

      {/* Footer */}
      <div className={`px-4 py-2 border-t ${riskStyle.border}`}>
        <p className="text-[9px] font-mono text-tx-muted text-center">
          This action cannot be executed without MSO authorization
        </p>
      </div>
    </div>
  )
}
