// ── Views ────────────────────────────────────────────────────────────────────

export type ViewId = 'chat' | 'executions' | 'system' | 'actions'

// ── Execution status values ───────────────────────────────────────────────────

/** Status values that come from the backend final_status field */
export type FinalStatus =
  | 'success'
  | 'failed'
  | 'needs_review'
  | 'approved'
  | 'rejected'
  | 'unknown'

/** Review actions that can be applied to an execution */
export type ReviewAction = 'approved' | 'rejected' | 'rerun'

// ── Execution list (GET /api/code/executions) ─────────────────────────────────

export interface ExecutionListItem {
  execution_id: string
  final_status: FinalStatus
  summary: string | null
  timestamp: string          // ISO 8601
  report_json_path: string | null
  report_md_path: string | null
  done_path: string | null
  metadata_path: string | null
  source: string | null
}

// ── Execution detail (GET /api/code/executions/{id}) ─────────────────────────

export interface TestResult {
  passed: number
  failed: number
}

export interface ValidationResult {
  final_status: string
  reasons: string[]
  validation_summary: string
}

/** Full metadata.json contents — also used for report.json (same shape) */
export interface ExecutionMetadata {
  execution_id: string
  status: string
  repo_path: string | null
  base_commit: string | null
  started_at: string
  finished_at: string | null
  final_status: FinalStatus
  error: string | null
  summary: string | null
  modified_files: string[]
  test_result: TestResult | null
  validation_result: ValidationResult | null
  report_json_path: string | null
  report_md_path: string | null
  notification_path: string | null
}

export interface ExecutionDetail {
  metadata: ExecutionMetadata
  report: ExecutionMetadata | null
  report_md_path: string | null
  log_path: string | null
  log_content: string | null
  review_action: ReviewAction | null
  reviewed_at: string | null
  review_comment: string | null
  rerun_of: string | null
  has_snapshot: boolean
}

// ── Execute (POST /api/code/execute) ─────────────────────────────────────────

export interface ExecutePayload {
  request_id: string
  source: string
  mode: string
  repo_path: string
  changes?: unknown[] | null
  test_spec?: { command: string[]; timeout_sec: number } | null
  validation_spec?: {
    require_tests: boolean
    require_changes: boolean
    allow_needs_review: boolean
  } | null
  metadata?: { trigger_type: string; requested_by: string; [k: string]: unknown }
}

export interface ExecuteResponse {
  ok: boolean
  execution_id: string
  final_status: FinalStatus
  summary: string | null
  report_json_path: string | null
  report_md_path: string | null
  done_path: string | null
  error: string | null
}

// ── Review / Rerun responses ──────────────────────────────────────────────────

export interface ReviewResponse {
  ok: boolean
  review_action: ReviewAction
  reviewed_at: string
  review_comment: string
}

/** Shape returned by POST /api/code/executions/{id}/rerun */
export interface RerunResponse {
  ok: boolean
  execution_id: string
  final_status: FinalStatus
  summary: string | null
  report_json_path: string | null
  report_md_path: string | null
  done_path: string | null
  error: string | null
  rerun_of: string
}

// ── API response envelopes ────────────────────────────────────────────────────

export interface ListExecutionsResponse {
  ok: boolean
  executions: ExecutionListItem[]
  count: number
}

export interface GetExecutionResponse {
  ok: boolean
  // all ExecutionDetail fields come at top level
  metadata: ExecutionDetail['metadata']
  report: ExecutionDetail['report']
  report_md_path: ExecutionDetail['report_md_path']
  log_path: ExecutionDetail['log_path']
  log_content: ExecutionDetail['log_content']
  review_action: ExecutionDetail['review_action']
  reviewed_at: ExecutionDetail['reviewed_at']
  review_comment: ExecutionDetail['review_comment']
  rerun_of: ExecutionDetail['rerun_of']
  has_snapshot: ExecutionDetail['has_snapshot']
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export type ChatRole = 'user' | 'assistant' | 'system'
export type ChatMessageStatus = 'sent' | 'loading' | 'error'

/**
 * Action chip / button that the backend asks the UI to render.
 * type='chip'    → send options[0] as the next message
 * type='confirm' → show a confirm/cancel button pair
 * type='select'  → show a list of options to choose from
 */
export interface ChatUIAction {
  type: string                          // 'chip' | 'confirm' | 'form' | 'select'
  label: string
  options?: string[]                    // for chip: [command]; for select: list
  fields?: string[]                     // for form: field names
  values?: Record<string, string>       // for form: pre-filled values (M27)
}

/**
 * Structured action contract sent to the backend alongside the fallback text.
 * Introduced in M11 — the current backend ignores it; future backend uses it.
 *
 * type='confirm'           → payload: { choice: 'confirm' | 'cancel' }
 * type='select'            → payload: { choice: string }
 * type='form'              → payload: { [field]: value, ... }
 * type='chip'              → payload: { text: string }
 * type='plan_item_execute' → id: item index, payload: PlanItem fields
 */
export interface ChatAction {
  type: string
  target?: string                    // trace_id of the originating message
  id?: string                        // item identifier (plan_item_execute)
  payload?: Record<string, unknown>
}

/** Domain/intent metadata attached to an assistant message for debug/display */
export interface ChatMessageMeta {
  domain?: string
  intent?: string
  mode?: string
  traceId?: string
  needsConfirmation?: boolean
}

/**
 * Generic plan item from backend plan[].
 * Covers FIN items (monto, categoria, ...) and WORK items (title, status, ...)
 * and any future domain without needing per-domain types.
 */
export type PlanItem = Record<string, unknown>

/**
 * Single message in the chat thread.
 * Designed to be a superset — fields added in later sprints are optional.
 */
export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  status: ChatMessageStatus
  createdAt: string         // ISO 8601
  uiActions?: ChatUIAction[]
  plan?: PlanItem[]         // plan[] items from backend, rendered under the message
  meta?: ChatMessageMeta
  /** Hint for special render variants (e.g. 'confirmation_request') */
  kind?: 'normal' | 'confirmation_request'
  /** True once any action on this message has been dispatched — freezes all interactive elements */
  handled?: boolean
  /** MSO governance trace — Phase 0 governance visibility */
  governanceTrace?: GovernanceTrace
}

