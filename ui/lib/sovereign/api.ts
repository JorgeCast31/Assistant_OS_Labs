// ── Sovereign API Layer ───────────────────────────────────────────────────────
// Handles communication with the backend for System Chat and MSO surfaces

import type {
  SovereignChatRequest,
  SovereignChatResponse,
  SurfaceType,
  ExecutionStatus,
  ExecutionStatusSource,
  MSOContext,
} from './types'
import type { ConfirmPreparedActionResult, MSOPolicyReviewResult, MSOAuthorityBindingResult } from '../types'

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
  sessionId?: string,
  msoContext?: MSOContext,
): Promise<SovereignChatResponse> {
  const payload: SovereignChatRequest = {
    text,
    surface,
    ...(sessionId && { session_id: sessionId }),
    ...(msoContext && { mso_context: msoContext }),
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
 * Record a human confirmation signal for a prepared action.
 * Does not grant execution authority or satisfy any authority chain step.
 * execution_allowed and can_execute_now remain false.
 */
export async function confirmPreparedAction(
  entryId: string,
  actionId: string,
  confirmed: boolean,
  operatorNote?: string,
): Promise<ConfirmPreparedActionResult> {
  try {
    const res = await fetch('/api/mso/prepared-actions/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        entry_id: entryId,
        action_id: actionId,
        confirmed,
        operator_note: operatorNote ?? '',
      }),
    })
    const data = await res.json()
    if (!res.ok) {
      return {
        ok: false,
        execution_allowed: false,
        can_execute_now: false,
        error: data.error ?? `Error ${res.status}`,
      }
    }
    return {
      ok: true,
      entry_id: data.entry_id,
      action_id: data.action_id,
      human_confirmation_status: data.human_confirmation_status,
      execution_allowed: false,
      can_execute_now: false,
      recorded_at: data.recorded_at,
      note: data.note,
    }
  } catch (err) {
    return {
      ok: false,
      execution_allowed: false,
      can_execute_now: false,
      error: err instanceof Error ? err.message : 'Network error',
    }
  }
}

/**
 * Request MSO capability policy review for a confirmed prepared action.
 * Produces MSOPolicyDecisionDraft — first authority chain artifact after HumanConfirmationRecord.
 * Does not grant execution authority. execution_allowed and can_execute_now remain false.
 */
export async function requestMSOPolicyReview(
  entryId: string,
  actionId: string,
): Promise<MSOPolicyReviewResult> {
  try {
    const res = await fetch('/api/mso/prepared-actions/policy-review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entry_id: entryId, action_id: actionId }),
    })
    const data = await res.json()
    if (!res.ok) {
      return {
        ok: false,
        execution_allowed: false,
        can_execute_now: false,
        error: data.error ?? `Error ${res.status}`,
      }
    }
    return {
      ok: true,
      entry_id: data.entry_id,
      action_id: data.action_id,
      policy_review_id: data.policy_review_id,
      policy_outcome: data.policy_outcome,
      capability_mode: data.capability_mode,
      execution_allowed: false,
      can_execute_now: false,
      used_execution: false,
      human_confirmation_satisfied: data.human_confirmation_satisfied,
      created_at: data.created_at,
      note: data.note,
    }
  } catch (err) {
    return {
      ok: false,
      execution_allowed: false,
      can_execute_now: false,
      error: err instanceof Error ? err.message : 'Network error',
    }
  }
}

/**
 * Request MSO authority binding draft for an approved policy review.
 * Produces MSOAuthorityBindingDraft — second authority chain artifact after MSOPolicyDecisionDraft.
 * Requires policy_outcome to be "approved" or "approved_confirm_only".
 * Does not call token_issuer, create AuthorizedPlan, call PoliceGate, or execute.
 * execution_allowed and can_execute_now remain false.
 */
export async function requestMSOAuthorityBinding(
  entryId: string,
  actionId: string,
): Promise<MSOAuthorityBindingResult> {
  try {
    const res = await fetch('/api/mso/prepared-actions/authority-binding', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entry_id: entryId, action_id: actionId }),
    })
    const data = await res.json()
    if (!res.ok) {
      return {
        ok: false,
        execution_allowed: false,
        can_execute_now: false,
        error: data.error ?? `Error ${res.status}`,
        policy_outcome: data.policy_outcome,
      }
    }
    return {
      ok: true,
      entry_id: data.entry_id,
      action_id: data.action_id,
      policy_review_id: data.policy_review_id,
      authority_binding_id: data.authority_binding_id,
      binding_status: data.binding_status,
      requires_authorized_plan: data.requires_authorized_plan,
      requires_police_gate: data.requires_police_gate,
      execution_allowed: false,
      can_execute_now: false,
      used_execution: false,
      created_at: data.created_at,
      note: data.note,
    }
  } catch (err) {
    return {
      ok: false,
      execution_allowed: false,
      can_execute_now: false,
      error: err instanceof Error ? err.message : 'Network error',
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
