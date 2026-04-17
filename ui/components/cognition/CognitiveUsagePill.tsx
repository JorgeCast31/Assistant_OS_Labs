'use client'

/**
 * M29: CognitiveUsagePill
 *
 * Per-message/response indicator shown when local cognition contributed.
 * Rendered inline in assistant messages when cognitive_trace.used = true.
 *
 * Rules:
 * - Only renders when cognitive_trace.used is explicitly true (from backend).
 * - Never invents participation — if used=false or trace is absent, renders nothing.
 * - Does not expose raw prompt text.
 */
import type { CognitiveTrace } from '@/lib/types'

interface Props {
  trace: CognitiveTrace | undefined | null
}

export function CognitiveUsagePill({ trace }: Props) {
  if (!trace?.used) return null

  const provider  = trace.provider ?? 'local'
  const taskType  = trace.task_type ?? ''
  const fallback  = trace.fallback_used
  const conf      = trace.confidence != null ? `${Math.round(trace.confidence * 100)}%` : null

  const title = [
    `Provider: ${provider}`,
    taskType  && `Task: ${taskType}`,
    trace.validation && `Validation: ${trace.validation}`,
    conf      && `Confidence: ${conf}`,
    fallback  && 'Fallback used',
  ].filter(Boolean).join(' · ')

  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-mono border border-accent/30 bg-accent/10 text-accent"
      title={title}
    >
      <span className="w-1 h-1 rounded-full bg-accent flex-shrink-0" />
      <span>{fallback ? 'local·fallback' : 'local·advisory'}</span>
      {conf && <span className="text-accent/70">{conf}</span>}
    </span>
  )
}
