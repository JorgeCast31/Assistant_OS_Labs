'use client'

import { useState, useRef, useCallback } from 'react'
import { sendSovereignMessage } from '@/lib/sovereign/api'
import { useMSOChatStore } from '@/stores/mso-chat-store'
import { MSOInteractionModeSelector } from './MSOInteractionModeSelector'
import type { SovereignMessage } from '@/lib/sovereign/types'

function makeId(): string {
  return `mso-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

function nowIso(): string {
  return new Date().toISOString()
}

interface MSOComposerProps {
  sessionId?: string
}

export function MSOComposer({ sessionId }: MSOComposerProps) {
  const [text, setText] = useState('')
  const { isLoading, appendMessage, updateMessage, setLoading, agentSeat, interactionMode, cognitionTier } =
    useMSOChatStore()
  const loadingMsgId = useRef<string | null>(null)

  const submit = useCallback(async () => {
    const trimmed = text.trim()
    if (!trimmed || isLoading) return

    setText('')

    const userMsg: SovereignMessage = {
      id: makeId(),
      role: 'user',
      content: trimmed,
      timestamp: nowIso(),
      surface: 'mso_direct',
    }
    appendMessage(userMsg)

    const loadingId = makeId()
    loadingMsgId.current = loadingId
    const loadingMsg: SovereignMessage = {
      id: loadingId,
      role: 'assistant',
      content: '…',
      timestamp: nowIso(),
      surface: 'mso_direct',
    }
    appendMessage(loadingMsg)
    setLoading(true)

    try {
      const response = await sendSovereignMessage(trimmed, 'mso_direct', sessionId, {
        agent_seat: agentSeat,
        interaction_mode: interactionMode,
        cognition_tier: cognitionTier,
      })

      const assistantMsg: Partial<SovereignMessage> = {
        content: response.message || '(empty response)',
        timestamp: nowIso(),
        executionStatus: response.execution_status,
        governanceTrace: response.governance_trace,
        decisionSource: response.decision_source,
        confidenceScore: response.confidence_score,
        // ALPHA PHASE 1 — provenance metadata
        responseSource: response.response_source,
        providerUsed: response.provider_used,
        modelUsed: response.model_used,
        cognitiveGeneration: response.cognitive_generation,
        fallbackUsed: response.fallback_used,
        fallbackReason: response.fallback_reason,
        narrativeContext: response.narrative_context,
        cognitiveTrace: response.cognitive_trace,
        executionAllowed: response.execution_allowed,
        canExecuteNow: response.can_execute_now,
        latencyMs: response.latency_ms,
        tokensIn: response.tokens_in,
        tokensOut: response.tokens_out,
        audit: response.audit,
        traceId: response.trace_id,
        rawResponse: response.raw_response,
      }

      if (!response.ok) {
        assistantMsg.executionStatus = response.execution_status ?? 'unavailable'
      }

      updateMessage(loadingId, assistantMsg)
    } catch {
      updateMessage(loadingId, {
        content: 'Connection error. Backend may be unavailable.',
        executionStatus: 'unavailable',
        timestamp: nowIso(),
      })
    } finally {
      setLoading(false)
      loadingMsgId.current = null
    }
  }, [text, isLoading, sessionId, appendMessage, updateMessage, setLoading])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void submit()
    }
  }

  return (
    <div className="border-t border-os-border bg-os-base px-4 py-3">
      <MSOInteractionModeSelector />
      <div className="flex gap-2 items-end mt-2">
        <textarea
          className="flex-1 resize-none rounded-lg border border-os-border bg-os-surface px-3 py-2 text-xs font-mono text-tx-primary placeholder:text-tx-muted focus:outline-none focus:ring-1 focus:ring-accent/50 disabled:opacity-50"
          rows={2}
          placeholder="Escribe al MSO…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
          aria-label="MSO message input"
        />
        <button
          onClick={() => void submit()}
          disabled={isLoading || !text.trim()}
          className="rounded-lg border border-accent/40 bg-accent/10 px-4 py-2 text-xs font-mono text-accent hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-40 transition-colors"
        >
          Send
        </button>
      </div>
      <p className="mt-1.5 text-[9px] font-mono text-tx-muted">
        {agentSeat} · {interactionMode} · {cognitionTier} · Execution is closed. · surface: mso_direct
      </p>
    </div>
  )
}
