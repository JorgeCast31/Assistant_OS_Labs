'use client'

import { useEffect } from 'react'
import { useSovereignStore } from '@/stores/sovereign-store'
import { checkWebhookHealth } from '@/lib/api'
import type { SystemHealth } from '@/lib/sovereign/types'
import { useReadinessSourcePolling } from '@/hooks/use-readiness-source-polling'
import { useCognitionPolling } from '@/hooks/use-cognition-polling'
import { SidebarNavigation } from './SidebarNavigation'
import { TopStatusBar } from './TopStatusBar'
import { SystemChatView } from './SystemChatView'
import { MSOView } from './MSOView'
import { AgentPanel } from './AgentPanel'
import { SovereignStatusView } from './SovereignStatusView'
import { SecurityView } from './SecurityView'

function toSovereignHealth(s: string): SystemHealth {
  if (s === 'ok')   return 'healthy'
  if (s === 'warn' || s === 'degraded') return 'degraded'
  return 'unavailable'
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SovereignShell() {
  const { activeView, activeAgent, setSystemState } = useSovereignStore()

  // Agent registry + capabilities polling (extracted to reusable hook)
  useReadinessSourcePolling()
  useCognitionPolling()

  // Webhook health polling — separate concern not shared with SystemView
  useEffect(() => {
    const poll = async () => {
      const webhookStatus = await checkWebhookHealth()
      setSystemState({ health: toSovereignHealth(webhookStatus) })
    }
    poll()
    const interval = setInterval(poll, 20_000)
    return () => clearInterval(interval)
  }, [setSystemState])

  const renderMainContent = () => {
    switch (activeView) {
      case 'system':
        return <SystemChatView />
      case 'sovereign-status':
        return <SovereignStatusView />
      case 'security':
        return <SecurityView />
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
