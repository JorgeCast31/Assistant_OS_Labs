'use client'

import { useState, useRef, useEffect, KeyboardEvent, Fragment } from 'react'
import { useSovereignStore } from '@/stores/sovereign-store'
import { sendSovereignMessage, sendMSOConfirmation } from '@/lib/sovereign/api'
import { PlanCard } from './PlanCard'
import { ConfirmationCard } from './ConfirmationCard'
import { AuthorityBadge } from './AuthorityBadge'
import { PolicyDecisionCard } from './PolicyDecisionCard'
import { AuthorityArtifactCard } from './AuthorityArtifactCard'
import { PendingConfirmationCard } from './PendingConfirmationCard'
import type { SovereignMessage, MSOPlanItem, ExecutionStatus, ExecutionStatusSource } from '@/lib/sovereign/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function genId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
}

function executionStatusClass(status: ExecutionStatus): string {
  switch (status) {
    case 'success':
      return 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25'
    case 'stub':
      return 'bg-amber-500/15 text-amber-300 border-amber-500/25'
    case 'partial':
      return 'bg-sky-500/15 text-sky-300 border-sky-500/25'
    case 'error':
      return 'bg-red-500/15 text-red-300 border-red-500/25'
    case 'unavailable':
      return 'bg-slate-500/15 text-slate-300 border-slate-500/25'
  }
}

function ExecutionStatusBadge({
  status,
  source = 'backend',
}: {
  status: ExecutionStatus
  source?: ExecutionStatusSource
}) {
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider ${executionStatusClass(status)}`}>
      execution_status: {status}{source === 'ui_fallback' ? ' (ui fallback)' : ''}
    </span>
  )
}

// ── RichText ──────────────────────────────────────────────────────────────────

type RichBlock =
  | { t: 'para'; text: string }
  | { t: 'list'; items: string[] }
  | { t: 'code'; lang: string; src: string }

function parseBlocks(raw: string): RichBlock[] {
  const blocks: RichBlock[] = []
  const fenceRe = /```(\w*)\n?([\s\S]*?)```/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = fenceRe.exec(raw)) !== null) {
    const before = raw.slice(last, m.index).trim()
    if (before) parseParagraphs(before, blocks)
    blocks.push({ t: 'code', lang: m[1] || 'text', src: m[2].trimEnd() })
    last = m.index + m[0].length
  }
  const tail = raw.slice(last).trim()
  if (tail) parseParagraphs(tail, blocks)
  return blocks.length ? blocks : [{ t: 'para', text: raw }]
}

function parseParagraphs(text: string, out: RichBlock[]) {
  const chunks = text.split(/\n{2,}/)
  for (const chunk of chunks) {
    const trimmed = chunk.trim()
    if (!trimmed) continue
    const lines = trimmed.split('\n')
    const isList = lines.every(l => /^[-•*]\s/.test(l))
    if (isList) {
      out.push({ t: 'list', items: lines.map(l => l.replace(/^[-•*]\s+/, '')) })
    } else {
      out.push({ t: 'para', text: trimmed })
    }
  }
}

function InlineText({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`)/)
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('`') && part.endsWith('`') ? (
          <code key={i} className="px-1 py-0.5 rounded bg-amber-500/10 text-[11px] font-mono text-amber-300 border border-amber-500/20">
            {part.slice(1, -1)}
          </code>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        )
      )}
    </>
  )
}

function RichText({ content }: { content: string }) {
  if (!content) return null
  try {
    const blocks = parseBlocks(content)
    return (
      <div className="space-y-2">
        {blocks.map((block, i) => {
          if (block.t === 'code') {
            return (
              <div key={i} className="rounded-lg overflow-hidden border border-amber-500/20">
                {block.lang && block.lang !== 'text' && (
                  <div className="px-3 py-1 bg-amber-500/5 border-b border-amber-500/20">
                    <span className="text-[10px] font-mono text-amber-400/60 uppercase tracking-wider">{block.lang}</span>
                  </div>
                )}
                <pre className="px-3 py-2.5 overflow-x-auto bg-os-elevated text-xs font-mono text-tx-primary whitespace-pre">
                  {block.src}
                </pre>
              </div>
            )
          }
          if (block.t === 'list') {
            return (
              <ul key={i} className="space-y-1 pl-3">
                {block.items.map((item, j) => (
                  <li key={j} className="flex gap-2 text-sm font-mono text-tx-primary">
                    <span className="text-amber-400/60 flex-shrink-0 mt-px">-</span>
                    <span><InlineText text={item} /></span>
                  </li>
                ))}
              </ul>
            )
          }
          return (
            <p key={i} className="text-sm font-mono text-tx-primary whitespace-pre-wrap break-words leading-relaxed">
              <InlineText text={block.text} />
            </p>
          )
        })}
      </div>
    )
  } catch {
    return <pre className="text-sm font-mono text-tx-primary whitespace-pre-wrap break-words">{content}</pre>
  }
}

