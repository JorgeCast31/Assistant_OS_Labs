'use client'

import { useUIStore } from '@/stores/ui-store'
import { useSeatProviderStore } from '@/stores/seat-provider-store'
import { usePreparedActionsStore } from '@/stores/prepared-actions-store'
import { useConfirmPendingStore } from '@/stores/confirm-pending-store'
import { useAuthorityStatusStore } from '@/stores/authority-status-store'
import { useSovereignStore } from '@/stores/sovereign-store'
import { useSeatProviderPolling } from '@/hooks/use-seat-provider-polling'
import { usePreparedActionsPolling } from '@/hooks/use-prepared-actions-polling'
import { useConfirmPendingPolling } from '@/hooks/use-confirm-pending-polling'
import { useAuthorityStatusPolling } from '@/hooks/use-authority-status-polling'
import { MissionControlChainView } from './MissionControlChainView'

// ── Sub-components ──────────────────────────────────────────────────────────

function SituationTile({
  label,
  value,
  accent = false,
  warn = false,
}: {
  label: string
  value: string | number
  accent?: boolean
  warn?: boolean
}) {
  const color = warn ? 'text-warn' : accent ? 'text-ok' : 'text-tx-primary'
  return (
    <div className="bg-os-surface border border-os-border rounded-lg p-4">
      <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-mono font-semibold ${color}`}>{value}</p>
    </div>
  )
}

function PostureRow({
  label,
  value,
  tone = 'muted',
  note,
}: {
  label: string
  value: string
  tone?: 'ok' | 'warn' | 'muted'
  note?: string
}) {
  const toneClass =
    tone === 'ok' ? 'text-ok border-ok/30 bg-ok/10' :
    tone === 'warn' ? 'text-warn border-warn/30 bg-warn/10' :
    'text-tx-muted border-os-border bg-os-base'

  return (
    <div className="rounded-lg border border-os-border bg-os-surface p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-mono text-tx-secondary">{label}</p>
        <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border ${toneClass}`}>
          {value}
        </span>
      </div>
      {note && <p className="mt-1 text-[10px] font-mono text-tx-muted">{note}</p>}
    </div>
  )
}

function NextStepBanner({ text, sub }: { text: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-accent/30 bg-accent/5 p-4">
      <p className="text-xs font-mono text-accent">{text}</p>
      {sub && <p className="mt-1 text-[10px] font-mono text-tx-muted">{sub}</p>}
    </div>
  )
}