export interface SendChatRequest {
  /** Natural-language text. Optional when action is provided; required otherwise. */
  text?: string
  session_context?: {
    context_id?: string
    pending_flow?: string | null
    pending_data?: Record<string, unknown>
    last_domain?: string | null
  }
  conversation_id?: string
  /** Structured action contract (M11). Current backend ignores it; forward-compat. */
  action?: ChatAction
  /** M17: backend session id for persistent history. */
  session_id?: string
}

export interface SendChatResponse {
  ok: boolean
  message: string
  trace_id: string
  domain: string
  intent: string
  mode: string
  needs_confirmation: boolean
  missing_fields?: string[]
  session: {
    context_id?: string
    pending_flow?: string | null
    [k: string]: unknown
  }
  ui_actions?: ChatUIAction[]
  plan?: unknown[]
  audit?: Record<string, unknown>
  /** MSO governance trace — Phase 0 governance visibility */
  governance_trace?: GovernanceTrace
}

// ── System ───────────────────────────────────────────────────────────────────

export type HealthStatus = 'ok' | 'warn' | 'degraded' | 'down' | 'unknown'

// ── Operational Mode (MSO Governance) ────────────────────────────────────────

/** System operational mode as reported by the MSO governance layer */
export type OperationalMode = 'NORMAL' | 'DEGRADED' | 'FROZEN' | 'UNKNOWN'

/** Governance decision type from the MSO */
export type GovernanceDecisionType = 'ALLOW' | 'BLOCK' | 'REQUIRE_CONFIRMATION' | 'DEGRADED'

/** Governance trace attached to chat responses */
export interface GovernanceTrace {
  decision: GovernanceDecisionType
  reason?: string
  policy_id?: string
  risk_level?: 'low' | 'medium' | 'high' | 'critical'
}

/** System event for the event log */
export interface SystemEvent {
  id: string
  type: 'execution_started' | 'execution_completed' | 'execution_failed' | 'system_frozen' | 'system_degraded' | 'system_normal' | 'kill_switch_activated'
  message: string
  timestamp: string
  metadata?: Record<string, unknown>
}

export interface SystemMetric {
  label: string
  value: string
  unit?: string
  status: HealthStatus
}

export interface SystemState {
  assistantStatus: HealthStatus
  runnerStatus: HealthStatus
  apiStatus: HealthStatus
  dbStatus: HealthStatus
  uptimeSeconds: number
  activeExecutions: number
  totalExecutions: number
  lastChecked: string
  metrics: SystemMetric[]
}

/** Real system data polled from backends — replaces MOCK_SYSTEM in M7 */
export interface SystemData {
  apiStatus: HealthStatus       // code_api :8000
  webhookStatus: HealthStatus   // webhook :8787
  activeExecutions: number
  needsReview: number
  lastUpdated: string | null    // ISO 8601
  error: string | null
  /** MSO operational mode — Phase 0 governance visibility */
  operationalMode: OperationalMode
  /** Recent system events — Phase 0 event log */
  recentEvents: SystemEvent[]
}

// ── HUD ──────────────────────────────────────────────────────────────────────

export interface HudIndicator {
  id: string
  label: string
  value: string | number
  status: HealthStatus | 'idle'
}

// ── M29: Cognition ────────────────────────────────────────────────────────────

/** Runtime status of a single cognitive provider as reported by the backend. */
export type CognitionProviderStatus = 'online' | 'offline' | 'degraded' | 'disabled'

/** Cognitive usage policy the operator can select. */
export type CognitionPolicy = 'auto' | 'prefer_local' | 'deterministic_only'

export interface CognitionProvider {
  provider_id: string
  label: string
  backend: string
  model: string
  status: CognitionProviderStatus
  latency_ms: number
  available_tasks: string[]
  degraded: boolean
  last_health_check: string | null
  error: string | null
  feature_enabled: boolean
}

export interface CognitionProvidersResponse {
  ok: boolean
  providers: CognitionProvider[]
  ui_cognition_enabled: boolean
  default_policy: CognitionPolicy
}

export interface CognitionPreferences {
  ok: boolean
  policy: CognitionPolicy
  set_by: 'user' | 'default'
}

/** Per-message trace of local LLM participation (M29). */
export interface CognitiveTrace {
  used: boolean
  provider: string | null
  task_type: string | null
  validation: string | null
  confidence: number | null
  fallback_used: boolean
  path?: string
}
