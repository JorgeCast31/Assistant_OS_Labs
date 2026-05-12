'use client'

import type { PreparedActionQueueEntry } from '@/lib/types'

// ── Types ─────────────────────────────────────────────────────────────────────

type ChainStatus = 'captured' | 'classified' | 'mapped' | 'traceable' | 'created' | 'pending_review' | 'pending' | 'closed' | 'unresolved' | 'unavailable'

interface ChainStage {
  label: string
  status: ChainStatus
  value: string | null
  note?: string
}

// ── Pure derivation — no backend call, no mutation ────────────────────────────

function deriveChain(item: PreparedActionQueueEntry): ChainStage[] {
  return [
    {
      label: 'Input',
      status: item.user_intent ? 'captured' : 'unresolved',
      value: item.user_intent
        ? item.user_intent.slice(0, 50) + (item.user_intent.length > 50 ? '…' : '')
        : null,
    },
    {
      label: 'Intent / Domain',
      status: item.domain && item.domain !== 'UNKNOWN' ? 'classified' : 'unresolved',
      value: [item.domain, item.requested_action].filter(Boolean).join(' / ') || null,
    },
    {
      label: 'Capability',
      status: item.capability_name ? 'mapped' : 'unresolved',
      value: item.capability_name
        ? [item.capability_name, item.capability_scope?.join(', ')].filter(Boolean).join(' — ')
        : null,
    },
    {
      label: 'Provider',
      status: item.provider_name ? 'traceable' : 'unavailable',
      value: [item.provider_name, item.model_name].filter(Boolean).join(' / ') || null,
    },
    {
      label: 'Proposal',
      status: item.proposal_id ? 'created' : 'unresolved',
      value: item.proposal_id ? `ref: ${item.proposal_id.slice(0, 14)}…` : null,
    },
    {
      label: 'AuthorityPreparation',
      status: item.preparation_id ? 'created' : 'unresolved',
      value: item.preparation_id ? `ref: ${item.preparation_id.slice(0, 14)}…` : null,
    },
    {
      label: 'ConfirmableAction',
      status: item.prepared_action_id ? 'created' : 'unresolved',
      value: item.prepared_action_id ? `ref: ${item.prepared_action_id.slice(0, 14)}…` : null,
    },
    {
      label: 'ManualReviewQueue',
      status: item.queue_entry_id ? 'pending_review' : 'unresolved',
      value: item.queue_entry_id ? `ref: ${item.queue_entry_id.slice(0, 14)}…` : null,
    },
    {
      label: 'Authority Pending',
      status: 'pending',
      value: null,
      note: 'PolicyDecision → CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate',
    },
    {
      label: 'Execution Closed',
      status: 'closed',
      value: null,
      note: 'Architectural invariant. Execution is closed.',
    },
  ]
}

// ── Status dot ────────────────────────────────────────────────────────────────

function ChainDot({ status, last }: { status: ChainStatus; last: boolean }) {
  const dotClass =
    status === 'captured' || status === 'classified' || status === 'mapped' ||
    status === 'created' || status === 'traceable'
      ? 'bg-ok'
      : status === 'pending_review'
      ? 'bg-warn'
      : status === 'unresolved' || status === 'unavailable'
      ? 'bg-warn/60'
      : 'bg-os-border'

  return (
    <div className="flex flex-col items-center flex-shrink-0" style={{ minWidth: '10px' }}>
      <div className={`w-2 h-2 rounded-full mt-0.5 ${dotClass}`} />
      {!last && <div className="w-px flex-1 bg-os-border mt-0.5" style={{ minHeight: '10px' }} />}
    </div>
  )
}

// ── Status badge ──────────────────────────────────────────────────────────────

function ChainBadge({ status }: { status: ChainStatus }) {
  const cls =
    status === 'captured' || status === 'classified' || status === 'mapped' ||
    status === 'created' || status === 'traceable'
      ? 'text-ok border-ok/30 bg-ok/10'
      : status === 'pending_review'
      ? 'text-warn border-warn/30 bg-warn/10'
      : status === 'unresolved' || status === 'unavailable'
      ? 'text-warn border-warn/30 bg-warn/10'
      : 'text-tx-muted border-os-border bg-os-base'

  const label = status === 'pending_review' ? 'pending review' : status

  return (
    <span className={`flex-shrink-0 px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-wider border ${cls}`}>
      {label}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function MissionControlChainView({
  latestItem,
  totalCount,
}: {
  latestItem: PreparedActionQueueEntry | null
  totalCount: number
}) {
  if (latestItem === null) {
    return (
      <div className="rounded-lg border border-os-border bg-os-surface p-4">
        <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">
          Current Operational Chain
        </p>
        <p className="text-[10px] font-mono text-tx-muted leading-relaxed">
          No active prepared action chain. Create a plan_request to begin a governed workflow.
        </p>
        <p className="text-[10px] font-mono text-tx-muted mt-1 leading-relaxed">
          Execution remains closed.
        </p>
      </div>
    )
  }

  const stages = deriveChain(latestItem)

  return (
    <div className="rounded-lg border border-os-border bg-os-surface p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest">
          Current Operational Chain — read-only
        </p>
        {totalCount > 1 && (
          <span className="text-[9px] font-mono text-tx-muted">
            latest of {totalCount}
          </span>
        )}
      </div>

      <div className="space-y-0">
        {stages.map((stage, i) => (
          <div key={stage.label} className="flex items-start gap-2">
            <ChainDot status={stage.status} last={i === stages.length - 1} />
            <div className="flex-1 flex items-start justify-between gap-2 pb-1.5 min-w-0">
              <div className="min-w-0">
                <p className="text-[10px] font-mono text-tx-secondary leading-tight">{stage.label}</p>
                {stage.value && (
                  <p className="text-[9px] font-mono text-tx-muted leading-tight mt-0.5 truncate max-w-[200px]">
                    {stage.value}
                  </p>
                )}
                {stage.note && (
                  <p className="text-[9px] font-mono text-tx-muted/70 leading-tight mt-0.5 truncate max-w-[200px]">
                    {stage.note}
                  </p>
                )}
              </div>
              <ChainBadge status={stage.status} />
            </div>
          </div>
        ))}
      </div>

      <p className="text-[9px] font-mono text-tx-muted mt-3 pt-2 border-t border-os-border/60">
        This is a read-only chain view. Execution remains closed. Open Confirm Queue to inspect full dossier. This does not execute, approve, or mutate state.
      </p>
    </div>
  )
}
