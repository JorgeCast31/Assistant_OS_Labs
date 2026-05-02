'use client'

import { useState, useEffect, useCallback } from 'react'
import { getRecentGovernanceDecisions } from '@/lib/api'
import type { GovernanceRecentResponse, GovernanceDecisionSummary } from '@/lib/types'

const LIMIT = 10

// ── Styling maps ──────────────────────────────────────────────────────────────
// ALLOW is intentionally neutral — it is NOT a health signal or authority badge.

const ACTION_DOT: Record<string, string> = {
  ALLOW:                'bg-idle',
  BLOCK:                'bg-err',
  REQUIRE_CONFIRMATION: 'bg-warn',
  DEGRADE:              'bg-warn',
}

const ACTION_TEXT: Record<string, string> = {
  ALLOW:                'text-tx-secondary',
  BLOCK:                'text-err',
  REQUIRE_CONFIRMATION: 'text-warn',
  DEGRADE:              'text-warn',
}

const RISK_TEXT: Record<string, string> = {
  low:    'text-tx-muted',
  medium: 'text-warn',
  high:   'text-err',
}

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtRef(ref: string): string {
  return ref.length > 14 ? `…${ref.slice(-12)}` : ref
}

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('es', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch {
    return iso
  }
}

// ── DecisionCard ──────────────────────────────────────────────────────────────

function DecisionCard({ d }: { d: GovernanceDecisionSummary }) {
  const dotClass  = ACTION_DOT[d.action]  ?? 'bg-idle'
  const textClass = ACTION_TEXT[d.action] ?? 'text-tx-secondary'
  const riskClass = RISK_TEXT[d.risk_level] ?? 'text-tx-muted'
  const firstReason  = d.reasons[0]
  const extraConstraints = d.constraints.length + d.interventions.length

  return (
    <div className="px-4 py-3 flex flex-col gap-1">
      {/* Action + timestamp */}
      <div className="flex items-center gap-2">
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotClass}`} />
        <span className={`text-xs font-mono font-semibold ${textClass}`}>
          {d.action}
        </span>
        <span className="text-[10px] font-mono text-tx-muted ml-auto">
          {fmtTime(d.created_at)}
        </span>
      </div>

      {/* Target */}
      <p className="text-[10px] font-mono text-tx-secondary pl-3.5">
        {d.target_domain} / {d.target_action}
      </p>

      {/* Risk · mode · exec mode */}
      <div className="flex items-center gap-3 pl-3.5 flex-wrap">
        <span className={`text-[10px] font-mono ${riskClass}`}>
          risk: {d.risk_level}
        </span>
        <span className="text-[10px] font-mono text-tx-muted">
          op: {d.operational_mode}
        </span>
        <span className="text-[10px] font-mono text-tx-muted">
          exec: {d.effective_execution_mode}
        </span>
      </div>

      {/* First reason */}
      {firstReason && (
        <p className="text-[10px] font-mono text-tx-muted pl-3.5 truncate">
          {firstReason.code}: {firstReason.detail}
          {d.reasons.length > 1 && ` (+${d.reasons.length - 1} more)`}
        </p>
      )}

      {/* Constraints / interventions count */}
      {extraConstraints > 0 && (
        <p className="text-[10px] font-mono text-tx-muted pl-3.5">
          {extraConstraints} constraint/intervention(s)
        </p>
      )}

      {/* Ref */}
      <p className="text-[10px] font-mono text-tx-muted pl-3.5">
        ref: {fmtRef(d.governance_ref)}
      </p>
    </div>
  )
}

// ── GovernanceRecentPanel ─────────────────────────────────────────────────────

export function GovernanceRecentPanel() {
  const [data,       setData]       = useState<GovernanceRecentResponse | null>(null)
  const [loading,    setLoading]    = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setFetchError(null)
    try {
      const result = await getRecentGovernanceDecisions(LIMIT)
      setData(result)
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : 'Request failed')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  return (
    <div className="bg-os-surface border border-os-border rounded-lg overflow-hidden">

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-os-border">
        <div>
          <p className="text-xs font-mono font-medium text-tx-secondary">
            Recent Governance
          </p>
          <p className="text-[10px] font-mono text-tx-muted mt-0.5">
            Ephemeral runtime decisions — not MSO health, does not imply MSO active.
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
          aria-label="Refresh governance decisions"
        >
          <span className={loading ? 'animate-spin inline-block' : ''}>↺</span>
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-2 px-4 py-4">
          <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
          <span className="text-xs font-mono text-tx-muted">Loading…</span>
        </div>
      )}

      {/* Fetch error */}
      {!loading && fetchError && (
        <div className="px-4 py-4">
          <p className="text-[10px] font-mono text-tx-muted">
            Governance history unavailable. {fetchError}
          </p>
        </div>
      )}

      {/* Empty state */}
      {!loading && !fetchError && data && data.count === 0 && (
        <div className="px-4 py-4">
          <p className="text-[10px] font-mono text-tx-muted">
            No recent governance decisions recorded since backend start.
          </p>
          <p className="text-[10px] font-mono text-tx-muted mt-1">
            This does not mean MSO is inactive.
          </p>
        </div>
      )}

      {/* Decision list */}
      {!loading && !fetchError && data && data.count > 0 && (
        <div className="divide-y divide-os-border">
          {data.decisions.map((d) => (
            <DecisionCard key={d.governance_ref} d={d} />
          ))}
        </div>
      )}

    </div>
  )
}
