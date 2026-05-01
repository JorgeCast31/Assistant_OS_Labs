'use client'

import { useSovereignStore } from '@/stores/sovereign-store'
import { StatusIndicator } from './StatusIndicator'

// ── Component ─────────────────────────────────────────────────────────────────

export function TopStatusBar() {
  const { systemState, msoState, pendingEscalations } = useSovereignStore()

  const formatTime = () => {
    if (!systemState.lastUpdated) return '--:--:--'
    try {
      return new Date(systemState.lastUpdated).toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    } catch {
      return '--:--:--'
    }
  }

  return (
    <header className="flex items-center justify-between px-4 py-2 bg-os-surface border-b border-os-border">
      {/* Left: System Health */}
      <div className="flex items-center gap-4">
        {/* System health has no backend source — display as unverified */}
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-tx-muted/40 flex-shrink-0" />
          <span className="text-[11px] font-mono text-tx-secondary uppercase tracking-wider">
            System
          </span>
          <span className="text-[11px] font-mono text-tx-muted">
            UNVERIFIED
          </span>
        </div>

        <div className="w-px h-4 bg-os-border" />

        {/* MSO Status — show live status only after operator interaction */}
        <div className="flex items-center gap-2">
          {(msoState.lastDecision !== null || msoState.executionState !== 'idle')
            ? <StatusIndicator type="authority" status={msoState.status} size="md" pulse={msoState.status === 'deciding'} />
            : <span className="w-2 h-2 rounded-full bg-tx-muted/40 flex-shrink-0" />
          }
          <span className="text-[11px] font-mono text-tx-secondary uppercase tracking-wider">
            MSO
          </span>
          <span className={`text-[11px] font-mono ${
            (msoState.lastDecision !== null || msoState.executionState !== 'idle')
              ? msoState.status === 'active'   ? 'text-amber-400'
              : msoState.status === 'deciding' ? 'text-amber-500'
              :                                  'text-red-400'
              : 'text-tx-muted'
          }`}>
            {(msoState.lastDecision !== null || msoState.executionState !== 'idle')
              ? msoState.status.toUpperCase()
              : '—'}
          </span>
        </div>

        <div className="w-px h-4 bg-os-border" />

        {/* Agents Count */}
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-mono text-tx-secondary uppercase tracking-wider">
            Agents
          </span>
          <span className="text-[11px] font-mono text-slate-300">
            {systemState.activeAgents}/{systemState.totalAgents}
          </span>
          {pendingEscalations.length > 0 && (
            <span className="px-1.5 py-0.5 text-[9px] font-mono bg-amber-500/20 text-amber-400 rounded animate-pulse">
              {pendingEscalations.length} PENDING
            </span>
          )}
        </div>
      </div>

      {/* Right: Execution State + Time */}
      <div className="flex items-center gap-4">
        {/* Execution State */}
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-mono text-tx-muted uppercase tracking-wider">
            Exec
          </span>
          <span className={`text-[11px] font-mono px-2 py-0.5 rounded ${
            msoState.executionState === 'idle' ? 'bg-slate-700/50 text-slate-400' :
            msoState.executionState === 'executing' ? 'bg-amber-500/20 text-amber-400 animate-pulse' :
            msoState.executionState === 'awaiting_confirmation' ? 'bg-amber-500/20 text-amber-400' :
            msoState.executionState === 'completed' ? 'bg-emerald-500/20 text-emerald-400' :
            msoState.executionState === 'failed' ? 'bg-red-500/20 text-red-400' :
            msoState.executionState === 'blocked' ? 'bg-red-500/20 text-red-400' :
            'bg-teal-500/20 text-teal-400'
          }`}>
            {msoState.executionState.toUpperCase().replace('_', ' ')}
          </span>
        </div>

        <div className="w-px h-4 bg-os-border" />

        {/* Time */}
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-mono text-tx-muted">
            Last sync
          </span>
          <span className="text-[11px] font-mono text-tx-secondary tabular-nums">
            {formatTime()}
          </span>
        </div>
      </div>
    </header>
  )
}
