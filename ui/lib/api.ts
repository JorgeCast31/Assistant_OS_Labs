import type {
  ListExecutionsResponse,
  GetExecutionResponse,
  ExecutionDetail,
  ReviewResponse,
  RerunResponse,
  ExecutePayload,
  ExecuteResponse,
  SendChatRequest,
  SendChatResponse,
  HealthStatus,
  ChatAction,
  OperationalMode,
  SystemEvent,
  ExecutionStatus,
  ExecutionStatusSource,
  GovernanceRecentResponse,
  GovernanceStatusResponse,
  AuthorityStatusResponse,
  OutcomeStatusQuery,
  OutcomeStatusResponse,
  MSOEntityStatusResponse,
  MSOSeatStatusResponse,
} from './types'

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'

// Used only for system health checks (no auth required, URL is not sensitive)
export const WEBHOOK_BASE_URL =
  process.env.NEXT_PUBLIC_WEBHOOK_BASE_URL ?? 'http://localhost:8787'

export const RUNTIME_ENDPOINTS = {
  codeApiHealth: `${API_BASE_URL}/health`,
  codeApiExecutions: `${API_BASE_URL}/api/code/executions`,
  webhookHealth: `${WEBHOOK_BASE_URL}/health`,
  webhookMsoState: `${WEBHOOK_BASE_URL}/mso/state`,
  webhookSystemAssistantState: `${WEBHOOK_BASE_URL}/system-assistant/state`,
  webhookSystemCapabilities: `${WEBHOOK_BASE_URL}/system/capabilities`,
  webhookAgentsRegistry: `${WEBHOOK_BASE_URL}/agents/registry`,
  systemStateProxy: '/api/system/runtime-state',
} as const

/**
 * FREEZE_CONTROL: Governance kill-switch configuration.
 *
 * Proxy routes:
 *   POST /api/system/freeze   → POST /admin/governance/mode  (mode=FROZEN)
 *   POST /api/system/restore  → POST /admin/governance/mode  (mode=NORMAL)
 *
 * Both proxies share the same backend authority — there is no parallel
 * authority introduced by adding restore. They require ASSISTANT_ADMIN_TOKEN
 * server-side; the UI buttons render "Unavailable" when that env var is
 * absent (fail-closed at the proxy layer).
 */
export const FREEZE_CONTROL = {
  available: true,
  endpoint: '/api/system/freeze',
  restoreEndpoint: '/api/system/restore',
  message: 'Freeze control is not available. Set ASSISTANT_ADMIN_TOKEN to enable.',
} as const

// ── Helpers ───────────────────────────────────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    ...init,
  })
  if (!res.ok) {
    throw new Error(`API ${path} → ${res.status} ${res.statusText}`)
  }
  const json = await res.json()
  if (!json.ok) {
    throw new Error(`API ${path} → ok=false: ${json.error ?? 'unknown error'}`)
  }
  return json as T
}

const EXECUTION_STATUSES: ExecutionStatus[] = ['real', 'stub', 'unavailable', 'partial']

function executionStatusOf(value: unknown): ExecutionStatus | undefined {
  return typeof value === 'string' && EXECUTION_STATUSES.includes(value as ExecutionStatus)
    ? value as ExecutionStatus
    : undefined
}

export class ChatApiError extends Error {
  executionStatus: ExecutionStatus
  executionStatusSource: ExecutionStatusSource

