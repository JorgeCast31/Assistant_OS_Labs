'use client'

import { useEffect, useState } from 'react'
import { useSovereignStore } from '@/stores/sovereign-store'
import { MachineOperatorConsole } from './MachineOperatorConsole'
import type { AgentId } from '@/lib/sovereign/types'

// ── Types ─────────────────────────────────────────────────────────────────────

interface AgentPanelProps {
  agentId: AgentId | null
}

interface RegistryAgent {
  id: string
  name: string
  status: string
  capabilities: string[]
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AgentPanel({ agentId }: AgentPanelProps) {
  const { setActiveAgent } = useSovereignStore()
  const [agents, setAgents] = useState<RegistryAgent[]>([])
  const [registryLoading, setRegistryLoading] = useState(true)

  useEffect(() => {
    fetch('/api/agents/registry')
      .then(r => r.json())
      .then((data: { ok?: boolean; agents?: RegistryAgent[] }) => {
        if (data.ok && Array.isArray(data.agents)) {
          setAgents(data.agents)
        }
      })
      .catch(() => {})
      .finally(() => setRegistryLoading(false))
  }, [])

  // No agent selected — show selection view with live registry
  if (!agentId) {
    return (
      <div className="flex flex-col h-full bg-os-base">
        {/* Header */}
        <div className="px-6 py-4 border-b border-os-border bg-os-surface">
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-slate-400" />
            <div>
              <h2 className="text-sm font-mono font-semibold text-tx-primary">
                Agents Surface
              </h2>
              <p className="text-[10px] font-mono text-tx-muted">
                Operational Layer - Select an agent to operate
              </p>
            </div>
          </div>
        </div>

        {/* Agent Selection */}
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="max-w-md text-center">
            <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-slate-600/10 border border-slate-600/20 flex items-center justify-center">
              <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
                <rect x="6" y="6" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="2" className="text-slate-500" />
                <rect x="22" y="6" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="2" className="text-slate-500" />
                <rect x="6" y="22" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="2" className="text-slate-500" />
                <path d="M22 28h12M28 22v12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-slate-400" />
              </svg>
            </div>
            <h3 className="text-lg font-mono font-medium text-tx-primary mb-2">
              Agents Surface
            </h3>
            <p className="text-sm font-mono text-tx-secondary leading-relaxed mb-6">
              This is the operational layer. Agents here operate with delegated
              authority and must escalate to MSO for protected actions.
            </p>

            {/* Available Agents — fetched from backend registry */}
            <div className="space-y-2">
              <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">
                Available Agents
              </p>

              {registryLoading && (
                <p className="text-xs font-mono text-tx-muted">Loading registry…</p>
              )}

              {!registryLoading && agents.length === 0 && (
                <p className="text-xs font-mono text-tx-muted">No agents registered</p>
              )}

              {agents.map((agent) => (
                <button
                  key={agent.id}
                  onClick={() => setActiveAgent(agent.id)}
                  className="
                    w-full flex items-center gap-4 px-4 py-3 rounded-xl
                    bg-slate-600/10 border border-slate-600/20
                    hover:bg-slate-600/20 hover:border-slate-600/30
                    transition-all
                  "
                >
                  <div className="w-10 h-10 rounded-lg bg-slate-600/30 border border-slate-500/30 flex items-center justify-center">
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-slate-300">
                      <rect x="2" y="2" width="16" height="12" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
                      <path d="M5 18h10M7 14v4M13 14v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                      <path d="M5 6h10M5 9h7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                    </svg>
                  </div>
                  <div className="flex-1 text-left">
                    <span className="text-sm font-mono font-medium text-tx-primary block">
                      {agent.name ?? agent.id}
                    </span>
                    <span className="text-[10px] font-mono text-tx-muted">
                      {agent.capabilities.slice(0, 2).join(', ') || 'No capabilities listed'}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className={`w-1.5 h-1.5 rounded-full ${
                      agent.status === 'active' ? 'bg-green-400' :
                      agent.status === 'degraded' ? 'bg-yellow-400' :
                      'bg-slate-400'
                    }`} />
                    <span className="text-[10px] font-mono text-slate-400 uppercase">
                      {agent.status}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Render specific agent console
  if (agentId === 'machine_operator') {
    return <MachineOperatorConsole />
  }

  // Fallback for agents registered in backend but without a UI console yet
  return (
    <div className="flex items-center justify-center h-full">
      <p className="text-sm font-mono text-tx-muted">
        Agent <span className="text-tx-primary">{agentId}</span> — console not yet available
      </p>
    </div>
  )
}
