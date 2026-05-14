// ── Sovereign API Layer ───────────────────────────────────────────────────────
// Handles communication with the backend for System Chat and MSO surfaces

import type {
  SovereignChatRequest,
  SovereignChatResponse,
  SurfaceType,
  ExecutionStatus,
  ExecutionStatusSource,
} from './types'

const EXECUTION_STATUSES: ExecutionStatus[] = ['real', 'stub', 'unavailable', 'partial']

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
      execution_status: backendStatus ?? (ok ? undefined : 'unavailable'),
      execution_status_source: statusSource(backendStatus) ?? (ok ? undefined : 'ui_fallback'),
      plan: data.plan,
      governance_trace: data.governance_trace,
      // Extended MSO response fields
      execution_mode: data.execution_mode,
      policy_decision: data.policy_decision,
      authority_artifact: data.authority_artifact,
      pending_confirmation: data.pending_confirmation,
      confirmation: data.confirmation,
      // ALFA-FLIGHT-02 §5 — optional traceability passthrough. Absent in
      // backend response → absent here. Never inferred.
      decision_source: typeof data.decision_source === 'string' &&
                       (data.decision_source === 'llm' || data.decision_source === 'rule' || data.decision_source === 'hybrid')
        ? data.decision_source : undefined,
      confidence_score: typeof data.confidence_score === 'number' && Number.isFinite(data.confidence_score)
        ? data.confidence_score : undefined,
      // ALPHA PHASE 1 — provenance metadata
      response_source: data.response_source,
      provider_used: data.provider_used,
      model_used: data.model_used,
      cognitive_generation: data.cognitive_generation,
      fallback_used: data.fallback_used,
      fallback_reason: data.fallback_reason,
      narrative_context: data.narrative_context,
      cognitive_trace: data.cognitive_trace,
      execution_allowed: data.execution_allowed,
      can_execute_now: data.can_execute_now,
      latency_ms: data.latency_ms,
      tokens_in: data.tokens_in,
      tokens_out: data.tokens_out,
      audit: data.audit,
      raw_response: data,
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
