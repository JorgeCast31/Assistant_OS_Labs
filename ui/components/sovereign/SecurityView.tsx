'use client'

import { AuthorityMatrixPanel } from './AuthorityMatrixPanel'
import { ExecutionNotOpenPanel } from './ExecutionNotOpenPanel'

function SecurityRow({
  label,
  status,
  tone = 'ok',
}: {
  label: string
  status: string
  tone?: 'ok' | 'warn' | 'muted'
}) {
  const toneClass =
    tone === 'ok' ? 'text-ok border-ok/30 bg-ok/10' :
    tone === 'warn' ? 'text-warn border-warn/30 bg-warn/10' :
    'text-tx-muted border-os-border bg-os-base'

  return (
    <div className="rounded-lg border border-os-border bg-os-surface p-3 flex items-center justify-between gap-3">
      <p className="text-xs font-mono text-tx-secondary">{label}</p>
      <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border ${toneClass}`}>
        {status}
      </span>
    </div>
  )
}

export function SecurityView() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <div>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest">
            Security
          </p>
          <p className="text-xs font-mono text-tx-secondary mt-1">
            Police and authority posture for sovereign governance.
          </p>
        </div>

        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Police Guardrails
          </p>
          <div className="space-y-2">
            <SecurityRow label="Police Gate" status="Active / Fail-closed" tone="ok" />
            <SecurityRow label="Token lifecycle" status="Enforced" tone="ok" />
            <SecurityRow label="Binding verification" status="Enforced" tone="ok" />
            <SecurityRow label="AuthorizedPlan ref binding" status="Enforced" tone="ok" />
            <SecurityRow label="Capability scope" status="Enforced" tone="ok" />
            <SecurityRow label="Delegated seat validation" status="Active" tone="ok" />
            <SecurityRow label="Direct-call guards" status="Active" tone="ok" />
            <SecurityRow label="Quarantine" status="Not active / no quarantined agents" tone="muted" />
          </div>
        </section>

        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Blocked Paths
          </p>
          <div className="rounded-lg border border-os-border bg-os-surface p-4 space-y-2">
            <p className="text-xs font-mono text-tx-primary">- HOST direct-call without authority</p>
            <p className="text-xs font-mono text-tx-primary">- MACHINE_OPERATOR direct-call without authority</p>
            <p className="text-xs font-mono text-tx-primary">- OpenClaw operational execution</p>
          </div>
        </section>

        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Remaining Gap
          </p>
          <div className="rounded-lg border border-warn/30 bg-warn/10 p-4">
            <p className="text-xs font-mono text-warn">Temporal Restriction: Pending</p>
          </div>
        </section>

        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Authority Matrix
          </p>
          <AuthorityMatrixPanel />
        </section>

        <ExecutionNotOpenPanel />
      </div>
    </div>
  )
}
