'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useUIStore } from '@/stores/ui-store'
import type { ViewId } from '@/lib/types'

function IconSovereign() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M8 1.5L2 5v6l6 3.5 6-3.5V5L8 1.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M8 8v6.5M2 5l6 3 6-3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

interface NavItem {
  id: ViewId
  label: string
  icon: React.ReactNode
}

function IconChat() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M2 3a1 1 0 011-1h10a1 1 0 011 1v7a1 1 0 01-1 1H9l-3 2v-2H3a1 1 0 01-1-1V3z"
        stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  )
}

function IconExecutions() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <rect x="2" y="2" width="5" height="5" rx="0.8" stroke="currentColor" strokeWidth="1.3" />
      <rect x="9" y="2" width="5" height="5" rx="0.8" stroke="currentColor" strokeWidth="1.3" />
      <rect x="2" y="9" width="5" height="5" rx="0.8" stroke="currentColor" strokeWidth="1.3" />
      <path d="M9 11.5h5M11.5 9v5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  )
}

function IconSystem() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <rect x="1.5" y="1.5" width="13" height="10" rx="1.2" stroke="currentColor" strokeWidth="1.3" />
      <path d="M5 14h6M8 11.5V14" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      <circle cx="8" cy="6.5" r="2" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  )
}

function IconActions() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M8 2l1.5 4.5H14l-3.8 2.8 1.5 4.5L8 11.2l-3.7 2.6 1.5-4.5L2 6.5h4.5L8 2z"
        stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  )
}

const NAV_ITEMS: NavItem[] = [
  { id: 'chat',       label: 'Chat',       icon: <IconChat /> },
  { id: 'executions', label: 'Executions', icon: <IconExecutions /> },
  { id: 'system',     label: 'System',     icon: <IconSystem /> },
  { id: 'actions',    label: 'Actions',    icon: <IconActions /> },
]

export function Sidebar() {
  const { activeView, setView } = useUIStore()
  const pathname = usePathname()
  const isSovereignActive = pathname === '/sovereign'

  return (
    <aside className="flex flex-col w-56 bg-os-base border-r border-os-border h-full flex-shrink-0">
      {/* Brand */}
      <div className="flex items-center gap-2.5 px-4 py-4 border-b border-os-border">
        <div className="w-6 h-6 rounded bg-accent/20 border border-accent/40 flex items-center justify-center">
          <span className="text-accent text-xs font-bold font-mono">A</span>
        </div>
        <span className="text-tx-primary text-sm font-mono font-semibold tracking-tight">
          AssistantOS
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-3 space-y-0.5">
        <p className="px-2 pb-2 text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest">
          Navigation
        </p>

        {/* Sovereign Link - above other nav items */}
        <Link
          href="/sovereign"
          className={`
            w-full flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-mono
            transition-colors duration-100 text-left
            ${isSovereignActive
              ? 'bg-accent/15 text-accent border border-accent/25'
              : 'text-tx-secondary hover:bg-os-surface hover:text-tx-primary border border-transparent'
            }
          `}
        >
          <span className={isSovereignActive ? 'text-accent' : 'text-tx-muted'}>
            <IconSovereign />
          </span>
          Sovereign
          {isSovereignActive && (
            <span className="ml-auto w-1 h-1 rounded-full bg-accent" />
          )}
        </Link>

        {NAV_ITEMS.map((item) => {
          const isActive = activeView === item.id
          return (
            <button
              key={item.id}
              onClick={() => setView(item.id)}
              className={`
                w-full flex items-center gap-2.5 px-2.5 py-2 rounded text-sm font-mono
                transition-colors duration-100 text-left
                ${isActive
                  ? 'bg-accent/15 text-accent border border-accent/25'
                  : 'text-tx-secondary hover:bg-os-surface hover:text-tx-primary border border-transparent'
                }
              `}
            >
              <span className={isActive ? 'text-accent' : 'text-tx-muted'}>
                {item.icon}
              </span>
              {item.label}
              {isActive && (
                <span className="ml-auto w-1 h-1 rounded-full bg-accent" />
              )}
            </button>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-os-border">
        <p className="text-[10px] font-mono text-tx-muted">
          Sprint M1 · <span className="text-tx-muted">dev</span>
        </p>
      </div>
    </aside>
  )
}
