'use client'

/**
 * M29: CognitiveStatusPanel
 *
 * Expanded status panel for all cognitive providers.
 * Shown in the System view when ui_cognition_enabled = true.
 *
 * Rules:
 * - State is backend-derived only — never invented.
 * - No chat path, no model invocation UI.
 */
import { useCognitionStore } from '@/stores/cognition-store'
import type { CognitionProvider, CognitionProviderStatus } from '@/lib/types'

const STATUS_COLOR: Record<CognitionProviderStatus, string> = {
  online:   'text-ok',
  offline:  'text-err',
  degraded: 'text-warn',
  disabled: 'text-idle',
}

const STATUS_DOT: Record<CognitionProviderStatus, string> = {
  online:   'bg-ok',
  offline:  'bg-err',
  degraded: 'bg-warn',
  disabled: 'bg-idle',
}

function ProviderRow({ provider }: { provider: CognitionProvider }) {
  const status = provider.status
  return (
    <div className="flex flex-col gap-1 p-3 rounded border border-os-border bg-os-surface">
      {/* Header row */}
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[status]}`} />
        <span className="text-xs font-mono font-medium text-tx-primary">{provider.label}</span>
        <span className={`ml-auto text-[10px] font-mono uppercase tracking-wider ${STATUS_COLOR[status]}`}>
          {status}
        </span>
      </div>

      {/* Details */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 mt-1 text-[10px] font-mono text-tx-muted">
        <span>backend</span>
        <span className="text-tx-secondary">{provider.backend || '—'}</span>
        <span>model</span>
        <span className="text-tx-secondary truncate">{provider.model || '—'}</span>
        {provider.latency_ms > 0 && (
          <>
            <span>latency</span>
            <span className="text-tx-secondary">{provider.latency_ms}ms</span>
          </>
        )}
        {provider.last_health_check && (
          <>
            <span>checked</span>
            <span className="text-tx-secondary truncate">
              {new Date(provider.last_health_check).toLocaleTimeString()}
            </span>
          </>
        )}
      </div>

      {/* Available tasks */}
      {provider.available_tasks.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {provider.available_tasks.map((t) => (
            <span
              key={t}
              className="px-1 py-0.5 rounded text-[9px] font-mono bg-os-elevated text-tx-muted border border-os-border"
            >
              {t}
            </span>
          ))}
        </div>
      )}

      {/* Error */}
      {provider.error && (
        <p className="mt-1 text-[10px] font-mono text-warn truncate" title={provider.error}>
          {provider.error}
        </p>
      )}
    </div>
  )
}

export function CognitiveStatusPanel() {
  const uiEnabled  = useCognitionStore((s) => s.uiEnabled)
  const providers  = useCognitionStore((s) => s.providers)
  const lastPolled = useCognitionStore((s) => s.lastPolled)
  const pollError  = useCognitionStore((s) => s.pollError)

  if (!uiEnabled) return null

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h3 className="text-[11px] font-mono font-medium text-tx-secondary uppercase tracking-wider">
          Cognitive Providers
        </h3>
        {lastPolled && (
          <span className="text-[9px] font-mono text-tx-muted">
            {new Date(lastPolled).toLocaleTimeString()}
          </span>
        )}
      </div>

      {pollError && (
        <p className="text-[10px] font-mono text-warn px-2">{pollError}</p>
      )}

      {providers.length === 0 ? (
        <p className="text-[10px] font-mono text-tx-muted px-1">No providers reported.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {providers.map((p) => (
            <ProviderRow key={p.provider_id} provider={p} />
          ))}
        </div>
      )}
    </section>
  )
}
