'use client'

import type { PolicyDecision } from '@/lib/sovereign/types'

interface PolicyDecisionCardProps {
  decision: PolicyDecision
}

export function PolicyDecisionCard({ decision }: PolicyDecisionCardProps) {
  const decisionColors = {
    ALLOW: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
    BLOCK: 'bg-red-500/10 border-red-500/30 text-red-400',
    REQUIRE_CONFIRMATION: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
    ESCALATE: 'bg-orange-500/10 border-orange-500/30 text-orange-400',
  }

  const riskColors = {
    low: 'bg-emerald-500/20 text-emerald-400',
    medium: 'bg-amber-500/20 text-amber-400',
    high: 'bg-orange-500/20 text-orange-400',
    critical: 'bg-red-500/20 text-red-400',
  }

  return (
    <div className={`rounded-lg border p-3 ${decisionColors[decision.decision]}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="opacity-80">
            <path d="M7 1L12 4V10L7 13L2 10V4L7 1Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
            {decision.decision === 'ALLOW' && (
              <path d="M5 7L6.5 8.5L9 5.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
            )}
            {decision.decision === 'BLOCK' && (
              <path d="M5 5L9 9M9 5L5 9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            )}
            {(decision.decision === 'REQUIRE_CONFIRMATION' || decision.decision === 'ESCALATE') && (
              <path d="M7 5V7.5M7 9V9.01" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            )}
          </svg>
          <span className="text-xs font-mono font-semibold uppercase tracking-wider">
            Policy Decision
          </span>
        </div>
        <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-current/10">
          {decision.decision.replace('_', ' ')}
        </span>
      </div>

      <p className="text-xs font-mono opacity-90 leading-relaxed">
        {decision.reason}
      </p>

      <div className="flex items-center gap-3 mt-2 pt-2 border-t border-current/20">
        {decision.policy_id && (
          <span className="text-[9px] font-mono opacity-60">
            Policy: {decision.policy_id}
          </span>
        )}
        {decision.risk_level && (
          <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${riskColors[decision.risk_level]}`}>
            {decision.risk_level.toUpperCase()} RISK
          </span>
        )}
      </div>
    </div>
  )
}