  constructor(
    message: string,
    executionStatus: ExecutionStatus,
    executionStatusSource: ExecutionStatusSource = 'ui_fallback',
  ) {
    super(message)
    this.name = 'ChatApiError'
    this.executionStatus = executionStatus
    this.executionStatusSource = executionStatusSource
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

export async function getExecutions() {
  const data = await apiFetch<ListExecutionsResponse>('/api/code/executions')
  return data.executions
}

export async function getExecutionDetail(id: string): Promise<ExecutionDetail> {
  const data = await apiFetch<GetExecutionResponse>(
    `/api/code/executions/${id}`
  )
  return {
    metadata:       data.metadata,
    report:         data.report,
    report_md_path: data.report_md_path,
    log_path:       data.log_path,
    log_content:    data.log_content,
    review_action:  data.review_action,
    reviewed_at:    data.reviewed_at,
    review_comment: data.review_comment,
    rerun_of:       data.rerun_of,
    has_snapshot:   data.has_snapshot,
  }
}

export async function reviewExecution(
  id: string,
  action: string,
  comment: string,
): Promise<ReviewResponse> {
  return apiFetch<ReviewResponse>(`/api/code/executions/${id}/review`, {
    method: 'POST',
    body: JSON.stringify({ action, comment: comment.trim().slice(0, 500) }),
  })
}

export async function rerunExecution(id: string): Promise<RerunResponse> {
  return apiFetch<RerunResponse>(`/api/code/executions/${id}/rerun`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export async function executeCode(payload: ExecutePayload): Promise<ExecuteResponse> {
  return apiFetch<ExecuteResponse>('/api/code/execute', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

// ── System health ─────────────────────────────────────────────────────────────

/** GET /health on the code_api server (port 8000). Returns 'ok' or 'down'. */
export async function getSystemHealth(): Promise<HealthStatus> {
  try {
    const res = await fetch(RUNTIME_ENDPOINTS.codeApiHealth, {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return 'down'
    const json = await res.json()
    return json.status === 'ok' ? 'ok' : 'warn'
  } catch {
    return 'down'
  }
}

/** GET /health on the webhook server (port 8787). Returns 'ok' or 'down'. */
export async function checkWebhookHealth(): Promise<HealthStatus> {
  try {
    const res = await fetch(RUNTIME_ENDPOINTS.webhookHealth, {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return 'down'
    const json = await res.json()
    return json.status === 'ok' ? 'ok' : 'warn'
  } catch {
    return 'down'
  }
}

// ── System State (MSO Governance) ─────────────────────────────────────────────

interface SystemStateResponse {
  ok: boolean
  operational_mode: OperationalMode
  events?: SystemEvent[]
}

export interface SystemAssistantSnapshot {
  generated_at?: string
  status?: string
  operational_mode?: string | null
  warnings?: string[]
}

export interface SystemAssistantInterpretation {
  status: 'healthy' | 'partial' | 'unavailable' | 'unknown'
  summary: string
  observations: string[]
  warnings: string[]
  narrative: true
  source: 'system_assistant'
  execution_status: null
}

export interface SystemAssistantStateResponse {
  ok: boolean
  snapshot: SystemAssistantSnapshot
  interpretation: SystemAssistantInterpretation
}

/**
 * GET /api/system/runtime-state — internal Next.js proxy to the webhook
 * operability surface. Fallback to UNKNOWN if the proxy or backend is
 * unavailable.
 */
export async function getSystemState(): Promise<{ mode: OperationalMode; events: SystemEvent[] }> {
  try {
    const res = await fetch(RUNTIME_ENDPOINTS.systemStateProxy, {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) {
      return { mode: 'UNKNOWN', events: [] }
    }
    const json = await res.json() as SystemStateResponse
    return {
      mode: json.operational_mode ?? 'UNKNOWN',
      events: json.events ?? [],
    }
  } catch {
    return { mode: 'UNKNOWN', events: [] }
  }
}

// ── System Capabilities ───────────────────────────────────────────────────────
// Response shape matches assistant_os/operability.py:build_system_capabilities_response()

export interface SystemCapabilitiesFeatures {
  authority_artifact: boolean
  replay_prevention: boolean
  runner_enforced: boolean
  /** 'stub' | 'real' | 'unknown' — typed defensively as string for forward compat */
  code_apply_mode: string
  /** 'available' | 'unavailable' | 'unknown' */
  machine_operator: string
}

export type CapabilityStatus = 'revoked' | 'granted' | 'available' | 'blocked' | 'unavailable'

export interface SystemCapability {
  id: string
  domain: string | null
  mode: string | null
  status: CapabilityStatus
  requires_confirmation: boolean
}

export interface SystemCapabilitiesResponse {
  ok: boolean
  /** null when the proxy or backend is unavailable */
  features: SystemCapabilitiesFeatures | null
  domains: string[]
  capabilities: SystemCapability[]
  error?: string
}

/** GET /api/system/capabilities — Next.js proxy to :8787/system/capabilities. */
export async function getSystemCapabilities(): Promise<SystemCapabilitiesResponse> {
  const UNAVAILABLE: SystemCapabilitiesResponse = {
    ok: false,
    features: null,
    domains: [],
    capabilities: [],
  }
  try {
    const res = await fetch('/api/system/capabilities', {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return UNAVAILABLE
    const json = await res.json() as SystemCapabilitiesResponse
    return json.ok ? json : UNAVAILABLE
  } catch {
    return UNAVAILABLE
  }
}

/**
 * GET /system-assistant/state on the webhook backend.
 * The backend response is the source of truth; this helper only fetches it.
 */
export async function getSystemAssistantState(): Promise<SystemAssistantStateResponse> {
  const res = await fetch('/api/system-assistant/state', {
    cache: 'no-store',
    signal: AbortSignal.timeout(4000),
  })

  if (!res.ok) {
    throw new Error(`System Assistant state unavailable (${res.status})`)
  }

  const json = await res.json() as SystemAssistantStateResponse
  if (!json.ok) {
    throw new Error('System Assistant state unavailable')
  }

  return json
}

/**
 * Format a backend/proxy block payload as the canonical operator-facing block.
 *
 *   Blocked:
 *     domain=...
 *     action=...
 *     reason=...
 *     suggestion=...
 *
 * Falls back to the raw error/message when no structured fields are present, so
 * the UI never silently drops a backend error.
 *
 * Exported in 02 so every surface (chat-view error path, MSO Direct error
 * path, System Chat informational guard, freeze/restore controls) renders
 * blocks identically — no per-surface drift.
 */
export function formatBlockedMessage(payload: Record<string, unknown>, fallback: string): string {
  const domain     = typeof payload.domain     === 'string' ? payload.domain     : null
  const action     = typeof payload.action     === 'string' ? payload.action     : null
  const reason     = typeof payload.reason     === 'string' ? payload.reason     : null
  const suggestion = typeof payload.suggestion === 'string' ? payload.suggestion : null
  const errorText  = typeof payload.error      === 'string' ? payload.error
                  : typeof payload.message    === 'string' ? payload.message
                  : null

  const hasStructured = Boolean(domain || action || reason || suggestion)
  if (!hasStructured) {
    return errorText ?? fallback
  }

  const lines = ['Blocked:']
  if (domain)     lines.push(`  domain=${domain}`)
  if (action)     lines.push(`  action=${action}`)
  if (reason)     lines.push(`  reason=${reason}`)
  if (suggestion) lines.push(`  suggestion=${suggestion}`)
  if (errorText)  lines.push('', errorText)
  return lines.join('\n')
}

/**
 * Redirect target catalog. Surface names follow the sovereign-store viewIds.
 * Mapped to operator-facing labels here so every surface speaks the same
 * vocabulary when offering an alternative path.
 */
export type RedirectTarget = 'mso' | 'machine_operator'

export interface RedirectOption {
  target: RedirectTarget
  label:  string
  hint:   string
}

/**
 * Decide which redirect targets to offer for a blocked / informational
 * response. The decision is intentionally simple and rule-based — no
 * classifier, no model — so a "what should I do next?" question always
 * has a deterministic, auditable answer.
 *
 *   - If the source surface is informational (System Chat, Chat principal),
 *     offer both Plan (MSO) and Execute (Machine Operator). The operator
 *     picks intent.
 *   - If the source surface is MSO and we are blocking, offer Machine
 *     Operator only — MSO already owns planning.
 *   - If the source surface is Machine Operator, offer MSO only — MO
 *     does not plan.
 *
 * The catalog is always non-empty: every block carries at least one
 * actionable next step. This is the §3 / §4 invariant from the brief
 * ("Nunca silencio ni bloqueo plano").
 */
export function redirectsForSurface(
  surface: 'chat' | 'system_chat' | 'mso' | 'machine_operator',
): RedirectOption[] {
  switch (surface) {
    case 'mso':
      return [
        { target: 'machine_operator', label: 'Ejecutar con Machine Operator', hint: 'Operational lane (real execution)' },
      ]
    case 'machine_operator':
      return [
        { target: 'mso',              label: 'Planificar con MSO',           hint: 'Sovereign planning + confirmation' },
      ]
    case 'chat':
    case 'system_chat':
    default:
      return [
        { target: 'mso',              label: 'Planificar con MSO',           hint: 'Sovereign planning + confirmation' },
        { target: 'machine_operator', label: 'Ejecutar con Machine Operator', hint: 'Operational lane (real execution)' },
      ]
  }
}

/**
 * POST /api/system/restore — calls the authenticated Next.js proxy which forwards
 * to POST /admin/governance/mode on the webhook server with mode=NORMAL.
 *
 * Symmetric to freezeSystem(). Fails-closed identically: if
 * ASSISTANT_ADMIN_TOKEN is absent on the server the proxy returns 503 and the
 * canonical Blocked: block is rendered. There is NO new authority — the
 * single endpoint /admin/governance/mode handles both freeze (mode=FROZEN)
 * and restore (mode=NORMAL).
 */
export async function restoreSystem(): Promise<{ ok: boolean; message: string }> {
  if (!FREEZE_CONTROL.available) {
    return {
      ok: false,
      message: FREEZE_CONTROL.message,
    }
  }

  try {
    const res = await fetch(FREEZE_CONTROL.restoreEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      signal: AbortSignal.timeout(15000),
    })

    const json = (await res.json().catch(
      () => ({ ok: false, error: `HTTP ${res.status}` }),
    )) as Record<string, unknown>

    if (!res.ok || json.ok === false) {
      return {
        ok: false,
        message: formatBlockedMessage(json, `Restore failed (${res.status})`),
      }
    }

    return {
      ok: true,
      message: typeof json.message === 'string' ? json.message : 'System restored to NORMAL',
    }
  } catch (err) {
    return {
      ok: false,
      message: err instanceof Error ? err.message : 'Restore request failed',
    }
  }
}

/**
 * POST /api/system/freeze — calls the authenticated Next.js proxy which forwards
 * to POST /admin/governance/mode on the webhook server with mode=FROZEN.
 * Fails-closed if FREEZE_CONTROL.available is false (or if ASSISTANT_ADMIN_TOKEN
 * is absent on the server — the proxy returns 503 in that case).
 */
export async function freezeSystem(): Promise<{ ok: boolean; message: string }> {
  // Fail-closed: refuse to attempt if not marked available
  if (!FREEZE_CONTROL.available) {
    return {
      ok: false,
      message: FREEZE_CONTROL.message,
    }
  }

  try {
    const res = await fetch(FREEZE_CONTROL.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      signal: AbortSignal.timeout(15000),
    })

    const json = (await res.json().catch(
      () => ({ ok: false, error: `HTTP ${res.status}` }),
    )) as Record<string, unknown>

    if (!res.ok || json.ok === false) {
      return {
        ok: false,
        message: formatBlockedMessage(json, `Freeze failed (${res.status})`),
      }
    }

    return {
      ok: true,
      message: typeof json.message === 'string' ? json.message : 'System freeze initiated',
    }
  } catch (err) {
    return {
      ok: false,
      message: err instanceof Error ? err.message : 'Freeze request failed',
    }
  }
}

// ── Chat (POST /api/chat/process → Next.js route handler → webhook) ──────────
//
// The browser calls the internal Next.js route, which injects the token
// server-side. ASSISTANT_TOKEN never appears in the client bundle.

export async function sendChatMessage(
  req: SendChatRequest,
): Promise<SendChatResponse> {
  // Always include a text field for backward-compat with the current backend.
  // When only a structured action is provided we synthesise a fallback string.
  const body: Record<string, unknown> = {
    text: req.text ?? (req.action ? `[action:${(req.action as ChatAction).type}]` : ''),
  }
  if (req.session_context) body.session_context = req.session_context
  if (req.conversation_id) body.conversation_id = req.conversation_id
  if (req.action)          body.action           = req.action
  if (req.session_id)      body.session_id       = req.session_id
  if (req.surface)         body.surface          = req.surface

  const res = await fetch('/api/chat/process', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache:  'no-store',
    body:   JSON.stringify(body),
    signal: AbortSignal.timeout(30000),
  })
  if (!res.ok) {
    const json = await res.json().catch(() => ({}))
    const backendStatus = executionStatusOf((json as Record<string, unknown>).execution_status)
    throw new ChatApiError(
      (json as Record<string, unknown>).error as string
        ?? `Chat API → ${res.status} ${res.statusText}`,
      backendStatus ?? 'unavailable',
      backendStatus ? 'backend' : 'ui_fallback',
    )
  }
  const json = await res.json()
  if (!json.ok) {
    const backendStatus = executionStatusOf(json.execution_status)
    throw new ChatApiError(
      `Chat API → ok=false: ${json.error ?? 'unknown error'}`,
      backendStatus ?? 'unavailable',
      backendStatus ? 'backend' : 'ui_fallback',
    )
  }
  const backendStatus = executionStatusOf(json.execution_status)
  if (backendStatus) {
    json.execution_status = backendStatus
    json.execution_status_source = 'backend'
  } else {
    delete json.execution_status
    delete json.execution_status_source
  }
  return json as SendChatResponse
}

// ── Chat Sessions (M17) ───────────────────────────────────────────────────────
//
// All session calls go through Next.js route handlers that inject the token.

/** Backend session shape (snake_case, as returned by the webhook server). */
export interface BackendSession {
  id:         string
  title:      string
  context_id: string | null
  created_at: string
  updated_at: string
  messages?:  Array<Record<string, unknown>>
}

async function sessionFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    ...init,
  })
  const json = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }))
  if (!res.ok || !json.ok) {
    throw new Error(json?.error ?? `Session API error ${res.status}`)
  }
  return json as T
}

export async function apiListSessions(): Promise<BackendSession[]> {
  const data = await sessionFetch<{ ok: boolean; sessions: BackendSession[] }>(
    '/api/chat/sessions',
  )
  return data.sessions
}

export async function apiCreateSession(opts?: {
  id?: string
  title?: string
}): Promise<BackendSession> {
  const data = await sessionFetch<{ ok: boolean; session: BackendSession }>(
    '/api/chat/sessions',
    { method: 'POST', body: JSON.stringify(opts ?? {}) },
  )
  return data.session
}

export async function apiGetSession(id: string): Promise<BackendSession> {
  const data = await sessionFetch<{ ok: boolean; session: BackendSession }>(
    `/api/chat/sessions/${id}`,
  )
  return data.session
}

export async function apiUpdateSession(
  id: string,
  patch: { title?: string; context_id?: string | null; messages?: unknown[] },
): Promise<BackendSession> {
  const data = await sessionFetch<{ ok: boolean; session: BackendSession }>(
    `/api/chat/sessions/${id}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  )
  return data.session
}

export async function apiDeleteSession(id: string): Promise<void> {
  await sessionFetch(`/api/chat/sessions/${id}`, { method: 'DELETE' })
}

// ── Message search (M21) ──────────────────────────────────────────────────────

export interface MessageSearchResult {
  messageId:    string
  sessionId:    string
  sessionTitle: string
  text:         string
  createdAt:    string
}

/**
 * GET /api/chat/search?q=...
 * Returns up to 50 results ordered by createdAt DESC.
 * Returns [] on any error (non-throwing).
 */
export async function apiSearchMessages(q: string): Promise<MessageSearchResult[]> {
  try {
    const res  = await fetch(`/api/chat/search?q=${encodeURIComponent(q)}`, { cache: 'no-store' })
    const json = await res.json()
    if (!res.ok || !json.ok) return []
    return (json.results ?? []) as MessageSearchResult[]
  } catch {
    return []
  }
}

// ── MSO Governance Recent (S-MSO-FE-01A) ─────────────────────────────────────

const GOVERNANCE_UNAVAILABLE: GovernanceRecentResponse = {
  ok: false,
  source: 'mso_governance',
  decisions: [],
  count: 0,
  limit: 20,
  ephemeral: true,
}

/**
 * GET /api/mso/governance/recent — recent in-memory governance decisions.
 * Calls the local Next.js proxy which injects the auth token server-side.
 * Returns an empty envelope on any error — never throws.
 */
export async function getRecentGovernanceDecisions(
  limit?: number,
): Promise<GovernanceRecentResponse> {
  try {
    const path = limit !== undefined
      ? `/api/mso/governance/recent?limit=${limit}`
      : '/api/mso/governance/recent'
    const res = await fetch(path, {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return GOVERNANCE_UNAVAILABLE
    const json = await res.json() as GovernanceRecentResponse
    return json.ok ? json : GOVERNANCE_UNAVAILABLE
  } catch {
    return GOVERNANCE_UNAVAILABLE
  }
}

// ── MSO Governance Status (S-MSO-GS-01) ──────────────────────────────────────

const GOVERNANCE_STATUS_UNAVAILABLE: GovernanceStatusResponse = {
  ok: false,
  source: 'mso_governance',
  operational_mode: 'UNKNOWN',
  operational_mode_reason: '',
  operational_mode_source: 'derived',
  hardened_domains: [],
  hardened_domain_count: 0,
  active_revocation_count: 0,
  active_grant_count: 0,
  recent_anomaly_count: 0,
  ephemeral: true,
}

/**
 * GET /api/mso/governance/status — current operational mode and governance state counts.
 * Calls the local Next.js proxy which injects the auth token server-side.
 * Returns an unavailable envelope on any error — never throws.
 */
export async function getGovernanceStatus(): Promise<GovernanceStatusResponse> {
  try {
    const res = await fetch('/api/mso/governance/status', {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return GOVERNANCE_STATUS_UNAVAILABLE
    const json = await res.json() as GovernanceStatusResponse
    return json.ok ? json : GOVERNANCE_STATUS_UNAVAILABLE
  } catch {
    return GOVERNANCE_STATUS_UNAVAILABLE
  }
}

// ── CODE readiness (S-CODE-READINESS-01D) ────────────────────────────────────
// Read-only passive surface. Browser → Next.js proxy → webhook backend.
// Never carries authority. Never triggers execution.

import type { CodeReadinessResponse } from './types'
import type { ConfirmPendingResponse } from './types'
import type { PreparedActionsQueueResponse } from './types'
import type { MSOSeatProviderResponse } from './types'

const CODE_READINESS_UNAVAILABLE: CodeReadinessResponse = {
  ok: false,
  source: 'code_readiness',
  domain: 'CODE',
  feature_enabled: false,
  last_health_check: '',
  note:
    'Readiness is source availability and configuration only — it is not authority. ' +
    'Capabilities are governed by MSO.',
  code_api_reachable: false,
  code_api_url: '',
  code_api_latency_ms: 0,
  code_api_error: 'CODE readiness backend unavailable',
  apply_execution_mode: 'stub',
  apply_real_enabled: false,
  runner_backend_probed: false,
  runner_backend_available: null,
  runner_backend_latency_ms: null,
  runner_backend_error: null,
  runner_timeout_seconds: 0,
  runner_memory_limit: '',
  runner_cpu_limit: '',
  runner_base_image: '',
  code_capabilities: [],
  code_capability_allowed_count: 0,
  code_capability_confirm_only_count: 0,
  code_capability_blocked_count: 0,
  error: 'CODE readiness backend unavailable',
}

/**
 * GET /api/code/readiness — passive CODE readiness summary.
 * Calls the LOCAL Next.js proxy (`/api/code/readiness`) which injects auth
 * server-side. The browser MUST NEVER call the webhook backend directly.
 * Returns an unavailable envelope on any error — never throws.
 */
export async function getCodeReadiness(): Promise<CodeReadinessResponse> {
  try {
    const res = await fetch('/api/code/readiness', {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return CODE_READINESS_UNAVAILABLE
    const json = await res.json() as CodeReadinessResponse
    return json.ok ? json : { ...CODE_READINESS_UNAVAILABLE, error: json.error ?? 'unavailable' }
  } catch {
    return CODE_READINESS_UNAVAILABLE
  }
}

const CONFIRM_PENDING_UNAVAILABLE: ConfirmPendingResponse = {
  ok: false,
  source: 'confirm_flow',
  pending_count: 0,
  expired_pending_count: 0,
  pending: [],
  note: 'Confirm queue is observability only; confirmation remains governed.',
  error: 'Confirm pending backend unavailable',
}

/**
 * GET /api/confirm/pending — passive confirm queue summary.
 * Calls the LOCAL Next.js proxy only and never exposes webhook auth in browser.
 * Returns an unavailable envelope on any error — never throws.
 */
export async function getConfirmPending(limit = 10): Promise<ConfirmPendingResponse> {
  const safeLimit = Number.isFinite(limit)
    ? Math.max(1, Math.min(50, Math.trunc(limit)))
    : 10

  try {
    const res = await fetch(`/api/confirm/pending?limit=${safeLimit}`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return CONFIRM_PENDING_UNAVAILABLE
    const json = await res.json() as ConfirmPendingResponse
    return json.ok ? json : { ...CONFIRM_PENDING_UNAVAILABLE, error: json.error ?? 'unavailable' }
  } catch {
    return CONFIRM_PENDING_UNAVAILABLE
  }
}

const AUTHORITY_STATUS_UNAVAILABLE: AuthorityStatusResponse = {
  ok: false,
  source: 'authority_status',
  note: 'Authority status is posture, not execution permission.',
  capabilities: [],
  counts: {
    total: 0,
    allow: 0,
    confirm_only: 0,
    deny: 0,
    blocked: 0,
    active_grants: 0,
    active_revocations: 0,
  },
  error: 'Authority status backend unavailable',
}

/**
 * GET /api/mso/authority/status — passive authority matrix summary.
 * Calls the local Next.js proxy only and never exposes webhook auth in browser.
 * Returns an unavailable envelope on any error — never throws.
 */
export async function getAuthorityStatus(): Promise<AuthorityStatusResponse> {
  try {
    const res = await fetch('/api/mso/authority/status', {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return AUTHORITY_STATUS_UNAVAILABLE
    const json = await res.json() as AuthorityStatusResponse
    return json.ok ? json : { ...AUTHORITY_STATUS_UNAVAILABLE, error: json.error ?? 'unavailable' }
  } catch {
    return AUTHORITY_STATUS_UNAVAILABLE
  }
}

const OUTCOME_STATUS_UNAVAILABLE: OutcomeStatusResponse = {
  ok: false,
  source: 'outcome_status',
  note: 'Outcome status is observational; it does not grant execution permission.',
  found: false,
  query: {},
  outcome: {
    status: 'unknown',
    result_type: null,
    execution_status: 'unknown',
    domain: null,
    action: null,
    message: 'Outcome status unavailable',
    error_type: 'backend_unavailable',
    error_message: 'Outcome status backend unavailable',
  },
  correlation: {},
  sources: {},
  source_errors: [],
  error: 'Outcome status backend unavailable',
}

/**
 * GET /api/mso/outcome/status — passive execution outcome observability.
 * Calls the local Next.js proxy only and never exposes webhook auth in browser.
 * Returns an unavailable envelope on any error — never throws.
 */
export async function getOutcomeStatus(query?: OutcomeStatusQuery): Promise<OutcomeStatusResponse> {
  const params = new URLSearchParams()
  if (query?.plan_id) params.set('plan_id', query.plan_id)
  if (query?.context_id) params.set('context_id', query.context_id)
  if (query?.trace_id) params.set('trace_id', query.trace_id)
  if (query?.execution_id) params.set('execution_id', query.execution_id)

  const querySuffix = params.toString()
  const path = querySuffix
    ? `/api/mso/outcome/status?${querySuffix}`
    : '/api/mso/outcome/status'

  try {
    const res = await fetch(path, {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return OUTCOME_STATUS_UNAVAILABLE
    const json = await res.json() as OutcomeStatusResponse
    return json.ok ? json : { ...OUTCOME_STATUS_UNAVAILABLE, error: json.error ?? 'unavailable' }
  } catch {
    return OUTCOME_STATUS_UNAVAILABLE
  }
}

// ── Prepared action review queue (S-PREPARED-ACTIONS-01) ─────────────────
// Read-only passive surface. Browser → Next.js proxy → webhook backend.
// Never carries execution authority. Never approves or executes.

const PREPARED_ACTIONS_UNAVAILABLE: PreparedActionsQueueResponse = {
  ok: false,
  source: 'prepared_action_queue',
  count: 0,
  items: [],
  review_only: true,
  execution_allowed: false,
  can_execute_now: false,
  note: 'Prepared action review queue is read-only. Human confirmation and the full authority chain are still pending.',
  error: 'Prepared actions backend unavailable',
}

/**
 * GET /api/mso/prepared-actions/pending — read-only prepared action queue.
 * Returns all ConfirmablePreparedActionQueueEntry items waiting for manual review.
 * Review-only: execution_allowed=false, can_execute_now=false at all times.
 * Never throws.
 */
export async function getPreparedActionsPending(): Promise<PreparedActionsQueueResponse> {
  try {
    const res = await fetch('/api/mso/prepared-actions/pending', {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return PREPARED_ACTIONS_UNAVAILABLE
    const json = await res.json() as PreparedActionsQueueResponse
    return json.ok ? json : { ...PREPARED_ACTIONS_UNAVAILABLE, error: json.error ?? 'unavailable' }
  } catch {
    return PREPARED_ACTIONS_UNAVAILABLE
  }
}

// ---------------------------------------------------------------------------
// MSO Seat Provider — S-MSO-SEAT-PROVIDER-01
// ---------------------------------------------------------------------------

const MSO_SEAT_PROVIDER_UNAVAILABLE: MSOSeatProviderResponse = {
  ok: false,
  seat_provider: null,
  description: 'MSO Seat provider metadata unavailable.',
  execution_allowed: false,
  can_execute_now: false,
  note: 'MSO Seat provider metadata is read-only. Provider availability is config-derived — no network calls are made. This surface does not execute, approve, or issue tokens.',
}

export async function getMSOSeatProvider(): Promise<MSOSeatProviderResponse> {
  try {
    const res = await fetch('/api/mso/seat/provider', {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return MSO_SEAT_PROVIDER_UNAVAILABLE
    const json = await res.json() as MSOSeatProviderResponse
    return json.ok !== undefined ? json : MSO_SEAT_PROVIDER_UNAVAILABLE
  } catch {
    return MSO_SEAT_PROVIDER_UNAVAILABLE
  }
}

// ---------------------------------------------------------------------------
// MSO Entity Status — S-MISSION-CONTROL-ORCHESTRATION-SPACES-ALPHA-01
// Read-only boundary description. Never executes.
// ---------------------------------------------------------------------------

const MSO_ENTITY_STATUS_UNAVAILABLE: MSOEntityStatusResponse = {
  ok: false,
  source: 'mso_entity_status',
  entity: 'MSO',
  execution_allowed: false,
  used_execution: false,
  error: 'MSO entity status unavailable',
}

export async function getMSOEntityStatus(): Promise<MSOEntityStatusResponse> {
  try {
    const res = await fetch('/api/mso/entity/status', {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return MSO_ENTITY_STATUS_UNAVAILABLE
    const json = await res.json() as MSOEntityStatusResponse
    return json.ok !== undefined ? json : MSO_ENTITY_STATUS_UNAVAILABLE
  } catch {
    return MSO_ENTITY_STATUS_UNAVAILABLE
  }
}

// ---------------------------------------------------------------------------
// MSO Seat Status — S-MISSION-CONTROL-ORCHESTRATION-SPACES-ALPHA-01
// Read-only cognitive seat snapshot. Never executes.
// ---------------------------------------------------------------------------

const MSO_SEAT_STATUS_UNAVAILABLE: MSOSeatStatusResponse = {
  ok: false,
  source: 'mso_seat_status',
  used_execution: false,
  cognitive_only: true,
  error: 'MSO seat status unavailable',
}

export async function getMSOSeatStatus(): Promise<MSOSeatStatusResponse> {
  try {
    const res = await fetch('/api/mso/seat/status', {
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return MSO_SEAT_STATUS_UNAVAILABLE
    const json = await res.json() as MSOSeatStatusResponse
    return json.ok !== undefined ? json : MSO_SEAT_STATUS_UNAVAILABLE
  } catch {
    return MSO_SEAT_STATUS_UNAVAILABLE
  }
}
