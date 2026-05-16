'use client'

import { useState } from 'react'
import { useConfirmPendingPolling } from '@/hooks/use-confirm-pending-polling'
import { useConfirmPendingStore } from '@/stores/confirm-pending-store'
import { usePreparedActionsPolling } from '@/hooks/use-prepared-actions-polling'
import { usePreparedActionsStore } from '@/stores/prepared-actions-store'
import type { PreparedActionQueueEntry } from '@/lib/types'
import { AuthorityTimeline } from './AuthorityTimeline'
import { PreparedActionDetailPanel } from './PreparedActionDetailPanel'
import { confirmPreparedAction } from '@/lib/sovereign/api'
import { getPreparedActionsPending } from '@/lib/api'

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

function shortenId(value: string | null | undefined): string {
  if (!value) return '—'
  if (value.length <= 16) return value
  return `${value.slice(0, 8)}...${value.slice(-4)}`
}

function PreparedActionItem({ item }: { item: PreparedActionQueueEntry }) {
  const [confirmStatus, setConfirmStatus] = useState<string | null>(null)
  const [isConfirming, setIsConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const setPreparedActions = usePreparedActionsStore((s) => s.setPreparedActions)

  async function handleConfirm(confirmed: boolean) {
    setIsConfirming(true)
    setConfirmError(null)
    const result = await confirmPreparedAction(
      item.queue_entry_id,
      item.prepared_action_id,
      confirmed,
    )
    setIsConfirming(false)
    if (result.ok && result.human_confirmation_status) {
      setConfirmStatus(result.human_confirmation_status)
      try {
        const fresh = await getPreparedActionsPending()
        setPreparedActions(fresh)
      } catch {
        // poll will catch up on next cycle
      }
    } else {
      setConfirmError(result.error ?? 'Confirmation failed')
    }
  }

  const effectiveStatus = confirmStatus ?? item.human_confirmation_status

  return (
    <div className="px-4 py-3">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        <div className="col-span-2 md:col-span-3">
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Queue Entry</p>
          <p className="text-xs font-mono text-tx-secondary">{shortenId(item.queue_entry_id)}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Domain</p>
          <p className="text-xs font-mono text-tx-secondary">{item.domain || '—'}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Action</p>
          <p className="text-xs font-mono text-tx-secondary">{item.requested_action || '—'}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Capability</p>
          <p className="text-xs font-mono text-tx-secondary">{item.capability_name || '—'}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Intent</p>
          <p className="text-xs font-mono text-tx-secondary truncate">{item.user_intent || '—'}</p>
        </div>
        {(item.provider_name || item.model_name) && (
          <div className="col-span-2 md:col-span-3">
            <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Provider</p>
            <p className="text-xs font-mono text-tx-secondary">
              {[item.provider_name, item.model_name].filter(Boolean).join(' / ')}
            </p>
          </div>
        )}
      </div>
      <AuthorityTimeline item={item} />

      {/* Human Review Action — operational surface, separate from inspection panel */}
      <div className="mt-3 pt-2 border-t border-os-border/60">
        <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">
          Human Review Action
        </p>
        {effectiveStatus === 'human_confirmed' ? (
          <p className="text-[10px] font-mono text-ok">Review confirmed. Execution remains closed.</p>
        ) : effectiveStatus === 'human_rejected' ? (
          <p className="text-[10px] font-mono text-warn">Rejected. Execution remains closed.</p>
        ) : (
          <>
            <p className="text-[10px] font-mono text-tx-muted mb-2 leading-relaxed">
              Does not execute, grant tokens, or call PoliceGate. Execution remains closed.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => handleConfirm(true)}
                disabled={isConfirming}
                className="px-3 py-1.5 text-[10px] font-mono bg-ok/10 text-ok border border-ok/30 rounded hover:bg-ok/20 disabled:opacity-50 cursor-default"
              >
                {isConfirming ? 'Recording…' : 'Confirm Review'}
              </button>
              <button
                onClick={() => handleConfirm(false)}
                disabled={isConfirming}
                className="px-3 py-1.5 text-[10px] font-mono bg-warn/10 text-warn border border-warn/30 rounded hover:bg-warn/20 disabled:opacity-50 cursor-default"
              >
                Reject
              </button>
            </div>
            {confirmError && (
              <p className="text-[10px] font-mono text-warn mt-2">{confirmError}</p>
            )}
          </>
        )}
      </div>

      <details className="mt-3">
        <summary className="text-[10px] font-mono text-tx-muted cursor-default py-1 select-none">
          Inspect prepared action
        </summary>
        <PreparedActionDetailPanel item={item} />
      </details>
    </div>
  )
}

export function ConfirmFlowQueuePanel() {
  useConfirmPendingPolling()
  usePreparedActionsPolling()

  const confirmPending = useConfirmPendingStore((s) => s.confirmPending)
  const isPolling = useConfirmPendingStore((s) => s.isPolling)
  const lastPolled = useConfirmPendingStore((s) => s.lastPolled)
  const pollError = useConfirmPendingStore((s) => s.pollError)

  const preparedActions = usePreparedActionsStore((s) => s.preparedActions)
  const preparedActionsError = usePreparedActionsStore((s) => s.pollError)

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

      {/* Prepared Actions — Manual Review Only */}
      <div className="border-t border-os-border">
        <div className="px-4 py-3 border-b border-os-border">
          <p className="text-xs font-mono text-tx-secondary uppercase tracking-wider">
            Prepared Actions — Manual Review Only
          </p>
          <p className="text-[10px] font-mono text-tx-muted mt-1 leading-relaxed">
            Manual review only. This is not execution. Human confirmation and the full authority chain are still pending.
          </p>
          {preparedActionsError && (
            <p className="text-[10px] font-mono text-warn mt-1">Poll error: {preparedActionsError}</p>
          )}
        </div>
        <div className="divide-y divide-os-border">
          {(preparedActions?.items ?? []).length === 0 ? (
            <div className="px-4 py-3 text-[10px] font-mono text-tx-muted">
              No prepared actions waiting for manual review.
            </div>
          ) : (
            (preparedActions?.items ?? []).slice(0, 10).map((item) => (
              <PreparedActionItem key={item.queue_entry_id} item={item} />
            ))
          )}
        </div>
      </div>
    </div>
  )
}
