'use client'

/**
 * PlanStatusIndicator — read-only prepare lifecycle status for a Draft Store Plan.
 *
 * Design contract:
 *   - Shows prepare lifecycle: Plan → ACK → PrepareRequest → PreparedAction.
 *   - Provides "Acknowledge Plan" action ONLY when status = mso_review_ack_pending.
 *   - Provides "Prepare for Review" action ONLY when status = acked_prepare_not_requested.
 *   - NEVER shows Execute, Running, Live, Authorized, Approved, Completed.
 *   - ACK does NOT authorize. Prepare does NOT execute.
 *   - Actions require user confirmation before calling backend.
 *
 * Sprint: #232 — PlanStatusIndicator UI and Mission Control Integration.
 */

import { useState, useEffect, useCallback } from 'react'
import { getPlanPrepareStatus, ackPlan, preparePlan } from '@/lib/api'
import type { PlanPrepareStatusResponse, PlanPrepareStatusValue } from '@/lib/types'

// ── Status label config ────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  PlanPrepareStatusValue | 'unknown',
  { label: string; color: string; dot: string }
> = {
  no_plan:                      { label: 'Plan not found',               color: 'text-red-400',     dot: 'bg-red-400' },
  draft:                        { label: 'Draft',                         color: 'text-slate-400',   dot: 'bg-slate-400' },
  planning:                     { label: 'Planning',                      color: 'text-amber-400',   dot: 'bg-amber-400' },
  mso_review_ack_pending:       { label: 'ACK Pending',                   color: 'text-blue-400',    dot: 'bg-blue-400' },
  mso_review_ack_rejected:      { label: 'ACK Rejected',                  color: 'text-red-400',     dot: 'bg-red-400' },
  acked_prepare_not_requested:  { label: 'ACKed — Prepare Available',     color: 'text-cyan-400',    dot: 'bg-cyan-400' },
  prepared_awaiting_confirmation: { label: 'Prepared — Awaiting Confirmation', color: 'text-violet-400', dot: 'bg-violet-400' },
  prepare_rejected:             { label: 'Prepare Rejected',              color: 'text-red-400',     dot: 'bg-red-400' },
  requires_review:              { label: 'Requires Review',               color: 'text-amber-400',   dot: 'bg-amber-400' },
  operator_seat_mismatch:       { label: 'Seat mismatch',                 color: 'text-red-400',     dot: 'bg-red-400' },
  unknown:                      { label: 'Unknown',                       color: 'text-tx-muted',    dot: 'bg-tx-muted' },
}

// Forbidden labels — defense-in-depth: these must never appear in this component.
// If any of these is detected, the component renders an error state.
const FORBIDDEN_LABELS = new Set([
  'execute', 'running', 'live', 'authorized', 'approved', 'completed',
  'ready to execute', 'authorized for execution',
])

