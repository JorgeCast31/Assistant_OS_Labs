'use client'

import React from 'react'
import type { SovereignMessage } from '@/lib/sovereign/types'

interface MSOMessageRawDrawerProps {
  msg: SovereignMessage
  isOpen: boolean
  onClose: () => void
}

export function MSOMessageRawDrawer({ msg, isOpen, onClose }: MSOMessageRawDrawerProps) {
  if (!isOpen) return null

  // Show raw response if preserved, otherwise fall back to mapped metadata
  const displayMetadata = msg.rawResponse || {
    response_source: msg.responseSource,
    execution_status: msg.executionStatus,
    provider_used: msg.providerUsed,
    model_used: msg.modelUsed,
    cognitive_generation: msg.cognitiveGeneration,
    fallback_used: msg.fallbackUsed,
    fallback_reason: msg.fallbackReason,
    execution_allowed: msg.executionAllowed,
    can_execute_now: msg.canExecuteNow,
    latency_ms: msg.latencyMs,
    tokens_in: msg.tokensIn,
    tokens_out: msg.tokensOut,
    narrative_context: msg.narrativeContext,
    cognitive_trace: msg.cognitiveTrace,
    governance_trace: msg.governanceTrace,
    decision_source: msg.decisionSource,
    confidence_score: msg.confidenceScore,
    audit: msg.audit,
    trace_id: msg.traceId,
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-end bg-black/40 backdrop-blur-sm transition-opacity" onClick={onClose}>
      <div
        className="h-full w-full max-w-lg overflow-y-auto border-l border-os-border bg-os-base p-6 shadow-2xl transition-transform animate-in slide-in-from-right duration-300"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-6 flex items-center justify-between border-b border-os-border pb-4">
          <div>
            <h3 className="text-sm font-mono font-bold uppercase tracking-widest text-tx-primary">
              Raw Message Metadata
            </h3>
            <p className="text-[10px] font-mono text-tx-muted mt-1">
              Complete backend provenance for assistant response
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-tx-muted hover:bg-os-surface hover:text-tx-primary transition-colors"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="space-y-6 font-mono text-[11px]">
          <section>
            <p className="mb-2 uppercase text-tx-muted tracking-widest text-[9px] font-bold">Provenance Summary</p>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded border border-os-border bg-os-surface p-2">
                <p className="text-[9px] text-tx-muted mb-0.5">Source</p>
                <p className="text-tx-primary truncate">{msg.responseSource || 'N/A'}</p>
              </div>
              <div className="rounded border border-os-border bg-os-surface p-2">
                <p className="text-[9px] text-tx-muted mb-0.5">Status</p>
                <p className="text-tx-primary truncate">{msg.executionStatus || 'N/A'}</p>
              </div>
              <div className="rounded border border-os-border bg-os-surface p-2">
                <p className="text-[9px] text-tx-muted mb-0.5">Provider</p>
                <p className="text-tx-primary truncate">{msg.providerUsed || 'None'}</p>
              </div>
              <div className="rounded border border-os-border bg-os-surface p-2">
                <p className="text-[9px] text-tx-muted mb-0.5">Trace ID</p>
                <p className="text-tx-primary truncate">{msg.traceId || 'Not reported'}</p>
              </div>
            </div>
          </section>

          <section>
            <p className="mb-2 uppercase text-tx-muted tracking-widest text-[9px] font-bold">
              {msg.rawResponse ? 'Exact Backend Response' : 'Mapped Backend Metadata'}
            </p>
            <div className="rounded border border-os-border bg-os-surface p-4 overflow-x-auto whitespace-pre leading-relaxed text-tx-secondary">
              {JSON.stringify(displayMetadata, null, 2)}
            </div>
          </section>

          <section className="rounded-lg border border-warn/20 bg-warn/5 p-3">
            <p className="text-[10px] leading-normal text-warn italic">
              Verification mode: This is the exact truth returned by the backend.
              The LLM cannot influence execution status or authority.
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}
