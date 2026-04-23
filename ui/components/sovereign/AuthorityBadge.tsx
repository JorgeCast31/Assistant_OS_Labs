'use client'

import type { GovernanceTrace } from '@/lib/sovereign/types'

// ── Governance Decision Styles ────────────────────────────────────────────────

const DECISION_STYLES: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  ALLOW:                { bg: 'bg-emerald-500/10',  border: 'border-emerald-500/25', text: 'text-emerald-400', icon: 'check' },
  BLOCK:                { bg: 'bg-red-500/10',      border: 'border-red-500/25',     text: 'text-red-400',     icon: 'block' },
  REQUIRE_CONFIRMATION: { bg: 'bg-amber-500/10',    border: 'border-amber-500/25',   text: 'text-amber-400',   icon: 'alert' },
  DEGRADED:             { bg: 'bg-amber-500/10',    border: 'border-amber-500/25',   text: 'text-amber-400',   icon: 'warn' },
}

const RISK_STYLES: Record<string, string> = {
  low:      'text-slate-400',
  medium:   'text-amber-400',
  high:     'text-orange-400',
  critical: 'text-red-400',
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function IconCheck() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
      <path d="M2 5.5L4 7.5L8 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function IconBlock() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
      <path d="M2.5 2.5L7.5 7.5M7.5 2.5L2.5 7.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function IconAlert() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
      <path d="M5 3V5.5M5 7V7.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function IconWarn() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
      <path d="M5 2L9 8H1L5 2Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" fill="none" />
    </svg>
  )
}

const ICONS: Record<string, () => JSX.Element> = {
  check: IconCheck,
  block: IconBlock,
  alert: IconAlert,
  warn:  IconWarn,
}

// ── Component ─────────────────────────────────────────────────────────────────

interface AuthorityBadgeProps {
  trace: GovernanceTrace
  compact?: boolean
}

export function AuthorityBadge({ trace, compact = false }: AuthorityBadgeProps) {
  const style = DECISION_STYLES[trace.decision] ?? DECISION_STYLES.ALLOW
  const IconComponent = ICONS[style.icon]

  // In compact mode, don't show simple ALLOW decisions
  if (compact && trace.decision === 'ALLOW' && !trace.reason && !trace.risk_level) {
    return null
  }

  return (
    <div className={compact ? '' : 'mt-2 pt-2 border-t border-os-border/50'}>
      <div 
        className={`
          inline-flex items-center gap-1.5 px-2 py-1 rounded 
          text-[10px] font-mono ${style.bg} ${style.border} border
        `}
      >
        <span className={style.text}>
          <IconComponent />
        </span>
        <span className={style.text}>{trace.decision}</span>
        
        {trace.risk_level && trace.risk_level !== 'low' && (
          <>
            <span className="text-slate-600">|</span>
            <span className={RISK_STYLES[trace.risk_level]}>
              {trace.risk_level.toUpperCase()}
            </span>
          </>
        )}
        
        {trace.policy_id && (
          <>
            <span className="text-slate-600">|</span>
            <span className="text-slate-500">{trace.policy_id}</span>
          </>
        )}
      </div>
      
      {!compact && trace.reason && (
        <p className="text-[10px] font-mono text-slate-500 mt-1 ml-0.5">
          {trace.reason}
        </p>
      )}
    </div>
  )
}
