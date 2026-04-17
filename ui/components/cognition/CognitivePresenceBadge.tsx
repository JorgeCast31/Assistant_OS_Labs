'use client'

/**
 * M29: CognitivePresenceBadge
 *
 * Persistent HUD indicator showing the local cognitive engine's status.
 * Rendered in TopHUD when ui_cognition_enabled = true.
 *
 * Rules:
 * - Never invents status — all state comes from the store (backend-derived).
 * - Renders nothing when the feature is disabled.
 * - Does NOT expose a chat path or direct model access.
 */
import { useCognitionStore } from '@/stores/cognition-store'
import type { CognitionProviderStatus } from '@/lib/types'

const STATUS_DOT: Record<CognitionProviderStatus, string> = {
  online:   'bg-ok',
  offline:  'bg-err',
  degraded: 'bg-warn',
  disabled: 'bg-idle',
}

const STATUS_LABEL: Record<CognitionProviderStatus, string> = {
  online:   'local·on',
  offline:  'local·off',
  degraded: 'local·deg',
  disabled: 'local·dis',
}

export function CognitivePresenceBadge() {
  const uiEnabled = useCognitionStore((s) => s.uiEnabled)
  const isPolling = useCognitionStore((s) => s.isPolling)
  const local     = useCognitionStore((s) => s.providers.find((p) => p.provider_id === 'local_llm'))

  if (!uiEnabled) return null

  const status: CognitionProviderStatus = local?.status ?? 'disabled'
  const dotColor = STATUS_DOT[status]
  const label    = STATUS_LABEL[status]
  const title    = local
    ? `${local.label} — ${status}${local.model ? ` (${local.model})` : ''}${local.latency_ms ? ` · ${local.latency_ms}ms` : ''}`
    : 'Local cognitive engine — unknown'

  return (
    <div
      className="flex items-center gap-1.5 px-1.5 py-0.5 rounded border border-os-border bg-os-surface"
      title={title}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotColor} ${isPolling ? 'animate-pulse' : ''}`}
      />
      <span className="text-[9px] font-mono text-tx-muted uppercase tracking-wider hidden sm:inline">
        {label}
      </span>
    </div>
  )
}
