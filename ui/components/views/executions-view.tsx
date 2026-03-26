'use client'

import { useEffect, useRef, useState } from 'react'
import { useUIStore }  from '@/stores/ui-store'
import { StatusBadge } from '@/components/shared/status-badge'
import { Panel }       from '@/components/shared/panel'
import {
  getExecutions,
  getExecutionDetail,
  reviewExecution,
  rerunExecution,
} from '@/lib/api'
import type {
  ExecutionListItem,
  ExecutionDetail,
  ReviewAction,
  FinalStatus,
  HealthStatus,
  RerunResponse,
} from '@/lib/types'

// ── Status helpers ────────────────────────────────────────────────────────────

function execStatusToBadge(s: FinalStatus | string): HealthStatus | 'idle' {
  switch (s) {
    case 'success':
    case 'approved':  return 'ok'
    case 'failed':
    case 'rejected':  return 'down'
    case 'needs_review': return 'warn'
    default:          return 'idle'
  }
}

function reviewActionToBadge(a: ReviewAction): HealthStatus | 'idle' {
  switch (a) {
    case 'approved': return 'ok'
    case 'rejected': return 'down'
    case 'rerun':    return 'warn'
  }
}

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtTime(iso: string) {
  try {
    return new Date(iso).toLocaleString('es', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

function fmtDuration(start: string, end: string | null) {
  if (!end) return 'running…'
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (ms < 1000) return ms + 'ms'
  if (ms < 60000) return (ms / 1000).toFixed(1) + 's'
  return Math.round(ms / 60000) + 'm ' + Math.round((ms % 60000) / 1000) + 's'
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-os-elevated rounded ${className}`} />
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface ReviewOverride {
  action: ReviewAction
  at: string
  comment: string
}

type ListState =
  | { phase: 'loading' }
  | { phase: 'loaded'; items: ExecutionListItem[] }
  | { phase: 'empty' }
  | { phase: 'error'; message: string }

type DetailState =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'loaded'; detail: ExecutionDetail }
  | { phase: 'error'; message: string }

// ── ExecListItem ──────────────────────────────────────────────────────────────

function ExecListItem({
  exec,
  isSelected,
  reviewOverride,
}: {
  exec: ExecutionListItem
  isSelected: boolean
  reviewOverride?: ReviewOverride
}) {
  const { setSelectedExecution } = useUIStore()

  return (
    <button
      onClick={() => setSelectedExecution(exec.execution_id)}
      className={`
        w-full text-left px-3 py-2.5 border-b border-os-border last:border-b-0
        transition-colors duration-100
        ${isSelected
          ? 'bg-accent/10 border-l-2 border-l-accent'
          : 'hover:bg-os-elevated border-l-2 border-l-transparent'
        }
      `}
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <span className={`text-xs font-mono truncate max-w-[140px] ${isSelected ? 'text-tx-primary' : 'text-tx-secondary'}`}>
          {exec.execution_id}
        </span>
        <div className="flex items-center gap-1 flex-shrink-0">
          {reviewOverride && (
            <StatusBadge
              status={reviewActionToBadge(reviewOverride.action)}
              label={reviewOverride.action}
              dot
            />
          )}
          {!reviewOverride && (
            <StatusBadge status={execStatusToBadge(exec.final_status)} label={exec.final_status} dot />
          )}
          {reviewOverride && (
            <StatusBadge status={execStatusToBadge(exec.final_status)} label={exec.final_status} />
          )}
        </div>
      </div>
      {exec.summary && (
        <p className="text-[11px] font-mono text-tx-muted line-clamp-1 mb-1">{exec.summary}</p>
      )}
      <div className="flex items-center gap-2 text-[10px] font-mono text-tx-muted">
        <span>{exec.source ?? 'unknown'}</span>
        <span>·</span>
        <span>{fmtTime(exec.timestamp)}</span>
      </div>
    </button>
  )
}

// ── ExecList ──────────────────────────────────────────────────────────────────

function ExecList({
  state,
  selectedId,
  reviewOverrides,
}: {
  state: ListState
  selectedId: string | null
  reviewOverrides: Record<string, ReviewOverride>
}) {
  if (state.phase === 'loading') {
    return (
      <div className="p-3 space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="space-y-1.5">
            <Skeleton className="h-3 w-3/4" />
            <Skeleton className="h-2.5 w-full" />
            <Skeleton className="h-2 w-1/2" />
          </div>
        ))}
      </div>
    )
  }
  if (state.phase === 'error') {
    return (
      <div className="p-4 space-y-1">
        <p className="text-xs font-mono text-err">Failed to load executions</p>
        <p className="text-[10px] font-mono text-tx-muted">{state.message}</p>
      </div>
    )
  }
  if (state.phase === 'empty') {
    return (
      <div className="flex flex-col items-center justify-center flex-1 py-12 px-4 text-center">
        <p className="text-xs font-mono text-tx-secondary mb-1">No executions found</p>
        <p className="text-[10px] font-mono text-tx-muted">Run a CODE command to see executions here.</p>
      </div>
    )
  }

  return (
    <>
      {state.items.map(exec => (
        <ExecListItem
          key={exec.execution_id}
          exec={exec}
          isSelected={exec.execution_id === selectedId}
          reviewOverride={reviewOverrides[exec.execution_id]}
        />
      ))}
    </>
  )
}

// ── Review panel ──────────────────────────────────────────────────────────────

interface ReviewPanelProps {
  detail: ExecutionDetail
  onReviewSubmit: (action: ReviewAction, comment: string) => Promise<void>
  onRerunLaunch: () => Promise<void>
}

function ReviewPanel({ detail, onReviewSubmit, onRerunLaunch }: ReviewPanelProps) {
  const [comment, setComment]               = useState('')
  const [submitting, setSubmitting]         = useState<ReviewAction | null>(null)
  const [submitError, setSubmitError]       = useState<string | null>(null)
  const [rerunning, setRerunning]           = useState(false)
  const [rerunError, setRerunError]         = useState<string | null>(null)
  const [confirmReject, setConfirmReject]   = useState(false)

  // Reset form when detail changes (different execution selected)
  useEffect(() => {
    setComment('')
    setSubmitting(null)
    setSubmitError(null)
    setRerunning(false)
    setRerunError(null)
    setConfirmReject(false)
  }, [detail.metadata.execution_id])

  const reviewAction = detail.review_action
  const needsReview  = detail.metadata.final_status === 'needs_review'

  // Only show panel for needs_review executions
  if (!needsReview) return null

  async function submit(action: ReviewAction) {
    setSubmitting(action)
    setSubmitError(null)
    setConfirmReject(false)
    try {
      await onReviewSubmit(action, comment)
      setComment('')
    } catch (err) {
      setSubmitError(String(err))
    } finally {
      setSubmitting(null)
    }
  }

  async function launchRerun() {
    setRerunning(true)
    setRerunError(null)
    try {
      await onRerunLaunch()
    } catch (err) {
      setRerunError(String(err))
    } finally {
      setRerunning(false)
    }
  }

  const busy = submitting !== null || rerunning

  return (
    <div className="flex-shrink-0 border-t border-os-border bg-os-surface">
      {/* Already reviewed — show banner */}
      {reviewAction ? (
        <div className="px-4 py-3 space-y-2">
          <div className="flex items-center gap-2">
            <StatusBadge
              status={reviewActionToBadge(reviewAction)}
              label={
                reviewAction === 'approved' ? 'Approved' :
                reviewAction === 'rejected' ? 'Rejected' :
                'Marked for rerun'
              }
              dot size="md"
            />
            {detail.reviewed_at && (
              <span className="text-[10px] font-mono text-tx-muted">
                {fmtTime(detail.reviewed_at)}
              </span>
            )}
          </div>
          {detail.review_comment && (
            <p className="text-[11px] font-mono text-tx-muted italic">
              &ldquo;{detail.review_comment}&rdquo;
            </p>
          )}
          {/* Launch rerun button — only if review_action=rerun AND has_snapshot */}
          {reviewAction === 'rerun' && detail.has_snapshot && (
            <div className="pt-1">
              <button
                onClick={launchRerun}
                disabled={rerunning}
                className="
                  px-3 py-1.5 text-xs font-mono rounded border
                  bg-accent/10 border-accent/30 text-accent
                  hover:bg-accent/20 transition-colors
                  disabled:opacity-50 disabled:cursor-not-allowed
                "
              >
                {rerunning ? 'Launching…' : 'Launch rerun'}
              </button>
              {rerunError && (
                <p className="mt-1 text-[10px] font-mono text-err">{rerunError}</p>
              )}
            </div>
          )}
          {reviewAction === 'rerun' && !detail.has_snapshot && (
            <p className="text-[10px] font-mono text-tx-muted">
              No stored snapshot — rerun not available for this execution.
            </p>
          )}
        </div>
      ) : (
        /* Not yet reviewed — show action form */
        <div className="px-4 py-3 space-y-2.5">
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-wider">
            Review
          </p>

          <textarea
            value={comment}
            onChange={e => setComment(e.target.value)}
            placeholder="Optional comment (max 500 chars)…"
            maxLength={500}
            rows={2}
            disabled={busy}
            className="
              w-full bg-os-elevated border border-os-border rounded
              px-3 py-2 text-xs font-mono text-tx-primary
              placeholder:text-tx-muted resize-none outline-none
              focus:border-accent/50 transition-colors
              disabled:opacity-50 disabled:cursor-not-allowed
            "
          />

          {submitError && (
            <p className="text-[10px] font-mono text-err">{submitError}</p>
          )}

          <div className="flex items-center gap-2">
            {/* Approve */}
            <button
              onClick={() => submit('approved')}
              disabled={busy}
              className="
                px-3 py-1.5 text-xs font-mono rounded border
                bg-ok/10 border-ok/30 text-ok
                hover:bg-ok/20 transition-colors
                disabled:opacity-50 disabled:cursor-not-allowed
              "
            >
              {submitting === 'approved' ? 'Approving…' : 'Approve'}
            </button>

            {/* Reject — 2-step confirmation */}
            {!confirmReject ? (
              <button
                onClick={() => setConfirmReject(true)}
                disabled={busy}
                className="
                  px-3 py-1.5 text-xs font-mono rounded border
                  bg-err/10 border-err/30 text-err
                  hover:bg-err/20 transition-colors
                  disabled:opacity-50 disabled:cursor-not-allowed
                "
              >
                Reject
              </button>
            ) : (
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => submit('rejected')}
                  disabled={busy}
                  className="
                    px-3 py-1.5 text-xs font-mono rounded border
                    bg-err border-err text-white
                    hover:bg-err/80 transition-colors
                    disabled:opacity-50 disabled:cursor-not-allowed
                  "
                >
                  {submitting === 'rejected' ? 'Rejecting…' : 'Confirm reject'}
                </button>
                <button
                  onClick={() => setConfirmReject(false)}
                  disabled={busy}
                  className="
                    px-2.5 py-1.5 text-xs font-mono rounded border
                    border-os-border text-tx-muted
                    hover:text-tx-secondary transition-colors
                    disabled:opacity-50
                  "
                >
                  Cancel
                </button>
              </div>
            )}

            {/* Rerun later */}
            <button
              onClick={() => submit('rerun')}
              disabled={busy}
              className="
                px-3 py-1.5 text-xs font-mono rounded border
                border-os-border text-tx-secondary
                hover:bg-os-elevated hover:text-tx-primary transition-colors
                disabled:opacity-50 disabled:cursor-not-allowed
              "
            >
              {submitting === 'rerun' ? 'Saving…' : 'Rerun later'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Tab components ────────────────────────────────────────────────────────────

type TabId = 'summary' | 'logs' | 'changes' | 'validation'

const TABS: { id: TabId; label: string }[] = [
  { id: 'summary',    label: 'Summary' },
  { id: 'logs',       label: 'Logs' },
  { id: 'changes',    label: 'Changes' },
  { id: 'validation', label: 'Validation' },
]

function TabSummary({ detail }: { detail: ExecutionDetail }) {
  const m = detail.metadata
  const rows: [string, string | null | undefined][] = [
    ['ID',          m.execution_id],
    ['Status',      m.final_status],
    ['Phase',       m.status],
    ['Started',     m.started_at ? fmtTime(m.started_at) : null],
    ['Finished',    m.finished_at ? fmtTime(m.finished_at) : null],
    ['Duration',    m.started_at ? fmtDuration(m.started_at, m.finished_at) : null],
    ['Repo',        m.repo_path],
    ['Base commit', m.base_commit],
    ['Rerun of',    detail.rerun_of],
  ]

  return (
    <div className="space-y-4">
      {m.summary && (
        <Panel title="Summary">
          <p className="text-xs font-mono text-tx-secondary leading-relaxed">{m.summary}</p>
        </Panel>
      )}
      {m.error && (
        <Panel title="Error">
          <p className="text-xs font-mono text-err leading-relaxed whitespace-pre-wrap">{m.error}</p>
        </Panel>
      )}
      <Panel title="Metadata">
        <dl className="space-y-2">
          {rows.filter(([, v]) => v != null && v !== '').map(([k, v]) => (
            <div key={k} className="flex gap-3 text-xs font-mono">
              <dt className="text-tx-muted w-24 flex-shrink-0">{k}</dt>
              <dd className="text-tx-primary break-all">{v}</dd>
            </div>
          ))}
        </dl>
      </Panel>
    </div>
  )
}

function TabLogs({ detail }: { detail: ExecutionDetail }) {
  const lines = detail.log_content?.split('\n') ?? []
  if (!detail.log_content) {
    return (
      <Panel title="Logs">
        <p className="text-xs font-mono text-tx-muted">
          {detail.log_path
            ? `No log content returned. Path: ${detail.log_path}`
            : 'No log available.'}
        </p>
      </Panel>
    )
  }
  return (
    <Panel title={`Logs · ${lines.length} lines`} noPad>
      <div className="px-4 py-3 overflow-x-auto max-h-[50vh] overflow-y-auto">
        {lines.map((line, i) => (
          <div key={i} className="flex gap-2 text-[11px] font-mono whitespace-pre">
            <span className="text-os-border-hi select-none w-6 text-right flex-shrink-0">{i + 1}</span>
            <span className="text-tx-muted">{line}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function TabChanges({ detail }: { detail: ExecutionDetail }) {
  const files =
    detail.metadata.modified_files?.length
      ? detail.metadata.modified_files
      : detail.report?.modified_files ?? []

  if (files.length === 0) {
    return (
      <Panel title="Changes">
        <p className="text-xs font-mono text-tx-muted">No recorded changes.</p>
      </Panel>
    )
  }
  return (
    <Panel title={`Modified files · ${files.length}`} noPad>
      <div className="divide-y divide-os-border">
        {files.map(f => (
          <div key={f} className="flex items-center gap-2 px-4 py-2.5">
            <span className="text-ok text-[10px] font-mono select-none">M</span>
            <span className="text-xs font-mono text-tx-secondary break-all">{f}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function TabValidation({ detail }: { detail: ExecutionDetail }) {
  const vr = detail.metadata.validation_result ?? detail.report?.validation_result ?? null
  const tr = detail.metadata.test_result ?? detail.report?.test_result ?? null

  if (!vr && !tr) {
    return (
      <Panel title="Validation">
        <p className="text-xs font-mono text-tx-muted">No validation data.</p>
      </Panel>
    )
  }
  return (
    <div className="space-y-4">
      {vr && (
        <Panel title="Validation result">
          <div className="space-y-3">
            <StatusBadge status={execStatusToBadge(vr.final_status)} label={vr.final_status} dot size="md" />
            {vr.validation_summary && (
              <p className="text-xs font-mono text-tx-secondary leading-relaxed">{vr.validation_summary}</p>
            )}
            {vr.reasons.length > 0 && (
              <ul className="space-y-1 text-xs font-mono text-tx-muted list-none">
                {vr.reasons.map((r, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="select-none">·</span>{r}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Panel>
      )}
      {tr && (
        <Panel title="Test result">
          <div className="flex items-center gap-4 text-xs font-mono">
            <span className="text-ok">{tr.passed} passed</span>
            {tr.failed > 0 && <span className="text-err">{tr.failed} failed</span>}
          </div>
        </Panel>
      )}
    </div>
  )
}

// ── ExecDetail ────────────────────────────────────────────────────────────────

interface ExecDetailProps {
  state: DetailState
  onReviewComplete: (id: string, override: ReviewOverride) => void
  onRerunComplete: (result: RerunResponse) => void
}

function ExecDetail({ state, onReviewComplete, onRerunComplete }: ExecDetailProps) {
  const [activeTab, setActiveTab] = useState<TabId>('summary')

  useEffect(() => {
    if (state.phase === 'loaded') setActiveTab('summary')
  }, [state.phase])

  if (state.phase === 'idle') {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-xs font-mono text-tx-muted">Select an execution to inspect</p>
      </div>
    )
  }
  if (state.phase === 'loading') {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-4 w-32" />
        <div className="space-y-2 mt-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-3 w-full" />
          ))}
        </div>
      </div>
    )
  }
  if (state.phase === 'error') {
    return (
      <div className="p-6 space-y-2">
        <p className="text-xs font-mono text-err">Failed to load execution detail</p>
        <p className="text-[10px] font-mono text-tx-muted">{state.message}</p>
      </div>
    )
  }

  const { detail } = state

  async function handleReviewSubmit(action: ReviewAction, comment: string) {
    const res = await reviewExecution(detail.metadata.execution_id, action, comment)
    onReviewComplete(detail.metadata.execution_id, {
      action: res.review_action,
      at:     res.reviewed_at,
      comment: res.review_comment,
    })
  }

  async function handleRerunLaunch() {
    const res = await rerunExecution(detail.metadata.execution_id)
    onRerunComplete(res)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-os-border flex-shrink-0">
        <div className="flex items-center gap-2 mb-1">
          <StatusBadge
            status={execStatusToBadge(detail.metadata.final_status)}
            label={detail.metadata.final_status}
            dot size="md"
          />
          {detail.review_action && (
            <StatusBadge
              status={reviewActionToBadge(detail.review_action)}
              label={detail.review_action}
              dot
            />
          )}
          {detail.has_snapshot && !detail.review_action && (
            <span className="text-[9px] font-mono border border-os-border text-tx-muted px-1.5 py-0.5 rounded">
              rerunnable
            </span>
          )}
        </div>
        <p className="text-xs font-mono text-tx-secondary font-medium">
          {detail.metadata.execution_id}
        </p>
        {detail.metadata.summary && (
          <p className="text-[11px] font-mono text-tx-muted mt-0.5 line-clamp-2">
            {detail.metadata.summary}
          </p>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-os-border flex-shrink-0">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`
              px-4 py-2 text-[11px] font-mono border-b-2 transition-colors
              ${activeTab === tab.id
                ? 'border-accent text-accent'
                : 'border-transparent text-tx-muted hover:text-tx-secondary'
              }
            `}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Scrollable tab content */}
      <div className="flex-1 overflow-y-auto p-4 min-h-0">
        {activeTab === 'summary'    && <TabSummary    detail={detail} />}
        {activeTab === 'logs'       && <TabLogs       detail={detail} />}
        {activeTab === 'changes'    && <TabChanges    detail={detail} />}
        {activeTab === 'validation' && <TabValidation detail={detail} />}
      </div>

      {/* Review panel — sticky at bottom, outside scroll */}
      <ReviewPanel
        detail={detail}
        onReviewSubmit={handleReviewSubmit}
        onRerunLaunch={handleRerunLaunch}
      />
    </div>
  )
}

// ── Constants ─────────────────────────────────────────────────────────────────

/** final_status values that mean the execution is still in flight */
const ACTIVE_STATUSES = new Set<string>(['running', 'pending'])

/** Polling interval when active executions exist */
const POLL_MS = 15_000

// ── ExecutionsView ────────────────────────────────────────────────────────────

export function ExecutionsView() {
  const {
    selectedExecutionId, setSelectedExecution,
    pendingExecution, setPendingExecution,
  } = useUIStore()

  const [listState, setListState]             = useState<ListState>({ phase: 'loading' })
  const [detailState, setDetailState]         = useState<DetailState>({ phase: 'idle' })
  const [reviewOverrides, setReviewOverrides] = useState<Record<string, ReviewOverride>>({})
  const [isRefreshing, setIsRefreshing]       = useState(false)
  const [refreshError, setRefreshError]       = useState<string | null>(null)

  // ── Refs ────────────────────────────────────────────────────────────────────

  /** Prevents concurrent refresh calls */
  const refreshingRef = useRef(false)

  /** Mirrors selectedExecutionId so the polling callback always sees fresh value */
  const selectedIdRef = useRef<string | null>(selectedExecutionId)
  useEffect(() => { selectedIdRef.current = selectedExecutionId }, [selectedExecutionId])

  /** Mirrors the latest `refresh` function so the interval never goes stale */
  const refreshRef = useRef<() => Promise<void>>(async () => {})

  // ── Derived: are there active executions? ───────────────────────────────────

  const hasActive =
    listState.phase === 'loaded' &&
    listState.items.some(i => ACTIVE_STATUSES.has(i.final_status))

  // ── Refresh function ────────────────────────────────────────────────────────
  //
  // Rules:
  //  - guard against concurrent calls (refreshingRef)
  //  - does NOT set listState to 'loading' — keeps current data visible
  //  - only updates listState if initial load is already done
  //  - on list fetch success: silently refreshes detail IF selected exec is active
  //  - on error: preserves current data, surfaces a discrete error message

  async function refresh() {
    if (refreshingRef.current) return
    refreshingRef.current = true
    setIsRefreshing(true)
    setRefreshError(null)

    try {
      const items = await getExecutions()

      // Update list — but never interrupt the initial loading phase
      setListState(prev => {
        if (prev.phase === 'loading') return prev
        if (items.length === 0) return { phase: 'empty' }
        return { phase: 'loaded', items }
      })

      // Refresh detail only if the selected execution is still active in the fresh list
      const selId = selectedIdRef.current
      if (selId) {
        const freshItem = items.find(i => i.execution_id === selId)
        if (freshItem && ACTIVE_STATUSES.has(freshItem.final_status)) {
          const detail = await getExecutionDetail(selId)
          // Don't interrupt if a different load is in progress
          setDetailState(prev =>
            prev.phase === 'loading' ? prev : { phase: 'loaded', detail }
          )
        }
      }
    } catch (err) {
      // Keep existing data — just show a discrete error
      setRefreshError(String(err))
    } finally {
      refreshingRef.current = false
      setIsRefreshing(false)
    }
  }

  // Keep refreshRef up-to-date so the interval always calls the latest closure
  useEffect(() => { refreshRef.current = refresh })

  // ── Polling interval — only active when hasActive is true ──────────────────

  useEffect(() => {
    if (!hasActive) return
    const id = setInterval(() => { void refreshRef.current() }, POLL_MS)
    return () => clearInterval(id)
  }, [hasActive])

  // ── Consume pendingExecution from store (set by ActionsView after execute) ──

  useEffect(() => {
    if (!pendingExecution) return
    if (listState.phase !== 'loaded') return

    setListState(prev => {
      if (prev.phase !== 'loaded') return prev
      const alreadyIn = prev.items.some(i => i.execution_id === pendingExecution.execution_id)
      if (alreadyIn) return prev
      return { ...prev, items: [pendingExecution, ...prev.items] }
    })
    setPendingExecution(null)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listState.phase, pendingExecution])

  // ── Initial list load ───────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false
    async function load() {
      setListState({ phase: 'loading' })
      try {
        const items = await getExecutions()
        if (cancelled) return
        if (items.length === 0) {
          setListState({ phase: 'empty' })
        } else {
          setListState({ phase: 'loaded', items })
          if (!selectedExecutionId) setSelectedExecution(items[0].execution_id)
        }
      } catch (err) {
        if (cancelled) return
        setListState({ phase: 'error', message: String(err) })
      }
    }
    load()
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Load detail on selection change ────────────────────────────────────────

  useEffect(() => {
    if (!selectedExecutionId) {
      setDetailState({ phase: 'idle' })
      return
    }
    let cancelled = false
    async function load() {
      setDetailState({ phase: 'loading' })
      try {
        const detail = await getExecutionDetail(selectedExecutionId!)
        if (cancelled) return
        setDetailState({ phase: 'loaded', detail })
      } catch (err) {
        if (cancelled) return
        setDetailState({ phase: 'error', message: String(err) })
      }
    }
    load()
    return () => { cancelled = true }
  }, [selectedExecutionId])

  // ── Callbacks from ExecDetail ───────────────────────────────────────────────

  function handleReviewComplete(id: string, override: ReviewOverride) {
    setReviewOverrides(prev => ({ ...prev, [id]: override }))
    setDetailState(prev => {
      if (prev.phase !== 'loaded') return prev
      return {
        ...prev,
        detail: {
          ...prev.detail,
          review_action:  override.action,
          reviewed_at:    override.at,
          review_comment: override.comment,
        },
      }
    })
  }

  function handleRerunComplete(result: RerunResponse) {
    const newItem: ExecutionListItem = {
      execution_id:     result.execution_id,
      final_status:     result.final_status,
      summary:          result.summary,
      timestamp:        new Date().toISOString(),
      report_json_path: result.report_json_path,
      report_md_path:   result.report_md_path,
      done_path:        result.done_path,
      metadata_path:    null,
      source:           'rerun',
    }
    setListState(prev => {
      if (prev.phase !== 'loaded') return prev
      return { ...prev, items: [newItem, ...prev.items] }
    })
    setSelectedExecution(result.execution_id)
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  const itemCount = listState.phase === 'loaded' ? listState.items.length : null

  return (
    <div className="flex h-full">
      {/* LEFT — execution list */}
      <div className="w-72 flex-shrink-0 border-r border-os-border flex flex-col bg-os-base overflow-hidden">

        {/* List header: title + polling indicator + refresh button + count */}
        <div className="px-3 py-2 border-b border-os-border flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-wider">
              Executions
            </span>
            {/* Pulsing dot while polling is active and not currently refreshing */}
            {hasActive && !isRefreshing && (
              <span
                className="inline-block w-1.5 h-1.5 rounded-full bg-accent animate-pulse"
                title="Auto-polling every 15s"
              />
            )}
          </div>

          <div className="flex items-center gap-2.5">
            <button
              onClick={() => { void refresh() }}
              disabled={isRefreshing || listState.phase === 'loading'}
              className="
                text-[10px] font-mono text-tx-muted
                hover:text-tx-secondary transition-colors
                disabled:opacity-40 disabled:cursor-not-allowed
                flex items-center gap-1
              "
              title="Refresh list and detail"
            >
              <span className={isRefreshing ? 'animate-spin inline-block' : ''}>↺</span>
              {isRefreshing ? 'Refreshing…' : 'Refresh'}
            </button>
            {itemCount != null && (
              <span className="text-[10px] font-mono text-tx-muted">{itemCount} total</span>
            )}
          </div>
        </div>

        {/* Refresh error — discrete, below header, doesn't wipe list */}
        {refreshError && (
          <div className="px-3 py-1.5 border-b border-os-border bg-err/5 flex items-center justify-between">
            <p className="text-[10px] font-mono text-err truncate">
              Refresh failed: {refreshError}
            </p>
            <button
              onClick={() => setRefreshError(null)}
              className="text-[10px] font-mono text-tx-muted hover:text-tx-secondary ml-2 flex-shrink-0"
            >
              ✕
            </button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          <ExecList
            state={listState}
            selectedId={selectedExecutionId}
            reviewOverrides={reviewOverrides}
          />
        </div>
      </div>

      {/* RIGHT — detail + review */}
      <div className="flex-1 bg-os-base overflow-hidden flex flex-col">
        <ExecDetail
          state={detailState}
          onReviewComplete={handleReviewComplete}
          onRerunComplete={handleRerunComplete}
        />
      </div>
    </div>
  )
}
