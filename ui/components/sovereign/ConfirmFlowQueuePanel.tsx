'use client'

import { useConfirmPendingPolling } from '@/hooks/use-confirm-pending-polling'
import { useConfirmPendingStore } from '@/stores/confirm-pending-store'

function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  if (!Number.isFinite(seconds)) return '—'
  return `${seconds}s`
}

function shortenContextId(value: string): string {
  if (!value) return '—'
  if (value.length <= 14) return value
  return `${value.slice(0, 6)}...${value.slice(-4)}`
}

export function ConfirmFlowQueuePanel() {
  useConfirmPendingPolling()

  const confirmPending = useConfirmPendingStore((s) => s.confirmPending)
  const isPolling = useConfirmPendingStore((s) => s.isPolling)
  const lastPolled = useConfirmPendingStore((s) => s.lastPolled)
  const pollError = useConfirmPendingStore((s) => s.pollError)

  const entries = (confirmPending?.pending ?? []).slice(0, 10)
  const pendingCount = confirmPending?.pending_count ?? 0
  const expiredCount = confirmPending?.expired_pending_count ?? 0
  const oldestAge = confirmPending?.oldest_age_seconds
  const nearestExpiry = confirmPending?.nearest_expiry_seconds
  const sourceNote = confirmPending?.note
    ?? 'Confirm queue is observability only; confirmation remains governed.'

  return (
    <div className="rounded-lg border border-os-border bg-os-surface overflow-hidden">
      <div className="px-4 py-3 border-b border-os-border">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs font-mono text-tx-secondary uppercase tracking-wider">
            Confirm Queue
          </p>
          <span className={`text-[10px] font-mono ${isPolling ? 'text-tx-muted' : 'text-tx-secondary'}`}>
            {isPolling ? 'Polling...' : 'Polled'}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 py-3 border-b border-os-border">
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Pending</p>
          <p className="text-sm font-mono text-tx-primary">{pendingCount}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Expired</p>
          <p className="text-sm font-mono text-tx-primary">{expiredCount}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Oldest Age</p>
          <p className="text-sm font-mono text-tx-primary">{fmtDuration(oldestAge)}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Nearest Expiry</p>
          <p className="text-sm font-mono text-tx-primary">{fmtDuration(nearestExpiry)}</p>
        </div>
      </div>

      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-[10px] font-mono text-tx-muted leading-relaxed">
          Confirm queue is observability only; confirmation remains governed.
        </p>
        {sourceNote !== 'Confirm queue is observability only; confirmation remains governed.' && (
          <p className="text-[10px] font-mono text-tx-muted mt-1 leading-relaxed">{sourceNote}</p>
        )}
        {pollError && (
          <p className="text-[10px] font-mono text-warn mt-1">Poll error: {pollError}</p>
        )}
        {lastPolled && (
          <p className="text-[10px] font-mono text-tx-muted mt-1">
            Last polled: {new Date(lastPolled).toLocaleTimeString('es', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            })}
          </p>
        )}
      </div>

      <div className="divide-y divide-os-border">
        {entries.length === 0 ? (
          <div className="px-4 py-3 text-[10px] font-mono text-tx-muted">No pending entries.</div>
        ) : (
          entries.map((entry, index) => (
            <div key={`${entry.context_id}-${index}`} className="px-4 py-3 grid grid-cols-2 md:grid-cols-5 gap-2">
              <div>
                <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Context</p>
                <p className="text-xs font-mono text-tx-secondary">{shortenContextId(entry.context_id)}</p>
              </div>
              <div>
                <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Operation</p>
                <p className="text-xs font-mono text-tx-secondary">{entry.operation || '—'}</p>
              </div>
              <div>
                <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Age</p>
                <p className="text-xs font-mono text-tx-secondary">{fmtDuration(entry.age_seconds)}</p>
              </div>
              <div>
                <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Time To Expiry</p>
                <p className="text-xs font-mono text-tx-secondary">{fmtDuration(entry.time_to_expire_seconds)}</p>
              </div>
              <div>
                <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Expired</p>
                <p className={`text-xs font-mono ${entry.expired ? 'text-warn' : 'text-ok'}`}>
                  {entry.expired ? 'yes' : 'no'}
                </p>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
