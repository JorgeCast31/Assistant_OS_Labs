'use client'

import type { PreparedActionQueueEntry } from '@/lib/types'
import { AuthorityTimeline } from './AuthorityTimeline'
import { PreparedActionInputTrace } from './PreparedActionInputTrace'

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  const display = !value ? '—' : value
  return (
    <div>
      <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">{label}</p>
      <p className="text-xs font-mono text-tx-secondary break-all">{display}</p>
    </div>
  )
}

function SectionHeader({ title }: { title: string }) {
  return (
    <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2 mt-3 first:mt-0">
      {title}
    </p>
  )
}

export function PreparedActionDetailPanel({ item }: { item: PreparedActionQueueEntry }) {
  const nextSafeStep =
    item.human_confirmation_status === 'pending'
      ? 'Review the prepared action. Human confirmation is still pending.'
      : 'Awaiting human review.'

  return (
    <div className="mt-2 space-y-0">

      {/* A. Input / Intent */}
      <SectionHeader title="Input / Intent" />
      <div className="grid grid-cols-1 gap-2">
        <Field label="User Intent" value={item.user_intent} />
        <Field label="Domain" value={item.domain} />
        <Field label="Requested Action" value={item.requested_action} />
      </div>

      {/* B. Origin Trace */}
      <PreparedActionInputTrace item={item} />

      {/* C. Capability */}
      <SectionHeader title="Capability" />
      <div className="grid grid-cols-1 gap-2">
        <Field label="Capability Name" value={item.capability_name} />
        <Field label="Capability Scope" value={item.capability_scope?.join(', ') || null} />
      </div>

      {/* C. Provider / Seat Trace */}
      <SectionHeader title="Provider / Seat Trace" />
      <div className="grid grid-cols-1 gap-2">
        <Field label="Provider Name" value={item.provider_name} />
        <Field label="Model Name" value={item.model_name} />
        <Field label="Delegated Seat Ref" value={item.delegated_seat_ref} />
      </div>

      {/* D. Artifact Chain */}
      <SectionHeader title="Artifact Chain" />
      <div className="grid grid-cols-1 gap-2">
        <Field label="Proposal ID" value={item.proposal_id} />
        <Field label="Preparation ID" value={item.preparation_id} />
        <Field label="Prepared Action ID" value={item.prepared_action_id} />
        <Field label="Queue Entry ID" value={item.queue_entry_id} />
      </div>

      {/* E. Review State */}
      <SectionHeader title="Review State" />
      <div className="grid grid-cols-2 gap-2">
        <Field label="Status" value={item.status} />
        <Field label="Human Confirmation Status" value={item.human_confirmation_status} />
        <Field label="Review Only" value={String(item.review_only)} />
        <Field label="Execution Allowed" value={String(item.execution_allowed)} />
        <Field label="Can Execute Now" value={String(item.can_execute_now)} />
        <Field label="Created At" value={item.created_at} />
      </div>

      {/* F. Authority Timeline */}
      <AuthorityTimeline item={item} />

      {/* G. Execution Boundary */}
      <div className="mt-3 pt-2 border-t border-os-border/60">
        <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-1">
          Execution Boundary
        </p>
        <p className="text-[10px] font-mono text-tx-muted leading-relaxed">
          Inspection only. This does not execute, approve, reject, issue tokens, create AuthorizedPlan, or call PoliceGate.
        </p>
      </div>

      {/* H. Next Safe Step */}
      <div className="mt-3">
        <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-1">
          Next Safe Step
        </p>
        <p className="text-[10px] font-mono text-tx-muted leading-relaxed">
          {nextSafeStep}
        </p>
        <p className="text-[10px] font-mono text-tx-muted leading-relaxed mt-1">
          Execution remains closed until PolicyDecision → CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate are satisfied.
        </p>
      </div>

    </div>
  )
}
