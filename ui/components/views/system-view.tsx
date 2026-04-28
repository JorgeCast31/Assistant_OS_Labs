'use client'

import { useState } from 'react'
import { useUIStore }       from '@/stores/ui-store'
import { useSystemPolling } from '@/hooks/use-system-polling'
import { StatusBadge }      from '@/components/shared/status-badge'
import { FREEZE_CONTROL, RUNTIME_ENDPOINTS, freezeSystem } from '@/lib/api'
import type { HealthStatus, OperationalMode, SystemEvent } from '@/lib/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTimestamp(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('es', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function fmtEndpoint(url: string): string {
  try {
    const parsed = new URL(url, 'http://localhost')
    return parsed.origin === 'http://localhost' && url.startsWith('/')
      ? parsed.pathname
      : `${parsed.host} · ${parsed.pathname}`
  } catch {
    return url
  }
}

// HealthStatus → label for the System view.
// "unknown" only appears during the very first poll cycle (before any HTTP
// roundtrip has completed). Once the user has fetched at least once, status
// becomes "ok" or "down". The label collapses unknown into a transient
// "Initializing" state — never the final operator-facing word.
const STATUS_LABEL: Record<HealthStatus, string> = {
  ok:       'Online',
  warn:     'Warning',
  degraded: 'Degraded',
  down:     'Offline',
  unknown:  'Initializing',
}

// ── Operational Mode styling ──────────────────────────────────────────────────

const MODE_STYLES: Record<OperationalMode, { bg: string; border: string; text: string; dot: string }> = {
  NORMAL:   { bg: 'bg-ok/10',   border: 'border-ok/30',   text: 'text-ok',       dot: 'bg-ok' },
  DEGRADED: { bg: 'bg-warn/10', border: 'border-warn/30', text: 'text-warn',     dot: 'bg-warn' },
  FROZEN:   { bg: 'bg-err/10',  border: 'border-err/30',  text: 'text-err',      dot: 'bg-err' },
  UNKNOWN:  { bg: 'bg-idle/10', border: 'border-idle/30', text: 'text-tx-muted', dot: 'bg-idle' },
}

const MODE_DESCRIPTIONS: Record<OperationalMode, string> = {
  NORMAL:   'System operating normally. All capabilities enabled.',
  DEGRADED: 'System operating in degraded mode. Some capabilities may be restricted.',
  FROZEN:   'System is frozen. No new operations will be processed.',
  // UNKNOWN is rendered only when the operability surface itself is unreachable.
  // Tell the operator what is offline rather than leaving them to guess.
  UNKNOWN:  'Operability surface offline. Cannot read operational mode from the webhook server.',
}

// ── Event type styling ────────────────────────────────────────────────────────

const EVENT_TYPE_STYLES: Record<string, { icon: string; color: string }> = {
  execution_started:    { icon: '▶',  color: 'text-accent' },
  execution_completed:  { icon: '✓',  color: 'text-ok' },
  execution_failed:     { icon: '✕',  color: 'text-err' },
  system_frozen:        { icon: '❄',  color: 'text-err' },
  system_degraded:      { icon: '⚠',  color: 'text-warn' },
  system_normal:        { icon: '●',  color: 'text-ok' },
  kill_switch_activated: { icon: '⛔', color: 'text-err' },
  task_transition:      { icon: '⇄',  color: 'text-accent' },
  governance:           { icon: '⚖',  color: 'text-warn' },
}

// ── ServiceCard ───────────────────────────────────────────────────────────────

function ServiceCard({
  label,
  subtitle,
  status,
}: {
  label: string
  subtitle: string
  status: HealthStatus
}) {
  return (
    <div className="bg-os-surface border border-os-border rounded-lg p-4 flex items-center justify-between">
      <div>
        <p className="text-xs font-mono text-tx-secondary">{label}</p>
        <p className="text-[10px] font-mono text-tx-muted mt-0.5">{subtitle}</p>
      </div>
      <StatusBadge status={status} label={STATUS_LABEL[status]} dot size="md" />
    </div>
  )
}

// ── StatTile ──────────────────────────────────────────────────────────────────

function StatTile({
  label,
  value,
  accent,
}: {
  label: string
  value: string | number
  accent?: boolean
}) {
  return (
    <div className="bg-os-surface border border-os-border rounded-lg p-4">
      <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-mono font-semibold ${accent ? 'text-accent' : 'text-tx-primary'}`}>
        {value}
      </p>
    </div>
  )
}

// ── OperationalModeCard ───────────────────────────────────────────────────────

function OperationalModeCard({ mode }: { mode: OperationalMode }) {
  const style = MODE_STYLES[mode] ?? MODE_STYLES.UNKNOWN
  const description = MODE_DESCRIPTIONS[mode] ?? MODE_DESCRIPTIONS.UNKNOWN

  return (
    <div className={`rounded-lg p-4 border ${style.bg} ${style.border}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className={`w-2.5 h-2.5 rounded-full ${style.dot} ${mode === 'FROZEN' ? 'animate-pulse' : ''}`} />
        <span className={`text-sm font-mono font-semibold uppercase tracking-wider ${style.text}`}>
          {mode}
        </span>
      </div>
      <p className="text-xs font-mono text-tx-secondary">{description}</p>
    </div>
  )
}

