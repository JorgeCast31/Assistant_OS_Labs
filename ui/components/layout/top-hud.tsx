'use client'

import { useUIStore } from '@/stores/ui-store'
import type { ViewId, HealthStatus, OperationalMode } from '@/lib/types'
import { CognitivePresenceBadge } from '@/components/cognition/CognitivePresenceBadge'

const VIEW_TITLES: Record<ViewId, string> = {
  chat:       'Chat',
  executions: 'Executions',
  system:     'System',
  actions:    'Actions',
}

// ── Health dot ────────────────────────────────────────────────────────────────

const DOT_COLOR: Record<HealthStatus, string> = {
  ok:       'bg-ok',
  warn:     'bg-warn',
  degraded: 'bg-warn',
  down:     'bg-err',
  unknown:  'bg-idle',
}

// ── Operational Mode styling ──────────────────────────────────────────────────

const MODE_STYLES: Record<OperationalMode, { bg: string; text: string; dot: string; label: string }> = {
  NORMAL:   { bg: 'bg-ok/10',   text: 'text-ok',   dot: 'bg-ok',   label: 'NORMAL' },
  DEGRADED: { bg: 'bg-warn/10', text: 'text-warn', dot: 'bg-warn', label: 'DEGRADED' },
  FROZEN:   { bg: 'bg-err/10',  text: 'text-err',  dot: 'bg-err',  label: 'FROZEN' },
  UNKNOWN:  { bg: 'bg-idle/10', text: 'text-tx-muted', dot: 'bg-idle', label: 'UNKNOWN' },
}

function overallHealth(
  api: HealthStatus,
  webhook: HealthStatus,
): HealthStatus {
  if (api === 'down')                                    return 'down'
  if (api === 'unknown' && webhook === 'unknown')        return 'unknown'
  if (webhook === 'down' || api === 'warn')              return 'warn'
  if (api === 'ok' && webhook === 'ok')                           return 'ok'
  return 'warn'
}

// ── HUD ───────────────────────────────────────────────────────────────────────

export function TopHUD() {
  const { activeView, systemData, isSystemRefreshing } = useUIStore()
  const { apiStatus, webhookStatus, activeExecutions, needsReview, operationalMode } = systemData

  const health = overallHealth(apiStatus, webhookStatus)
  const dotColor = DOT_COLOR[health]
  const isInitializing = apiStatus === 'unknown' && webhookStatus === 'unknown'
  const modeStyle = MODE_STYLES[operationalMode] ?? MODE_STYLES.UNKNOWN

  return (
    <header className="flex items-center justify-between h-12 px-4 bg-os-base border-b border-os-border flex-shrink-0">
      {/* Left: view title */}
      <div className="flex items-center gap-3">
        <span className="text-sm font-mono font-medium text-tx-primary">
          {VIEW_TITLES[activeView]}
        </span>
        <span className="text-os-border">|</span>
        <span className="text-xs font-mono text-tx-muted">AssistantOS</span>
      </div>

      {/* Right: live indicators */}
      <div className="flex items-center gap-4">

        {/* Operational Mode Badge — Phase 0 */}
        <div
          className={`flex items-center gap-1.5 px-2 py-0.5 rounded border ${modeStyle.bg} border-current/20`}
          title={`Operational Mode: ${operationalMode}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${modeStyle.dot} ${operationalMode === 'FROZEN' ? 'animate-pulse' : ''}`} />
          <span className={`text-[10px] font-mono font-medium uppercase tracking-wider ${modeStyle.text}`}>
            {modeStyle.label}
          </span>
        </div>

        {/* M29: Local cognitive engine presence badge */}
        <CognitivePresenceBadge />

        {/* Overall health dot */}
        <div className="flex items-center gap-1.5" title={`API: ${apiStatus} · Webhook: ${webhookStatus}`}>
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotColor} ${isSystemRefreshing ? 'animate-pulse' : ''} ${isInitializing ? 'opacity-40' : ''}`} />
          <span className="text-[10px] font-mono text-tx-muted hidden sm:inline">
            {health === 'ok' ? 'online' : health === 'unknown' ? '…' : health}
          </span>
        </div>

        {/* Active executions */}
        <div className="flex items-center gap-1.5" title="Active executions">
          <span className="text-[10px] font-mono text-tx-muted hidden sm:inline uppercase tracking-wider">active</span>
          <span className={`text-xs font-mono tabular-nums ${activeExecutions > 0 ? 'text-accent' : 'text-tx-muted'}`}>
            {activeExecutions}
          </span>
        </div>

        {/* Needs review */}
        {needsReview > 0 && (
          <div className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-warn/15 border border-warn/30" title="Needs review">
            <span className="text-[10px] font-mono text-warn uppercase tracking-wider">review</span>
            <span className="text-xs font-mono text-warn tabular-nums">{needsReview}</span>
          </div>
        )}
      </div>
    </header>
  )
}
