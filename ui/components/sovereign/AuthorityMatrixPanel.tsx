'use client'

import { useAuthorityStatusPolling } from '@/hooks/use-authority-status-polling'
import { useAuthorityStatusStore } from '@/stores/authority-status-store'

function boolFlag(value: boolean): string {
  return value ? 'yes' : 'no'
}

function shortAction(value: string): string {
  if (!value) return '—'
  if (value.length <= 34) return value
  return `${value.slice(0, 30)}...`
}

export function AuthorityMatrixPanel() {
  useAuthorityStatusPolling()

  const authorityStatus = useAuthorityStatusStore((s) => s.authorityStatus)
  const isPolling = useAuthorityStatusStore((s) => s.isPolling)
  const lastPolled = useAuthorityStatusStore((s) => s.lastPolled)
  const pollError = useAuthorityStatusStore((s) => s.pollError)

  const counts = authorityStatus?.counts ?? {
    total: 0,
    allow: 0,
    confirm_only: 0,
    deny: 0,
    blocked: 0,
    active_grants: 0,
    active_revocations: 0,
  }

  const capabilities = authorityStatus?.capabilities ?? []

  return (
    <div className="rounded-lg border border-os-border bg-os-surface overflow-hidden">
      <div className="px-4 py-3 border-b border-os-border">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs font-mono text-tx-secondary uppercase tracking-wider">Authority Matrix</p>
          <span className={`text-[10px] font-mono ${isPolling ? 'text-tx-muted' : 'text-tx-secondary'}`}>
            {isPolling ? 'Polling...' : 'Polled'}
          </span>
        </div>
      </div>

      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-[10px] font-mono text-tx-muted leading-relaxed">
          Authority status is posture, not execution permission.
        </p>
        <p className="text-[10px] font-mono text-tx-muted mt-1 leading-relaxed">
          {authorityStatus?.note ?? 'Authority status is posture, not execution permission.'}
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
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Total</p>
          <p className="text-sm font-mono text-tx-primary">{counts.total}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Allow</p>
          <p className="text-sm font-mono text-ok">{counts.allow}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Confirm Only</p>
          <p className="text-sm font-mono text-warn">{counts.confirm_only}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Blocked</p>
          <p className="text-sm font-mono text-err">{counts.blocked}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Deny</p>
          <p className="text-sm font-mono text-err">{counts.deny}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Active Grants</p>
          <p className="text-sm font-mono text-tx-primary">{counts.active_grants}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Active Revocations</p>
          <p className="text-sm font-mono text-tx-primary">{counts.active_revocations}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Source</p>
          <p className="text-sm font-mono text-tx-primary">{authorityStatus?.source ?? 'authority_status'}</p>
        </div>
      </div>

      {!authorityStatus?.ok && (
        <div className="px-4 py-3 border-b border-os-border">
          <p className="text-[10px] font-mono text-warn">Authority status unavailable (fail-soft).</p>
          {authorityStatus?.error && (
            <p className="text-[10px] font-mono text-tx-muted mt-1">{authorityStatus.error}</p>
          )}
        </div>
      )}

      <div className="divide-y divide-os-border">
        {capabilities.length === 0 ? (
          <div className="px-4 py-3 text-[10px] font-mono text-tx-muted">No capabilities reported.</div>
        ) : (
          capabilities.map((row, idx) => (
            <div key={`${row.domain}-${row.action}-${idx}`} className="px-4 py-3 grid grid-cols-2 md:grid-cols-5 gap-2">
              <div>
                <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Domain</p>
                <p className="text-xs font-mono text-tx-secondary">{row.domain || '—'}</p>
              </div>
              <div>
                <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Action</p>
                <p className="text-xs font-mono text-tx-secondary">{shortAction(row.action)}</p>
              </div>
              <div>
                <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Mode / Posture</p>
                <p className="text-xs font-mono text-tx-secondary">{row.mode} / {row.effective_posture}</p>
              </div>
              <div>
                <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Grant / Revoke</p>
                <p className="text-xs font-mono text-tx-secondary">{boolFlag(row.active_grant)} / {boolFlag(row.active_revocation)}</p>
              </div>
              <div>
                <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Allowed</p>
                <p className={`text-xs font-mono ${row.allowed ? 'text-ok' : 'text-err'}`}>{boolFlag(row.allowed)}</p>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
