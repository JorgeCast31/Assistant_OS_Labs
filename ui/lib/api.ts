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
  webhookSystemCapabilities: `${WEBHOOK_BASE_URL}/system/capabilities`,
  webhookAgentsRegistry: `${WEBHOOK_BASE_URL}/agents/registry`,
  systemStateProxy: '/api/system/runtime-state',
} as const

export const FREEZE_CONTROL = {
  available: true,
  endpoint: '/api/system/freeze',
  message: 'Freeze control is available through the authenticated proxy.',
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

/**
 * POST /api/system/freeze — calls the authenticated proxy which forwards
 * to the webhook governance endpoint. Returns actual success/error from backend.
 */
export async function freezeSystem(): Promise<{ ok: boolean; message: string }> {
  try {
    const res = await fetch(FREEZE_CONTROL.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      signal: AbortSignal.timeout(15000),
    })

    const json = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }))

    if (!res.ok || !json.ok) {
      return {
        ok: false,
        message: json.error ?? json.message ?? `Freeze failed (${res.status})`,
      }
    }

    return {
      ok: true,
      message: json.message ?? 'System freeze initiated',
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

  const res = await fetch('/api/chat/process', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache:  'no-store',
    body:   JSON.stringify(body),
    signal: AbortSignal.timeout(30000),
  })
  if (!res.ok) {
    const json = await res.json().catch(() => ({}))
    throw new Error(
      (json as Record<string, unknown>).error as string
        ?? `Chat API → ${res.status} ${res.statusText}`
    )
  }
  const json = await res.json()
  if (!json.ok) {
    throw new Error(`Chat API → ok=false: ${json.error ?? 'unknown error'}`)
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
