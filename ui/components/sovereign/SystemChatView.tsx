'use client'

import { useState, useRef, useEffect, KeyboardEvent, Fragment } from 'react'
import { useSovereignStore } from '@/stores/sovereign-store'
import { sendSovereignMessage } from '@/lib/sovereign/api'
import type { SovereignMessage, ExecutionStatus, ExecutionStatusSource } from '@/lib/sovereign/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function genId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
}

function executionStatusClass(status: ExecutionStatus): string {
  switch (status) {
    case 'real':
      return 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25'
    case 'stub':
      return 'bg-amber-500/15 text-amber-300 border-amber-500/25'
    case 'partial':
      return 'bg-sky-500/15 text-sky-300 border-sky-500/25'
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
          <code key={i} className="px-1 py-0.5 rounded bg-teal-500/10 text-[11px] font-mono text-teal-300 border border-teal-500/20">
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
              <div key={i} className="rounded-lg overflow-hidden border border-teal-500/20">
                {block.lang && block.lang !== 'text' && (
                  <div className="px-3 py-1 bg-teal-500/5 border-b border-teal-500/20">
                    <span className="text-[10px] font-mono text-teal-400/60 uppercase tracking-wider">{block.lang}</span>
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
                    <span className="text-teal-400/60 flex-shrink-0 mt-px">-</span>
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
}

function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  
  return (
    <div className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-lg bg-teal-500/10 border border-teal-500/20 flex items-center justify-center flex-shrink-0">
          <span className="text-teal-400 text-[10px] font-mono font-bold">S</span>
        </div>
      )}
      
      <div className={`
        max-w-[75%] px-4 py-3 rounded-xl
        ${isUser 
          ? 'bg-teal-500/10 border border-teal-500/20 text-tx-primary' 
          : 'bg-os-elevated border border-os-border text-tx-primary'
        }
      `}>
        <RichText content={message.content} />
        {!isUser && message.executionStatus && (
          <div className="mt-2">
            <ExecutionStatusBadge status={message.executionStatus} source={message.executionStatusSource} />
          </div>
        )}
        
        {/* Timestamp */}
        <div className="mt-2 pt-1.5 border-t border-os-border/50">
          <span className="text-[9px] font-mono text-tx-muted">
            {new Date(message.timestamp).toLocaleTimeString('en-US', {
              hour12: false,
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        </div>
      </div>
      
      {isUser && (
        <div className="w-7 h-7 rounded-lg bg-slate-600/30 border border-slate-500/30 flex items-center justify-center flex-shrink-0">
          <span className="text-slate-400 text-[10px] font-mono">U</span>
        </div>
      )}
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SystemChatView() {
  const { systemChatMessages, addSystemChatMessage } = useSovereignStore()
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [systemChatMessages])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSend = async () => {
    const text = input.trim()
    if (!text || isLoading) return

    setInput('')
    setIsLoading(true)

    // Add user message
    const userMsg: SovereignMessage = {
      id: genId(),
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
      surface: 'system_chat',
    }
    addSystemChatMessage(userMsg)

    // Send to API
    const response = await sendSovereignMessage(text, 'system_chat')

    // ALFA-FLIGHT-01.5 informational guard.
    //
    // System Chat is the informational layer — its UI contract states
    // "This surface never executes or authorizes actions." The backend
    // however is single-source-of-truth and may classify any text into a
    // plan / confirmation flow (that is correct backend behavior; surface
    // is never an authority verdict). When the backend response carries
    // plan / needs_confirmation / executionMode / non-ALLOW governance,
    // we render it here as an informational redirect to MSO Direct or
    // Machine Operator instead of leaking spurious action artefacts into
    // the System Chat surface.
    const hasPlan       = Array.isArray(response.plan) && response.plan.length > 0
    const needsConfirm  = response.needs_confirmation === true
    const hasExecMode   = response.execution_mode != null && response.execution_mode !== 'direct'
    const govDecision   = response.governance_trace?.decision
    const govNonAllow   = govDecision != null && govDecision !== 'ALLOW'
    const isExecutiveResponse = hasPlan || needsConfirm || hasExecMode || govNonAllow

    let content: string
    if (!response.ok) {
      content = `Error: ${response.error ?? 'unknown error'}`
    } else if (isExecutiveResponse) {
      content =
        'Blocked:\n' +
        '  domain=SYSTEM\n' +
        '  action=surface.system_chat.executive_intent\n' +
        '  reason=System Chat is the informational layer; it does not render plans or confirmations.\n' +
        '  suggestion=Switch to MSO Direct or Machine Operator to issue an executive request.'
    } else {
      content = response.message
    }

    // Add assistant response
    const assistantMsg: SovereignMessage = {
      id: genId(),
      role: 'assistant',
      content,
      timestamp: new Date().toISOString(),
      surface: 'system_chat',
      // We intentionally drop plan/executionMode/pendingConfirmation here
      // — System Chat does not render those. governanceTrace and
      // executionStatus stay so the operator still sees backend honesty
      // signals.
      governanceTrace: response.governance_trace,
      executionStatus: response.execution_status,
      executionStatusSource: response.execution_status_source,
    }
    addSystemChatMessage(assistantMsg)

    setIsLoading(false)
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
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-teal-400" />
          <div>
            <h2 className="text-sm font-mono font-semibold text-teal-400">
              System Chat
            </h2>
            <p className="text-[10px] font-mono text-tx-muted">
              Informational Layer - Safe queries, no execution
            </p>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {systemChatMessages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-16 h-16 rounded-2xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-center mb-4">
              <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
                <circle cx="16" cy="16" r="6" stroke="currentColor" strokeWidth="2" className="text-teal-400" />
                <circle cx="16" cy="16" r="12" stroke="currentColor" strokeWidth="2" strokeDasharray="3 3" className="text-teal-400/40" />
              </svg>
            </div>
            <h3 className="text-lg font-mono font-medium text-tx-primary mb-2">
              System Chat
            </h3>
            <p className="text-sm font-mono text-tx-secondary max-w-md leading-relaxed">
              This is the informational layer. Ask questions about the system,
              query status, or explore capabilities.
            </p>
            <p className="text-xs font-mono text-teal-400/60 mt-4">
              This surface never executes or authorizes actions.
            </p>
          </div>
        )}

        {systemChatMessages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {isLoading && (
          <div className="flex gap-3 justify-start">
            <div className="w-7 h-7 rounded-lg bg-teal-500/10 border border-teal-500/20 flex items-center justify-center flex-shrink-0">
              <span className="text-teal-400 text-[10px] font-mono font-bold">S</span>
            </div>
            <div className="px-4 py-3 rounded-xl bg-os-elevated border border-os-border">
              <div className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
                <div className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse [animation-delay:150ms]" />
                <div className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse [animation-delay:300ms]" />
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
              placeholder="Ask the system..."
              rows={1}
              className="
                w-full px-4 py-3 rounded-xl
                bg-os-base border border-teal-500/20
                text-sm font-mono text-tx-primary placeholder:text-tx-muted
                outline-none focus:border-teal-500/40 focus:ring-1 focus:ring-teal-500/20
                transition-all resize-none
              "
            />
          </div>
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="
              px-5 py-3 rounded-xl
              bg-teal-500/10 border border-teal-500/30 
              text-sm font-mono text-teal-400
              hover:bg-teal-500/20 hover:border-teal-500/40
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-all
            "
          >
            Send
          </button>
        </div>
        <p className="text-[9px] font-mono text-tx-muted mt-2 text-center">
          Informational queries only - no commands executed from this surface
        </p>
      </div>
    </div>
  )
}
