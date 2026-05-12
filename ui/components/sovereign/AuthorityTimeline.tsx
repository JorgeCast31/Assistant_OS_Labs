'use client'

import type { PreparedActionQueueEntry } from '@/lib/types'

// ── Types ───────────────────────────────────────────────────────────────────

type StageStatus = 'created' | 'pending_review' | 'pending' | 'closed'

interface TimelineStage {
  name: string
  status: StageStatus
  note?: string
}

// ── Pure derivation — no backend call, no mutation ────────────────────────

export function deriveAuthorityTimeline(item: PreparedActionQueueEntry): TimelineStage[] {
  return [
    {
      name: 'Proposal',
      status: item.proposal_id ? 'created' : 'pending',
      note: item.proposal_id ? `ref: ${item.proposal_id.slice(0, 14)}…` : undefined,
    },
    {
      name: 'AuthorityPreparation',
      status: item.preparation_id ? 'created' : 'pending',
      note: item.preparation_id ? `ref: ${item.preparation_id.slice(0, 14)}…` : undefined,
    },
    {
      name: 'ConfirmableAction',
      status: item.prepared_action_id ? 'created' : 'pending',
      note: item.prepared_action_id ? `ref: ${item.prepared_action_id.slice(0, 14)}…` : undefined,
    },
    {
      name: 'ManualReviewQueue',
      status: item.queue_entry_id ? 'pending_review' : 'pending',
      note: 'Waiting for human review. This panel is read-only.',
    },
    {
      name: 'HumanConfirmation',
      status: 'pending',
      note: item.human_confirmation_status,
    },
    {
      name: 'PolicyDecision',
      status: 'pending',
    },
    {
      name: 'CapabilityToken',
      status: 'pending',
    },
    {
      name: 'OperationBinding',
      status: 'pending',
    },
    {
      name: 'AuthorizedPlan',
      status: 'pending',
    },
    {
      name: 'PoliceGate',
      status: 'pending',
    },
    {
      name: 'Execution',
      status: 'closed',
      note: 'Architectural invariant. Execution is closed.',
    },
  ]
}

// ── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: StageStatus }) {
  const cls =
    status === 'created'
      ? 'text-ok border-ok/30 bg-ok/10'
      : status === 'pending_review'
      ? 'text-warn border-warn/30 bg-warn/10'
      : status === 'closed'
      ? 'text-tx-muted border-os-border bg-os-base'
      : 'text-tx-muted border-os-border bg-os-base'

  const label = status === 'pending_review' ? 'pending review' : status

  return (
    <span className={`flex-shrink-0 px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-wider border ${cls}`}>
      {label}
    </span>
  )
}

// ── Dot connector ─────────────────────────────────────────────────────────────

function StageDot({ status, last }: { status: StageStatus; last: boolean }) {
  const dotClass =
    status === 'created'
      ? 'bg-ok'
      : status === 'pending_review'
      ? 'bg-warn'
      : status === 'closed'
      ? 'bg-tx-muted/40'
      : 'bg-os-border'

  return (
    <div className="flex flex-col items-center flex-shrink-0" style={{ minWidth: '10px' }}>
      <div className={`w-2 h-2 rounded-full mt-0.5 ${dotClass}`} />
      {!last && <div className="w-px flex-1 bg-os-border mt-0.5" style={{ minHeight: '10px' }} />}
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AuthorityTimeline({ item }: { item: PreparedActionQueueEntry }) {
  const stages = deriveAuthorityTimeline(item)

  return (
    <div className="mt-3 pt-3 border-t border-os-border/60">
      <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2 px-1">
        Authority Timeline — read-only
      </p>
      <div className="space-y-0">
        {stages.map((stage, i) => (
          <div key={stage.name} className="flex items-start gap-2 px-1">
            <StageDot status={stage.status} last={i === stages.length - 1} />
            <div className="flex-1 flex items-start justify-between gap-2 pb-1.5">
              <div className="min-w-0">
                <p className="text-[10px] font-mono text-tx-secondary leading-tight">{stage.name}</p>
                {stage.note && (
                  <p className="text-[9px] font-mono text-tx-muted leading-tight mt-0.5 truncate max-w-[220px]">
                    {stage.note}
                  </p>
                )}
              </div>
              <StatusBadge status={stage.status} />
            </div>
          </div>
        ))}
      </div>
      <p className="text-[9px] font-mono text-tx-muted mt-2 px-1">
        No action from this panel executes, approves, or issues tokens.
      </p>
    </div>
  )
}
