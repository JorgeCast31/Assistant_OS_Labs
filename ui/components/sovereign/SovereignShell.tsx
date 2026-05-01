'use client'

import { useEffect } from 'react'
import { useSovereignStore } from '@/stores/sovereign-store'
import { checkWebhookHealth } from '@/lib/api'
import { getRegisteredAgents } from '@/lib/sovereign/agents'
import type { SystemHealth } from '@/lib/sovereign/types'
import { SidebarNavigation } from './SidebarNavigation'
import { TopStatusBar } from './TopStatusBar'
import { SystemChatView } from './SystemChatView'
import { MSOView } from './MSOView'
import { AgentPanel } from './AgentPanel'

function toSovereignHealth(s: string): SystemHealth {
  if (s === 'ok')   return 'healthy'
  if (s === 'warn' || s === 'degraded') return 'degraded'
  return 'unavailable'
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SovereignShell() {
  const { activeView, activeAgent, setSystemState, setRegisteredAgents } = useSovereignStore()

  useEffect(() => {
    const poll = async () => {
      const [webhookStatus, agents] = await Promise.all([
        checkWebhookHealth(),
        getRegisteredAgents(),
      ])
      setRegisteredAgents(agents)
      setSystemState({
        health: toSovereignHealth(webhookStatus),
        lastUpdated: new Date().toISOString(),
      })
    }

    poll()
    const interval = setInterval(poll, 20_000)
    return () => clearInterval(interval)
  }, [setSystemState, setRegisteredAgents])

  const renderMainContent = () => {
    switch (activeView) {
      case 'system':
        return <SystemChatView />
      case 'mso':
        return <MSOView />
      case 'agents':
        return <AgentPanel agentId={activeAgent} />
      default:
        return <SystemChatView />
    }
  }

  return (
    <div className="flex h-screen w-screen bg-os-base overflow-hidden text-tx-primary">
      <SidebarNavigation />

      {/* Main column */}
      <div className="flex flex-col flex-1 min-w-0">
        <TopStatusBar />

        <main className="flex-1 overflow-hidden">
          {renderMainContent()}
        </main>
      </div>
    </div>
  )
}
