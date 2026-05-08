import type { MissionExecutionCandidateRecord } from '@/lib/sovereign/police-types'

const missionExecutionCandidateFixture: MissionExecutionCandidateRecord = {
  candidate_id: 'candidate-static-001',
  mission_id: 'mission-static-001',
  activity_id: 'activity-static-001',
  workstream_id: 'workstream-static-001',
  agent_id: 'agent-static-001',
  agent_profile_id: 'agent-profile-static-001',
  police_evaluation_id: 'police-eval-static-001',
  police_evaluation_outcome: 'ALLOW',
  operation_key: 'audit.read.static',
  candidate_status: 'PENDING_GATE',
  created_at: '2026-05-07T12:01:00Z',
}

export function MissionExecutionCandidatePanel() {
  const record = missionExecutionCandidateFixture

  return (
    <section className="rounded-lg border border-os-border bg-os-surface overflow-hidden">
      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-xs font-mono text-tx-secondary uppercase tracking-wider">
          Mission Candidate
        </p>
      </div>

      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-[10px] font-mono text-tx-muted leading-relaxed">
          pending_gate is a neutral waiting state and does not grant execution permission.
        </p>
        <p className="text-[10px] font-mono text-tx-muted mt-1">
          Read-only surface. No mutation controls.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 py-3">
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">State</p>
          <p className="text-sm font-mono text-tx-primary">{record.candidate_status}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Outcome Ref</p>
          <p className="text-sm font-mono text-tx-secondary">{record.police_evaluation_outcome}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Candidate ID</p>
          <p className="text-sm font-mono text-tx-secondary break-words">{record.candidate_id}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Mission ID</p>
          <p className="text-sm font-mono text-tx-secondary break-words">{record.mission_id}</p>
        </div>
      </div>
    </section>
  )
}
