// ── Sovereign API Layer ───────────────────────────────────────────────────────
// Handles communication with the backend for System Chat and MSO surfaces

import type {
  SovereignChatRequest,
  SovereignChatResponse,
  SurfaceType,
} from './types'

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
      return {
        ok: false,
        message: data.error || `Error ${res.status}`,
        trace_id: '',
        needs_confirmation: false,
        error: data.error || 'Request failed',
      }
    }

    return {
      ok: true,
      message: data.message || '',
      trace_id: data.trace_id || '',
      domain: data.domain,
      intent: data.intent,
      mode: data.mode,
      needs_confirmation: data.needs_confirmation || false,
      plan: data.plan,
      governance_trace: data.governance_trace,
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Network error'
    return {
      ok: false,
      message: msg,
      trace_id: '',
      needs_confirmation: false,
      error: msg,
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
