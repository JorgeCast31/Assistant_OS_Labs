'use client'

import type { OutcomeStatusResponse } from '@/lib/types'
import { useOutcomeStatusPolling } from '@/hooks/use-outcome-status-polling'
import { useOutcomeStatusStore } from '@/stores/outcome-status-store'

const NOTE_COPY = 'Outcome status is observational; it does not grant execution permission.'

function valueOrDash(value: string | null | undefined): string {
  if (!value) return '—'
  return value
}

function boolOrUnknown(value: boolean | undefined): string {
  if (value === true) return 'yes'
  if (value === false) return 'no'
  return 'unknown'
}

function outcomeViewState(response: OutcomeStatusResponse | null): 'found' | 'not_found' | 'unknown' {
  if (!response) return 'unknown'
  if (!response.ok) return 'unknown'
  return response.found ? 'found' : 'not_found'
}

export function OutcomeStatusPanel() {
  useOutcomeStatusPolling()

  const outcomeStatus = useOutcomeStatusStore((s) => s.outcomeStatus)
  const isPolling = useOutcomeStatusStore((s) => s.isPolling)
  const lastPolled = useOutcomeStatusStore((s) => s.lastPolled)
  const pollError = useOutcomeStatusStore((s) => s.pollError)

  const state = outcomeViewState(outcomeStatus)
  const outcome = outcomeStatus?.outcome
  const correlation = outcomeStatus?.correlation ?? {}
  const sources = outcomeStatus?.sources ?? {}
  const sourceErrors = outcomeStatus?.source_errors ?? []

  return (
    <div className="rounded-lg border border-os-border bg-os-surface overflow-hidden">
      <div className="px-4 py-3 border-b border-os-border">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs font-mono text-tx-secondary uppercase tracking-wider">Outcome Status</p>
          <span className={`text-[10px] font-mono ${isPolling ? 'text-tx-muted' : 'text-tx-secondary'}`}>
            {isPolling ? 'Polling...' : 'Polled'}
          </span>
        </div>
      </div>

      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-[10px] font-mono text-tx-muted leading-relaxed">
          {outcomeStatus?.note ?? NOTE_COPY}
        </p>
        {pollError && <p className="text-[10px] font-mono text-warn mt-1">Poll error: {pollError}</p>}
        {lastPolled && (
          <p className="text-[10px] font-mono text-tx-muted mt-1">
            Last polled: {new Date(lastPolled).toLocaleTimeString('es', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            })}
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 py-3 border-b border-os-border">
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">State</p>
          <p className="text-sm font-mono text-tx-primary">{state}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Status</p>
          <p className="text-sm font-mono text-tx-primary">{valueOrDash(outcome?.status)}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Result Type</p>
          <p className="text-sm font-mono text-tx-primary">{valueOrDash(outcome?.result_type)}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Execution Status</p>
          <p className="text-sm font-mono text-tx-primary">{valueOrDash(outcome?.execution_status)}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Domain</p>
          <p className="text-sm font-mono text-tx-primary">{valueOrDash(outcome?.domain)}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Action</p>
          <p className="text-sm font-mono text-tx-primary">{valueOrDash(outcome?.action)}</p>
        </div>
        <div className="col-span-2">
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Message</p>
          <p className="text-sm font-mono text-tx-primary break-words">{valueOrDash(outcome?.message)}</p>
        </div>
      </div>

      {(outcome?.error_type || outcome?.error_message || outcomeStatus?.error) && (
        <div className="px-4 py-3 border-b border-os-border">
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Errors</p>
          <p className="text-xs font-mono text-warn mt-1">
            error_type: {valueOrDash(outcome?.error_type)}
          </p>
          <p className="text-xs font-mono text-warn mt-1 break-words">
            error_message: {valueOrDash(outcome?.error_message ?? outcomeStatus?.error)}
          </p>
        </div>
      )}

      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-2">Correlation</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <p className="text-xs font-mono text-tx-secondary">plan_id: {valueOrDash(correlation.plan_id)}</p>
          <p className="text-xs font-mono text-tx-secondary">context_id: {valueOrDash(correlation.context_id)}</p>
          <p className="text-xs font-mono text-tx-secondary">trace_id: {valueOrDash(correlation.trace_id)}</p>
          <p className="text-xs font-mono text-tx-secondary">task_id: {valueOrDash(correlation.task_id)}</p>
          <p className="text-xs font-mono text-tx-secondary">execution_id: {valueOrDash(correlation.execution_id)}</p>
          <p className="text-xs font-mono text-tx-secondary">policy_decision_ref: {valueOrDash(correlation.policy_decision_ref)}</p>
          <p className="text-xs font-mono text-tx-secondary">governance_ref: {valueOrDash(correlation.governance_ref)}</p>
          <p className="text-xs font-mono text-tx-secondary">execution_mode: {valueOrDash(correlation.execution_mode)}</p>
        </div>
      </div>

      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-2">Sources</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <p className="text-xs font-mono text-tx-secondary">task_registry: {boolOrUnknown(sources.task_registry)}</p>
          <p className="text-xs font-mono text-tx-secondary">trace_chain: {boolOrUnknown(sources.trace_chain)}</p>
          <p className="text-xs font-mono text-tx-secondary">context_store_pending: {boolOrUnknown(sources.context_store_pending)}</p>
          <p className="text-xs font-mono text-tx-secondary">runner_metadata: {boolOrUnknown(sources.runner_metadata)}</p>
        </div>
      </div>

      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-2">Source Errors</p>
        {sourceErrors.length === 0 ? (
          <p className="text-xs font-mono text-tx-secondary">None reported.</p>
        ) : (
          <div className="space-y-1">
            {sourceErrors.map((item, idx) => (
              <p key={`${item.source}-${idx}`} className="text-xs font-mono text-warn break-words">
                {item.source}: {item.error}
              </p>
            ))}
          </div>
        )}
      </div>

      {(!outcomeStatus?.ok || !outcomeStatus?.found) && (
        <div className="px-4 py-3">
          <p className="text-[10px] font-mono text-warn">Outcome status unavailable or not found (fail-soft).</p>
        </div>
      )}
    </div>
  )
}
