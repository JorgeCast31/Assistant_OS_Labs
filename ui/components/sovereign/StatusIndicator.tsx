'use client'

import type { AuthorityStatus, AgentStatus, SystemHealth } from '@/lib/sovereign/types'

// ── Status color mappings ─────────────────────────────────────────────────────

const AUTHORITY_COLORS: Record<AuthorityStatus, { bg: string; ring: string; text: string }> = {
  active:   { bg: 'bg-amber-400',  ring: 'ring-amber-400/30', text: 'text-amber-400' },
  deciding: { bg: 'bg-amber-500',  ring: 'ring-amber-500/30', text: 'text-amber-500' },
  blocked:  { bg: 'bg-red-500',    ring: 'ring-red-500/30',   text: 'text-red-500' },
}

const AGENT_COLORS: Record<AgentStatus, { bg: string; ring: string; text: string }> = {
  idle:         { bg: 'bg-slate-400',  ring: 'ring-slate-400/30', text: 'text-slate-400' },
  active:       { bg: 'bg-emerald-400', ring: 'ring-emerald-400/30', text: 'text-emerald-400' },
  degraded:     { bg: 'bg-amber-400',  ring: 'ring-amber-400/30', text: 'text-amber-400' },
  dormant:      { bg: 'bg-slate-600',  ring: 'ring-slate-600/30', text: 'text-slate-600' },
  waiting_auth: { bg: 'bg-amber-500',  ring: 'ring-amber-500/30', text: 'text-amber-500' },
}

const HEALTH_COLORS: Record<SystemHealth, { bg: string; ring: string; text: string }> = {
  healthy:     { bg: 'bg-teal-400',   ring: 'ring-teal-400/30', text: 'text-teal-400' },
  degraded:    { bg: 'bg-amber-400',  ring: 'ring-amber-400/30', text: 'text-amber-400' },
  unavailable: { bg: 'bg-red-500',    ring: 'ring-red-500/30',   text: 'text-red-500' },
}

// ── Types ─────────────────────────────────────────────────────────────────────

type StatusType = 'authority' | 'agent' | 'health'

interface StatusIndicatorProps {
  type: StatusType
  status: AuthorityStatus | AgentStatus | SystemHealth
  size?: 'sm' | 'md' | 'lg'
  showLabel?: boolean
  pulse?: boolean
}

// ── Component ─────────────────────────────────────────────────────────────────

export function StatusIndicator({
  type,
  status,
  size = 'md',
  showLabel = false,
  pulse = false,
}: StatusIndicatorProps) {
  const getColors = () => {
    switch (type) {
      case 'authority':
        return AUTHORITY_COLORS[status as AuthorityStatus] ?? AUTHORITY_COLORS.active
      case 'agent':
        return AGENT_COLORS[status as AgentStatus] ?? AGENT_COLORS.idle
      case 'health':
        return HEALTH_COLORS[status as SystemHealth] ?? HEALTH_COLORS.unavailable
    }
  }

  const colors = getColors()
  
  const sizeClasses = {
    sm: 'w-1.5 h-1.5',
    md: 'w-2 h-2',
    lg: 'w-2.5 h-2.5',
  }

  const shouldPulse = pulse || status === 'deciding' || status === 'active' || status === 'waiting_auth'

  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`relative flex ${sizeClasses[size]}`}>
        {shouldPulse && (
          <span 
            className={`absolute inset-0 rounded-full ${colors.bg} opacity-40 animate-ping`}
          />
        )}
        <span 
          className={`relative inline-block w-full h-full rounded-full ${colors.bg} ring-2 ${colors.ring}`}
        />
      </span>
      {showLabel && (
        <span className={`text-[10px] font-mono uppercase tracking-wider ${colors.text}`}>
          {status.replace('_', ' ')}
        </span>
      )}
    </span>
  )
}
