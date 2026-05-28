'use client'

import { useState, useEffect } from 'react'
import { getEntity } from '@/lib/sovereign/entity-registry'
import { useUIStore } from '@/stores/ui-store'
import { useSeatProviderStore } from '@/stores/seat-provider-store'
import { usePreparedActionsStore } from '@/stores/prepared-actions-store'
import { useConfirmPendingStore } from '@/stores/confirm-pending-store'
import { useAuthorityStatusStore } from '@/stores/authority-status-store'
import { useSovereignStore } from '@/stores/sovereign-store'
import { useSeatProviderPolling } from '@/hooks/use-seat-provider-polling'
import { usePreparedActionsPolling } from '@/hooks/use-prepared-actions-polling'
import { useConfirmPendingPolling } from '@/hooks/use-confirm-pending-polling'
import { useAuthorityStatusPolling } from '@/hooks/use-authority-status-polling'
import {
  getMissionControlStatus,
  getMissionControlReadiness,
  getOrchestrationSnapshot,
  getAuthorityTraceSnapshot,
  getMissionControlLifecycleSnapshot,
} from '@/lib/api'
import { MissionControlChainView } from './MissionControlChainView'
import { OutcomeStatusPanel } from './OutcomeStatusPanel'
import type {
  MissionLifecycleState,
  MissionControlPlan,
  OrchestrationThread,
  MSOEntityStatusResponse,
  MSOSeatStatusResponse,
  MissionControlStatusResponse,
  MissionControlReadinessResponse,
  OrchestrationSnapshotResponse,
  AuthorityTraceSnapshotResponse,
  LifecycleSnapshotResponse,
} from '@/lib/types'

// ── Backend truth-contract polling hooks ─────────────────────────────────────
//
// Each hook fetches once on mount and refreshes every 30 s. Fail-soft:
// returns null (or the UNAVAILABLE sentinel from the helper) on any error.
// Never throws. No execution path.

function useMCStatusQuery() {
  const [data, setData] = useState<MissionControlStatusResponse | null>(null)
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      const result = await getMissionControlStatus()
      if (!cancelled) setData(result)
    }
    poll()
    const id = setInterval(poll, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])
  return data
}

function useMCReadinessQuery() {
  const [data, setData] = useState<MissionControlReadinessResponse | null>(null)
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      const result = await getMissionControlReadiness()
      if (!cancelled) setData(result)
    }
    poll()
    const id = setInterval(poll, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])
  return data
}

function useMCOrchestrationQuery() {
  const [data, setData] = useState<OrchestrationSnapshotResponse | null>(null)
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      const result = await getOrchestrationSnapshot()
      if (!cancelled) setData(result)
    }
    poll()
    const id = setInterval(poll, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])
  return data
}

function useMCTraceQuery() {
  const [data, setData] = useState<AuthorityTraceSnapshotResponse | null>(null)
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      const result = await getAuthorityTraceSnapshot()
      if (!cancelled) setData(result)
    }
    poll()
    const id = setInterval(poll, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])
  return data
}

// S-MISSION-CONTROL-LIFECYCLE-SNAPSHOT-01
function useMCLifecycleQuery() {
  const [data, setData] = useState<LifecycleSnapshotResponse | null>(null)
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      const result = await getMissionControlLifecycleSnapshot()
      if (!cancelled) setData(result)
    }
    poll()
    const id = setInterval(poll, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])
  return data
}

// ── Tab identifiers ───────────────────────────────────────────────────────────

type MCTab = 'planner' | 'mso' | 'arms' | 'orchestration' | 'outcome'

const TAB_CONFIG: Array<{ id: MCTab; label: string; sublabel: string; color: string; borderColor: string; bgColor: string }> = [
  { id: 'planner',       label: 'Planner',       sublabel: 'Draft & Escalate',      color: 'text-violet-400', borderColor: 'border-violet-400/40', bgColor: 'bg-violet-400/10' },
  { id: 'mso',          label: 'MSO',            sublabel: 'Governed Preparation',  color: 'text-amber-400',  borderColor: 'border-amber-400/40',  bgColor: 'bg-amber-400/10'  },
  { id: 'arms',         label: 'Arms',           sublabel: 'Executor Availability', color: 'text-cyan-400',   borderColor: 'border-cyan-400/40',   bgColor: 'bg-cyan-400/10'   },
  { id: 'orchestration',label: 'Orchestration',  sublabel: 'State View',            color: 'text-teal-400',   borderColor: 'border-teal-400/40',   bgColor: 'bg-teal-400/10'   },
  { id: 'outcome',      label: 'Outcome',        sublabel: 'Authority Trace',       color: 'text-rose-400',   borderColor: 'border-rose-400/40',   bgColor: 'bg-rose-400/10'   },
]

// ── Shared sub-components ─────────────────────────────────────────────────────

function SituationTile({
  label,
  value,
  accent = false,
  warn = false,
}: {
  label: string
  value: string | number
  accent?: boolean
  warn?: boolean
}) {
  const color = warn ? 'text-warn' : accent ? 'text-ok' : 'text-tx-primary'
  return (
    <div className="bg-os-surface border border-os-border rounded-lg p-4">
      <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-mono font-semibold ${color}`}>{value}</p>
    </div>
  )
}

function PostureRow({
  label,
  value,
  tone = 'muted',
  note,
}: {
  label: string
  value: string
  tone?: 'ok' | 'warn' | 'muted'
  note?: string
}) {
  const toneClass =
    tone === 'ok'   ? 'text-ok border-ok/30 bg-ok/10' :
    tone === 'warn' ? 'text-warn border-warn/30 bg-warn/10' :
    'text-tx-muted border-os-border bg-os-base'

  return (
    <div className="rounded-lg border border-os-border bg-os-surface p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-mono text-tx-secondary">{label}</p>
        <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border ${toneClass}`}>
          {value}
        </span>
      </div>
      {note && <p className="mt-1 text-[10px] font-mono text-tx-muted">{note}</p>}
    </div>
  )
}

// S-MISSION-CONTROL-LANGUAGE-HARDENING-01
// Dangerous lifecycle labels must never be rendered on a surface that cannot execute.
// Applied before CSS lookup and text render — the guard is unconditional.
const DANGEROUS_LIFECYCLE_DISPLAY_MAP: Readonly<Record<string, string>> = {
  running:   'blocked',  // never: implies live execution which never comes from this surface
  executing: 'blocked',  // defense in depth
  completed: 'closed',   // never: implies execution completed — impossible from this surface
}

