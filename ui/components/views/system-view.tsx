'use client'

import { useUIStore }       from '@/stores/ui-store'
import { useSystemPolling } from '@/hooks/use-system-polling'
import { StatusBadge }      from '@/components/shared/status-badge'
import type { HealthStatus } from '@/lib/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTimestamp(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('es', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

const STATUS_LABEL: Record<HealthStatus, string> = {
  ok:       'Online',
  warn:     'Warning',
  degraded: 'Degraded',
  down:     'Offline',
  unknown:  'Unknown',
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

        {/* Services */}
        {!isInitializing && (
          <section>
            <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
              Services
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <ServiceCard
                label="CODE API"
                subtitle="localhost:8000 · /health"
                status={apiStatus}
              />
              <ServiceCard
                label="Assistant / Webhook"
                subtitle="localhost:8787 · /health"
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

        {/* Debug row */}
        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Endpoints
          </p>
          <div className="bg-os-surface border border-os-border rounded-lg divide-y divide-os-border">
            {[
              { label: 'CODE API health',  url: 'http://localhost:8000/health',         status: apiStatus },
              { label: 'Webhook health',   url: 'http://localhost:8787/health',         status: webhookStatus },
              { label: 'Executions list',  url: 'http://localhost:8000/api/code/executions', status: 'ok' as HealthStatus },
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
