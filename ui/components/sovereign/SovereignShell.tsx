'use client'

import { useEffect } from 'react'
import { useSovereignStore } from '@/stores/sovereign-store'
import { SidebarNavigation } from './SidebarNavigation'
import { TopStatusBar } from './TopStatusBar'
import { SystemChatView } from './SystemChatView'
import { MSOView } from './MSOView'
import { AgentPanel } from './AgentPanel'

// ── Component ─────────────────────────────────────────────────────────────────

export function SovereignShell() {
  const { activeView, activeAgent, setSystemState } = useSovereignStore()

  // Simulate periodic system state updates
  useEffect(() => {
    const updateState = () => {
      setSystemState({ lastUpdated: new Date().toISOString() })
    }
    
    updateState()
    const interval = setInterval(updateState, 5000)
    return () => clearInterval(interval)
  }, [setSystemState])

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
