'use client'

import { useEffect, useState } from 'react'
import { useUIStore } from '@/stores/ui-store'
import { useSystemPolling } from '@/hooks/use-system-polling'
import {
  getSystemAssistantState,
  type SystemAssistantStateResponse,
} from '@/lib/api'
import { ExecutionNotOpenPanel } from './ExecutionNotOpenPanel'

function statusClass(status: string): string {
  switch (status) {
    case 'healthy':
      return 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25'
    case 'partial':
      return 'bg-amber-500/15 text-amber-300 border-amber-500/25'
    case 'unavailable':
      return 'bg-slate-500/15 text-slate-300 border-slate-500/25'
    default:
      return 'bg-sky-500/15 text-sky-300 border-sky-500/25'
  }
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider ${statusClass(status)}`}>
      status: {status}
    </span>
  )
}
export function SystemChatView() {
  const { systemData, isSystemRefreshing } = useUIStore()
  const { refresh } = useSystemPolling()
  const [state, setState] = useState<SystemAssistantStateResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadState = async () => {
    setIsLoading(true)
    setError(null)

    try {
      const next = await getSystemAssistantState()
      setState(next)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to load System Assistant state.'
      setError(message)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    void loadState()
  }, [])

  const interpretation = state?.interpretation
  const snapshot = state?.snapshot
  const operationalMode = systemData.operationalMode

  const modeClass =
    operationalMode === 'NORMAL'
      ? 'text-ok'
      : operationalMode === 'DEGRADED'
        ? 'text-warn'
        : operationalMode === 'FROZEN'
          ? 'text-err'
          : 'text-tx-muted'

  return (
    <div className="flex flex-col h-full bg-os-base">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-os-border bg-os-surface">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-teal-400" />
          <div>
            <h2 className="text-sm font-mono font-semibold text-teal-400">
              System
            </h2>
            <p className="text-[10px] font-mono text-tx-muted">
              Global runtime posture and passive observability
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={isSystemRefreshing}
            className="rounded-lg border border-os-border px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider text-tx-secondary transition-colors hover:border-os-border-hi disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isSystemRefreshing ? 'Refreshing…' : 'Refresh runtime'}
          </button>
          <button
            type="button"
            onClick={() => void loadState()}
            disabled={isLoading}
            className="rounded-lg border border-teal-500/25 bg-teal-500/10 px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider text-teal-300 transition-all hover:bg-teal-500/15 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? 'Refreshing…' : 'Refresh assistant'}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        <div className="rounded-xl border border-os-border bg-os-elevated px-4 py-4">
          <p className="text-[10px] font-mono uppercase tracking-wider text-teal-400/70">
            System posture
          </p>
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="rounded-lg border border-os-border p-3">
              <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Operational mode</p>
              <p className={`mt-1 text-sm font-mono ${modeClass}`}>{operationalMode}</p>
            </div>
            <div className="rounded-lg border border-os-border p-3">
              <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Code API</p>
              <p className="mt-1 text-sm font-mono text-tx-primary">{systemData.apiStatus}</p>
            </div>
            <div className="rounded-lg border border-os-border p-3">
              <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Webhook</p>
              <p className="mt-1 text-sm font-mono text-tx-primary">{systemData.webhookStatus}</p>
            </div>
            <div className="rounded-lg border border-os-border p-3">
              <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Authority stack</p>
              <p className="mt-1 text-sm font-mono text-tx-primary">Policy + Police + AuthorizedPlan required</p>
            </div>
            <div className="rounded-lg border border-os-border p-3">
              <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Execution path</p>
              <p className="mt-1 text-sm font-mono text-warn">Guarded</p>
            </div>
            <div className="rounded-lg border border-os-border p-3">
              <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">OpenClaw</p>
              <p className="mt-1 text-sm font-mono text-tx-muted">Disabled</p>
            </div>
          </div>
        </div>

        <ExecutionNotOpenPanel />

        {isLoading && !state && (
          <div className="rounded-xl border border-os-border bg-os-elevated px-4 py-4">
            <div className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
              <div className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse [animation-delay:150ms]" />
              <div className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse [animation-delay:300ms]" />
            </div>
            <p className="mt-3 text-sm font-mono text-tx-secondary">
              Loading System Assistant state from the backend.
            </p>
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-4">
            <p className="text-xs font-mono uppercase tracking-wider text-amber-300">
              Passive error state
            </p>
            <p className="mt-2 text-sm font-mono text-tx-primary">
              {error}
            </p>
            <p className="mt-2 text-xs font-mono text-tx-muted">
              This view remains read-only and does not issue retries beyond re-fetching the same endpoint.
            </p>
          </div>
        )}

        {!isLoading && !state && !error && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-16 h-16 rounded-2xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-center mb-4">
              <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
                <circle cx="16" cy="16" r="6" stroke="currentColor" strokeWidth="2" className="text-teal-400" />
                <circle cx="16" cy="16" r="12" stroke="currentColor" strokeWidth="2" strokeDasharray="3 3" className="text-teal-400/40" />
              </svg>
            </div>
            <h3 className="text-lg font-mono font-medium text-tx-primary mb-2">
              System Chat
            </h3>
            <p className="text-sm font-mono text-tx-secondary max-w-md leading-relaxed">
              This is the informational layer. Ask questions about the system,
              query status, or explore capabilities.
            </p>
            <p className="text-xs font-mono text-teal-400/60 mt-4">
              This surface never executes or authorizes actions.
            </p>
          </div>
        )}

        {state && interpretation && (
          <>
            <div className="rounded-xl border border-os-border bg-os-elevated px-4 py-4 space-y-3">
              <div className="flex items-center gap-3 flex-wrap">
                <StatusBadge status={interpretation.status} />
                <span className="inline-flex items-center rounded border border-slate-500/25 bg-slate-500/10 px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider text-slate-300">
                  source: {interpretation.source}
                </span>
                <span className="inline-flex items-center rounded border border-slate-500/20 bg-slate-500/8 px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider text-slate-400/60">
                  exec: null
                </span>
              </div>

              <div>
                <p className="text-[10px] font-mono uppercase tracking-wider text-teal-400/60">
                  Assistant summary
                </p>
                <p className="mt-2 text-sm font-mono leading-relaxed text-tx-primary">
                  {interpretation.summary}
                </p>
              </div>

              {snapshot?.operational_mode != null && (
                <div>
                  <p className="text-[10px] font-mono uppercase tracking-wider text-teal-400/60">
                    Assistant-reported mode
                  </p>
                  <div className="mt-2 flex items-center gap-2">
                    <p className="text-sm font-mono text-tx-primary">
                      {snapshot.operational_mode}
                    </p>
                    {(snapshot.operational_mode === 'UNKNOWN' || snapshot.operational_mode === null) && (
                      <span className="text-[9px] font-mono text-amber-300/70 border border-amber-500/20 rounded px-1.5 py-0.5">
                        UNKNOWN ≠ NORMAL
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="rounded-xl border border-os-border bg-os-elevated px-4 py-4">
              <p className="text-[10px] font-mono uppercase tracking-wider text-teal-400/60">
                Observations
              </p>
              <ul className="mt-3 space-y-2">
                {interpretation.observations.map((item, index) => (
                  <li key={`${item}-${index}`} className="flex gap-2 text-sm font-mono text-tx-primary">
                    <span className="mt-px text-teal-400/60">-</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="rounded-xl border border-os-border bg-os-elevated px-4 py-4">
              <p className="text-[10px] font-mono uppercase tracking-wider text-teal-400/60">
                Warnings
              </p>
              {interpretation.warnings.length > 0 ? (
                <ul className="mt-3 space-y-2">
                  {interpretation.warnings.map((warning, index) => (
                    <li key={`${warning}-${index}`} className="flex gap-2 text-sm font-mono text-tx-primary">
                      <span className="mt-px text-amber-300">!</span>
                      <span>{warning}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-3 text-sm font-mono text-tx-secondary">
                  No warnings reported by the backend.
                </p>
              )}
            </div>
          </>
        )}
      </div>

      <div className="px-6 py-4 border-t border-os-border bg-os-surface">
        <p className="text-[9px] font-mono text-tx-muted text-center">
          Passive view only. This surface summarizes runtime status and re-fetches system-assistant state without execution.
        </p>
      </div>
    </div>
  )
}
