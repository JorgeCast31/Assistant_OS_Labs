'use client'

import { useEffect } from 'react'
import { useSovereignStore } from '@/stores/sovereign-store'
import { checkWebhookHealth, getSystemCapabilities } from '@/lib/api'
import { fetchAgentRegistryWithMeta } from '@/lib/sovereign/agents'
import type { SystemHealth, ReadinessSourceState } from '@/lib/sovereign/types'
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
      const currentState = useSovereignStore.getState().systemState
      const prevAgentSrc = currentState.agentRegistrySource
      const prevCapSrc = currentState.capabilitiesSource

      const [webhookStatus, agentResult, capResult] = await Promise.all([
        checkWebhookHealth(),
        fetchAgentRegistryWithMeta(prevAgentSrc),
        getSystemCapabilities(),
      ])

      const capCheckedAt = new Date().toISOString()
      const hadPriorCapSuccess = prevCapSrc.lastSuccessfulAt != null
      let capabilitiesSource: ReadinessSourceState
      if (!capResult.ok) {
        capabilitiesSource = {
          status: hadPriorCapSuccess ? 'stale' : 'unavailable',
          lastCheckedAt: capCheckedAt,
          lastSuccessfulAt: prevCapSrc.lastSuccessfulAt,
          error: capResult.error ?? 'Capabilities unavailable',
        }
      } else {
        const hasData = capResult.capabilities.length > 0 || capResult.domains.length > 0
        capabilitiesSource = {
          status: hasData ? 'available' : 'empty',
          lastCheckedAt: capCheckedAt,
          lastSuccessfulAt: capCheckedAt,
          error: null,
        }
      }

      // Preserve prior registeredAgents and totalAgents when stale — clearing
      // them would erase data the stale status is supposed to keep visible.
      if (agentResult.source.status !== 'stale') {
        setRegisteredAgents(agentResult.agents)
      }
      setSystemState({
        health: toSovereignHealth(webhookStatus),
        lastUpdated: capCheckedAt,
        agentRegistrySource: agentResult.source,
        capabilitiesSource,
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
