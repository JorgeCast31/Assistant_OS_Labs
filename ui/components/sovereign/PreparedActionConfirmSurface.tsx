'use client'

import { useState } from 'react'
import type { PreparedActionQueueEntry, MSOPolicyReviewResult, MSOAuthorityBindingResult } from '@/lib/types'
import { confirmPreparedAction, requestMSOPolicyReview, requestMSOAuthorityBinding } from '@/lib/sovereign/api'
import { getPreparedActionsPending } from '@/lib/api'
import { usePreparedActionsStore } from '@/stores/prepared-actions-store'

const POLICY_OUTCOME_LABELS: Record<string, string> = {
  approved: 'Policy: Approved',
  approved_confirm_only: 'Policy: Approved (confirm-only)',
  denied: 'Policy: Denied',
}

const POLICY_OUTCOME_COLORS: Record<string, string> = {
  approved: 'text-ok',
  approved_confirm_only: 'text-ok',
  denied: 'text-warn',
}

const APPROVED_OUTCOMES = new Set(['approved', 'approved_confirm_only'])

export function PreparedActionConfirmSurface({ item }: { item: PreparedActionQueueEntry }) {
  const [isConfirming, setIsConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const [localStatus, setLocalStatus] = useState<string | null>(null)
  const [policyReview, setPolicyReview] = useState<MSOPolicyReviewResult | null>(null)
  const [policyError, setPolicyError] = useState<string | null>(null)
  const [authorityBinding, setAuthorityBinding] = useState<MSOAuthorityBindingResult | null>(null)
  const [bindingError, setBindingError] = useState<string | null>(null)
  const setPreparedActions = usePreparedActionsStore((s) => s.setPreparedActions)

  const effectiveStatus = localStatus ?? item.human_confirmation_status
  const effectivePolicyOutcome = policyReview?.policy_outcome ?? item.policy_outcome
  const effectiveBindingStatus = authorityBinding?.binding_status ?? item.authority_binding_status

  async function handleConfirm(confirmed: boolean) {
    if (isConfirming) return
    setIsConfirming(true)
    setConfirmError(null)
    setPolicyError(null)
    setBindingError(null)
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

      if (confirmed) {
        const review = await requestMSOPolicyReview(
          item.queue_entry_id,
          item.prepared_action_id ?? item.queue_entry_id,
        )
        setPolicyReview(review)
        if (!review.ok) {
          setPolicyError(review.error ?? 'Policy review failed')
        } else if (review.policy_outcome && APPROVED_OUTCOMES.has(review.policy_outcome)) {
          const binding = await requestMSOAuthorityBinding(
            item.queue_entry_id,
            item.prepared_action_id ?? item.queue_entry_id,
          )
          setAuthorityBinding(binding)
          if (!binding.ok) {
            setBindingError(binding.error ?? 'Authority binding failed')
          }
        }
      }

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
        {effectivePolicyOutcome && (
          <p className={`text-[10px] font-mono mt-1 ${POLICY_OUTCOME_COLORS[effectivePolicyOutcome] ?? 'text-tx-muted'}`}>
            {POLICY_OUTCOME_LABELS[effectivePolicyOutcome] ?? effectivePolicyOutcome}
          </p>
        )}
        {policyError && (
          <p className="text-[10px] font-mono text-warn mt-1">{policyError}</p>
        )}
        {effectiveBindingStatus && (
          <p className="text-[10px] font-mono text-ok mt-1">
            Authority binding: {effectiveBindingStatus}
          </p>
        )}
        {bindingError && (
          <p className="text-[10px] font-mono text-warn mt-1">{bindingError}</p>
        )}
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