function fmtTime(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('es', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

// ── Component ───────────────────────────────────────────────────────────────

export function MissionControlView() {
  useSeatProviderPolling()
  usePreparedActionsPolling()
  useConfirmPendingPolling()
  useAuthorityStatusPolling()

  const { operationalMode, webhookStatus, apiStatus, lastUpdated } = useUIStore((s) => s.systemData)
  const seatProvider = useSeatProviderStore((s) => s.seatProvider)
  const preparedActions = usePreparedActionsStore((s) => s.preparedActions)
  const confirmPending = useConfirmPendingStore((s) => s.confirmPending)
  const authorityStatus = useAuthorityStatusStore((s) => s.authorityStatus)
  const registeredAgents = useSovereignStore((s) => s.systemState.registeredAgents)

  const provider = seatProvider?.seat_provider ?? null
  const preparedCount = preparedActions?.count ?? 0
  const latestItem = preparedActions?.items?.[0] ?? null
  const confirmCount = confirmPending?.pending_count ?? 0
  const authCounts = authorityStatus?.counts ?? null
  const modeOk = operationalMode === 'NORMAL'

  const nextStep = (() => {
    if (operationalMode !== 'NORMAL' && operationalMode !== 'UNKNOWN') {
      return {
        text: 'Resolve governance restriction.',
        sub: `Operational mode: ${operationalMode}. Review governance status before proceeding.`,
      }
    }
    if (preparedCount > 0) {
      return {
        text: 'Review pending prepared actions.',
        sub: `${preparedCount} action${preparedCount !== 1 ? 's' : ''} waiting for manual review in the confirm queue.`,
      }
    }
    return {
      text: 'Create a plan_request.',
      sub: 'No prepared actions pending. Send a plan_request to the cognitive seat to begin a governed workflow.',
    }
  })()

  const agentCount = registeredAgents.length

  return (
    <div className="h-full overflow-y-auto bg-os-base">
      <div className="max-w-3xl mx-auto p-6 space-y-6">

        {/* Header */}
        <div>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest">
            Mission Control
          </p>
          <p className="text-xs font-mono text-tx-secondary mt-1">
            Read-only composite situation room. This does not execute. MSO coordinates; execution remains governed and closed.
          </p>
          <p className="text-[10px] font-mono text-tx-muted mt-1">
            Prepared actions are waiting for manual review. No action from this panel approves, executes, or issues tokens.
          </p>
        </div>

        {/* Runtime Snapshot */}
        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Runtime Snapshot
          </p>
          <div className="grid grid-cols-3 gap-3">
            <SituationTile
              label="Operational Mode"
              value={operationalMode}
              accent={modeOk}
              warn={!modeOk && operationalMode !== 'UNKNOWN'}
            />
            <SituationTile
              label="System"
              value={`${apiStatus} / ${webhookStatus}`}
              accent={apiStatus === 'ok' && webhookStatus === 'ok'}
            />
            <SituationTile
              label="Last Update"
              value={fmtTime(lastUpdated)}
            />
          </div>
        </section>

        {/* MSO Seat */}
        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            MSO Seat
          </p>
          <div className="space-y-2">
            {provider === null ? (
              <PostureRow
                label="Cognitive Provider"
                value="Not configured"
                tone="warn"
                note="Set MSO_SEAT_PROVIDER env var to configure (anthropic, llama)."
              />
            ) : (
              <>
                <PostureRow
                  label="Provider"
                  value={provider.provider_name}
                  tone={provider.is_available ? 'ok' : 'warn'}
                  note={`Model: ${provider.model_name} · ${provider.local_or_remote}`}
                />
                <PostureRow
                  label="Availability"
                  value={provider.availability}
                  tone={provider.is_available ? 'ok' : 'warn'}
                />
              </>
            )}
            <PostureRow
              label="Cognitive Only"
              value="Yes"
              tone="ok"
              note="Invariant. used_execution=false enforced by provider contract."
            />
            <PostureRow
              label="Execution Allowed"
              value="No"
              tone="muted"
              note="Architectural invariant. MSO Seat coordinates; it does not execute."
            />
            <PostureRow label="Can Execute Now" value="No" tone="muted" />
          </div>
        </section>

        {/* Queue Snapshot */}
        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Queue Snapshot
          </p>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <SituationTile
              label="Prepared Actions"
              value={preparedActions === null ? '…' : preparedCount}
              accent={preparedActions !== null && preparedCount === 0}
              warn={preparedCount > 0}
            />
            <SituationTile
              label="Confirm Pending"
              value={confirmPending === null ? '…' : confirmCount}
              accent={confirmPending !== null && confirmCount === 0}
              warn={confirmCount > 0}
            />
          </div>
          {preparedCount > 0 ? (
            <div className="rounded-lg border border-warn/30 bg-warn/5 p-3">
              <p className="text-[10px] font-mono text-warn">
                {preparedCount} prepared action{preparedCount !== 1 ? 's' : ''} waiting for manual review.
                Execution remains closed. Each action includes a read-only authority timeline showing all 11 stages. Open Confirm Queue to inspect prepared action details.
              </p>
            </div>
          ) : (
            <PostureRow label="Queue Status" value="Clear" tone="ok" note="No prepared actions pending." />
          )}
        </section>

        {/* Current Operational Chain */}
        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Current Operational Chain
          </p>
          <MissionControlChainView latestItem={latestItem} totalCount={preparedCount} />
        </section>

        {/* Authority Posture */}
        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Authority Posture
          </p>
          <div className="space-y-2">
            {authCounts !== null ? (
              <>
                <PostureRow
                  label="Capabilities"
                  value={`${authCounts.allow} allow / ${authCounts.deny} deny`}
                  tone="muted"
                  note={`${authCounts.total} total · ${authCounts.confirm_only} confirm-only · Active grants: ${authCounts.active_grants}`}
                />
                <PostureRow
                  label="Active Revocations"
                  value={String(authCounts.active_revocations)}
                  tone={authCounts.active_revocations > 0 ? 'warn' : 'ok'}
                />
              </>
            ) : (
              <PostureRow label="Authority Matrix" value="Loading…" tone="muted" />
            )}
            <PostureRow
              label="Police Gate"
              value="Fail-closed"
              tone="ok"
              note="8-step enforcement: token present, registered, not expired, not consumed, binding match, authorized plan, delegated seat valid, capability in scope."
            />
            <PostureRow
              label="Governed Execution"
              value="Closed"
              tone="muted"
              note="Full chain required: PolicyDecision → CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate."
            />
          </div>
        </section>

        {/* Agents / Destinations */}
        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Agents / Destinations
          </p>
          <div className="space-y-2">
            <PostureRow
              label="CODE/docs"
              value="Candidate"
              tone="ok"
              note="Plan pipeline active. Governed execution not yet wired for CODE/docs in current sprint."
            />
            <PostureRow
              label="HOST"
              value="Guarded"
              tone="muted"
              note="Not operational. Requires full authority chain."
            />
            <PostureRow
              label="MACHINE_OPERATOR"
              value="Guarded"
              tone="muted"
              note="Not operational in current sprint."
            />
            <PostureRow
              label="OpenClaw"
              value="Disabled"
              tone="muted"
              note="Not available in current configuration."
            />
            {agentCount > 0 && (
              <p className="text-[10px] font-mono text-tx-muted px-1">
                Registered agents: {agentCount}
              </p>
            )}
          </div>
        </section>

        {/* Next Safe Step */}
        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Next Safe Step
          </p>
          <div className="space-y-2">
            <NextStepBanner text={nextStep.text} sub={nextStep.sub} />
            <div className="rounded-lg border border-os-border bg-os-surface p-3">
              <p className="text-[10px] font-mono text-tx-muted">
                Execution remains closed. No action from this panel executes, approves, or issues tokens.
              </p>
            </div>
          </div>
        </section>

      </div>
    </div>
  )
}
