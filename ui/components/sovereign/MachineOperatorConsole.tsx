'use client'

import { useState, useRef, useEffect, KeyboardEvent } from 'react'
import { useSovereignStore } from '@/stores/sovereign-store'
import { executeAgentCommand } from '@/lib/sovereign/agents'
import { EscalationCard } from './EscalationCard'
import { StatusIndicator } from './StatusIndicator'
import type { AgentCommand, EscalationRequest } from '@/lib/sovereign/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function genId(): string {
  return `cmd_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
}

// ── Command Entry ─────────────────────────────────────────────────────────────

interface CommandEntryProps {
  command: AgentCommand
}

function CommandEntry({ command }: CommandEntryProps) {
  const statusColors: Record<AgentCommand['status'], string> = {
    pending:   'text-slate-400',
    executing: 'text-amber-400',
    completed: 'text-emerald-400',
    failed:    'text-red-400',
    escalated: 'text-amber-400',
  }

  return (
    <div className="space-y-1">
      {/* Command */}
      <div className="flex items-start gap-2">
        <span className="text-emerald-400 text-xs font-mono flex-shrink-0">{'>'}</span>
        <span className="text-xs font-mono text-tx-primary break-all">
          {command.command}
        </span>
        <span className={`text-[9px] font-mono ${statusColors[command.status]} ml-auto flex-shrink-0`}>
          [{command.status}]
        </span>
      </div>
      
      {/* Output */}
      {command.output && (
        <div className="ml-4 pl-2 border-l border-os-border">
          <pre className="text-xs font-mono text-tx-secondary whitespace-pre-wrap break-all">
            {command.output}
          </pre>
        </div>
      )}
      
      {/* Error */}
      {command.error && (
        <div className="ml-4 pl-2 border-l border-red-500/30">
          <pre className="text-xs font-mono text-red-400 whitespace-pre-wrap break-all">
            {command.error}
          </pre>
        </div>
      )}
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function MachineOperatorConsole() {
  const { 
    agentState, 
    setAgentState, 
    addEscalation,
    setActiveView,
  } = useSovereignStore()
  
  const [input, setInput] = useState('')
  const [isExecuting, setIsExecuting] = useState(false)
  const [pendingEscalation, setPendingEscalation] = useState<EscalationRequest | null>(null)
  const [commandHistory, setCommandHistory] = useState<AgentCommand[]>([])
  
  const outputRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    outputRef.current?.scrollTo({
      top: outputRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [commandHistory, pendingEscalation])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleExecute = async () => {
    const cmd = input.trim()
    if (!cmd || isExecuting) return

    setInput('')
    setIsExecuting(true)
    setAgentState({ status: 'active' })
    setPendingEscalation(null)

    // Add pending command
    const command: AgentCommand = {
      id: genId(),
      command: cmd,
      timestamp: new Date().toISOString(),
      status: 'executing',
    }
    setCommandHistory(prev => [...prev, command])

    // Execute via mock adapter
    const response = await executeAgentCommand({
      command: cmd,
      agentId: 'machine_operator',
    })

    // Update command with result
    setCommandHistory(prev => prev.map(c => 
      c.id === command.id 
        ? { 
            ...c, 
            status: response.status, 
            output: response.output,
            error: response.error,
            escalation: response.escalation,
          }
        : c
    ))

    // Handle escalation
    if (response.escalation) {
      setPendingEscalation(response.escalation)
      setAgentState({ status: 'waiting_auth' })
    } else {
      setAgentState({ status: 'idle' })
    }

    setIsExecuting(false)
    inputRef.current?.focus()
  }

  const handleSendToMSO = (suggestedCommand: string) => {
    if (pendingEscalation) {
      addEscalation(pendingEscalation)
      setPendingEscalation(null)
      setAgentState({ status: 'idle' })
      setActiveView('mso')
    }
  }

  const handleDismissEscalation = () => {
    setPendingEscalation(null)
    setAgentState({ status: 'idle' })
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleExecute()
    }
  }

  return (
    <div className="flex flex-col h-full bg-os-base">
      {/* Header */}
      <div className="px-4 py-3 border-b border-os-border bg-os-surface">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-slate-600/30 border border-slate-500/30 flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-slate-300">
                <rect x="2" y="2" width="12" height="9" rx="1" stroke="currentColor" strokeWidth="1.3" />
                <path d="M4 14h8M6 11v3M10 11v3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
                <path d="M4 5.5h8M4 8h5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
              </svg>
            </div>
            <div>
              <h2 className="text-sm font-mono font-semibold text-tx-primary">
                Machine Operator
              </h2>
              <p className="text-[10px] font-mono text-tx-muted">
                Operational Layer - Delegated execution
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <StatusIndicator type="agent" status={agentState.status} size="md" showLabel pulse={agentState.status === 'active'} />
          </div>
        </div>
      </div>

      {/* Console Output */}
      <div 
        ref={outputRef}
        className="flex-1 overflow-y-auto p-4 font-mono text-sm bg-[#0a0b0e] space-y-3"
      >
        {/* Initial message */}
        {commandHistory.length === 0 && !pendingEscalation && (
          <div className="space-y-2 text-tx-muted">
            <p className="text-xs">Machine Operator — browser execution lane</p>
            <p className="text-xs">Type &apos;help&apos; for available capabilities</p>
            <p className="text-xs text-slate-500/70">
              Each response includes [execution_status: real|unavailable]
            </p>
            <div className="h-px bg-os-border my-3" />
          </div>
        )}

        {/* Command history */}
        {commandHistory.map((cmd) => (
          <CommandEntry key={cmd.id} command={cmd} />
        ))}

        {/* Executing indicator */}
        {isExecuting && (
          <div className="flex items-center gap-2">
            <span className="text-amber-400 text-xs font-mono">{'>'}</span>
            <div className="flex items-center gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse" />
              <div className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse [animation-delay:150ms]" />
              <div className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse [animation-delay:300ms]" />
            </div>
          </div>
        )}

        {/* Pending Escalation */}
        {pendingEscalation && (
          <div className="mt-4">
            <EscalationCard
              escalation={pendingEscalation}
              onSendToMSO={handleSendToMSO}
              onDismiss={handleDismissEscalation}
            />
          </div>
        )}
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-os-border bg-[#0a0b0e]">
        <div className="flex items-center gap-2">
          <span className="text-emerald-400 text-sm font-mono">$</span>
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Enter command..."
            disabled={isExecuting || pendingEscalation !== null}
            className="
              flex-1 bg-transparent
              text-sm font-mono text-tx-primary placeholder:text-tx-muted
              outline-none
              disabled:opacity-50 disabled:cursor-not-allowed
            "
          />
          <button
            onClick={handleExecute}
            disabled={!input.trim() || isExecuting || pendingEscalation !== null}
            className="
              px-3 py-1.5 rounded
              bg-slate-600/30 border border-slate-500/30
              text-xs font-mono text-slate-300
              hover:bg-slate-600/50 hover:border-slate-500/50
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-colors
            "
          >
            Run
          </button>
        </div>
      </div>
    </div>
  )
}