// ── KillSwitchButton ──────────────────────────────────────────────────────────

function KillSwitchButton({ onFrozen }: { onFrozen: () => void }) {
  const [showConfirm, setShowConfirm] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null)

  if (!FREEZE_CONTROL.available) {
    return (
      <div className="rounded-lg p-4 border border-warn/30 bg-warn/5">
        <p className="text-xs font-mono text-warn font-medium mb-1">Freeze Control Unavailable</p>
        <p className="text-[10px] font-mono text-tx-secondary">
          {FREEZE_CONTROL.message}
        </p>
      </div>
    )
  }

  async function handleFreeze() {
    setIsLoading(true)
    setResult(null)
    try {
      const res = await freezeSystem()
      setResult(res)
      if (res.ok) {
        onFrozen()
      }
    } catch (err) {
      setResult({ ok: false, message: err instanceof Error ? err.message : 'Unknown error' })
    } finally {
      setIsLoading(false)
      setShowConfirm(false)
    }
  }

  if (result) {
    return (
      <div className={`rounded-lg p-4 border ${result.ok ? 'bg-err/10 border-err/30' : 'bg-warn/10 border-warn/30'}`}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className={`text-xs font-mono font-medium ${result.ok ? 'text-err' : 'text-warn'}`}>
              {result.ok ? 'System Frozen' : 'Freeze Failed'}
            </p>
            <pre className="text-[10px] font-mono text-tx-muted mt-0.5 whitespace-pre-wrap break-words">
              {result.message}
            </pre>
          </div>
          <button
            onClick={() => setResult(null)}
            className="text-[10px] font-mono text-tx-muted hover:text-tx-secondary flex-shrink-0"
          >
            Dismiss
          </button>
        </div>
      </div>
    )
  }

  if (showConfirm) {
    return (
      <div className="rounded-lg p-4 border border-err/30 bg-err/5">
        <p className="text-xs font-mono text-err font-medium mb-2">Confirm System Freeze</p>
        <p className="text-[10px] font-mono text-tx-secondary mb-3">
          This will immediately freeze all system operations. No new tasks will be processed until manually unfrozen.
        </p>
        <div className="flex gap-2">
          <button
            onClick={handleFreeze}
            disabled={isLoading}
            className="
              px-3 py-1.5 text-xs font-mono rounded border
              bg-err/20 border-err/40 text-err
              hover:bg-err/30 transition-colors
              disabled:opacity-50 disabled:cursor-not-allowed
            "
          >
            {isLoading ? 'Freezing…' : 'Confirm Freeze'}
          </button>
          <button
            onClick={() => setShowConfirm(false)}
            disabled={isLoading}
            className="
              px-3 py-1.5 text-xs font-mono rounded border
              bg-os-elevated border-os-border text-tx-secondary
              hover:border-os-border-hi transition-colors
              disabled:opacity-50 disabled:cursor-not-allowed
            "
          >
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <button
      onClick={() => setShowConfirm(true)}
      className="
        w-full px-4 py-3 rounded-lg border
        bg-err/5 border-err/20 text-err
        hover:bg-err/10 hover:border-err/30 transition-colors
        flex items-center justify-center gap-2
      "
    >
      <span className="text-sm">⛔</span>
      <span className="text-xs font-mono font-medium uppercase tracking-wider">Freeze System</span>
    </button>
  )
}

// ── EventLog ──────────────────────────────────────────────────────────────────

