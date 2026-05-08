import type { CandidateAuditRecordShape } from '@/lib/sovereign/police-types'

const candidateAuditRecordFixture: CandidateAuditRecordShape = {
  audit_id: 'audit-static-001',
  event_type: 'candidate_created',
  candidate_id: 'candidate-static-001',
  mission_id: 'mission-static-001',
  agent_id: 'agent-static-001',
  police_evaluation_id: 'police-eval-static-001',
  police_evaluation_outcome: 'ALLOW',
  operation_key: 'audit.read.static',
  created_at: '2026-05-07T12:02:00Z',
}

export function CandidateAuditRecordPanel() {
  const record = candidateAuditRecordFixture

  return (
    <section className="rounded-lg border border-os-border bg-os-surface overflow-hidden">
      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-xs font-mono text-tx-secondary uppercase tracking-wider">
          Candidate Audit Record
        </p>
      </div>

      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-[10px] font-mono text-tx-muted leading-relaxed">
          CandidateAuditRecord is observational evidence, not authority.
        </p>
        <p className="text-[10px] font-mono text-tx-muted mt-1">
          Read-only surface. No mutation controls.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 py-3">
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Event</p>
          <p className="text-sm font-mono text-tx-primary">{record.event_type}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Outcome Ref</p>
          <p className="text-sm font-mono text-tx-secondary">{record.police_evaluation_outcome}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Audit ID</p>
          <p className="text-sm font-mono text-tx-secondary break-words">{record.audit_id}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Candidate ID</p>
          <p className="text-sm font-mono text-tx-secondary break-words">{record.candidate_id}</p>
        </div>
      </div>
    </section>
  )
}
