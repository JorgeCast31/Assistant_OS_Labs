'use client'

import { useState } from 'react'
import type { PreparedActionQueueEntry } from '@/lib/types'
import { confirmPreparedAction } from '@/lib/sovereign/api'
import { getPreparedActionsPending } from '@/lib/api'
import { usePreparedActionsStore } from '@/stores/prepared-actions-store'

export function PreparedActionConfirmSurface({ item }: { item: PreparedActionQueueEntry }) {
  const [isConfirming, setIsConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const [localStatus, setLocalStatus] = useState<string | null>(null)
  const setPreparedActions = usePreparedActionsStore((s) => s.setPreparedActions)

  const effectiveStatus = localStatus ?? item.human_confirmation_status

  async function handleConfirm(confirmed: boolean) {
    if (isConfirming) return
    setIsConfirming(true)
    setConfirmError(null)
    try {
      const result = await confirmPreparedAction(
        item.queue_entry_id,
        item.prepared_action_id ?? item.queue_entry_id,
        confirmed,
      )
      if (!result.ok) {
        setConfirmError(result.error ?? 'Confirm request failed')
        return
      }
      setLocalStatus(result.human_confirmation_status ?? (confirmed ? 'human_confirmed' : 'human_rejected'))
      const refreshed = await getPreparedActionsPending()
      setPreparedActions(refreshed)
    } catch (err) {
      setConfirmError(err instanceof Error ? err.message : 'Network error')
    } finally {
      setIsConfirming(false)
    }
  }

  if (effectiveStatus === 'human_confirmed' || effectiveStatus === 'human_rejected') {
    const label = effectiveStatus === 'human_confirmed' ? 'Confirmed' : 'Rejected'
    const color = effectiveStatus === 'human_confirmed' ? 'text-ok' : 'text-warn'
    return (
      <div className="mt-3 pt-2 border-t border-os-border/60">
        <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-1">
          Human Confirmation Signal
        </p>
        <p className={`text-[10px] font-mono ${color}`}>Signal recorded: {label}</p>
        <p className="text-[10px] font-mono text-tx-muted mt-1 leading-relaxed">
          Signal recorded. Execution remains closed pending full authority chain.
        </p>
      </div>
    )
  }

  return (
    <div className="mt-3 pt-2 border-t border-os-border/60">
      <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-1">
        Human Confirmation Signal
      </p>
      <p className="text-[10px] font-mono text-tx-muted mb-2 leading-relaxed">
        Record a human signal only. Does not execute, approve, or authorize. execution_allowed remains false.
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={isConfirming}
          onClick={() => handleConfirm(true)}
          className="px-3 py-1 text-[10px] font-mono rounded border border-os-border text-tx-secondary hover:text-tx-primary hover:border-tx-muted disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {isConfirming ? 'Recording…' : 'Confirm Review'}
        </button>
        <button
          type="button"
          disabled={isConfirming}
          onClick={() => handleConfirm(false)}
          className="px-3 py-1 text-[10px] font-mono rounded border border-os-border text-warn hover:border-warn disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {isConfirming ? 'Recording…' : 'Reject'}
        </button>
      </div>
      {confirmError && (
        <p className="text-[10px] font-mono text-warn mt-2">{confirmError}</p>
      )}
    </div>
  )
}
