'use client'

/**
 * AuthorityHealthPanel — Authority/Health Surface v0 (observational).
 *
 * Reveals the real readiness of the system without ever implying capability.
 * It shows GO / AMBER / STOP / NO_VERIFICADO per check, plus blockers, and a
 * permanent banner making clear the UI is observational and can_execute_now is
 * false. It NEVER renders an execute/approve/deny control.
 *
 * Self-contained: fetches /api/system/authority-health directly (own polling),
 * so mounting it introduces no new store/hook coupling.
 */

import { useEffect, useState } from 'react'

type CheckStatus = 'GO' | 'AMBER' | 'STOP' | 'NO_VERIFICADO'

interface HealthCheck {
  check: string
  status: CheckStatus
  detail: string
  extra?: Record<string, unknown>
}

interface HealthSnapshot {
  ok?: boolean
  overall?: CheckStatus
  generated_at?: string
  can_execute_now?: boolean
  execution_allowed?: boolean
  authority_granted?: boolean
  runner_available?: boolean
  durable_queue_present?: boolean
  backend_deploy_enabled?: boolean
  ui_is_observational?: boolean
  checks?: HealthCheck[]
  blockers?: { check: string; detail: string }[]
  warnings?: { check: string; detail: string }[]
  error?: string
}

const STATUS_STYLE: Record<CheckStatus, { dot: string; text: string; border: string; label: string }> = {
  GO:            { dot: 'bg-ok',   text: 'text-ok',       border: 'border-ok/30 bg-ok/10',     label: 'GO' },
  AMBER:         { dot: 'bg-warn', text: 'text-warn',     border: 'border-warn/30 bg-warn/10', label: 'AMBER' },
  STOP:          { dot: 'bg-err',  text: 'text-err',      border: 'border-err/30 bg-err/10',   label: 'STOP' },
  NO_VERIFICADO: { dot: 'bg-idle', text: 'text-tx-muted', border: 'border-os-border bg-os-base', label: 'NO_VERIFICADO' },
}

function statusOf(s?: CheckStatus): CheckStatus {
  return s && s in STATUS_STYLE ? s : 'NO_VERIFICADO'
}

function StatusBadge({ status }: { status: CheckStatus }) {
  const st = STATUS_STYLE[statusOf(status)]
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border ${st.border} ${st.text}`}>
      {st.label}
    </span>
  )
}

export function AuthorityHealthPanel({ pollMs = 8000 }: { pollMs?: number }) {
  const [snap, setSnap] = useState<HealthSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true

    async function load() {
      try {
        const res = await fetch('/api/system/authority-health', { cache: 'no-store' })
        const data = (await res.json()) as HealthSnapshot
        if (!alive) return
        setSnap(data)
        setFetchError(null)
      } catch (err) {
        if (!alive) return
        setFetchError(err instanceof Error ? err.message : String(err))
      } finally {
        if (alive) setLoading(false)
      }
    }

    load()
    const id = setInterval(load, pollMs)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [pollMs])

  const overall = statusOf(snap?.overall)
  const overallStyle = STATUS_STYLE[overall]
  const checks = snap?.checks ?? []
  const blockers = snap?.blockers ?? []

  return (
    <section className="bg-os-surface border border-os-border rounded-lg p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${overallStyle.dot}`} />
          <h3 className="text-sm font-mono font-semibold text-tx-primary">Authority / Health Surface</h3>
          <span className="text-[10px] font-mono text-tx-muted">v0</span>
        </div>
        <StatusBadge status={overall} />
      </div>

      {/* Observational banner — always visible, never implies capability */}
      <div className="rounded border border-warn/30 bg-warn/10 px-3 py-2">
        <p className="text-[11px] font-mono text-warn">
          Observational surface · UI does not execute or authorize ·{' '}
          <span className="font-semibold">can_execute_now = false</span>
        </p>
      </div>

      {loading && !snap ? (
        <p className="text-xs font-mono text-tx-muted">Loading readiness…</p>
      ) : null}

      {fetchError ? (
        <p className="text-xs font-mono text-err">Surface unreachable: {fetchError} (treated as NO_VERIFICADO)</p>
      ) : null}

      {snap?.error ? (
        <p className="text-xs font-mono text-warn">Backend note: {snap.error}</p>
      ) : null}

      {/* Hard flags */}
      <div className="grid grid-cols-3 gap-2">
        <Flag label="Runner" value={snap?.runner_available ? 'available' : 'blocked'} tone={snap?.runner_available ? 'warn' : 'muted'} />
        <Flag label="Durable queue" value={snap?.durable_queue_present ? 'present' : 'absent'} tone="muted" />
        <Flag label="Backend deploy" value={snap?.backend_deploy_enabled ? 'enabled' : 'off'} tone="muted" />
      </div>

      {/* Checks */}
      <div className="space-y-2">
        {checks.map((c) => (
          <div key={c.check} className="rounded-lg border border-os-border bg-os-base p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-mono text-tx-secondary">{c.check}</p>
              <StatusBadge status={c.status} />
            </div>
            {c.detail ? (
              <p className="mt-1 text-[11px] font-mono text-tx-muted leading-relaxed">{c.detail}</p>
            ) : null}
          </div>
        ))}
        {checks.length === 0 && !loading ? (
          <p className="text-xs font-mono text-tx-muted">No checks reported.</p>
        ) : null}
      </div>

      {/* Blockers */}
      {blockers.length > 0 ? (
        <div className="rounded border border-err/30 bg-err/10 px-3 py-2">
          <p className="text-[10px] font-mono uppercase tracking-wider text-err mb-1">Blockers (STOP)</p>
          <ul className="space-y-1">
            {blockers.map((b) => (
              <li key={b.check} className="text-[11px] font-mono text-err">
                <span className="font-semibold">{b.check}:</span> {b.detail}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {snap?.generated_at ? (
        <p className="text-[10px] font-mono text-tx-muted">Generated at {snap.generated_at}</p>
      ) : null}
    </section>
  )
}

function Flag({ label, value, tone }: { label: string; value: string; tone: 'warn' | 'muted' }) {
  const toneClass = tone === 'warn' ? 'text-warn' : 'text-tx-muted'
  return (
    <div className="bg-os-base border border-os-border rounded-lg p-3">
      <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-xs font-mono font-semibold ${toneClass}`}>{value}</p>
    </div>
  )
}

export default AuthorityHealthPanel
