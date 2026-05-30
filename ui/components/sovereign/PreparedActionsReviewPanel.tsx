'use client'

/**
 * PreparedActionsReviewPanel — read-only review queue for ConfirmablePreparedActions.
 *
 * Design contract:
 *   - Lists PreparedActions pending human review via getPreparedActionsPending().
 *   - Allows human to record explicit confirmation via confirmPreparedAction().
 *   - Allows human to trigger policy evaluation via triggerPolicyReview().
 *   - Allows human to create authority binding draft via triggerAuthorityBinding().
 *   - All actions record drafts only. Does NOT execute.
 *   - Does NOT grant execution authority. Does NOT issue tokens. Does NOT call Police.
 *   - execution_allowed and can_execute_now remain False at all times.
 *   - PreparedAction is review-only. Human confirmation is NOT execution.
 *   - Policy Review is NOT final authorization. Authority Binding Draft is NOT a token.
 *
 * Sprint: #235 — Authority Chain Inline Actions UI.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  getPreparedActionsPending,
  confirmPreparedAction,
  triggerPolicyReview,
  triggerAuthorityBinding,
} from '@/lib/api'
import type {
  PreparedActionQueueEntry,
  PreparedActionsQueueResponse,
  OperationTraceV0,
} from '@/lib/types'

// ── Props ─────────────────────────────────────────────────────────────────────

interface PreparedActionsReviewPanelProps {
  operatorSeat?: string
  compact?: boolean
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusChip({ status }: { status: string }) {
  if (status === 'pending_review') {
    return (
      <span className="inline-block px-1.5 py-0.5 rounded text-[8px] font-mono bg-amber-400/10 border border-amber-400/30 text-amber-400 whitespace-nowrap">
        Prepared — Awaiting Confirmation
      </span>
    )
  }
  if (status === 'human_confirmed') {
    return (
      <span className="inline-block px-1.5 py-0.5 rounded text-[8px] font-mono bg-sky-400/10 border border-sky-400/30 text-sky-400 whitespace-nowrap">
        Human Confirmation Recorded
      </span>
    )
  }
  return (
    <span className="inline-block px-1.5 py-0.5 rounded text-[8px] font-mono bg-os-surface border border-os-border text-tx-muted whitespace-nowrap">
      {status}
    </span>
  )
}

// ── Operation trace ───────────────────────────────────────────────────────────

function stepStatusColor(status: string): string {
  if (status === 'complete') return 'text-green-400'
  if (status === 'pending') return 'text-amber-400'
  if (status === 'denied' || status === 'blocked') return 'text-red-400'
  if (status === 'blocked_by_design') return 'text-red-400/60'
  if (status === 'draft_complete') return 'text-sky-400'
  return 'text-tx-muted'
}

function OperationTraceView({ trace }: { trace: OperationTraceV0 }) {
  return (
    <div className="pt-1 border-t border-amber-400/10 space-y-0.5">
      <div className="text-[7px] font-mono text-tx-secondary uppercase tracking-wider mb-1">
        operation_trace_v0
      </div>
      {trace.steps.map((step) => (
        <div key={step.step} className="flex items-center gap-1.5 text-[8px] font-mono">
          <span className={stepStatusColor(step.status)}>
            [{step.status}]
          </span>
          <span className="text-tx-secondary">{step.label}</span>
        </div>
      ))}
      {trace.next_safe_step && (
        <div className="mt-1 text-[7px] font-mono text-tx-muted">
          <span className="text-tx-secondary">next_safe_step:</span>{' '}
          {trace.next_safe_step}
        </div>
      )}
    </div>
  )
}

// ── Entry card ────────────────────────────────────────────────────────────────

interface EntryCardProps {
  entry: PreparedActionQueueEntry
  onConfirm: (entry: PreparedActionQueueEntry) => Promise<void>
  confirming: boolean
  onEvaluatePolicy: (entry: PreparedActionQueueEntry) => Promise<void>
  evaluatingPolicy: boolean
  onCreateBinding: (entry: PreparedActionQueueEntry) => Promise<void>
  creatingBinding: boolean
}

function EntryCard({
  entry,
  onConfirm,
  confirming,
  onEvaluatePolicy,
  evaluatingPolicy,
  onCreateBinding,
  creatingBinding,
}: EntryCardProps) {
  const showEvaluatePolicy =
    entry.human_confirmation_status === 'human_confirmed' && !entry.policy_review_id
  const showCreateBinding =
    (entry.policy_outcome === 'approved' || entry.policy_outcome === 'approved_confirm_only') &&
    !entry.authority_binding_id

  return (
    <div className="rounded border border-amber-400/20 bg-amber-400/5 p-3 space-y-2 text-[9px] font-mono">

      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1 min-w-0">
          <StatusChip status={entry.human_confirmation_status === 'human_confirmed' ? 'human_confirmed' : entry.status} />
          <span className="text-tx-muted mt-0.5">
            <span className="text-tx-secondary">action_id:</span>{' '}
            <span className="text-amber-300">{entry.prepared_action_id}</span>
          </span>
        </div>

        {/* Action buttons column */}
        <div className="flex flex-col gap-1 shrink-0">
          {/* Confirm button — only for pending_review entries */}
          {entry.status === 'pending_review' && entry.human_confirmation_status === 'pending' && (
            <button
              onClick={() => onConfirm(entry)}
              disabled={confirming}
              aria-label="Confirm PreparedAction"
              className="px-2 py-1 rounded text-[9px] font-mono bg-sky-400/10 border border-sky-400/30 text-sky-400 hover:bg-sky-400/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {confirming ? 'Recording…' : 'Confirm PreparedAction'}
            </button>
          )}

          {/* Evaluate Policy — shown after human confirmation, no existing policy review */}
          {showEvaluatePolicy && (
            <button
              onClick={() => onEvaluatePolicy(entry)}
              disabled={evaluatingPolicy}
              aria-label="Evaluate Policy"
              className="px-2 py-1 rounded text-[9px] font-mono bg-violet-400/10 border border-violet-400/30 text-violet-400 hover:bg-violet-400/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {evaluatingPolicy ? 'Evaluating…' : 'Evaluate Policy'}
            </button>
          )}

          {/* Create Authority Binding Draft — shown when policy approved, no binding yet */}
          {showCreateBinding && (
            <button
              onClick={() => onCreateBinding(entry)}
              disabled={creatingBinding}
              aria-label="Create Authority Binding Draft"
              className="px-2 py-1 rounded text-[9px] font-mono bg-indigo-400/10 border border-indigo-400/30 text-indigo-400 hover:bg-indigo-400/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {creatingBinding ? 'Creating Draft…' : 'Create Authority Binding Draft'}
            </button>
          )}
        </div>
      </div>

      {/* Entry metadata */}
      <div className="space-y-0.5 text-tx-muted leading-relaxed">
        <div>
          <span className="text-tx-secondary">entry_id:</span> {entry.queue_entry_id}
        </div>
        {entry.preparation_id && (
          <div>
            <span className="text-tx-secondary">preparation_id:</span> {entry.preparation_id}
          </div>
        )}
        {entry.proposal_id && (
          <div>
            <span className="text-tx-secondary">proposal_id:</span> {entry.proposal_id}
          </div>
        )}
        <div>
          <span className="text-tx-secondary">domain:</span> {entry.domain}
        </div>
        <div>
          <span className="text-tx-secondary">action:</span> {entry.requested_action}
        </div>
        {entry.capability_name && (
          <div>
            <span className="text-tx-secondary">capability:</span> {entry.capability_name}
          </div>
        )}
        {entry.user_intent && (
          <div>
            <span className="text-tx-secondary">intent:</span>{' '}
            <span className="text-tx-primary">{entry.user_intent}</span>
          </div>
        )}
        <div>
          <span className="text-tx-secondary">created_at:</span> {entry.created_at}
        </div>
      </div>

      {/* Safety invariants */}
      <div className="flex flex-wrap gap-1.5 pt-1 border-t border-amber-400/10">
        <span className="px-1 py-0.5 rounded text-[7px] font-mono bg-red-400/5 border border-red-400/20 text-red-400/70">
          execution_allowed: false
        </span>
        <span className="px-1 py-0.5 rounded text-[7px] font-mono bg-red-400/5 border border-red-400/20 text-red-400/70">
          can_execute_now: false
        </span>
        <span className="px-1 py-0.5 rounded text-[7px] font-mono bg-tx-muted/5 border border-os-border text-tx-muted">
          No execution is triggered
        </span>
      </div>

      {/* Operation trace */}
      {entry.operation_trace_v0 && (
        <OperationTraceView trace={entry.operation_trace_v0} />
      )}

      {/* Police readiness summary if present */}
      {entry.police_readiness && (
        <div className="pt-1 border-t border-amber-400/10 text-tx-muted space-y-0.5">
          <div>
            <span className="text-tx-secondary">readiness:</span>{' '}
            {entry.police_readiness.readiness_status}
          </div>
          {entry.police_readiness.next_safe_step && (
            <div>
              <span className="text-tx-secondary">next_safe_step:</span>{' '}
              {entry.police_readiness.next_safe_step}
            </div>
          )}
        </div>
      )}

      {/* Notes */}
      {entry.notes && (
        <div className="pt-1 border-t border-amber-400/10 text-tx-muted italic leading-relaxed">
          {entry.notes}
        </div>
      )}

    </div>
  )
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export function PreparedActionsReviewPanel({
  compact = false,
}: PreparedActionsReviewPanelProps) {
  const [data, setData] = useState<PreparedActionsQueueResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [evaluatingPolicyId, setEvaluatingPolicyId] = useState<string | null>(null)
  const [creatingBindingId, setCreatingBindingId] = useState<string | null>(null)
  const [confirmError, setConfirmError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    const res = await getPreparedActionsPending()
    setData(res)
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleConfirm = useCallback(
    async (entry: PreparedActionQueueEntry) => {
      const msg =
        `Confirm prepared action for human review?\n\n` +
        `action_id: ${entry.prepared_action_id}\n` +
        `domain: ${entry.domain}\n` +
        `action: ${entry.requested_action}\n\n` +
        `This records your confirmation for review purposes only.\n` +
        `No execution is triggered. No authority is granted.\n` +
        `Requires Human Confirmation — Review-only.`
      if (!window.confirm(msg)) return

      setConfirmingId(entry.queue_entry_id)
      setConfirmError(null)
      const result = await confirmPreparedAction({
        entry_id: entry.queue_entry_id,
        action_id: entry.prepared_action_id,
        confirmed: true,
      })
      setConfirmingId(null)
      if (!result.ok) {
        setConfirmError(result.error ?? 'Confirm failed')
      }
      await load()
    },
    [load],
  )

  const handleEvaluatePolicy = useCallback(
    async (entry: PreparedActionQueueEntry) => {
      const msg =
        `Trigger policy evaluation for this prepared action?\n\n` +
        `action_id: ${entry.prepared_action_id}\n` +
        `domain: ${entry.domain}\n` +
        `action: ${entry.requested_action}\n\n` +
        `This records a policy decision draft only.\n` +
        `No execution is triggered. No authority is granted.\n` +
        `Policy Review — Draft chain only.`
      if (!window.confirm(msg)) return

      setEvaluatingPolicyId(entry.queue_entry_id)
      setConfirmError(null)
      const result = await triggerPolicyReview({
        entry_id: entry.queue_entry_id,
        action_id: entry.prepared_action_id,
      })
      setEvaluatingPolicyId(null)
      if (!result.ok) {
        setConfirmError(result.error ?? 'Policy evaluation failed')
      }
      await load()
    },
    [load],
  )

  const handleCreateBinding = useCallback(
    async (entry: PreparedActionQueueEntry) => {
      const msg =
        `Create authority binding draft for this prepared action?\n\n` +
        `action_id: ${entry.prepared_action_id}\n` +
        `domain: ${entry.domain}\n` +
        `action: ${entry.requested_action}\n\n` +
        `This records an authority binding draft only.\n` +
        `No execution is triggered. No token is issued.\n` +
        `Authority Binding Draft — MSO draft chain only.`
      if (!window.confirm(msg)) return

      setCreatingBindingId(entry.queue_entry_id)
      setConfirmError(null)
      const result = await triggerAuthorityBinding({
        entry_id: entry.queue_entry_id,
        action_id: entry.prepared_action_id,
      })
      setCreatingBindingId(null)
      if (!result.ok) {
        setConfirmError(result.error ?? 'Authority binding failed')
      }
      await load()
    },
    [load],
  )

  const items = data?.items ?? []
  const hasError = data && !data.ok

  return (
    <div className={`space-y-3 ${compact ? 'text-[8px]' : ''}`}>

      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-col">
          <span className="text-[10px] font-mono text-amber-400 uppercase tracking-wider">
            PreparedAction Queue — Review
          </span>
          <span className="text-[8px] font-mono text-tx-muted mt-0.5">
            Operator confirmation required · Review-only · No execution is triggered
          </span>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="px-2 py-1 rounded text-[9px] font-mono bg-os-surface border border-os-border text-tx-muted hover:text-tx-secondary hover:border-os-border-active disabled:opacity-40 transition-colors"
        >
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {/* Note banner */}
      {data?.note && (
        <p className="text-[8px] font-mono text-tx-muted px-2 py-1 rounded bg-os-surface border border-os-border leading-relaxed">
          {data.note}
        </p>
      )}

      {/* Error state */}
      {(hasError || confirmError) && (
        <div className="text-[9px] font-mono text-red-400 px-2 py-1 rounded bg-red-400/5 border border-red-400/20">
          {confirmError ?? data?.error ?? 'Prepared actions backend unavailable'}
        </div>
      )}

      {/* Readiness summary */}
      {data?.readiness_summary && items.length > 0 && (
        <div className="text-[8px] font-mono text-tx-muted px-2 py-1 rounded bg-os-surface border border-os-border space-y-0.5">
          <div className="text-tx-secondary">Readiness Summary</div>
          <div>awaiting_human_confirmation: {data.readiness_summary.awaiting_human_confirmation}</div>
          <div>awaiting_policy_review: {data.readiness_summary.awaiting_policy_review}</div>
          {data.readiness_summary.next_safe_operator_actions?.length > 0 && (
            <div>
              next_safe_actions: {data.readiness_summary.next_safe_operator_actions.join(' · ')}
            </div>
          )}
        </div>
      )}

      {/* Entry list */}
      {loading && !data && (
        <p className="text-[9px] font-mono text-tx-muted">Loading prepared actions…</p>
      )}

      {!loading && items.length === 0 && !hasError && (
        <p className="text-[9px] font-mono text-tx-muted">
          No prepared actions pending.
        </p>
      )}

      {items.map((entry) => (
        <EntryCard
          key={entry.queue_entry_id}
          entry={entry}
          onConfirm={handleConfirm}
          confirming={confirmingId === entry.queue_entry_id}
          onEvaluatePolicy={handleEvaluatePolicy}
          evaluatingPolicy={evaluatingPolicyId === entry.queue_entry_id}
          onCreateBinding={handleCreateBinding}
          creatingBinding={creatingBindingId === entry.queue_entry_id}
        />
      ))}

    </div>
  )
}
