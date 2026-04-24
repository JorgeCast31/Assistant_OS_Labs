'use client'

import Link from 'next/link'
import { useSovereignStore } from '@/stores/sovereign-store'
import { StatusIndicator } from './StatusIndicator'
import type { SovereignViewId } from '@/lib/sovereign/types'

function IconHome() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M2 6L7 2l5 4v6a1 1 0 01-1 1H3a1 1 0 01-1-1V6z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M5 13V8h4v5" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  )
}

// ── Zone Configuration ────────────────────────────────────────────────────────

interface ZoneConfig {
  id: SovereignViewId
  label: string
  sublabel: string
  icon: React.ReactNode
  color: {
    active: string
    inactive: string
    border: string
    bg: string
  }
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function IconSystem() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <circle cx="9" cy="9" r="3" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="9" cy="9" r="7" stroke="currentColor" strokeWidth="1.3" strokeDasharray="2 2" />
    </svg>
  )
}

function IconMSO() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <path d="M9 2L16 6V12L9 16L2 12V6L9 2Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M9 6V10M9 12V12.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function IconAgents() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="3" y="3" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.3" />
      <rect x="10" y="3" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.3" />
      <rect x="3" y="10" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.3" />
      <path d="M10 12.5h5M12.5 10v5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  )
}

function IconMachineOp() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="2" y="2" width="10" height="8" rx="1" stroke="currentColor" strokeWidth="1.2" />
      <path d="M4 12h6M5 10v2M9 10v2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M4 5h6M4 7h4" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
    </svg>
  )
}

// ── Zone Definitions ──────────────────────────────────────────────────────────

const ZONES: ZoneConfig[] = [
  {
    id: 'system',
    label: 'System',
    sublabel: 'Informational Layer',
    icon: <IconSystem />,
    color: {
      active: 'text-teal-400',
      inactive: 'text-slate-500',
      border: 'border-teal-400/30',
      bg: 'bg-teal-400/10',
    },
  },
  {
    id: 'mso',
    label: 'MSO',
    sublabel: 'Sovereign Layer',
    icon: <IconMSO />,
    color: {
      active: 'text-amber-400',
      inactive: 'text-slate-500',
      border: 'border-amber-400/30',
      bg: 'bg-amber-400/10',
    },
  },
  {
    id: 'agents',
    label: 'Agents',
    sublabel: 'Operational Layer',
    icon: <IconAgents />,
    color: {
      active: 'text-slate-300',
      inactive: 'text-slate-500',
      border: 'border-slate-400/30',
      bg: 'bg-slate-400/10',
    },
  },
]

// ── Component ─────────────────────────────────────────────────────────────────

export function SidebarNavigation() {
  const { 
    activeView, 
    setActiveView, 
    activeAgent, 
    setActiveAgent,
    msoState,
    agentState,
    pendingEscalations,
  } = useSovereignStore()

  return (
    <aside className="flex flex-col w-60 bg-os-base border-r border-os-border h-full flex-shrink-0">
      {/* Brand */}
      <div className="flex items-center gap-3 px-4 py-4 border-b border-os-border">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500/20 to-amber-500/20 border border-os-border-hi flex items-center justify-center">
          <span className="text-teal-400 text-sm font-bold font-mono">S</span>
        </div>
        <div>
          <span className="text-tx-primary text-sm font-mono font-semibold tracking-tight block">
            Sovereign
          </span>
          <span className="text-tx-muted text-[10px] font-mono">
            Operating Interface
          </span>
        </div>
      </div>

      {/* Home Link */}
      <div className="px-3 pt-3 pb-1">
        <Link
          href="/"
          className="flex items-center gap-2 px-3 py-2 rounded-lg text-slate-500 hover:text-tx-secondary hover:bg-os-surface transition-colors duration-100 border border-transparent"
        >
          <IconHome />
          <span className="text-xs font-mono font-medium">Home</span>
        </Link>
      </div>

      {/* Zones */}
      <nav className="flex-1 px-3 py-3 space-y-1">
        {ZONES.map((zone) => {
          const isActive = activeView === zone.id
          const color = zone.color
          
          return (
            <div key={zone.id}>
              <button
                onClick={() => {
                  setActiveView(zone.id)
                  if (zone.id !== 'agents') {
                    setActiveAgent(null)
                  }
                }}
                className={`
                  w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left
                  transition-all duration-150
                  ${isActive 
                    ? `${color.bg} ${color.border} border ${color.active}` 
                    : `${color.inactive} hover:bg-os-surface hover:text-tx-secondary border border-transparent`
                  }
                `}
              >
                <span className={isActive ? color.active : color.inactive}>
                  {zone.icon}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-mono font-medium">
                      {zone.label}
                    </span>
                    {zone.id === 'mso' && (
                      <StatusIndicator 
                        type="authority" 
                        status={msoState.status} 
                        size="sm" 
                        pulse={msoState.status === 'deciding'}
                      />
                    )}
                    {zone.id === 'agents' && pendingEscalations.length > 0 && (
                      <span className="px-1.5 py-0.5 text-[9px] font-mono bg-amber-500/20 text-amber-400 rounded">
                        {pendingEscalations.length}
                      </span>
                    )}
                  </div>
                  <span className="text-[10px] font-mono text-slate-600 block">
                    {zone.sublabel}
                  </span>
                </div>
                {isActive && (
                  <span className={`w-1 h-4 rounded-full ${color.active.replace('text-', 'bg-')}`} />
                )}
              </button>

              {/* Agent Submenu */}
              {zone.id === 'agents' && isActive && (
                <div className="ml-8 mt-1 space-y-0.5">
                  <button
                    onClick={() => setActiveAgent('machine_operator')}
                    className={`
                      w-full flex items-center gap-2 px-2.5 py-2 rounded text-left
                      transition-colors duration-100
                      ${activeAgent === 'machine_operator'
                        ? 'bg-slate-700/50 text-slate-200 border border-slate-600/50'
                        : 'text-slate-500 hover:text-slate-400 hover:bg-os-surface border border-transparent'
                      }
                    `}
                  >
                    <IconMachineOp />
                    <span className="text-xs font-mono">Machine Operator</span>
                    <StatusIndicator 
                      type="agent" 
                      status={agentState.status} 
                      size="sm" 
                    />
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-os-border">
        <p className="text-[10px] font-mono text-tx-muted">
          Alpha v0.1 · <span className="text-teal-500/60">sovereign</span>
        </p>
      </div>
    </aside>
  )
}
