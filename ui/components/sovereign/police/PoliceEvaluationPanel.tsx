import type { PoliceEvaluationRecord } from '@/lib/sovereign/police-types'

const policeEvaluationFixture: PoliceEvaluationRecord = {
  evaluation_id: 'police-eval-static-001',
  request_id: 'request-static-001',
  outcome: 'ALLOW',
  risk_level: 'LOW',
  violations: [],
  allowed_tools: ['read_audit_records'],
  denied_tools: ['write_runtime_state'],
  allowed_environments: ['local_readonly'],
  denied_environments: ['production_runtime'],
  why_blocked: null,
  required_confirmation_reason: null,
  created_at: '2026-05-07T12:00:00Z',
}

export function PoliceEvaluationPanel() {
  const record = policeEvaluationFixture

  return (
    <section className="rounded-lg border border-os-border bg-os-surface overflow-hidden">
      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-xs font-mono text-tx-secondary uppercase tracking-wider">Police Evaluation</p>
      </div>

      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-[10px] font-mono text-tx-muted leading-relaxed">
          PoliceEvaluation.ALLOW is observational and not execution authorization.
        </p>
        <p className="text-[10px] font-mono text-tx-muted mt-1">
          Read-only surface. No mutation controls.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 py-3">
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Outcome</p>
          <p className="text-sm font-mono text-tx-primary">{record.outcome}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Risk</p>
          <p className="text-sm font-mono text-tx-secondary">{record.risk_level}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Evaluation ID</p>
          <p className="text-sm font-mono text-tx-secondary break-words">{record.evaluation_id}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Request ID</p>
          <p className="text-sm font-mono text-tx-secondary break-words">{record.request_id}</p>
        </div>
      </div>
    </section>
  )
}
