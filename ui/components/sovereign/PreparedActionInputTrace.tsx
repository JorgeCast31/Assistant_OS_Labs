'use client'

import type { PreparedActionQueueEntry } from '@/lib/types'

// ── Types ─────────────────────────────────────────────────────────────────────

type TraceStatus = 'captured' | 'classified' | 'mapped' | 'traceable' | 'created' | 'queued' | 'closed' | 'unavailable' | 'unresolved'

interface TraceStage {
  label: string
  status: TraceStatus
  value: string | null
  note?: string
}

// ── Pure derivation — no backend call, no mutation ────────────────────────────

export function deriveInputTrace(item: PreparedActionQueueEntry): TraceStage[] {
  return [
    {
      label: 'User Input',
      status: 'captured',
      value: item.user_intent || null,
      note: 'Original user intent as received.',
    },
    {
      label: 'Domain Classification',
      status: item.domain && item.domain !== 'UNKNOWN' ? 'classified' : 'unresolved',
      value: item.domain || null,
      note: item.domain === 'UNKNOWN' ? 'Domain could not be classified.' : undefined,
    },
    {
      label: 'Requested Action',
      status: item.requested_action ? 'captured' : 'unresolved',
      value: item.requested_action || null,
    },
    {
      label: 'Capability Mapping',
      status: item.capability_name ? 'mapped' : 'unresolved',
      value: item.capability_name
        ? [item.capability_name, item.capability_scope?.join(', ')].filter(Boolean).join(' — ')
        : null,
      note: item.capability_scope?.length ? `scope: ${item.capability_scope.join(', ')}` : undefined,
    },
    {
      label: 'MSO Seat Provider',
      status: item.provider_name ? 'traceable' : 'unavailable',
      value: item.provider_name
        ? [item.provider_name, item.model_name, item.delegated_seat_ref].filter(Boolean).join(' / ')
        : null,
      note: !item.provider_name ? 'Provider not recorded for this entry.' : undefined,
    },
    {
      label: 'Proposal Artifact',
      status: item.proposal_id ? 'created' : 'unresolved',
      value: item.proposal_id || null,
      note: item.proposal_id ? `ref: ${item.proposal_id.slice(0, 16)}…` : undefined,
    },
    {
      label: 'Authority Preparation',
      status: item.preparation_id ? 'created' : 'unresolved',
      value: item.preparation_id || null,
      note: item.preparation_id ? `ref: ${item.preparation_id.slice(0, 16)}…` : undefined,
    },
    {
      label: 'Confirmable Action',
      status: item.prepared_action_id ? 'created' : 'unresolved',
      value: item.prepared_action_id || null,
      note: item.prepared_action_id ? `ref: ${item.prepared_action_id.slice(0, 16)}…` : undefined,
    },
    {
      label: 'Review Queue Entry',
      status: item.queue_entry_id ? 'queued' : 'unresolved',
      value: item.queue_entry_id || null,
      note: item.queue_entry_id ? `ref: ${item.queue_entry_id.slice(0, 16)}…` : undefined,
    },
    {
      label: 'Current Boundary',
      status: 'closed',
      value: item.status || null,
      note: 'review_only — execution_closed. Full authority chain still pending.',
    },
  ]
}

// ── Status dot ────────────────────────────────────────────────────────────────

function TraceDot({ status, last }: { status: TraceStatus; last: boolean }) {
  const dotClass =
    status === 'captured' || status === 'classified' || status === 'mapped' || status === 'created' || status === 'queued' || status === 'traceable'
      ? 'bg-ok'
      : status === 'unresolved' || status === 'unavailable'
      ? 'bg-warn'
      : 'bg-tx-muted/40'

  return (
    <div className="flex flex-col items-center flex-shrink-0" style={{ minWidth: '10px' }}>
      <div className={`w-2 h-2 rounded-full mt-0.5 ${dotClass}`} />
      {!last && <div className="w-px flex-1 bg-os-border mt-0.5" style={{ minHeight: '10px' }} />}
    </div>
  )
}

// ── Status badge ──────────────────────────────────────────────────────────────

function TraceBadge({ status }: { status: TraceStatus }) {
  const cls =
    status === 'captured' || status === 'classified' || status === 'mapped' || status === 'created' || status === 'queued' || status === 'traceable'
      ? 'text-ok border-ok/30 bg-ok/10'
      : status === 'unresolved' || status === 'unavailable'
      ? 'text-warn border-warn/30 bg-warn/10'
      : 'text-tx-muted border-os-border bg-os-base'

  return (
    <span className={`flex-shrink-0 px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-wider border ${cls}`}>
      {status}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PreparedActionInputTrace({ item }: { item: PreparedActionQueueEntry }) {
  const stages = deriveInputTrace(item)

  return (
    <div className="mt-3 pt-3 border-t border-os-border/60">
      <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2 px-1">
        Origin Trace — read-only
      </p>
      <div className="space-y-0">
        {stages.map((stage, i) => (
          <div key={stage.label} className="flex items-start gap-2 px-1">
            <TraceDot status={stage.status} last={i === stages.length - 1} />
            <div className="flex-1 flex items-start justify-between gap-2 pb-1.5">
              <div className="min-w-0">
                <p className="text-[10px] font-mono text-tx-secondary leading-tight">{stage.label}</p>
                {stage.value && (
                  <p className="text-[9px] font-mono text-tx-muted leading-tight mt-0.5 truncate max-w-[220px]">
                    {stage.value}
                  </p>
                )}
                {stage.note && (
                  <p className="text-[9px] font-mono text-tx-muted/70 leading-tight mt-0.5 truncate max-w-[220px]">
                    {stage.note}
                  </p>
                )}
              </div>
              <TraceBadge status={stage.status} />
            </div>
          </div>
        ))}
      </div>
      <p className="text-[9px] font-mono text-tx-muted mt-2 px-1">
        Origin trace is read-only. It does not execute, approve, or mutate state.
      </p>
    </div>
  )
}