function isForbiddenStatus(status: string): boolean {
  return FORBIDDEN_LABELS.has(status.toLowerCase())
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface PlanStatusIndicatorProps {
  planId: string
  operatorSeat: string
  /** Show a compact version (label + dot only, no buttons). Default: false. */
  compact?: boolean
  /** Called after a successful ACK or prepare action. */
  onStatusChange?: (status: PlanPrepareStatusResponse) => void
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PlanStatusIndicator({
  planId,
  operatorSeat,
  compact = false,
  onStatusChange,
}: PlanStatusIndicatorProps) {
  const [status, setStatus] = useState<PlanPrepareStatusResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const fetchStatus = useCallback(async () => {
    setLoading(true)
    const result = await getPlanPrepareStatus(planId, operatorSeat)
    setStatus(result)
    setLoading(false)
    return result
  }, [planId, operatorSeat])

  useEffect(() => {
    fetchStatus()
  }, [fetchStatus])

  if (loading) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[10px] font-mono text-tx-muted">
        <span className="w-1.5 h-1.5 rounded-full bg-tx-muted animate-pulse" />
        Loading…
      </span>
    )
  }

  if (!status) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[10px] font-mono text-red-400">
        <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
        Prepare status unavailable
      </span>
    )
  }

  const rawStatus = status.status as string
  // Defense-in-depth: if somehow a forbidden status reaches here, show error
  if (isForbiddenStatus(rawStatus)) {
    console.error(`[PlanStatusIndicator] Received forbidden status: "${rawStatus}". This indicates a contract violation.`)
    return (
      <span className="inline-flex items-center gap-1.5 text-[10px] font-mono text-red-400">
        ⊘ Invalid status
      </span>
    )
  }

  const config = STATUS_CONFIG[rawStatus as PlanPrepareStatusValue] ?? STATUS_CONFIG.unknown

  // ── ACK action ──────────────────────────────────────────────────────────────
  const handleAck = async () => {
    if (!window.confirm(
      'Acknowledge this plan as MSO read receipt?\n\n' +
      'ACK is a read receipt — NOT an authorization. ' +
      'It does not prepare or execute anything.',
    )) return

    setActionLoading(true)
    setActionError(null)
    try {
      const result = await ackPlan(planId, {
        operator_seat: operatorSeat,
        acknowledged_by: operatorSeat,
        ack_status: 'acknowledged',
      })
      if (!result.ok) {
        setActionError(result.error ?? 'ACK failed')
      } else {
        const refreshed = await fetchStatus()
        onStatusChange?.(refreshed)
      }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'ACK error')
    } finally {
      setActionLoading(false)
    }
  }

  // ── Prepare action ───────────────────────────────────────────────────────────
  const handlePrepare = async () => {
    if (!window.confirm(
      'Prepare this plan for authority review?\n\n' +
      'This sends the plan to the confirm queue as a PreparedAction. ' +
      'Prepare does NOT execute. Human confirmation is still required before any authority chain step.',
    )) return

    setActionLoading(true)
    setActionError(null)
    try {
      const result = await preparePlan(planId, {
        operator_seat: operatorSeat,
        confirmation_acknowledged: true,
      })
      if (!result.ok) {
        setActionError(result.fail_closed_reason ?? result.error ?? 'Prepare failed')
      } else {
        const refreshed = await fetchStatus()
        onStatusChange?.(refreshed)
      }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Prepare error')
    } finally {
      setActionLoading(false)
    }
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  if (compact) {
    return (
      <span className={`inline-flex items-center gap-1.5 text-[10px] font-mono ${config.color}`}>
        <span className={`w-1.5 h-1.5 rounded-full ${config.dot} flex-shrink-0`} />
        {config.label}
      </span>
    )
  }

  const showAckButton = rawStatus === 'mso_review_ack_pending'
  const showPrepareButton = rawStatus === 'acked_prepare_not_requested'

  return (
    <div className="space-y-2">
      {/* Status badge */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-mono ${config.color} border-current/30 bg-current/5`}>
          <span className={`w-1.5 h-1.5 rounded-full ${config.dot} flex-shrink-0`} />
          {config.label}
        </span>
        {status.correlation_id && (
          <span className="text-[9px] font-mono text-tx-muted">
            corr: {status.correlation_id.slice(0, 20)}…
          </span>
        )}
      </div>

      {/* Missing requirements */}
      {status.missing_requirements.length > 0 && (
        <ul className="space-y-0.5">
          {status.missing_requirements.map((req, i) => (
            <li key={i} className="text-[9px] font-mono text-tx-muted flex items-start gap-1">
              <span className="text-tx-muted flex-shrink-0">→</span>
              {req}
            </li>
          ))}
        </ul>
      )}

      {/* Action buttons */}
      {(showAckButton || showPrepareButton) && (
        <div className="flex items-center gap-2">
          {showAckButton && (
            <button
              onClick={handleAck}
              disabled={actionLoading}
              className="px-3 py-1 text-[10px] font-mono rounded border border-blue-400/30 bg-blue-400/10 text-blue-400 hover:bg-blue-400/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {actionLoading ? 'Processing…' : 'Acknowledge Plan'}
            </button>
          )}
          {showPrepareButton && (
            <button
              onClick={handlePrepare}
              disabled={actionLoading}
              className="px-3 py-1 text-[10px] font-mono rounded border border-violet-400/30 bg-violet-400/10 text-violet-400 hover:bg-violet-400/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {actionLoading ? 'Processing…' : 'Prepare for Review'}
            </button>
          )}
        </div>
      )}

      {/* Action error */}
      {actionError && (
        <p className="text-[9px] font-mono text-red-400">
          ⊘ {actionError}
        </p>
      )}

      {/* Prepared action info */}
      {rawStatus === 'prepared_awaiting_confirmation' && status.prepared_action_id && (
        <div className="text-[9px] font-mono text-tx-muted space-y-0.5">
          <p>PreparedAction: <span className="text-violet-400">{status.prepared_action_id.slice(0, 16)}…</span></p>
          <p>Queue: <span className="text-tx-secondary">{status.confirm_queue_status ?? '—'}</span></p>
          <p className="text-tx-muted">
            Human confirmation required before any authority chain step.
            Use the Confirm Queue panel to review.
          </p>
        </div>
      )}
    </div>
  )
}
