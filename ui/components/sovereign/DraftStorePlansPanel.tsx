'use client'

/**
 * DraftStorePlansPanel — lists, creates, and escalates real Draft Store Plans.
 *
 * Design contract:
 *   - Lists real Plans from the Draft Store backend via listPlans(operatorSeat).
 *   - Creates new Plans via createPlan(). Plan IDs are generated client-side.
 *   - Allows escalation to mso_review via transitionPlan(), with explicit confirmation.
 *   - Shows PlanStatusIndicator inline for each plan (ACK/Prepare lifecycle).
 *   - NEVER shows Execute, Running, Live, Authorized, Approved, Completed.
 *   - Escalate to MSO Review is NOT ACK. ACK is NOT authorization. Prepare is NOT execution.
 *
 * Sprint: #233 — Draft Store Plans List UI.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  listPlans,
  createPlan,
  transitionPlan,
} from '@/lib/api'
import { PlanStateBadge } from './PlanStateBadge'
import { PlanStatusIndicator } from './PlanStatusIndicator'
import type {
  PlanDraftRecord,
  PlanDraftState,
  PlanDraftPayload,
  PlanRiskLevel,
} from '@/lib/types'

// ── Plan ID generator ─────────────────────────────────────────────────────────
// Format: plan_<timestamp_ms>_<uuid4_short>
// Matches plan_model.py canonical format.

function generatePlanId(): string {
  const ts = Date.now()
  const uuid = crypto.randomUUID().replace(/-/g, '').slice(0, 8)
  return `plan_${ts}_${uuid}`
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface DraftStorePlansPanelProps {
  /** Pre-fill the operator seat field. */
  defaultOperatorSeat?: string
  /** Compact layout. Default: false. */
  compact?: boolean
}

// ── Create form state ─────────────────────────────────────────────────────────

interface CreateFormState {
  title: string
  intent_summary: string
  domain: string
  risk_level: PlanRiskLevel | ''
  target_actions_raw: string   // comma-separated free-form strings
  notes: string
}

const EMPTY_FORM: CreateFormState = {
  title: '',
  intent_summary: '',
  domain: '',
  risk_level: '',
  target_actions_raw: '',
  notes: '',
}

// ── Component ─────────────────────────────────────────────────────────────────

