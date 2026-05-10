'use client'

import { useUIStore } from '@/stores/ui-store'
import { useSystemPolling } from '@/hooks/use-system-polling'
import { ExecutionNotOpenPanel } from './ExecutionNotOpenPanel'
import type { SystemEvent } from '@/lib/types'

function fmtTimestamp(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleTimeString('es', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

const EVENT_TYPE_STYLES: Record<string, { icon: string; color: string }> = {
  execution_started:    { icon: '>', color: 'text-accent' },
  execution_completed:  { icon: '+', color: 'text-ok' },
  execution_failed:     { icon: 'x', color: 'text-err' },
  system_frozen:        { icon: '!', color: 'text-err' },
  system_degraded:      { icon: '!', color: 'text-warn' },
  system_normal:        { icon: '*', color: 'text-ok' },
  kill_switch_activated: { icon: '!', color: 'text-err' },
  task_transition:      { icon: '~', color: 'text-accent' },
  governance:           { icon: '#', color: 'text-warn' },
}

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

function ChainRow({
  label,
  status,
  tone,
  note,
}: {
  label: string
  status: string
  tone: 'ok' | 'warn' | 'muted'
  note?: string
}) {
  const toneClass =
    tone === 'ok' ? 'text-ok border-ok/30 bg-ok/10' :
    tone === 'warn' ? 'text-warn border-warn/30 bg-warn/10' :
    'text-tx-muted border-os-border bg-os-base'

  return (
    <div className="rounded-lg border border-os-border bg-os-surface p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-mono text-tx-secondary">{label}</p>
        <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border ${toneClass}`}>
          {status}
        </span>
      </div>
      {note && (
        <p className="mt-1 text-[10px] font-mono text-tx-muted">{note}</p>
      )}
    </div>
  )
}

function RecentEventsPanel({ events }: { events: SystemEvent[] }) {
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
        const style = EVENT_TYPE_STYLES[event.type] ?? { icon: '*', color: 'text-tx-muted' }
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

export function SovereignStatusView() {
  const { systemData, isSystemRefreshing } = useUIStore()
  const { refresh } = useSystemPolling()

  const {
    apiStatus,
    webhookStatus,
    lastUpdated,
    error,
    operationalMode,
    recentEvents,
  } = systemData

  const isInitializing = apiStatus === 'unknown' && webhookStatus === 'unknown'

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest">
              Sovereign Status
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

        {error && (
          <div className="px-3 py-2 rounded bg-warn/10 border border-warn/30">
            <p className="text-[11px] font-mono text-warn">{error}</p>
          </div>
        )}

        {isInitializing && (
          <div className="flex items-center gap-2 py-2">
            <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
            <span className="text-xs font-mono text-tx-muted">Comprobando servicios...</span>
          </div>
        )}

        {!isInitializing && (
          <section>
            <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
              Runtime Snapshot
            </p>
            <div className="grid grid-cols-2 gap-3">
              <StatTile
                label="Operational Mode"
                value={operationalMode}
                accent={operationalMode !== 'UNKNOWN'}
              />
              <StatTile
                label="Connectivity"
                value={`${apiStatus}/${webhookStatus}`}
              />
            </div>
          </section>
        )}

        {!isInitializing && (
          <section>
            <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
              Executive Authority Chain
            </p>
            <div className="space-y-2">
              <ChainRow label="MSO Governance" status="Active" tone="ok" />
              <ChainRow label="Delegated MSO Seat" status="Traceable / Non-executing" tone="ok" />
              <ChainRow label="PolicyDecision" status="Present" tone="ok" />
              <ChainRow label="CapabilityToken" status="Lifecycle checked" tone="ok" />
              <ChainRow label="OperationBinding" status="Verified" tone="ok" />
              <ChainRow label="AuthorizedPlan Ref" status="Bound" tone="ok" />
              <ChainRow label="Capability Scope" status="Enforced" tone="ok" />
              <ChainRow label="Police Gate" status="Fail-closed" tone="ok" />
              <ChainRow label="Temporal Restriction" status="Pending" tone="warn" />
              <ChainRow label="CODE/docs Pilot" status="Next" tone="warn" />
              <ChainRow label="HOST/MACHINE_OPERATOR" status="Guarded" tone="muted" />
              <ChainRow label="OpenClaw" status="Disabled" tone="muted" />
            </div>
          </section>
        )}

        {!isInitializing && <ExecutionNotOpenPanel />}

        {!isInitializing && (
          <section>
            <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
              Recent Events
            </p>
            <RecentEventsPanel events={recentEvents} />
          </section>
        )}
      </div>
    </div>
  )
}
