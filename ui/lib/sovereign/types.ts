// ── Sovereign Interface Types ─────────────────────────────────────────────────
// Types for the three-layer sovereign operating interface

// ── View Identifiers ──────────────────────────────────────────────────────────

export type SovereignViewId = 'system' | 'sovereign-status' | 'security' | 'mso' | 'agents'

export type AgentId = string

// ── Status Types ──────────────────────────────────────────────────────────────

export type AuthorityStatus = 'active' | 'blocked' | 'deciding'

export type AgentStatus = 'idle' | 'active' | 'degraded' | 'dormant' | 'waiting_auth'

export type SystemHealth = 'healthy' | 'degraded' | 'unavailable'
export type ExecutionStatus = 'real' | 'stub' | 'unavailable' | 'partial'
export type ExecutionStatusSource = 'backend' | 'ui_fallback'

/**
 * ALFA-FLIGHT-02 §5 — optional traceability for assistant decisions.
 * Absence is never inferred as a value; renderers hide the badge when
 * missing.
 */
export type DecisionSource = 'llm' | 'rule' | 'hybrid'

// ── Surface Types (for API routing) ───────────────────────────────────────────

export type SurfaceType = 'system_chat' | 'mso_direct' | 'agent_command'

// ── Message Types ─────────────────────────────────────────────────────────────

export interface SovereignMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  surface: SurfaceType
  // MSO-specific fields
  plan?: MSOPlanItem[]
  requiresConfirmation?: boolean
  executionState?: ExecutionState
  governanceTrace?: GovernanceTrace
  executionStatus?: ExecutionStatus
  executionStatusSource?: ExecutionStatusSource
  // Extended MSO fields
  executionMode?: 'direct' | 'plan' | 'confirm' | 'blocked'
  policyDecision?: PolicyDecision
  authorityArtifact?: AuthorityArtifact
  pendingConfirmation?: PendingConfirmation
  // ALFA-FLIGHT-02 §5 — optional traceability badge data.
  decisionSource?: DecisionSource
  confidenceScore?: number
  // ALFA-FLIGHT-02 §3 — when present, render redirect chips below the message.
  redirectTargets?: ('mso' | 'machine_operator')[]
}

export interface GovernanceTrace {
  decision: 'ALLOW' | 'BLOCK' | 'REQUIRE_CONFIRMATION' | 'DEGRADED'
  reason?: string
  policy_id?: string
  risk_level?: 'low' | 'medium' | 'high' | 'critical'
}

// ── MSO Types ─────────────────────────────────────────────────────────────────

export interface MSOPlanItem {
  id: string
  step: number
  action: string
  description: string
  status: 'pending' | 'executing' | 'completed' | 'failed' | 'blocked'
  requiresAuth?: boolean
}

export type ExecutionState = 
  | 'idle'
  | 'planning'
  | 'awaiting_confirmation'
  | 'executing'
  | 'completed'
  | 'failed'
  | 'blocked'

export interface MSOState {
  status: AuthorityStatus
  currentPlan: MSOPlanItem[] | null
  executionState: ExecutionState
  lastDecision: string | null
  activePolicy: string | null
}

// ── Agent Types ───────────────────────────────────────────────────────────────

export interface AgentCommand {
  id: string
  command: string
  timestamp: string
  status: 'pending' | 'executing' | 'completed' | 'failed' | 'escalated'
  output?: string
  error?: string
  escalation?: EscalationRequest
}

export interface EscalationRequest {
  id: string
  agentId: AgentId
  reason: string
  suggestedCommand: string
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
  timestamp: string
}

export interface AgentState {
  id: AgentId
  name: string
  status: AgentStatus
  commandHistory: AgentCommand[]
  pendingEscalations: EscalationRequest[]
}

// ── Agent Registry ────────────────────────────────────────────────────────────
// Matches assistant_os/operability.py:build_agents_registry_response() per-agent shape.

export interface RegistryAgent {
  id: string
  name: string
  domain: string | null
  description: string | null
  status: string
  capabilities: string[]
  last_execution_at: string | null
  last_result: string | null
  policy_restricted: boolean
  requires_authority: boolean
  requires_review: boolean
}

// ── System State ──────────────────────────────────────────────────────────────

export interface SovereignSystemState {
  health: SystemHealth
  msoStatus: AuthorityStatus
  activeAgents: number
  totalAgents: number
  lastUpdated: string | null
  /** Full agent list from /agents/registry. Empty until first poll. */
  registeredAgents: RegistryAgent[]
  /** Source state for /agents/registry fetches. */
  agentRegistrySource: ReadinessSourceState
  /** Source state for /system/capabilities fetches. */
  capabilitiesSource: ReadinessSourceState
}

// ── Readiness Source Metadata ─────────────────────────────────────────────────
// Tracks the fetch state of each data source so future readiness UI can
// distinguish not-yet-loaded, loading, available, empty, unavailable, and stale.

export type ReadinessSourceStatus =
  | 'unknown'      // initial state; no fetch has been attempted
  | 'loading'      // fetch in flight
  | 'available'    // fetch succeeded and returned data
  | 'empty'        // fetch succeeded but source has no entries
  | 'unavailable'  // fetch failed; no prior success to fall back on
  | 'stale'        // fetch failed but a prior successful fetch exists

export interface ReadinessSourceState {
  status: ReadinessSourceStatus
  lastCheckedAt: string | null
  lastSuccessfulAt: string | null
  error: string | null
}

// ── API Request/Response Types ────────────────────────────────────────────────

export interface SovereignChatRequest {
  text: string
  surface: SurfaceType
  session_id?: string
}

export interface SovereignChatResponse {
  ok: boolean
  message: string
  trace_id: string
  domain?: string
  intent?: string
  mode?: string
  needs_confirmation: boolean
  plan?: MSOPlanItem[]
  governance_trace?: GovernanceTrace
  execution_status?: ExecutionStatus
  execution_status_source?: ExecutionStatusSource
  error?: string
  // Extended MSO response fields
  execution_mode?: 'direct' | 'plan' | 'confirm' | 'blocked'
  policy_decision?: PolicyDecision
  authority_artifact?: AuthorityArtifact
  pending_confirmation?: PendingConfirmation
  confirmation?: ConfirmationResult
  // ALFA-FLIGHT-02 §5 — optional traceability. Absent = no signal.
  decision_source?: DecisionSource
  confidence_score?: number
}

export interface PolicyDecision {
  decision: 'ALLOW' | 'BLOCK' | 'REQUIRE_CONFIRMATION' | 'ESCALATE'
  reason: string
  policy_id?: string
  risk_level?: 'low' | 'medium' | 'high' | 'critical'
}

export interface AuthorityArtifact {
  artifact_id: string
  type: 'plan' | 'command' | 'script' | 'action'
  summary: string
  details?: Record<string, unknown>
  requires_auth: boolean
  timestamp: string
}

export interface PendingConfirmation {
  confirmation_id: string
  prompt: string
  artifact?: AuthorityArtifact
  expires_at?: string
}

export interface ConfirmationResult {
  confirmed: boolean
  confirmed_at?: string
  cancelled_at?: string
  reason?: string
}

// ── Agent Command Request ─────────────────────────────────────────────────────

export interface AgentCommandRequest {
  command: string
  agentId: AgentId
}

export interface AgentCommandResponse {
  ok: boolean
  output: string
  status: AgentCommand['status']
  escalation?: EscalationRequest
  error?: string
}