function LifecycleBadge({ state }: { state: MissionLifecycleState | string }) {
  // Apply safety remapping before CSS lookup or text render.
  // Dangerous states are blocked unconditionally at display time.
  const safeState = DANGEROUS_LIFECYCLE_DISPLAY_MAP[state] ?? state

  const cls: Record<string, string> = {
    draft:                 'text-tx-muted border-os-border bg-os-base',
    planning:              'text-cyan-400 border-cyan-400/30 bg-cyan-400/10',
    mso_review:            'text-amber-400 border-amber-400/30 bg-amber-400/10',
    prepared:              'text-blue-400 border-blue-400/30 bg-blue-400/10',
    awaiting_confirmation: 'text-orange-400 border-orange-400/30 bg-orange-400/10',
    blocked:               'text-rose-400 border-rose-400/30 bg-rose-400/10',
    closed:                'text-tx-muted/50 border-os-border/50 bg-os-base',
    failed:                'text-rose-400 border-rose-400/30 bg-rose-400/10',
    cancelled:             'text-tx-muted border-os-border bg-os-base',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border ${cls[safeState] ?? 'text-tx-muted border-os-border bg-os-base'}`}>
      {safeState.replace(/_/g, ' ')}
    </span>
  )
}

// S-MISSION-CONTROL-LANGUAGE-HARDENING-01
// 'real' is an internal status value meaning "registered real arm implementation"
// (as opposed to a stub). The word 'real' rendered alone is execution-adjacent
// and misleading on a surface where no execution occurs.
// Display label override without changing the internal type contract.
const EXEC_STATUS_DISPLAY_LABEL: Readonly<Record<string, string>> = {
  real:        'registered',  // 'real arm' ≠ 'real execution'
  partial:     'partial',
  stub:        'stub',
  unavailable: 'unavailable',
}

function ExecStatusBadge({ status }: { status: 'real' | 'stub' | 'unavailable' | 'partial' }) {
  const cls = {
    real:        'text-ok border-ok/30 bg-ok/10',
    partial:     'text-warn border-warn/30 bg-warn/10',
    stub:        'text-amber-400 border-amber-400/30 bg-amber-400/10',
    unavailable: 'text-tx-muted border-os-border bg-os-base',
  }[status]
  return (
    <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono uppercase border ${cls}`}>
      {EXEC_STATUS_DISPLAY_LABEL[status] ?? status}
    </span>
  )
}

// ── Space 1: Planner ──────────────────────────────────────────────────────────