export function DraftStorePlansPanel({
  defaultOperatorSeat = '',
  compact = false,
}: DraftStorePlansPanelProps) {
  const [operatorSeat, setOperatorSeat] = useState(defaultOperatorSeat)
  const [plans, setPlans] = useState<PlanDraftRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)

  // Create form
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<CreateFormState>(EMPTY_FORM)
  const [createLoading, setCreateLoading] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // Per-plan action state
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({})
  const [actionError, setActionError] = useState<Record<string, string | null>>({})

  // ── Load plans ──────────────────────────────────────────────────────────────

  const loadPlans = useCallback(async (seat: string) => {
    if (!seat.trim()) return
    setLoading(true)
    setListError(null)
    const result = await listPlans(seat.trim())
    if (result.ok) {
      setPlans(result.plans)
      setListError(null)
    } else {
      setPlans([])
      setListError(result.error ?? 'Draft store unavailable')
    }
    setLoaded(true)
    setLoading(false)
  }, [])

  // Auto-load when defaultOperatorSeat provided
  useEffect(() => {
    if (defaultOperatorSeat) {
      loadPlans(defaultOperatorSeat)
    }
  }, [defaultOperatorSeat, loadPlans])

  const handleRefresh = () => {
    if (operatorSeat.trim()) {
      loadPlans(operatorSeat)
    }
  }

  // ── Create plan ─────────────────────────────────────────────────────────────

  const handleCreate = async () => {
    if (!form.title.trim() || !form.intent_summary.trim() || !form.domain.trim()) return
    if (!operatorSeat.trim()) {
      setCreateError('Operator seat is required to create a plan.')
      return
    }

    setCreateLoading(true)
    setCreateError(null)
    try {
      const targetActions = form.target_actions_raw
        .split(',')
        .map(s => s.trim())
        .filter(Boolean)

      const payload: PlanDraftPayload = {
        plan_id: generatePlanId(),
        title: form.title.trim(),
        intent_summary: form.intent_summary.trim(),
        domain: form.domain.trim(),
        operator_seat: operatorSeat.trim(),
        state: 'draft',
        schema_version: '1',
        ...(form.risk_level ? { risk_level: form.risk_level as PlanRiskLevel } : {}),
        ...(targetActions.length > 0 ? { target_actions: targetActions } : {}),
        ...(form.notes.trim() ? { notes: form.notes.trim() } : {}),
      }

      await createPlan(payload)
      setForm(EMPTY_FORM)
      setShowCreate(false)
      await loadPlans(operatorSeat)
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Create failed')
    } finally {
      setCreateLoading(false)
    }
  }

  // ── Escalate to MSO Review ──────────────────────────────────────────────────

  const handleEscalate = async (plan: PlanDraftRecord) => {
    if (!window.confirm(
      `Escalate plan "${plan.title}" to MSO Review?\n\n` +
      'The plan will be frozen and sent to MSO for sovereign review. ' +
      'This is NOT authorization or execution — it is an escalation for review. ' +
      'You will not be able to edit the plan after escalation.',
    )) return

    setActionLoading(prev => ({ ...prev, [plan.plan_id]: true }))
    setActionError(prev => ({ ...prev, [plan.plan_id]: null }))
    try {
      await transitionPlan(plan.plan_id, {
        operator_seat: operatorSeat,
        from_state: plan.state,
        to_state: 'mso_review',
        notes: 'Escalated to MSO Review by operator.',
      })
      await loadPlans(operatorSeat)
    } catch (err) {
      setActionError(prev => ({
        ...prev,
        [plan.plan_id]: err instanceof Error ? err.message : 'Escalation failed',
      }))
    } finally {
      setActionLoading(prev => ({ ...prev, [plan.plan_id]: false }))
    }
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">
          Draft Store Plans
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="text"
            value={operatorSeat}
            onChange={e => setOperatorSeat(e.target.value)}
            placeholder="operator_seat"
            className="bg-os-surface border border-os-border rounded px-2 py-1 text-[10px] font-mono text-tx-primary placeholder-tx-muted focus:outline-none focus:border-violet-400/50 w-36"
          />
          <button
            onClick={handleRefresh}
            disabled={!operatorSeat.trim() || loading}
            className="px-3 py-1 text-[10px] font-mono rounded border border-os-border bg-os-surface text-tx-secondary hover:text-tx-primary hover:border-violet-400/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? 'Loading…' : 'Refresh Plans'}
          </button>
          <button
            onClick={() => setShowCreate(v => !v)}
            className="px-3 py-1 text-[10px] font-mono rounded border border-violet-400/30 bg-violet-400/10 text-violet-400 hover:bg-violet-400/20 transition-colors"
          >
            {showCreate ? 'Cancel' : '+ Create Plan'}
          </button>
        </div>
      </div>

      {/* Create Plan form */}
      {showCreate && (
        <div className="rounded-lg border border-violet-400/20 bg-violet-400/5 p-3 space-y-3">
          <p className="text-[10px] font-mono text-violet-400 uppercase tracking-wider">
            New Plan — Draft Store
          </p>
          <p className="text-[9px] font-mono text-tx-muted">
            Creates a new Plan in the Draft Store. The plan does not execute.
            Escalation to MSO Review is a separate, explicit step.
          </p>

          <div className="space-y-2">
            <input
              type="text"
              value={form.title}
              onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
              placeholder="Mission objective / title"
              className="w-full bg-os-surface border border-os-border rounded px-2 py-1.5 text-[10px] font-mono text-tx-primary placeholder-tx-muted focus:outline-none focus:border-violet-400/50"
            />
            <input
              type="text"
              value={form.intent_summary}
              onChange={e => setForm(f => ({ ...f, intent_summary: e.target.value }))}
              placeholder="Intent summary"
              className="w-full bg-os-surface border border-os-border rounded px-2 py-1.5 text-[10px] font-mono text-tx-primary placeholder-tx-muted focus:outline-none focus:border-violet-400/50"
            />
            <input
              type="text"
              value={form.domain}
              onChange={e => setForm(f => ({ ...f, domain: e.target.value }))}
              placeholder="Domain (e.g. CODE, WORK, FIN)"
              className="w-full bg-os-surface border border-os-border rounded px-2 py-1.5 text-[10px] font-mono text-tx-primary placeholder-tx-muted focus:outline-none focus:border-violet-400/50"
            />
            <input
              type="text"
              value={form.target_actions_raw}
              onChange={e => setForm(f => ({ ...f, target_actions_raw: e.target.value }))}
              placeholder="Target actions (comma-separated, e.g. CODE_REVIEW, CODE_FIX)"
              className="w-full bg-os-surface border border-os-border rounded px-2 py-1.5 text-[10px] font-mono text-tx-primary placeholder-tx-muted focus:outline-none focus:border-violet-400/50"
            />
            <select
              value={form.risk_level}
              onChange={e => setForm(f => ({ ...f, risk_level: e.target.value as PlanRiskLevel | '' }))}
              className="w-full bg-os-surface border border-os-border rounded px-2 py-1.5 text-[10px] font-mono text-tx-primary focus:outline-none focus:border-violet-400/50"
            >
              <option value="">Risk level (optional)</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>

          {createError && (
            <p className="text-[9px] font-mono text-red-400">⊘ {createError}</p>
          )}

          <button
            onClick={handleCreate}
            disabled={!form.title.trim() || !form.intent_summary.trim() || !form.domain.trim() || createLoading}
            className="px-4 py-1.5 text-[10px] font-mono rounded border border-violet-400/30 bg-violet-400/10 text-violet-400 hover:bg-violet-400/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {createLoading ? 'Saving…' : 'Create Plan'}
          </button>
        </div>
      )}

      {/* Plan list */}
      {!loaded && !loading && operatorSeat.trim() && (
        <p className="text-[10px] font-mono text-tx-muted">Click &quot;Refresh Plans&quot; to load.</p>
      )}

      {loading && (
        <p className="text-[10px] font-mono text-tx-muted animate-pulse">Loading plans…</p>
      )}

      {listError && !loading && (
        <div className="rounded-lg border border-red-400/20 bg-red-400/5 p-3">
          <p className="text-[10px] font-mono text-red-400">⊘ Backend unavailable: {listError}</p>
        </div>
      )}

      {loaded && !loading && !listError && plans.length === 0 && (
        <div className="rounded-lg border border-os-border bg-os-surface p-3">
          <p className="text-[10px] font-mono text-tx-muted">
            No plans found for this operator seat.
          </p>
        </div>
      )}

      {plans.length > 0 && (
        <div className="space-y-3">
          {plans.map(plan => (
            <PlanRow
              key={plan.plan_id}
              plan={plan}
              operatorSeat={operatorSeat}
              compact={compact}
              isActionLoading={actionLoading[plan.plan_id] ?? false}
              actionError={actionError[plan.plan_id] ?? null}
              onEscalate={handleEscalate}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── PlanRow ───────────────────────────────────────────────────────────────────

interface PlanRowProps {
  plan: PlanDraftRecord
  operatorSeat: string
  compact: boolean
  isActionLoading: boolean
  actionError: string | null
  onEscalate: (plan: PlanDraftRecord) => void
}

function PlanRow({
  plan,
  operatorSeat,
  compact,
  isActionLoading,
  actionError,
  onEscalate,
}: PlanRowProps) {
  const canEscalate = plan.state === 'draft' || plan.state === 'planning'

  return (
    <div className="rounded-lg border border-os-border bg-os-surface p-3 space-y-2">
      {/* Plan header */}
      <div className="flex items-start justify-between gap-2 flex-wrap">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-mono font-medium text-tx-primary truncate">
            {plan.title}
          </p>
          <p className="text-[9px] font-mono text-tx-muted truncate">
            {plan.plan_id}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <PlanStateBadge state={plan.state} />
        </div>
      </div>

      {/* Intent summary */}
      {plan.intent_summary && (
        <p className="text-[10px] font-mono text-tx-secondary line-clamp-2">
          {plan.intent_summary}
        </p>
      )}

      {/* Domain + target_actions */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[9px] font-mono text-tx-muted">
          domain: <span className="text-tx-secondary">{plan.domain}</span>
        </span>
        {plan.target_actions && plan.target_actions.length > 0 && (
          <span className="text-[9px] font-mono text-tx-muted">
            actions: <span className="text-tx-secondary">{plan.target_actions.join(', ')}</span>
          </span>
        )}
        {plan.risk_level && (
          <span className="text-[9px] font-mono text-tx-muted">
            risk: <span className="text-tx-secondary">{plan.risk_level}</span>
          </span>
        )}
      </div>

      {/* Updated at */}
      <p className="text-[9px] font-mono text-tx-muted">
        updated: {new Date(plan.updated_at).toLocaleString()}
      </p>

      {/* Actions */}
      {canEscalate && (
        <div className="flex items-center gap-2">
          <button
            onClick={() => onEscalate(plan)}
            disabled={isActionLoading}
            className="px-3 py-1 text-[10px] font-mono rounded border border-blue-400/30 bg-blue-400/10 text-blue-400 hover:bg-blue-400/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {isActionLoading ? 'Processing…' : 'Escalate to MSO Review →'}
          </button>
        </div>
      )}

      {actionError && (
        <p className="text-[9px] font-mono text-red-400">⊘ {actionError}</p>
      )}

      {/* Prepare status — shown for all plans, handles its own loading */}
      {!compact && (
        <div className="pt-1 border-t border-os-border">
          <p className="text-[9px] font-mono text-tx-muted uppercase tracking-wider mb-1">
            Prepare Status
          </p>
          <PlanStatusIndicator
            planId={plan.plan_id}
            operatorSeat={operatorSeat}
            compact={true}
          />
        </div>
      )}
    </div>
  )
}
