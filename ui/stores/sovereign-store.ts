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
  RegistryAgent,
  ReadinessSourceState,
} from '@/lib/sovereign/types'

// ── Initial States ────────────────────────────────────────────────────────────

// SOURCE: local interaction state only.
// AuthorityStatus has no 'unknown' value; 'active' is the required initial type.
// This does NOT reflect backend authority health — it reflects whether the
// operator has interacted with MSO in this session. Renderers guard on
// lastDecision/executionState before showing live MSO status indicators.
const INITIAL_MSO_STATE: MSOState = {
  status: 'active',
  currentPlan: null,
  executionState: 'idle',
  lastDecision: null,
  activePolicy: 'default',
}

// SOURCE: read-only poll via SovereignShell (checkWebhookHealth + getRegisteredAgents).
// health               — starts 'unavailable'; updated to real value after first 20s poll.
// totalAgents          — starts 0; derived from registeredAgents.length after first poll.
// activeAgents         — no backend source; stays 0. Renderers show '—/N', not '0/N'.
// msoStatus            — not polled; mirrors msoState.status for legacy reasons only.
// lastUpdated          — null until first successful poll.
// registeredAgents     — empty until first poll; full RegistryAgent[] from /agents/registry.
// agentRegistrySource  — 'unknown' until first poll; updated each poll cycle.
// capabilitiesSource   — 'unknown' until first poll; updated each poll cycle.
const INITIAL_SOURCE_STATE: ReadinessSourceState = {
  status: 'unknown',
  lastCheckedAt: null,
  lastSuccessfulAt: null,
  error: null,
}

const INITIAL_SYSTEM_STATE: SovereignSystemState = {
  health: 'unavailable',
  msoStatus: 'active',
  activeAgents: 0,
  totalAgents: 0,
  lastUpdated: null,
  registeredAgents: [],
  agentRegistrySource: INITIAL_SOURCE_STATE,
  capabilitiesSource: INITIAL_SOURCE_STATE,
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

  // ALFA-FLIGHT-02 §3 — when a surface redirects the operator (e.g. System
  // Chat → MSO Direct), it stashes the original text here. The destination
  // surface picks it up on mount and pre-fills its composer, so the operator
  // does not have to retype. Cleared by the consumer immediately after read.
  pendingRedirectText: string | null

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
  setRegisteredAgents: (agents: RegistryAgent[]) => void

  // Actions - Escalations
  addEscalation: (escalation: EscalationRequest) => void
  removeEscalation: (id: string) => void
  clearEscalations: () => void

  // Actions - Redirect handoff
  setPendingRedirectText: (text: string | null) => void
  consumePendingRedirectText: () => string | null
}

// ── Store ─────────────────────────────────────────────────────────────────────

export const useSovereignStore = create<SovereignState>((set, get) => ({
  // Navigation
  activeView: 'sovereign-status',
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

  // ALFA-FLIGHT-02 §3 — redirect handoff buffer
  pendingRedirectText: null,

  // Navigation actions
  setActiveView: (view) => set({ activeView: view }),
  setActiveAgent: (agent) => set((state) => ({
    activeAgent: agent,
    // Only switch to 'agents' when selecting an agent; don't change view when clearing agent
    activeView: agent ? 'agents' : state.activeView,
  })),

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

  setRegisteredAgents: (agents) => set((state) => ({
    systemState: { ...state.systemState, registeredAgents: agents, totalAgents: agents.length },
  })),

  // Escalation actions
  addEscalation: (escalation) => set((state) => ({
    pendingEscalations: [...state.pendingEscalations, escalation],
  })),

  removeEscalation: (id) => set((state) => ({
    pendingEscalations: state.pendingEscalations.filter((e) => e.id !== id),
  })),

  clearEscalations: () => set({ pendingEscalations: [] }),

  // Redirect handoff actions
  setPendingRedirectText: (text: string | null) => set({ pendingRedirectText: text }),
  consumePendingRedirectText: (): string | null => {
    const text = get().pendingRedirectText
    if (text != null) set({ pendingRedirectText: null })
    return text
  },
}))