function PlannerSpace() {
  const [plan, setPlan] = useState<MissionControlPlan>({
    title: '',
    body: '',
    state: 'draft',
  })
  const { setActiveView, setPendingRedirectText } = useSovereignStore()

  const canEscalate = plan.title.trim().length > 0 && plan.body.trim().length > 0

  const handleEscalate = () => {
    if (!canEscalate) return
    const formattedText = `[PLAN REQUEST]\n\nMission: ${plan.title}\n\n${plan.body}`
    setPendingRedirectText(formattedText)
    setPlan(p => ({ ...p, state: 'mso_review', updatedAt: new Date().toISOString() }))
    setActiveView('mso')
  }

  const handleChange = (field: 'title' | 'body', value: string) => {
    setPlan(p => ({
      ...p,
      [field]: value,
      state: p.state === 'draft' || p.state === 'planning' ? 'planning' : p.state,
    }))
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-violet-400/20 bg-violet-400/5 p-4">
        <p className="text-xs font-mono text-violet-400 mb-1">Planner Space — ALPHA</p>
        <p className="text-[10px] font-mono text-tx-muted">
          Draft a mission or plan. The plan does not execute. Escalating sends it to MSO as a governed preparation request — no execution is triggered.
        </p>
      </div>

      <div>
        <label className="block text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-1">
          Mission Objective
        </label>
        <input
          type="text"
          value={plan.title}
          onChange={(e) => handleChange('title', e.target.value)}
          placeholder="Describe the mission objective…"
          className="w-full bg-os-surface border border-os-border rounded px-3 py-2 text-xs font-mono text-tx-primary placeholder-tx-muted focus:outline-none focus:border-violet-400/50 transition-colors"
        />
      </div>

      <div>
        <label className="block text-[10px] font-mono text-tx-muted uppercase tracking-wider mb-1">
          Plan Body
        </label>
        <textarea
          value={plan.body}
          onChange={(e) => handleChange('body', e.target.value)}
          placeholder="Describe the plan steps, context, or details…"
          rows={7}
          className="w-full bg-os-surface border border-os-border rounded px-3 py-2 text-xs font-mono text-tx-primary placeholder-tx-muted focus:outline-none focus:border-violet-400/50 resize-y transition-colors"
        />
      </div>

      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-tx-muted">Plan status:</span>
          <LifecycleBadge state={plan.state} />
        </div>
        {plan.updatedAt && (
          <span className="text-[10px] font-mono text-tx-muted">
            Updated: {new Date(plan.updatedAt).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
        )}
      </div>

      <div className="rounded-lg border border-os-border bg-os-surface p-4 space-y-3">
        <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Next Safe Step</p>
        <button
          onClick={handleEscalate}
          disabled={!canEscalate || plan.state === 'mso_review'}
          className="px-4 py-2 rounded text-xs font-mono bg-violet-400/10 border border-violet-400/30 text-violet-400 hover:bg-violet-400/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {plan.state === 'mso_review' ? 'Escalated to MSO ✓' : 'Escalate to MSO →'}
        </button>
        <p className="text-[10px] font-mono text-tx-muted">
          This sends the plan text to the MSO composer for governed preparation. No execution is triggered.
          The full authority chain (PolicyDecision → CapabilityToken → PoliceGate) remains required before anything executes.
        </p>
      </div>

      {plan.state === 'mso_review' && (
        <div className="rounded-lg border border-amber-400/30 bg-amber-400/5 p-3">
          <p className="text-xs font-mono text-amber-400">Plan forwarded to MSO for review.</p>
          <p className="text-[10px] font-mono text-tx-muted mt-1">
            Navigate to the MSO console to continue the governed preparation cycle. The plan text has been pre-filled in the MSO composer.
          </p>
          <button
            onClick={() => setPlan(p => ({ ...p, title: '', body: '', state: 'draft', updatedAt: undefined }))}
            className="mt-2 text-[10px] font-mono text-tx-muted hover:text-tx-secondary underline"
          >
            Clear plan and start over
          </button>
        </div>
      )}
    </div>
  )
}

// ── Space 2: MSO Escalation / Governed Preparation ───────────────────────────

function MSOEscalationSpace() {
  const [entityStatus, setEntityStatus] = useState<MSOEntityStatusResponse | null>(null)
  const [seatStatus, setSeatStatus] = useState<MSOSeatStatusResponse | null>(null)
  const [loading, setLoading] = useState(true)

  const preparedActions = usePreparedActionsStore((s) => s.preparedActions)
  const confirmPending = useConfirmPendingStore((s) => s.confirmPending)
  const seatProvider = useSeatProviderStore((s) => s.seatProvider)

  useEffect(() => {
    let cancelled = false
    const fetchStatus = async () => {
      try {
        const [entityRes, seatRes] = await Promise.all([
          fetch('/api/mso/entity/status', { cache: 'no-store', signal: AbortSignal.timeout(4000) }),
          fetch('/api/mso/seat/status',   { cache: 'no-store', signal: AbortSignal.timeout(4000) }),
        ])
        if (cancelled) return
        if (entityRes.ok) setEntityStatus(await entityRes.json())
        if (seatRes.ok)   setSeatStatus(await seatRes.json())
      } catch {
        // fail-soft: leave null
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchStatus()
    const interval = setInterval(fetchStatus, 30_000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  const provider      = seatProvider?.seat_provider ?? null

  // S-MISSION-CONTROL-LIFECYCLE-SNAPSHOT-01
  // Prefer backend lifecycle truth; fall back to Zustand while loading/unavailable.
  const lifecycleData = useMCLifecycleQuery()
  const preparedCount = lifecycleData !== null
    ? lifecycleData.queues_at_snapshot.prepared_actions_count
    : (preparedActions?.count ?? 0)
  const confirmCount  = lifecycleData !== null
    ? lifecycleData.queues_at_snapshot.confirm_pending_count
    : (confirmPending?.pending_count ?? 0)
  const currentStage: MissionLifecycleState = lifecycleData !== null
    ? lifecycleData.current_stage
    : (() => {
        if (confirmCount > 0)  return 'awaiting_confirmation' as const
        if (preparedCount > 0) return 'prepared' as const
        return 'planning' as const
      })()

  // Next stage: after awaiting_confirmation the full authority chain must complete
  // before any execution occurs — the honest state is 'blocked', not 'running'.
  // 'running' is prohibited: it implies live execution which never comes from this surface.
  const nextStage: MissionLifecycleState = (() => {
    if (currentStage === 'planning')              return 'mso_review'
    if (currentStage === 'prepared')              return 'awaiting_confirmation'
    if (currentStage === 'awaiting_confirmation') return 'blocked'  // authority chain required
    return 'blocked'                                                // default: execution closed
  })()

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-amber-400/20 bg-amber-400/5 p-4">
        <p className="text-xs font-mono text-amber-400 mb-1">MSO Escalation / Governed Preparation — ALPHA</p>
        <p className="text-[10px] font-mono text-tx-muted">
          MSO coordinates governed preparation. Execution remains closed.
          Human confirmation and the full authority chain are required before any execution occurs.
        </p>
      </div>

      {/* MSO Entity Status */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">MSO Entity</p>
        {loading ? (
          <PostureRow label="MSO Entity" value="Loading…" tone="muted" />
        ) : entityStatus === null ? (
          <PostureRow label="MSO Entity Status" value="unavailable" tone="warn" note="Entity status backend not reachable (fail-soft)." />
        ) : (
          <div className="space-y-2">
            <PostureRow
              label="Entity"
              value={entityStatus.entity ?? 'MSO'}
              tone={entityStatus.ok ? 'ok' : 'warn'}
              note={entityStatus.error}
            />
            {entityStatus.boundary && (
              <PostureRow label="Boundary" value={entityStatus.boundary} tone="muted" />
            )}
            <PostureRow
              label="Execution Allowed"
              value="No"
              tone="muted"
              note="execution_allowed=false — architectural invariant."
            />
            <PostureRow
              label="Used Execution"
              value="No"
              tone="ok"
              note="used_execution=false enforced by entity contract."
            />
            {entityStatus.authority_chain && entityStatus.authority_chain.length > 0 && (
              <div className="rounded-lg border border-os-border bg-os-surface p-3">
                <p className="text-[10px] font-mono text-tx-muted mb-2">Authority Chain Stages</p>
                <div className="flex flex-wrap gap-1">
                  {entityStatus.authority_chain.map((stage) => (
                    <span key={stage} className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-os-base border border-os-border text-tx-muted">
                      {stage}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {entityStatus.surfaces && entityStatus.surfaces.length > 0 && (
              <PostureRow label="Surfaces" value={entityStatus.surfaces.join(', ')} tone="muted" />
            )}
            {entityStatus.interaction_modes && entityStatus.interaction_modes.length > 0 && (
              <PostureRow label="Interaction Modes" value={entityStatus.interaction_modes.join(', ')} tone="muted" />
            )}
          </div>
        )}
      </section>

      {/* MSO Seat — cognitive provider seat */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">MSO Seat</p>
        {loading ? (
          <PostureRow label="Seat Status" value="Loading…" tone="muted" />
        ) : seatStatus === null ? (
          <PostureRow label="Seat Status" value="unavailable" tone="warn" note="Seat status backend not reachable (fail-soft)." />
        ) : (
          <div className="space-y-2">
            {seatStatus.active_seat ? (
              <PostureRow label="Active Seat" value={seatStatus.active_seat} tone={seatStatus.ok ? 'ok' : 'warn'} />
            ) : (
              <PostureRow label="Active Seat" value="not configured" tone="warn" />
            )}
            <PostureRow label="Cognitive Only" value="Yes" tone="ok" note="cognitive_only=true — invariant." />
            <PostureRow label="Used Execution"  value="No"  tone="ok" note="used_execution=false — invariant." />
            {seatStatus.available_seats && seatStatus.available_seats.length > 0 && (
              <div className="rounded-lg border border-os-border bg-os-surface p-3">
                <p className="text-[10px] font-mono text-tx-muted mb-2">Available Seats</p>
                <div className="space-y-1.5">
                  {seatStatus.available_seats.map((seat) => (
                    <div key={seat.name} className="flex items-center justify-between">
                      <div>
                        <span className="text-[10px] font-mono text-tx-secondary">{seat.name}</span>
                        {seat.provider && (
                          <span className="text-[9px] font-mono text-tx-muted ml-2">· {seat.provider}</span>
                        )}
                      </div>
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono border ${seat.available ? 'text-ok border-ok/30 bg-ok/10' : 'text-tx-muted border-os-border bg-os-base'}`}>
                        {seat.available ? 'available' : 'unavailable'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        {provider && (
          <div className="mt-2 space-y-2">
            <PostureRow
              label="Seat Provider"
              value={provider.provider_name}
              tone={provider.is_available ? 'ok' : 'warn'}
              note={`Model: ${provider.model_name} · ${provider.local_or_remote}`}
            />
          </div>
        )}
      </section>

      {/* Governed Preparation Cycle */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">Governed Preparation Cycle</p>
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-os-border bg-os-surface p-3">
              <p className="text-[10px] font-mono text-tx-muted mb-1.5">Current Stage</p>
              <LifecycleBadge state={currentStage} />
            </div>
            <div className="rounded-lg border border-os-border bg-os-surface p-3">
              <p className="text-[10px] font-mono text-tx-muted mb-1.5">Next Required Stage</p>
              <LifecycleBadge state={nextStage} />
            </div>
          </div>
          <PostureRow
            label="Execution Now Allowed"
            value="No"
            tone="muted"
            note="Full chain required: PolicyDecision → CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate."
          />
          <PostureRow
            label="Governed Execution"
            value="Closed"
            tone="muted"
            note="Execution is closed. No action from this panel executes, approves, or issues tokens."
          />
          <PostureRow
            label="Prepared Actions Pending"
            value={preparedActions === null ? '…' : String(preparedCount)}
            tone={preparedCount > 0 ? 'warn' : 'ok'}
          />
          <PostureRow
            label="Confirm Queue"
            value={confirmPending === null ? '…' : String(confirmCount)}
            tone={confirmCount > 0 ? 'warn' : 'ok'}
          />
        </div>
      </section>
    </div>
  )
}

// ── Space 3: Arms / Executor Availability ─────────────────────────────────────

function ArmsAvailabilitySpace() {
  // Backend truth readiness (preferred source)
  const readinessData     = useMCReadinessQuery()
  // Fallback: Zustand-derived agent registry
  const registeredAgents  = useSovereignStore((s) => s.systemState.registeredAgents)
  const agentRegistrySource = useSovereignStore((s) => s.systemState.agentRegistrySource)

  // Use backend arms when backend responded ok. Arms availability ≠ authorization.
  // can_execute_without_mso: false and requires_authority: true are always enforced.
  const useBackendArms = readinessData?.ok === true
  const backendArms    = useBackendArms ? readinessData!.arms : null
  const backendOverall = readinessData?.system.overall ?? null

  const mapExecStatus = (status: string): 'real' | 'stub' | 'unavailable' | 'partial' => {
    if (status === 'active')   return 'real'
    if (status === 'degraded') return 'partial'
    return 'unavailable'
  }

  const sourceOk = agentRegistrySource.status === 'available' || agentRegistrySource.status === 'stale'

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-cyan-400/20 bg-cyan-400/5 p-4">
        <p className="text-xs font-mono text-cyan-400 mb-1">Arms / Executor Availability — ALPHA</p>
        <p className="text-[10px] font-mono text-tx-muted">
          Visibility panel for known arms and executors as orchestration resources. This is not a direct execution launcher.
          No action from this panel executes, approves, or issues tokens.
        </p>
      </div>

      {/* Agents / Destinations sub-header */}
      <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest">Agents / Destinations</p>

      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-[10px] font-mono text-tx-muted">Registry source:</span>
        {useBackendArms ? (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-mono uppercase border text-ok border-ok/30 bg-ok/10">
            backend_read_model
          </span>
        ) : (
          <>
            <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono uppercase border ${
              agentRegistrySource.status === 'available' ? 'text-ok border-ok/30 bg-ok/10' :
              agentRegistrySource.status === 'stale'     ? 'text-warn border-warn/30 bg-warn/10' :
              agentRegistrySource.status === 'loading'   ? 'text-cyan-400 border-cyan-400/30 bg-cyan-400/10' :
              'text-tx-muted border-os-border bg-os-base'
            }`}>
              {agentRegistrySource.status}
            </span>
            {!sourceOk && agentRegistrySource.status !== 'loading' && (
              <span className="text-[10px] font-mono text-warn">Data may be fallback or unavailable.</span>
            )}
          </>
        )}
        {readinessData !== null && !readinessData.ok && (
          <span className="text-[10px] font-mono text-tx-muted">[derived fallback]</span>
        )}
        {backendOverall && (
          <span className="text-[10px] font-mono text-tx-muted">overall: {backendOverall}</span>
        )}
      </div>

      {/* Backend truth arms (preferred) */}
      {useBackendArms && backendArms !== null ? (
        backendArms.length === 0 ? (
          <div className="rounded-lg border border-os-border bg-os-surface p-4 space-y-2">
            <p className="text-[10px] font-mono text-tx-muted">
              No arms registered in agent registry. Overall: {backendOverall ?? 'unavailable'}. source: backend_read_model.
            </p>
            <ExecStatusBadge status="unavailable" />
            <p className="text-[9px] font-mono text-tx-muted/70">
              executionStatus: unavailable — no arms in backend registry.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {backendArms.map((arm) => (
              <div key={arm.id} className="rounded-lg border border-os-border bg-os-surface p-3" data-testid="backend-arm">
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="min-w-0">
                    <p className="text-xs font-mono text-tx-primary">{arm.label}</p>
                    <p className="text-[10px] font-mono text-tx-muted">source: {arm.readiness_source}</p>
                  </div>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono border ${
                      arm.available ? 'text-ok border-ok/30 bg-ok/10' : 'text-tx-muted border-os-border bg-os-base'
                    }`}>
                      {arm.available ? 'available' : 'unavailable'}
                    </span>
                    <ExecStatusBadge status={arm.execution_status} />
                  </div>
                </div>
                {/* Invariants always visible — arm availability ≠ authorization */}
                <div className="flex flex-wrap items-center gap-3 text-[9px] font-mono text-tx-muted">
                  <span>can_execute_without_mso: false</span>
                  <span>requires_authority: true</span>
                </div>
              </div>
            ))}
          </div>
        )
      ) : (
        /* Fallback: Zustand-derived registry data */
        registeredAgents.length === 0 ? (
          <div className="rounded-lg border border-os-border bg-os-surface p-4 space-y-2">
            <p className="text-[10px] font-mono text-tx-muted">
              No arms/executors registered in the current session. Registry source: {agentRegistrySource.status}.
            </p>
            <ExecStatusBadge status="unavailable" />
            <p className="text-[9px] font-mono text-tx-muted/70">
              executionStatus: unavailable — no backend agent registry data connected for this session.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {registeredAgents.map((agent) => {
              const exStatus = mapExecStatus(agent.status)
              return (
                <div key={agent.id} className="rounded-lg border border-os-border bg-os-surface p-3">
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div className="min-w-0">
                      <p className="text-xs font-mono text-tx-primary">{agent.name}</p>
                      {agent.domain && (
                        <p className="text-[10px] font-mono text-tx-muted">{agent.domain}</p>
                      )}
                      {agent.description && (
                        <p className="text-[10px] font-mono text-tx-muted/70 mt-0.5 truncate">{agent.description}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono border ${
                        agent.status === 'active'   ? 'text-ok border-ok/30 bg-ok/10' :
                        agent.status === 'degraded' ? 'text-warn border-warn/30 bg-warn/10' :
                        'text-tx-muted border-os-border bg-os-base'
                      }`}>
                        {agent.status}
                      </span>
                      <ExecStatusBadge status={exStatus} />
                    </div>
                  </div>
                  {agent.capabilities.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-1.5">
                      {agent.capabilities.map((cap) => (
                        <span key={cap} className="px-1 py-0.5 rounded text-[9px] font-mono bg-os-base border border-os-border text-tx-muted">
                          {cap}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="flex flex-wrap items-center gap-3">
                    {agent.requires_authority && (
                      <span className="text-[9px] font-mono text-tx-muted">requires_authority</span>
                    )}
                    {agent.requires_review && (
                      <span className="text-[9px] font-mono text-tx-muted">requires_review</span>
                    )}
                    {agent.policy_restricted && (
                      <span className="text-[9px] font-mono text-warn">policy_restricted</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )
      )}

      <div className="rounded-lg border border-os-border bg-os-base p-3">
        <p className="text-[10px] font-mono text-tx-muted">
          Execution is closed. Arms are visible as orchestration resources only. Direct invocation from this panel is architecturally prohibited.
          Runner is not reachable from UI without the full authority chain.
        </p>
      </div>
    </div>
  )
}

// ── Space 4: Orchestration View ───────────────────────────────────────────────

function OrchestrationViewSpace() {
  // Backend truth snapshot (preferred source). Never fabricates runs or live threads.
  const orchestrationData = useMCOrchestrationQuery()

  const { operationalMode, webhookStatus, apiStatus } = useUIStore((s) => s.systemData)
  // Fallback stores (used when backend snapshot is unavailable)
  const preparedActionsStore = usePreparedActionsStore((s) => s.preparedActions)
  const confirmPending       = useConfirmPendingStore((s) => s.confirmPending)

  // Backend snapshot is authoritative when ok. Runs/threads are always [] by contract.
  // live_execution is always false — Runner is never reachable from UI.
  const useBackendSnapshot = orchestrationData?.ok === true
  const liveExecution      = orchestrationData?.live_execution ?? false  // always false
  const orchestrationSource = useBackendSnapshot ? 'backend_read_model' : 'derived'

  // Prefer backend snapshot confirm count; fall back to Zustand store
  const backendConfirmCount  = useBackendSnapshot ? orchestrationData!.confirm_pending.length : null
  const confirmCount         = backendConfirmCount ?? confirmPending?.pending_count ?? 0
  const confirmPendingLoaded = useBackendSnapshot || confirmPending !== null
  const latestItem           = preparedActionsStore?.items?.[0] ?? null

  // Derive threads: backend prepared_actions preferred, Zustand fallback.
  // A prepared action is NOT a running execution — status is always 'prepared'.
  const threads: OrchestrationThread[] = useBackendSnapshot
    ? orchestrationData!.prepared_actions.map((a) => ({
        id:            a.id,
        label:         a.intent ?? a.domain ?? 'Prepared action',
        status:        'prepared' as const,
        assignedArm:   a.domain ?? undefined,
        executionStatus: 'unavailable' as const,
      }))
    : (preparedActionsStore?.items ?? []).map((item) => ({
        id:            item.queue_entry_id ?? item.prepared_action_id ?? item.proposal_id ?? 'unknown',
        label:         (item.user_intent?.slice(0, 70) ?? item.requested_action ?? 'Unknown mission intent'),
        status:        'prepared' as const,
        assignedArm:   item.domain ?? undefined,
        lastEvent:     item.preparation_id ? `preparation:${item.preparation_id.slice(0, 12)}` : undefined,
        executionStatus: 'unavailable' as const,
      }))

  const preparedCount = useBackendSnapshot
    ? orchestrationData!.prepared_actions.length
    : (preparedActionsStore?.count ?? 0)

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-teal-400/20 bg-teal-400/5 p-4">
        <p className="text-xs font-mono text-teal-400 mb-1">Orchestration View — ALPHA</p>
        <p className="text-[10px] font-mono text-tx-muted">
          Live-feeling read-model of orchestration state. Data sourced from the prepared action queue. No fabricated activity.
          Execution remains closed.
        </p>
      </div>

      {/* Runtime Snapshot */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">Runtime Snapshot</p>
        <div className="grid grid-cols-3 gap-3">
          <SituationTile
            label="Operational Mode"
            value={operationalMode}
            accent={operationalMode === 'NORMAL'}
            warn={operationalMode !== 'NORMAL' && operationalMode !== 'UNKNOWN'}
          />
          <SituationTile
            label="API"
            value={`${apiStatus} / ${webhookStatus}`}
            accent={apiStatus === 'ok' && webhookStatus === 'ok'}
          />
          <SituationTile
            label="Prepared Actions"
            value={orchestrationData === null ? '…' : String(preparedCount)}
            warn={preparedCount > 0}
            accent={orchestrationData !== null && preparedCount === 0}
          />
        </div>
        {/* Execution invariants — always surfaced */}
        <div className="mt-2 flex flex-wrap items-center gap-3 text-[9px] font-mono text-tx-muted">
          <span>live_execution: {String(liveExecution)}</span>
          <span>runner_reachable_from_ui: false</span>
          <span>source: {orchestrationSource}</span>
        </div>
      </section>

      {/* Queue Snapshot */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">Queue Snapshot</p>
        <div className="grid grid-cols-2 gap-3 mb-2">
          <SituationTile
            label="Prepared Actions"
            value={orchestrationData === null ? '…' : String(preparedCount)}
            warn={preparedCount > 0}
            accent={orchestrationData !== null && preparedCount === 0}
          />
          <SituationTile
            label="Confirm Pending"
            value={!confirmPendingLoaded ? '…' : String(confirmCount)}
            warn={confirmCount > 0}
            accent={confirmPendingLoaded && confirmCount === 0}
          />
        </div>
        {preparedCount > 0 ? (
          <div className="rounded-lg border border-warn/30 bg-warn/5 p-3">
            <p className="text-[10px] font-mono text-warn">
              {preparedCount} prepared action{preparedCount !== 1 ? 's' : ''} waiting for manual review.
              Each action includes a read-only authority timeline showing all 11 stages.
              Open Confirm Queue to inspect prepared action details.
              Execution remains closed.
            </p>
          </div>
        ) : (
          <PostureRow label="Queue Status" value="Clear" tone="ok" note="No prepared actions pending." />
        )}

        {/* Confirm Pending Items — read-only observability, no execution affordance */}
        {useBackendSnapshot && orchestrationData!.confirm_pending.length > 0 && (
          <div className="space-y-2 mt-3">
            <p className="text-[9px] font-mono text-tx-muted uppercase tracking-widest">Awaiting Confirmation</p>
            {orchestrationData!.confirm_pending.map((item) => (
              <div
                key={item.id}
                className="rounded-lg border border-orange-400/20 bg-orange-400/5 p-3"
                data-testid="confirm-pending-item"
              >
                <div className="flex items-start justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] font-mono text-orange-400 uppercase">awaiting_confirmation</span>
                    {item.domain && (
                      <span className="text-[9px] font-mono text-tx-muted">· {item.domain}</span>
                    )}
                  </div>
                  <span className="text-[9px] font-mono text-tx-muted/60 shrink-0 tabular-nums">
                    {item.id.slice(0, 12)}…
                  </span>
                </div>
                {item.intent && (
                  <p className="text-[10px] font-mono text-tx-secondary mb-1 line-clamp-2">{item.intent}</p>
                )}
                {item.requested_action && (
                  <p className="text-[9px] font-mono text-tx-muted">{item.requested_action}</p>
                )}
                <div className="mt-2 flex gap-3 text-[9px] font-mono text-tx-muted border-t border-os-border/40 pt-1.5">
                  <span>execution_allowed: false</span>
                  <span>can_execute_now: false</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Authority Posture */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">Authority Posture</p>
        <div className="space-y-2">
          <PostureRow
            label="Police Gate"
            value="Fail-closed"
            tone="ok"
            note="8-step enforcement: token present, registered, not expired, not consumed, binding match, authorized plan, delegated seat valid, capability in scope."
          />
          <PostureRow
            label="Governed Execution"
            value="Closed"
            tone="muted"
            note="Full chain required: PolicyDecision → CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate."
          />
        </div>
      </section>

      {/* Thread cards */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">Orchestration Threads</p>
        {threads.length === 0 ? (
          <div className="rounded-lg border border-os-border bg-os-surface p-4">
            <p className="text-[10px] font-mono text-tx-muted">
              No active orchestration threads. Create a plan_request via MSO to begin a governed workflow.
            </p>
            <p className="text-[9px] font-mono text-tx-muted/70 mt-1">
              executionStatus: unavailable — execution is closed until full authority chain is established.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {threads.map((thread) => (
              <div key={thread.id} className="rounded-lg border border-os-border bg-os-surface p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-mono text-tx-primary truncate">{thread.label}</p>
                    <div className="flex flex-wrap items-center gap-2 mt-1">
                      {thread.assignedArm && (
                        <span className="text-[9px] font-mono text-tx-muted">arm: {thread.assignedArm}</span>
                      )}
                      {thread.lastEvent && (
                        <span className="text-[9px] font-mono text-tx-muted truncate">{thread.lastEvent}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <LifecycleBadge state={thread.status} />
                    <ExecStatusBadge status={thread.executionStatus ?? 'unavailable'} />
                  </div>
                </div>
                <p className="text-[9px] font-mono text-tx-muted/60 mt-1.5">
                  id: {thread.id.length > 16 ? thread.id.slice(0, 16) + '…' : thread.id}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Operational chain */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">Operational Chain (Latest Thread)</p>
        <MissionControlChainView latestItem={latestItem} totalCount={preparedCount} />
      </section>
    </div>
  )
}

// ── Space 5: Outcome + Authority Trace ────────────────────────────────────────

const AUTHORITY_TRACE_STAGES = [
  {
    label: 'MSO Kernel',
    note:  'Cognitive control layer. Coordinates only — never executes. mso_direct surface.',
    status: 'active' as const,
  },
  {
    label: 'Intent Contract',
    note:  'user_intent captured, classified, and mapped to domain/action.',
    status: 'active' as const,
  },
  {
    label: 'Policy',
    note:  'PolicyDecision required. ALLOW / BLOCK / REQUIRE_CONFIRMATION / ESCALATE.',
    status: 'pending' as const,
  },
  {
    label: 'Governance',
    note:  'GovernanceDecision: operational mode checked, restriction enforced.',
    status: 'pending' as const,
  },
  {
    label: 'CapabilityToken',
    note:  'Issued only after valid PolicyDecision and GovernanceDecision.',
    status: 'pending' as const,
  },
  {
    label: 'Police Gate',
    note:  '8-step fail-closed enforcement: token present, registered, not expired, not consumed, binding match, authorized plan, delegated seat valid, capability in scope.',
    status: 'pending' as const,
  },
  {
    label: 'AuthorityArtifact',
    note:  'V2 artifact with OperationBinding + AuthorizedPlan. Created after Police gate passes.',
    status: 'pending' as const,
  },
  {
    label: 'Runner',
    note:  'Execution surface. Receives AuthorityArtifact only. Not reachable from UI directly.',
    status: 'closed' as const,
  },
  {
    label: 'Outcome',
    note:  'Execution result and observability record. Visible below via outcome status endpoint.',
    status: 'closed' as const,
  },
] as const

type TraceStageStatus = 'active' | 'pending' | 'closed'

function AuthorityTraceStage({
  label,
  note,
  status,
  last,
}: {
  label: string
  note: string
  status: TraceStageStatus
  last: boolean
}) {
  const dotClass =
    status === 'active'  ? 'bg-ok' :
    status === 'closed'  ? 'bg-os-border' :
    'bg-tx-muted/30'

  const labelClass =
    status === 'active' ? 'text-tx-primary' :
    status === 'closed' ? 'text-tx-muted/50' :
    'text-tx-muted'

  const badgeClass =
    status === 'active' ? 'text-ok border-ok/30 bg-ok/10' :
    status === 'closed' ? 'text-tx-muted/50 border-os-border/50 bg-os-base' :
    'text-tx-muted border-os-border/50 bg-os-base'

  return (
    <div className="flex items-start gap-2">
      <div className="flex flex-col items-center flex-shrink-0" style={{ minWidth: '10px' }}>
        <div className={`w-2 h-2 rounded-full mt-0.5 ${dotClass}`} />
        {!last && <div className="w-px flex-1 bg-os-border mt-0.5" style={{ minHeight: '10px' }} />}
      </div>
      <div className="flex-1 flex items-start justify-between gap-2 pb-1.5 min-w-0">
        <div className="min-w-0">
          <p className={`text-[10px] font-mono leading-tight ${labelClass}`}>{label}</p>
          <p className="text-[9px] font-mono text-tx-muted/60 leading-tight mt-0.5">{note}</p>
        </div>
        <span className={`flex-shrink-0 px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-wider border mt-0.5 ${badgeClass}`}>
          {status}
        </span>
      </div>
    </div>
  )
}

function OutcomeTraceSpace() {
  // Backend truth trace snapshot (preferred source)
  const traceData = useMCTraceQuery()
  // MC status outcome summary (read-model, enriched by build_mission_control_status)
  const mcStatus  = useMCStatusQuery()

  // Map backend MCTraceStage.state → local TraceStageStatus.
  // 'architectural' and 'unavailable' both map to 'closed' (architecturally closed to UI).
  // This is NOT a live runtime trace unless backend explicitly says trace_mode='live'.
  const mapTraceState = (state: string): TraceStageStatus => {
    if (state === 'available') return 'active'
    if (state === 'pending')   return 'pending'
    if (state === 'blocked')   return 'pending'
    return 'closed'  // 'unavailable' | 'architectural'
  }

  // Only use backend trace when ok and explicitly mode=snapshot. Never infer live execution.
  const useBackendTrace = traceData?.ok === true && traceData.trace_mode === 'snapshot'
  const traceModeLabel  = useBackendTrace
    ? 'snapshot · source: backend_read_model'
    : traceData?.ok === false
      ? 'unavailable · showing derived fallback'
      : 'loading…'

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-rose-400/20 bg-rose-400/5 p-4">
        <p className="text-xs font-mono text-rose-400 mb-1">Outcome + Authority Trace — ALPHA</p>
        <p className="text-[10px] font-mono text-tx-muted">
          Full authority chain trace (9 stages) and execution outcome. Outcome data from real backend when available;
          reported as unavailable/partial otherwise. No fabrication.
        </p>
      </div>

      {/* Authority trace */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">Authority Chain Trace</p>
        <div className="rounded-lg border border-os-border bg-os-surface p-4">
          {/* trace_mode annotation — always visible, never omitted */}
          <p className="text-[9px] font-mono text-tx-muted mb-3" data-testid="trace-mode-label">
            trace_mode: {traceModeLabel}
          </p>
          <div className="space-y-0">
            {useBackendTrace
              ? traceData!.stages.map((stage, i) => (
                  <AuthorityTraceStage
                    key={stage.id}
                    label={stage.label}
                    note={stage.evidence_ref ?? ''}
                    status={mapTraceState(stage.state)}
                    last={i === traceData!.stages.length - 1}
                  />
                ))
              : AUTHORITY_TRACE_STAGES.map((stage, i) => (
                  <AuthorityTraceStage
                    key={stage.label}
                    label={stage.label}
                    note={stage.note}
                    status={stage.status}
                    last={i === AUTHORITY_TRACE_STAGES.length - 1}
                  />
                ))
            }
          </div>
          <p className="text-[9px] font-mono text-tx-muted mt-3 pt-2 border-t border-os-border/60">
            Stages marked &quot;active&quot; reflect the current MSO session invariants.
            Stages marked &quot;pending&quot; require human confirmation and the full authority chain before progressing.
            Stages marked &quot;closed&quot; are architecturally closed to UI.
          </p>
        </div>
      </section>

      {/* Outcome summary — sourced from MC status read model */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">Outcome Summary</p>
        <div className="rounded-lg border border-os-border bg-os-surface p-4 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono text-tx-muted">status</span>
            <span
              className="text-[10px] font-mono text-tx-primary"
              data-testid="outcome-status-label"
            >
              {mcStatus === null ? '…' : (mcStatus.outcome?.status ?? 'unavailable')}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono text-tx-muted">execution_closed</span>
            <span
              className="text-[10px] font-mono text-tx-primary"
              data-testid="outcome-execution-closed"
            >
              {mcStatus === null ? '…' : String(mcStatus.outcome?.execution_closed ?? true)}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono text-tx-muted">found</span>
            <span className="text-[10px] font-mono text-tx-primary">
              {mcStatus === null ? '…' : String(mcStatus.outcome?.found ?? false)}
            </span>
          </div>
          {mcStatus?.outcome?.sources_checked && mcStatus.outcome.sources_checked.length > 0 && (
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono text-tx-muted">sources_checked</span>
              <span className="text-[10px] font-mono text-tx-primary">
                {mcStatus.outcome.sources_checked.join(', ')}
              </span>
            </div>
          )}
          <p className="text-[9px] font-mono text-tx-muted pt-1 border-t border-os-border/60">
            source: backend_read_model · execution_closed is always true
          </p>
        </div>
      </section>

      {/* Outcome status — detailed polling panel */}
      <section>
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">Execution Outcome</p>
        <OutcomeStatusPanel />
      </section>
    </div>
  )
}

// ── Tab bar ───────────────────────────────────────────────────────────────────

function TabBar({ active, onChange }: { active: MCTab; onChange: (tab: MCTab) => void }) {
  return (
    <div className="flex gap-1 border-b border-os-border pb-0 mb-0 overflow-x-auto flex-shrink-0">
      {TAB_CONFIG.map((tab) => {
        const isActive = active === tab.id
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            className={`
              flex flex-col items-start px-3 py-2.5 text-left whitespace-nowrap border-b-2 transition-all duration-150
              ${isActive
                ? `${tab.color} border-current`
                : 'text-tx-muted border-transparent hover:text-tx-secondary'
              }
            `}
          >
            <span className="text-xs font-mono font-medium">{tab.label}</span>
            <span className="text-[9px] font-mono opacity-60">{tab.sublabel}</span>
          </button>
        )
      })}
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function MissionControlView() {
  useSeatProviderPolling()
  usePreparedActionsPolling()
  useConfirmPendingPolling()
  useAuthorityStatusPolling()

  const [activeTab, setActiveTab] = useState<MCTab>('planner')

  // Backend truth — aggregated MC status for header badge
  const mcStatus = useMCStatusQuery()
  const mcState  = mcStatus?.mission_control.state ?? null

  const mcEntity = getEntity('mission_control')

  const { operationalMode } = useUIStore((s) => s.systemData)
  const preparedActions = usePreparedActionsStore((s) => s.preparedActions)
  const confirmPending  = useConfirmPendingStore((s) => s.confirmPending)
  const authorityStatus = useAuthorityStatusStore((s) => s.authorityStatus)

  // Prefer backend truth from mcStatus (already polled above); fall back to Zustand while loading
  const preparedCount = mcStatus !== null
    ? mcStatus.queues.prepared_actions_count
    : (preparedActions?.count ?? 0)
  const confirmCount  = mcStatus !== null
    ? mcStatus.queues.confirm_pending_count
    : (confirmPending?.pending_count ?? 0)
  const modeOk        = operationalMode === 'NORMAL'

  return (
    <div className="h-full flex flex-col bg-os-base overflow-hidden">

      {/* Header */}
      <div className="px-6 pt-5 pb-0 flex-shrink-0 border-b border-os-border">
        <div className="mb-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest">
                Mission Control · Orchestration Cockpit
              </p>
              <p className="text-xs font-mono text-tx-secondary mt-0.5">
                Visual cockpit for the full mission lifecycle. Planning → MSO → Governed Preparation → Confirmation → Orchestration → Outcome.
              </p>
            </div>
            {/* Status strip */}
            <div className="flex items-center gap-2 flex-shrink-0 flex-wrap justify-end">
              {/* Backend MC state badge — sourced from backend_read_model truth contract */}
              {mcState !== null && (
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase border ${
                    mcState === 'available' ? 'text-ok border-ok/30 bg-ok/10' :
                    mcState === 'partial'   ? 'text-warn border-warn/30 bg-warn/10' :
                    'text-tx-muted border-os-border bg-os-base'
                  }`}
                  data-testid="mc-state-badge"
                >
                  mc:{mcState}
                </span>
              )}
              <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase border ${modeOk ? 'text-ok border-ok/30 bg-ok/10' : 'text-warn border-warn/30 bg-warn/10'}`}>
                {operationalMode}
              </span>
              {preparedCount > 0 && (
                <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase border text-warn border-warn/30 bg-warn/10">
                  {preparedCount} prepared
                </span>
              )}
              {confirmCount > 0 && (
                <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase border text-orange-400 border-orange-400/30 bg-orange-400/10">
                  {confirmCount} pending
                </span>
              )}
              {authorityStatus?.counts && (
                <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase border text-tx-muted border-os-border bg-os-base">
                  auth: {authorityStatus.counts.allow}↑ {authorityStatus.counts.deny}↓
                </span>
              )}
            </div>
          </div>
          {mcEntity && (
            <p className="text-[9px] font-mono text-tx-muted mt-1 tracking-wider">
              entity:{mcEntity.id} · {mcEntity.execution_policy} · Read-only
            </p>
          )}
        </div>

        <TabBar active={activeTab} onChange={setActiveTab} />
      </div>

      {/* Lifecycle progress hint */}
      <div className="px-6 py-2 flex items-center gap-1 flex-shrink-0 border-b border-os-border/40 overflow-x-auto">
        {(['planner', 'mso', 'arms', 'orchestration', 'outcome'] as MCTab[]).map((tab, i) => {
          const cfg = TAB_CONFIG.find(t => t.id === tab)!
          const isActive = activeTab === tab
          return (
            <div key={tab} className="flex items-center gap-1 flex-shrink-0">
              <button
                onClick={() => setActiveTab(tab)}
                className={`text-[9px] font-mono px-1.5 py-0.5 rounded transition-colors ${isActive ? cfg.color : 'text-tx-muted hover:text-tx-secondary'}`}
              >
                {cfg.label}
              </button>
              {i < 4 && <span className="text-[9px] font-mono text-tx-muted/30">→</span>}
            </div>
          )
        })}
      </div>

      {/* Space content */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto p-6">
          {activeTab === 'planner'       && <PlannerSpace />}
          {activeTab === 'mso'           && <MSOEscalationSpace />}
          {activeTab === 'arms'          && <ArmsAvailabilitySpace />}
          {activeTab === 'orchestration' && <OrchestrationViewSpace />}
          {activeTab === 'outcome'       && <OutcomeTraceSpace />}
        </div>
      </div>

    </div>
  )
}
