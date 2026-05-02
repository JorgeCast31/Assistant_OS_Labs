'use client'

import { useState, useEffect, useCallback } from 'react'
import { getGovernanceStatus } from '@/lib/api'
import type { GovernanceStatusResponse, OperationalMode } from '@/lib/types'

// ── Styling maps ──────────────────────────────────────────────────────────────
// Mode colors communicate operational state — NOT health or activity.

const MODE_DOT: Record<string, string> = {
  NORMAL:     'bg-idle',
  FROZEN:     'bg-err',
  DEGRADED:   'bg-warn',
  RESTRICTED: 'bg-warn',
  UNKNOWN:    'bg-idle',
}

const MODE_TEXT: Record<string, string> = {
  NORMAL:     'text-tx-secondary',
  FROZEN:     'text-err',
  DEGRADED:   'text-warn',
  RESTRICTED: 'text-warn',
  UNKNOWN:    'text-tx-muted',
}

// ── Component ─────────────────────────────────────────────────────────────────

export function GovernanceStatusBand() {
  const [data,    setData]    = useState<GovernanceStatusResponse | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await getGovernanceStatus()
      setData(result)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const mode: OperationalMode = data?.operational_mode ?? 'UNKNOWN'
  const dotClass  = MODE_DOT[mode]  ?? 'bg-idle'
  const textClass = MODE_TEXT[mode] ?? 'text-tx-muted'

  return (
    <div className="bg-os-surface border border-os-border rounded-lg overflow-hidden">

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-os-border">
        <div>
          <p className="text-xs font-mono font-medium text-tx-secondary">
            Governance Status
          </p>
          <p className="text-[10px] font-mono text-tx-muted mt-0.5">
            Read from MSO state — does not imply MSO active or healthy.
          </p>
        </div>
        <button
          onClick={() => void load()}
          disabled={loading}
          className="
            px-2 py-1 text-[10px] font-mono rounded border
            border-os-border text-tx-muted
            hover:text-tx-secondary hover:border-os-border-hi transition-colors
            disabled:opacity-40 disabled:cursor-not-allowed
          "
          aria-label="Refresh governance status"
        >
          <span className={loading ? 'animate-spin inline-block' : ''}>↺</span>
        </button>
      </div>

      <div className="px-4 py-3 space-y-2">

        {loading && (
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
            <span className="text-xs font-mono text-tx-muted">Loading…</span>
          </div>
        )}

        {!loading && !data?.ok && (
          <p className="text-[10px] font-mono text-tx-muted">
            Governance status unavailable.
          </p>
        )}

        {!loading && data?.ok && (
          <>
            {/* Operational mode */}
            <div className="flex items-center gap-2">
              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotClass}`} />
              <span className="text-[10px] font-mono text-tx-muted">mode:</span>
              <span className={`text-xs font-mono font-semibold ${textClass}`}>
                {mode}
              </span>
              {(data.operational_mode_source === 'manual' || data.operational_mode_source === 'override') && (
                <span className="text-[10px] font-mono text-tx-muted">(operator override)</span>
              )}
            </div>

            {/* Reason — only shown when non-empty */}
            {data.operational_mode_reason && (
              <p className="text-[10px] font-mono text-tx-muted pl-3.5 truncate">
                reason: {data.operational_mode_reason}
              </p>
            )}

            {/* Counts row */}
            <div className="flex items-center gap-4 pl-3.5 flex-wrap">
              {data.hardened_domain_count > 0 && (
                <span className="text-[10px] font-mono text-warn">
                  hardened: {data.hardened_domain_count}
                </span>
              )}
              {data.active_revocation_count > 0 && (
                <span className="text-[10px] font-mono text-warn">
                  revocations: {data.active_revocation_count}
                </span>
              )}
              {data.recent_anomaly_count > 0 && (
                <span className="text-[10px] font-mono text-warn">
                  anomalies: {data.recent_anomaly_count}
                </span>
              )}
              {data.hardened_domain_count === 0
                && data.active_revocation_count === 0
                && data.recent_anomaly_count === 0 && (
                <span className="text-[10px] font-mono text-tx-muted">
                  no active restrictions
                </span>
              )}
            </div>

            {/* Hardened domains list — only when present */}
            {data.hardened_domains.length > 0 && (
              <p className="text-[10px] font-mono text-tx-muted pl-3.5 truncate">
                domains: {data.hardened_domains.join(', ')}
              </p>
            )}
          </>
        )}

      </div>
    </div>
  )
}