function EventLog({ events }: { events: SystemEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="bg-os-surface border border-os-border rounded-lg p-4">
        <p className="text-xs font-mono text-tx-muted text-center">No recent events</p>
      </div>
    )
  }

  return (
    <div className="bg-os-surface border border-os-border rounded-lg divide-y divide-os-border">
      {events.map((event) => {
        const style = EVENT_TYPE_STYLES[event.type] ?? { icon: '●', color: 'text-tx-muted' }
        return (
          <div key={event.id} className="px-4 py-2.5 flex items-start gap-3">
            <span className={`text-sm flex-shrink-0 mt-0.5 ${style.color}`}>{style.icon}</span>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-mono text-tx-primary truncate">{event.message}</p>
              <p className="text-[10px] font-mono text-tx-muted mt-0.5">
                {fmtTimestamp(event.timestamp)}
              </p>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── SystemView ────────────────────────────────────────────────────────────────

export function SystemView() {
  const { systemData, isSystemRefreshing } = useUIStore()
  const { refresh } = useSystemPolling()

  const {
    apiStatus,
    webhookStatus,
    activeExecutions,
    needsReview,
    lastUpdated,
    error,
    operationalMode,
    recentEvents,
  } = systemData

  const isInitializing = apiStatus === 'unknown' && webhookStatus === 'unknown'

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 space-y-6">

        {/* Header row */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest">
              System Status
            </p>
            {lastUpdated && (
              <p className="text-[10px] font-mono text-tx-muted mt-0.5">
                Updated {fmtTimestamp(lastUpdated)}
              </p>
            )}
          </div>

          <button
            onClick={() => void refresh()}
            disabled={isSystemRefreshing}
            className="
              flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-mono rounded border
              border-os-border text-tx-muted
              hover:text-tx-secondary hover:border-os-border-hi transition-colors
              disabled:opacity-40 disabled:cursor-not-allowed
            "
          >
            <span className={isSystemRefreshing ? 'animate-spin inline-block' : ''}>↺</span>
            Refresh
          </button>
        </div>

        {/* Error bar */}
        {error && (
          <div className="px-3 py-2 rounded bg-warn/10 border border-warn/30">
            <p className="text-[11px] font-mono text-warn">{error}</p>
          </div>
        )}

        {/* Loading state on first fetch */}
        {isInitializing && (
          <div className="flex items-center gap-2 py-2">
            <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
            <span className="text-xs font-mono text-tx-muted">Comprobando servicios…</span>
          </div>
        )}

        {/* Phase 0: Operational Mode */}
        {!isInitializing && (
          <section>
            <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
              Operational Mode
            </p>
            <OperationalModeCard mode={operationalMode} />
          </section>
        )}

        {/* Phase 0: Kill Switch */}
        {!isInitializing && operationalMode !== 'FROZEN' && (
          <section>
            <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
              Emergency Controls
            </p>
            <KillSwitchButton onFrozen={() => void refresh()} />
          </section>
        )}

        {/* Services */}
        {!isInitializing && (
          <section>
            <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
              Services
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <ServiceCard
                label="CODE API"
                subtitle={fmtEndpoint(RUNTIME_ENDPOINTS.codeApiHealth)}
                status={apiStatus}
              />
              <ServiceCard
                label="Assistant / Webhook"
                subtitle={fmtEndpoint(RUNTIME_ENDPOINTS.webhookHealth)}
                status={webhookStatus}
              />
            </div>
          </section>
        )}

        {/* Execution counters */}
        {!isInitializing && (
          <section>
            <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
              Executions
            </p>
            <div className="grid grid-cols-2 gap-3">
              <StatTile
                label="Active"
                value={activeExecutions}
                accent={activeExecutions > 0}
              />
              <StatTile
                label="Needs Review"
                value={needsReview}
                accent={needsReview > 0}
              />
            </div>
          </section>
        )}

        {/* Phase 0: Event Log */}
        {!isInitializing && (
          <section>
            <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
              Recent Events
            </p>
            <EventLog events={recentEvents} />
          </section>
        )}

        {/* Debug row */}
        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Endpoints
          </p>
          <div className="bg-os-surface border border-os-border rounded-lg divide-y divide-os-border">
            {[
              { label: 'CODE API health',     url: RUNTIME_ENDPOINTS.codeApiHealth,             status: apiStatus },
              { label: 'Webhook health',      url: RUNTIME_ENDPOINTS.webhookHealth,             status: webhookStatus },
              { label: 'System state proxy',  url: RUNTIME_ENDPOINTS.systemStateProxy,          status: webhookStatus },
              { label: 'Webhook MSO state',   url: RUNTIME_ENDPOINTS.webhookMsoState,           status: webhookStatus },
              { label: 'Capabilities',        url: RUNTIME_ENDPOINTS.webhookSystemCapabilities, status: webhookStatus },
              { label: 'Agents registry',     url: RUNTIME_ENDPOINTS.webhookAgentsRegistry,     status: webhookStatus },
              { label: 'Executions list',     url: RUNTIME_ENDPOINTS.codeApiExecutions,         status: apiStatus },
            ].map(row => (
              <div key={row.label} className="flex items-center justify-between px-4 py-2.5">
                <div>
                  <p className="text-xs font-mono text-tx-secondary">{row.label}</p>
                  <p className="text-[10px] font-mono text-tx-muted">{row.url}</p>
                </div>
                <StatusBadge status={row.status} dot />
              </div>
            ))}
          </div>
        </section>

      </div>
    </div>
  )
}
