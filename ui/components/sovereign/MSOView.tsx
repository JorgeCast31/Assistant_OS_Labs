'use client'

import { useUIStore } from '@/stores/ui-store'
import { useSeatProviderPolling } from '@/hooks/use-seat-provider-polling'
import { useSeatProviderStore } from '@/stores/seat-provider-store'
import { usePreparedActionsPolling } from '@/hooks/use-prepared-actions-polling'
import { usePreparedActionsStore } from '@/stores/prepared-actions-store'
import { useConfirmPendingPolling } from '@/hooks/use-confirm-pending-polling'
import { useConfirmPendingStore } from '@/stores/confirm-pending-store'
import { useMSOChatStore } from '@/stores/mso-chat-store'
import { ExecutionNotOpenPanel } from './ExecutionNotOpenPanel'
import { MSOInvariantStrip } from './MSOInvariantStrip'
import { MSOProviderSelector } from './MSOProviderSelector'
import { MSOChatTranscript } from './MSOChatTranscript'
import { MSOComposer } from './MSOComposer'

function StatusRow({
  label,
  value,
  tone = 'ok',
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

function availabilityTone(availability: string | undefined, isAvailable: boolean): 'ok' | 'warn' | 'muted' {
  if (isAvailable) return 'ok'
  if (availability === 'api_key_missing') return 'warn'
  if (availability === 'unavailable') return 'warn'
  return 'muted'
}

export function MSOView() {
  useSeatProviderPolling()
  usePreparedActionsPolling()
  useConfirmPendingPolling()

  const { operationalMode } = useUIStore((s) => s.systemData)
  const seatProvider = useSeatProviderStore((s) => s.seatProvider)
  const lastPolled = useSeatProviderStore((s) => s.lastPolled)
  const pollError = useSeatProviderStore((s) => s.pollError)

  const preparedActions = usePreparedActionsStore((s) => s.preparedActions)
  const confirmPending = useConfirmPendingStore((s) => s.confirmPending)

  const messages = useMSOChatStore((s) => s.messages)

  const provider = seatProvider?.seat_provider ?? null
  const providerLoaded = seatProvider !== null

  const providerName = provider?.provider_name ?? null
  const modelName = provider?.model_name ?? null
  const isAvailable = provider?.is_available ?? false
  const availability = provider?.availability ?? null
  const localOrRemote = provider?.local_or_remote ?? null

  const preparedCount = preparedActions?.count ?? 0
  const confirmCount = confirmPending?.pending_count ?? 0

  return (
    <div className="flex h-full flex-col bg-os-base">

      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="flex-none border-b border-os-border px-6 py-3 space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest">
              MSO · Conversational Console
            </p>
            <p className="text-xs font-mono text-tx-secondary mt-0.5">
              Cognitive control layer. MSO coordinates; it does not execute.
            </p>
          </div>

        </div>

        {/* Invariant strip — always visible */}
        <MSOInvariantStrip />
      </div>

      {/* ── Collapsible system status ───────────────────────────── */}
      <details className="flex-none overflow-y-auto border-b border-os-border bg-os-base">
        <summary className="cursor-pointer px-6 py-2 text-[10px] font-mono text-tx-muted hover:text-tx-secondary">
          System status
        </summary>
        <div className="max-w-3xl mx-auto px-6 py-4 space-y-6">

            {/* Provider selector */}
            <MSOProviderSelector />

            {/* Seat and Authority Posture */}
            <section>
              <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
                Seat and Authority Posture
              </p>
              <div className="space-y-2">
                <StatusRow
                  label="Seat Mode"
                  value="Cognitive / Non-executing"
                  tone="ok"
                  note="Architectural invariant. The seat coordinates; it does not execute."
                />
                <StatusRow
                  label="Execution Allowed"
                  value="No"
                  tone="muted"
                  note="Execution requires full authority chain: PolicyDecision → CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate."
                />
                <StatusRow label="Can Execute Now" value="No" tone="muted" />
                <StatusRow
                  label="Operational Mode"
                  value={operationalMode}
                  tone={operationalMode === 'NORMAL' ? 'ok' : 'warn'}
                  note="Live. Source: /mso/state."
                />
              </div>
            </section>

            {/* Seated Cognitive Provider */}
            <section>
              <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
                Seated Cognitive Provider
              </p>
              {!providerLoaded && (
                <div className="rounded-lg border border-os-border bg-os-surface p-3">
                  <p className="text-xs font-mono text-tx-muted">Polling provider metadata…</p>
                </div>
              )}
              {pollError && (
                <div className="rounded-lg border border-warn/30 bg-warn/10 p-3 mb-2">
                  <p className="text-[10px] font-mono text-warn">Poll error: {pollError}</p>
                </div>
              )}
              {providerLoaded && (
                <div className="space-y-2">
                  {provider === null ? (
                    <StatusRow
                      label="Seated Provider"
                      value="Not configured"
                      tone="muted"
                      note="Set MSO_SEAT_PROVIDER env var to configure a cognitive provider (anthropic, llama)."
                    />
                  ) : (
                    <>
                      <StatusRow
                        label="Provider"
                        value={providerName ?? 'unknown'}
                        tone={isAvailable ? 'ok' : 'warn'}
                        note="Live. Source: /mso/seat/provider. Config-derived — no network call."
                      />
                      <StatusRow
                        label="Model"
                        value={modelName || 'not set'}
                        tone={modelName ? 'ok' : 'muted'}
                      />
                      <StatusRow
                        label="Provider Availability"
                        value={availability ?? 'unknown'}
                        tone={availabilityTone(availability ?? undefined, isAvailable)}
                        note={
                          availability === 'api_key_missing'
                            ? 'API key not configured. Set the provider API key env var.'
                            : availability === 'not_configured'
                            ? 'Provider not configured. Check MSO_SEAT_PROVIDER env var.'
                            : availability === 'local_endpoint_missing'
                            ? 'Local endpoint URL not set. Check LOCAL_LLM_BASE_URL env var.'
                            : availability === 'not_implemented'
                            ? 'This provider adapter is not yet implemented.'
                            : undefined
                        }
                      />
                      <StatusRow
                        label="Deployment"
                        value={localOrRemote ?? 'unknown'}
                        tone="muted"
                      />
                      <StatusRow
                        label="Cognitive Only"
                        value="Yes"
                        tone="ok"
                        note="Invariant. used_execution=false enforced by provider contract."
                      />
                    </>
                  )}
                  {lastPolled && (
                    <p className="text-[10px] font-mono text-tx-muted px-1">
                      Last polled: {new Date(lastPolled).toLocaleTimeString('es', {
                        hour: '2-digit', minute: '2-digit', second: '2-digit',
                      })}
                    </p>
                  )}
                </div>
              )}
            </section>

            {/* Orchestration Capability */}
            <section>
              <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
                Orchestration Capability
              </p>
              <div className="space-y-2">
                <StatusRow label="Can prepare proposals" value="Yes" tone="ok" note="MSOExecutionProposal — cognitive only, non-executing." />
                <StatusRow label="Can prepare authority review" value="Yes" tone="ok" note="AuthorityPreparationRequest — declares all 5 pending authority steps." />
                <StatusRow label="Can create confirmable prepared action" value="Yes" tone="ok" note="ConfirmablePreparedAction — waiting_for_human_confirmation." />
                <StatusRow label="Can enqueue for manual review" value="Yes" tone="ok" note="ConfirmablePreparedActionQueueEntry — review_only=true." />
                <StatusRow label="Can execute directly" value="No" tone="muted" note="Architectural invariant. No execution path from this seat." />
              </div>
            </section>

            {/* Queue & Timeline Summary */}
            <section>
              <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
                Queue &amp; Timeline Summary
              </p>
              <div className="grid grid-cols-2 gap-3 mb-3">
                <div className="bg-os-surface border border-os-border rounded-lg p-4">
                  <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-1">Prepared Actions</p>
                  <p className={`text-2xl font-mono font-semibold ${preparedCount > 0 ? 'text-warn' : 'text-ok'}`}>
                    {preparedActions === null ? '…' : preparedCount}
                  </p>
                </div>
                <div className="bg-os-surface border border-os-border rounded-lg p-4">
                  <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-1">Confirm Pending</p>
                  <p className={`text-2xl font-mono font-semibold ${confirmCount > 0 ? 'text-warn' : 'text-ok'}`}>
                    {confirmPending === null ? '…' : confirmCount}
                  </p>
                </div>
              </div>
              <p className="text-[10px] font-mono text-tx-muted px-1">
                The full authority timeline has 11 stages from plan_request to execution.
                Review queue via Mission Control.
              </p>
            </section>

            {/* CODE/docs Posture */}
            <section>
              <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
                CODE/docs Posture
              </p>
              <div className="space-y-2">
                <StatusRow
                  label="Surface"
                  value="read-only"
                  tone="muted"
                  note="CODE/docs surface is read-only. No mutations via this seat."
                />
                <StatusRow
                  label="Execution"
                  value="Closed"
                  tone="muted"
                  note="Execution remains closed. No direct run path from this surface."
                />
              </div>
            </section>

            {/* Next Safe Step */}
            <section>
              <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
                Next Safe Step
              </p>
              <div className="rounded-lg border border-os-border bg-os-surface p-3">
                <p className="text-xs font-mono text-tx-secondary">
                  Submit a <span className="font-semibold text-tx-primary">plan_request</span> to begin
                  the authority chain. MSO will prepare a proposal for human review.
                </p>
              </div>
            </section>

            <ExecutionNotOpenPanel />
          </div>
        </details>

      {/* ── Chat transcript — scrollable center ────────────────── */}
      <div className="flex-1 overflow-y-auto">
        <MSOChatTranscript messages={messages} />
      </div>

      {/* ── Composer — pinned to bottom ─────────────────────────── */}
      <div className="flex-none">
        <MSOComposer />
      </div>
    </div>
  )
}