// ── Message Bubble ────────────────────────────────────────────────────────────

interface MessageBubbleProps {
  message: SovereignMessage
  onConfirm?: () => void
  onCancel?: () => void
  isLatest?: boolean
}

function MessageBubble({ message, onConfirm, onCancel, isLatest }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const showConfirmation = isLatest && message.requiresConfirmation && message.role === 'assistant'
  const hasPendingConfirmation = isLatest && message.pendingConfirmation && message.role === 'assistant'
  
  return (
    <div className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500/20 to-amber-600/10 border border-amber-500/30 flex items-center justify-center flex-shrink-0">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="text-amber-400">
            <path d="M7 1L12 4V10L7 13L2 10V4L7 1Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
          </svg>
        </div>
      )}
      
      <div className={`max-w-[80%] space-y-3`}>
        <div className={`
          px-4 py-3 rounded-xl
          ${isUser 
            ? 'bg-amber-500/10 border border-amber-500/25 text-tx-primary' 
            : 'bg-os-elevated border border-os-border text-tx-primary'
          }
        `}>
          <RichText content={message.content} />
          {!isUser && message.executionStatus && (
            <div className="mt-2">
              <ExecutionStatusBadge status={message.executionStatus} source={message.executionStatusSource} />
            </div>
          )}
          
          {/* Execution Mode Badge */}
          {message.executionMode && (
            <div className="mt-2">
              <span className={`text-[9px] font-mono px-2 py-1 rounded uppercase tracking-wider ${
                message.executionMode === 'direct' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
                message.executionMode === 'plan' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' :
                message.executionMode === 'confirm' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' :
                'bg-red-500/20 text-red-400 border border-red-500/30'
              }`}>
                Mode: {message.executionMode}
              </span>
            </div>
          )}

          {/* Policy Decision Card */}
          {message.policyDecision && (
            <div className="mt-3">
              <PolicyDecisionCard decision={message.policyDecision} />
            </div>
          )}

          {/* Authority Artifact Card */}
          {message.authorityArtifact && (
            <div className="mt-3">
              <AuthorityArtifactCard artifact={message.authorityArtifact} />
            </div>
          )}
          
          {/* Plan Display */}
          {message.plan && message.plan.length > 0 && (
            <div className="mt-3">
              <PlanCard items={message.plan} />
            </div>
          )}
          
          {/* Governance Badge */}
          {message.governanceTrace && (
            <AuthorityBadge trace={message.governanceTrace} />
          )}
          
          {/* Timestamp & State */}
          <div className="mt-2 pt-1.5 border-t border-os-border/50 flex items-center justify-between">
            <span className="text-[9px] font-mono text-tx-muted">
              {new Date(message.timestamp).toLocaleTimeString('en-US', {
                hour12: false,
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
            {message.executionState && message.executionState !== 'idle' && (
              <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${
                message.executionState === 'awaiting_confirmation' ? 'bg-amber-500/20 text-amber-400' :
                message.executionState === 'executing' ? 'bg-amber-500/20 text-amber-400 animate-pulse' :
                message.executionState === 'completed' ? 'bg-emerald-500/20 text-emerald-400' :
                message.executionState === 'failed' ? 'bg-red-500/20 text-red-400' :
                'bg-slate-500/20 text-slate-400'
              }`}>
                {message.executionState.toUpperCase().replace('_', ' ')}
              </span>
            )}
          </div>
        </div>

        {/* Pending Confirmation Card (from API) */}
        {hasPendingConfirmation && message.pendingConfirmation && onConfirm && onCancel && (
          <PendingConfirmationCard
            confirmation={message.pendingConfirmation}
            onConfirm={onConfirm}
            onCancel={onCancel}
          />
        )}

        {/* Legacy Confirmation Card (fallback) */}
        {showConfirmation && !hasPendingConfirmation && onConfirm && onCancel && (
          <ConfirmationCard
            message="Do you authorize this execution plan?"
            plan={message.plan}
            governanceTrace={message.governanceTrace}
            onConfirm={onConfirm}
            onCancel={onCancel}
          />
        )}
      </div>
      
      {isUser && (
        <div className="w-8 h-8 rounded-lg bg-slate-600/30 border border-slate-500/30 flex items-center justify-center flex-shrink-0">
          <span className="text-slate-400 text-[10px] font-mono">U</span>
        </div>
      )}
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function MSOView() {
  const { 
    msoMessages, 
    addMSOMessage, 
    updateLastMSOMessage,
    msoState,
    setMSOState,
    pendingEscalations,
    removeEscalation,
    setActiveView,
    setActiveAgent,
  } = useSovereignStore()
  
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msoMessages])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSend = async () => {
    const text = input.trim()
    if (!text || isLoading) return

    setInput('')
    setIsLoading(true)
    setMSOState({ status: 'deciding' })

    // Add user message
    const userMsg: SovereignMessage = {
      id: genId(),
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
      surface: 'mso_direct',
    }
    addMSOMessage(userMsg)

    // Send to API
    const response = await sendSovereignMessage(text, 'mso_direct')

    // Add assistant response with all extended fields
    const assistantMsg: SovereignMessage = {
      id: genId(),
      role: 'assistant',
      content: response.ok ? response.message : `Error: ${response.error}`,
      timestamp: new Date().toISOString(),
      surface: 'mso_direct',
      plan: response.plan as MSOPlanItem[] | undefined,
      requiresConfirmation: response.needs_confirmation,
      executionState: response.needs_confirmation ? 'awaiting_confirmation' : 'idle',
      governanceTrace: response.governance_trace,
      // Extended MSO fields from API
      executionMode: response.execution_mode,
      policyDecision: response.policy_decision,
      authorityArtifact: response.authority_artifact,
      pendingConfirmation: response.pending_confirmation,
      executionStatus: response.execution_status,
      executionStatusSource: response.execution_status_source,
    }
    addMSOMessage(assistantMsg)

    setMSOState({ 
      status: response.needs_confirmation ? 'deciding' : 'active',
      executionState: response.needs_confirmation ? 'awaiting_confirmation' : 'idle',
      currentPlan: response.plan as MSOPlanItem[] | undefined ?? null,
    })
    setIsLoading(false)
    inputRef.current?.focus()
  }

  const handleConfirm = async () => {
    setMSOState({ status: 'active', executionState: 'executing' })
    updateLastMSOMessage({ requiresConfirmation: false, executionState: 'executing' })
    
    // Send confirmation
    const response = await sendMSOConfirmation('', true)
    
    // Update state
    updateLastMSOMessage({ 
      executionState: response.ok ? 'completed' : 'failed'
    })
    setMSOState({ 
      status: 'active', 
      executionState: response.ok ? 'completed' : 'failed',
      lastDecision: new Date().toISOString(),
    })

    // Add result message
    const resultMsg: SovereignMessage = {
      id: genId(),
      role: 'assistant',
      content: response.ok ? response.message : `Execution failed: ${response.error}`,
      timestamp: new Date().toISOString(),
      surface: 'mso_direct',
      executionState: response.ok ? 'completed' : 'failed',
      executionStatus: response.execution_status,
      executionStatusSource: response.execution_status_source,
    }
    addMSOMessage(resultMsg)
  }

  const handleCancel = async () => {
    setMSOState({ status: 'active', executionState: 'idle' })
    updateLastMSOMessage({ requiresConfirmation: false, executionState: 'blocked' })
    
    await sendMSOConfirmation('', false)
    
    const cancelMsg: SovereignMessage = {
      id: genId(),
      role: 'assistant',
      content: 'Execution cancelled by operator authority.',
      timestamp: new Date().toISOString(),
      surface: 'mso_direct',
      executionState: 'blocked',
    }
    addMSOMessage(cancelMsg)
  }

  const handleEscalationAccept = (escalation: typeof pendingEscalations[0]) => {
    setInput(escalation.suggestedCommand)
    removeEscalation(escalation.id)
    inputRef.current?.focus()
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-full bg-os-base">
      {/* Header */}
      <div className="px-6 py-4 border-b border-os-border bg-os-surface">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-amber-400" />
            <div>
              <h2 className="text-sm font-mono font-semibold text-amber-400">
                MSO Direct
              </h2>
              <p className="text-[10px] font-mono text-tx-muted">
                Sovereign Layer - Authority and execution control
              </p>
            </div>
          </div>
          <div className={`px-3 py-1.5 rounded-lg text-xs font-mono ${
            msoState.status === 'active' ? 'bg-amber-500/10 border border-amber-500/20 text-amber-400' :
            msoState.status === 'deciding' ? 'bg-amber-500/20 border border-amber-500/30 text-amber-300 animate-pulse' :
            'bg-red-500/10 border border-red-500/20 text-red-400'
          }`}>
            {msoState.status.toUpperCase()}
          </div>
        </div>
      </div>

      {/* Pending Escalations */}
      {pendingEscalations.length > 0 && (
        <div className="px-6 py-3 border-b border-amber-500/20 bg-amber-500/5">
          <p className="text-[10px] font-mono text-amber-400 uppercase tracking-wider mb-2">
            Pending Escalations ({pendingEscalations.length})
          </p>
          <div className="space-y-2">
            {pendingEscalations.map((esc) => (
              <div key={esc.id} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-os-elevated border border-os-border">
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-mono text-tx-primary truncate">
                    {esc.reason}
                  </p>
                  <p className="text-[10px] font-mono text-tx-muted mt-0.5">
                    From: {esc.agentId}
                  </p>
                </div>
                <span className={`px-1.5 py-0.5 text-[8px] font-mono rounded uppercase ${
                  esc.riskLevel === 'critical' ? 'bg-red-500/20 text-red-400' :
                  esc.riskLevel === 'high' ? 'bg-orange-500/20 text-orange-400' :
                  'bg-amber-500/20 text-amber-400'
                }`}>
                  {esc.riskLevel}
                </span>
                <button
                  onClick={() => handleEscalationAccept(esc)}
                  className="px-2 py-1 text-[10px] font-mono bg-amber-500/10 border border-amber-500/20 text-amber-400 rounded hover:bg-amber-500/20 transition-colors"
                >
                  Review
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {msoMessages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-amber-500/10 to-amber-600/5 border border-amber-500/20 flex items-center justify-center mb-4">
              <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
                <path d="M20 5L35 13V27L20 35L5 27V13L20 5Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" className="text-amber-400" />
                <path d="M20 13V20M20 25V25.01" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className="text-amber-400" />
              </svg>
            </div>
            <h3 className="text-lg font-mono font-medium text-tx-primary mb-2">
              MSO Direct
            </h3>
            <p className="text-sm font-mono text-tx-secondary max-w-md leading-relaxed">
              This is the sovereign authority layer. Commands issued here can
              trigger execution after confirmation.
            </p>
            <p className="text-xs font-mono text-amber-400/60 mt-4">
              You are the final authority - all actions require your explicit approval.
            </p>
          </div>
        )}

        {msoMessages.map((msg, index) => (
          <MessageBubble 
            key={msg.id} 
            message={msg} 
            isLatest={index === msoMessages.length - 1}
            onConfirm={handleConfirm}
            onCancel={handleCancel}
          />
        ))}

        {isLoading && (
          <div className="flex gap-3 justify-start">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500/20 to-amber-600/10 border border-amber-500/30 flex items-center justify-center flex-shrink-0">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="text-amber-400 animate-pulse">
                <path d="M7 1L12 4V10L7 13L2 10V4L7 1Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="px-4 py-3 rounded-xl bg-os-elevated border border-os-border">
              <div className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse [animation-delay:150ms]" />
                <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse [animation-delay:300ms]" />
                <span className="text-[10px] font-mono text-amber-400/60 ml-2">
                  Processing authority request...
                </span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4 border-t border-os-border bg-os-surface">
        <div className="flex gap-3">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Issue a command..."
              rows={1}
              className="
                w-full px-4 py-3 rounded-xl
                bg-os-base border border-amber-500/20
                text-sm font-mono text-tx-primary placeholder:text-tx-muted
                outline-none focus:border-amber-500/40 focus:ring-1 focus:ring-amber-500/20
                transition-all resize-none
              "
            />
          </div>
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="
              px-5 py-3 rounded-xl
              bg-amber-500/10 border border-amber-500/30 
              text-sm font-mono text-amber-400
              hover:bg-amber-500/20 hover:border-amber-500/40
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-all
            "
          >
            Command
          </button>
        </div>
        <p className="text-[9px] font-mono text-amber-400/60 mt-2 text-center">
          Sovereign authority - commands may trigger execution with your confirmation
        </p>
      </div>
    </div>
  )
}
