'use client'

import type { OperationTraceV0 as OperationTraceV0Type } from '@/lib/types'

// ── Status → visual maps ──────────────────────────────────────────────────

const STEP_DOT: Record<string, string> = {
  complete:         'bg-ok',
  pending:          'bg-warn',
  missing:          'bg-idle',
  rejected:         'bg-err',
  denied:           'bg-err',
  blocked:          'bg-err',
  blocked_by_design:'bg-idle',
  draft_complete:   'bg-warn',
  not_ready:        'bg-idle',
}

const STEP_TEXT: Record<string, string> = {
  complete:         'text-ok',
  pending:          'text-warn',
  missing:          'text-tx-muted',
  rejected:         'text-err',
  denied:           'text-err',
  blocked:          'text-err',
  blocked_by_design:'text-tx-muted',
  draft_complete:   'text-warn',
  not_ready:        'text-tx-muted',
}

// ── Component ─────────────────────────────────────────────────────────────

export function OperationTraceV0({ trace }: { trace: OperationTraceV0Type | undefined }) {
  if (!trace || trace.steps.length === 0) {
    return (
      <div className="mt-3">
        <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-1">
          Operation Trace
        </p>
        <p className="text-[10px] font-mono text-tx-muted">Trace unavailable.</p>
      </div>
    )
  }

  return (
    <div className="mt-3">
      <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">
        Operation Trace v0
      </p>
      <div className="space-y-1">
        {trace.steps.map((step, i) => {
          const dot = STEP_DOT[step.status] ?? 'bg-idle'
          const text = STEP_TEXT[step.status] ?? 'text-tx-muted'
          return (
            <div key={i} className="flex items-start gap-2">
              <span className={`mt-[3px] w-2 h-2 rounded-full flex-shrink-0 ${dot}`} />
              <div>
                <span className={`text-[10px] font-mono font-medium ${text}`}>{step.label}</span>
                <span className="text-[10px] font-mono text-tx-muted ml-1">— {step.status}</span>
                {step.description && (
                  <p className="text-[10px] font-mono text-tx-muted leading-relaxed">
                    {step.description}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>
      {trace.next_safe_step && (
        <p className="text-[10px] font-mono text-tx-muted mt-2 pt-1 border-t border-os-border/40">
          {trace.next_safe_step}
        </p>
      )}
    </div>
  )
}
