'use client'

import { create } from 'zustand'
import type {
  SovereignViewId,
  AgentId,
  AuthorityStatus,
  SystemHealth,
  SovereignMessage,
  MSOState,
  AgentState,
  SovereignSystemState,
  EscalationRequest,
} from '@/lib/sovereign/types'

// ── Initial States ────────────────────────────────────────────────────────────

const INITIAL_MSO_STATE: MSOState = {
  status: 'active',
  currentPlan: null,
  executionState: 'idle',
  lastDecision: null,
  activePolicy: 'default',
}

const INITIAL_SYSTEM_STATE: SovereignSystemState = {
  health: 'healthy',
  msoStatus: 'active',
  activeAgents: 1,
  totalAgents: 1,
  lastUpdated: null,
}

const INITIAL_AGENT_STATE: AgentState = {
  id: 'machine_operator',
  name: 'Machine Operator',
  status: 'idle',
  commandHistory: [],
  pendingEscalations: [],
}

// ── Store Interface ───────────────────────────────────────────────────────────

interface SovereignState {
  // Navigation
  activeView: SovereignViewId
  activeAgent: AgentId | null
  
  // Messages per surface
  systemChatMessages: SovereignMessage[]
  msoMessages: SovereignMessage[]
  
  // States
  msoState: MSOState
  systemState: SovereignSystemState
  agentState: AgentState
  
  // Pending escalations (from agents to MSO)
  pendingEscalations: EscalationRequest[]
  
  // Actions - Navigation
  setActiveView: (view: SovereignViewId) => void
  setActiveAgent: (agent: AgentId | null) => void
  
  // Actions - Messages
  addSystemChatMessage: (msg: SovereignMessage) => void
  addMSOMessage: (msg: SovereignMessage) => void
  updateLastMSOMessage: (update: Partial<SovereignMessage>) => void
  
  // Actions - State updates
  setMSOState: (state: Partial<MSOState>) => void
  setSystemState: (state: Partial<SovereignSystemState>) => void
  setAgentState: (state: Partial<AgentState>) => void
  
  // Actions - Escalations
  addEscalation: (escalation: EscalationRequest) => void
  removeEscalation: (id: string) => void
  clearEscalations: () => void
}

// ── Store ─────────────────────────────────────────────────────────────────────

export const useSovereignStore = create<SovereignState>((set) => ({
  // Navigation
  activeView: 'system',
  activeAgent: null,
  
  // Messages
  systemChatMessages: [],
  msoMessages: [],
  
  // States
  msoState: INITIAL_MSO_STATE,
  systemState: INITIAL_SYSTEM_STATE,
  agentState: INITIAL_AGENT_STATE,
  
  // Pending escalations
  pendingEscalations: [],
  
  // Navigation actions
  setActiveView: (view) => set({ activeView: view }),
  setActiveAgent: (agent) => set({ 
    activeAgent: agent,
    activeView: agent ? 'agents' : 'system',
  }),
  
  // Message actions
  addSystemChatMessage: (msg) => set((state) => ({
    systemChatMessages: [...state.systemChatMessages, msg],
  })),
  
  addMSOMessage: (msg) => set((state) => ({
    msoMessages: [...state.msoMessages, msg],
  })),
  
  updateLastMSOMessage: (update) => set((state) => {
    const messages = [...state.msoMessages]
    if (messages.length > 0) {
      messages[messages.length - 1] = { ...messages[messages.length - 1], ...update }
    }
    return { msoMessages: messages }
  }),
  
  // State updates
  setMSOState: (update) => set((state) => ({
    msoState: { ...state.msoState, ...update },
    systemState: {
      ...state.systemState,
      msoStatus: update.status ?? state.msoState.status,
    },
  })),
  
  setSystemState: (update) => set((state) => ({
    systemState: { ...state.systemState, ...update },
  })),
  
  setAgentState: (update) => set((state) => ({
    agentState: { ...state.agentState, ...update },
  })),
  
  // Escalation actions
  addEscalation: (escalation) => set((state) => ({
    pendingEscalations: [...state.pendingEscalations, escalation],
  })),
  
  removeEscalation: (id) => set((state) => ({
    pendingEscalations: state.pendingEscalations.filter((e) => e.id !== id),
  })),
  
  clearEscalations: () => set({ pendingEscalations: [] }),
}))
