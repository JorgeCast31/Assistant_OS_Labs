'use client'

import { useUIStore } from '@/stores/ui-store'
import { ExecutionNotOpenPanel } from './ExecutionNotOpenPanel'

function StatusRow({
  label,
  value,
  tone = 'ok',
  note,
}: {
  label: string
  value: string
  tone?: 'ok' | 'warn' | 'muted'
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
          {value}
        </span>
      </div>
      {note && <p className="mt-1 text-[10px] font-mono text-tx-muted">{note}</p>}
    </div>
  )
}

export function MSOView() {
  const { operationalMode } = useUIStore((s) => s.systemData)

  return (
    <div className="h-full overflow-y-auto bg-os-base">
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <div>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest">
            MSO
          </p>
          <p className="text-xs font-mono text-tx-secondary mt-1">
            Control and cognitive layer. Delegated seat is traceable and non-executing.
          </p>
        </div>

        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Seat and Authority Posture
          </p>
          <div className="space-y-2">
            <StatusRow label="MSO Core" value="Available" tone="ok" />
            <StatusRow label="Delegated MSO Seat" value="Available" tone="ok" />
            <StatusRow label="Seat Mode" value="Delegated / Non-executing" tone="ok" />
            <StatusRow label="Current Seat Actor" value="Unknown" tone="muted" note="No live actor endpoint is wired in this tab." />
            <StatusRow label="Seat Traceability" value="Enabled" tone="ok" />
            <StatusRow label="Seat Context Propagation" value="Enabled" tone="ok" />
            <StatusRow label="Seat Runtime Validation" value="Enabled" tone="ok" note="Validated through authority metadata path and police gate checks." />
            <StatusRow label="Can execute directly" value="No" tone="muted" />
            <StatusRow label="Can prepare plans" value="Pending harness" tone="warn" note="CODE/docs pilot harness is next direction, not active." />
            <StatusRow label="Operational Mode" value={operationalMode} tone={operationalMode === 'UNKNOWN' ? 'warn' : 'ok'} />
          </div>
        </section>

        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Next Direction
          </p>
          <div className="rounded-lg border border-warn/30 bg-warn/10 p-4">
            <p className="text-xs font-mono text-warn">CODE/docs pilot harness</p>
            <p className="mt-1 text-[10px] font-mono text-warn/80">Planned next step. Not operational in current runtime.</p>
          </div>
        </section>

        <ExecutionNotOpenPanel />
      </div>
    </div>
  )
}
