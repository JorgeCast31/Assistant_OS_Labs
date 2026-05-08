// Observational DTOs for the future Police/Audit showroom.
// These shapes describe records only; they do not provide execution authority.

export type PoliceEvaluationOutcome = 'ALLOW' | 'DENY' | 'REQUIRES_CONFIRMATION'

export type PoliceRiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type CandidateStatus = 'PENDING_GATE'

export interface PoliceViolationRecord {
  code: string
  message: string
  severity: PoliceRiskLevel
  field: string | null
}

export interface PoliceEvaluationRecord {
  evaluation_id: string
  request_id: string
  outcome: PoliceEvaluationOutcome
  risk_level: PoliceRiskLevel
  violations: PoliceViolationRecord[]
  allowed_tools: string[]
  denied_tools: string[]
  allowed_environments: string[]
  denied_environments: string[]
  why_blocked: string | null
  required_confirmation_reason: string | null
  created_at: string
}

export interface MissionExecutionCandidateRecord {
  candidate_id: string
  mission_id: string
  activity_id: string | null
  workstream_id: string | null
  agent_id: string
  agent_profile_id: string
  police_evaluation_id: string
  police_evaluation_outcome: PoliceEvaluationOutcome
  operation_key: string
  candidate_status: CandidateStatus
  created_at: string
}

export interface CandidateAuditRecordShape {
  audit_id: string
  event_type: 'candidate_created'
  candidate_id: string
  mission_id: string
  agent_id: string
  police_evaluation_id: string
  police_evaluation_outcome: PoliceEvaluationOutcome
  operation_key: string
  created_at: string
}

export interface AgentPermissionProfileShape {
  agent_id: string
  declared_capabilities: string[]
  permitted_tools: string[]
  permitted_environments: string[]
  requires_review: boolean
  status: string
}
