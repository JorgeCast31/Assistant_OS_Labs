// ── Sovereign API Layer ───────────────────────────────────────────────────────
// Handles communication with the backend for System Chat and MSO surfaces

import type {
  SovereignChatRequest,
  SovereignChatResponse,
  SurfaceType,
  ExecutionStatus,
  ExecutionStatusSource,
} from './types'

const EXECUTION_STATUSES: ExecutionStatus[] = ['success', 'stub', 'unavailable', 'partial', 'error']

function executionStatusOf(value: unknown): ExecutionStatus | undefined {
  return typeof value === 'string' && EXECUTION_STATUSES.includes(value as ExecutionStatus)
    ? value as ExecutionStatus
    : undefined
}

function statusSource(status: ExecutionStatus | undefined): ExecutionStatusSource | undefined {
  return status ? 'backend' : undefined
}

/**
 * Send a message through the sovereign interface.
 * Routes to the same backend endpoint but with surface context.
 */
export async function sendSovereignMessage(
  text: string,
  surface: SurfaceType,
  sessionId?: string
): Promise<SovereignChatResponse> {
  const payload: SovereignChatRequest = {
    text,
    surface,
    ...(sessionId && { session_id: sessionId }),
  }

  try {
    const res = await fetch('/api/chat/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    const data = await res.json()

    if (!res.ok) {
      const backendStatus = executionStatusOf(data.execution_status)
      return {
        ok: false,
        message: data.error || `Error ${res.status}`,
        trace_id: '',
        needs_confirmation: false,
        error: data.error || 'Request failed',
        execution_status: backendStatus ?? 'unavailable',
        execution_status_source: backendStatus ? 'backend' : 'ui_fallback',
      }
    }

    const ok = data.ok !== false
    const backendStatus = executionStatusOf(data.execution_status)

    return {
      ok,
      message: data.message || '',
      trace_id: data.trace_id || '',
      domain: data.domain,
      intent: data.intent,
      mode: data.mode,
      needs_confirmation: data.needs_confirmation || data.pending_confirmation != null || false,
      execution_status: backendStatus ?? (ok ? undefined : 'error'),
      execution_status_source: statusSource(backendStatus) ?? (ok ? undefined : 'ui_fallback'),
      plan: data.plan,
      governance_trace: data.governance_trace,
      // Extended MSO response fields
      execution_mode: data.execution_mode,
      policy_decision: data.policy_decision,
      authority_artifact: data.authority_artifact,
      pending_confirmation: data.pending_confirmation,
      confirmation: data.confirmation,
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Network error'
    return {
      ok: false,
      message: msg,
      trace_id: '',
      needs_confirmation: false,
      error: msg,
      execution_status: 'unavailable',
      execution_status_source: 'ui_fallback',
    }
  }
}

/**
 * Send a confirmation response to MSO
 */
export async function sendMSOConfirmation(
  traceId: string,
  confirmed: boolean,
  sessionId?: string
): Promise<SovereignChatResponse> {
  const text = confirmed ? 'confirmar' : 'cancelar'
  return sendSovereignMessage(text, 'mso_direct', sessionId)
}
