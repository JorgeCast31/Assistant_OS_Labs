'use client'

import { useUIStore }          from '@/stores/ui-store'
import { useSystemPolling }    from '@/hooks/use-system-polling'
import { useCognitionPolling } from '@/hooks/use-cognition-polling'
import { Sidebar }             from './sidebar'
import { TopHUD }              from './top-hud'
import { ChatView }            from '@/components/views/chat-view'
import { ExecutionsView }      from '@/components/views/executions-view'
import { SystemView }          from '@/components/views/system-view'
import { ActionsView }         from '@/components/views/actions-view'
import { SovereignInterface }  from '@/components/sovereign'

export function AppShell() {
  const { activeView } = useUIStore()

  // Starts polling system health for the app lifetime.
  // TopHUD and SystemView read from Zustand — no prop drilling needed.
  useSystemPolling()

  // M29: Starts polling cognition provider health for the app lifetime.
  // CognitivePresenceBadge and CognitiveStatusPanel read from cognition-store.
  useCognitionPolling()

  return (
    <div className="flex h-screen w-screen bg-os-base overflow-hidden text-tx-primary">
      <Sidebar />

      {/* Main column */}
      <div className="flex flex-col flex-1 min-w-0">
        <TopHUD />

        <main className="flex-1 overflow-hidden">
          {activeView === 'chat'       && <ChatView />}
          {activeView === 'sovereign'  && <SovereignInterface />}
          {activeView === 'executions' && <ExecutionsView />}
          {activeView === 'system'     && <SystemView />}
          {activeView === 'actions'    && <ActionsView />}
        </main>
      </div>
    </div>
  )
}
