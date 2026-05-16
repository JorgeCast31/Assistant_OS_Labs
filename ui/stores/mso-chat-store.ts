import { create } from 'zustand'
import type { SovereignMessage, MSOAgentSeat, MSOInteractionMode, MSOCognitionTier } from '@/lib/sovereign/types'

interface MSOChatState {
  messages: SovereignMessage[]
  isLoading: boolean
  // SPRINT-ALPHA-05.5: operator-selected MSO context controls
  agentSeat: MSOAgentSeat
  interactionMode: MSOInteractionMode
  cognitionTier: MSOCognitionTier
  appendMessage: (message: SovereignMessage) => void
  updateMessage: (id: string, patch: Partial<SovereignMessage>) => void
  setLoading: (loading: boolean) => void
  resetTranscript: () => void
  setAgentSeat: (seat: MSOAgentSeat) => void
  setInteractionMode: (mode: MSOInteractionMode) => void
  setCognitionTier: (tier: MSOCognitionTier) => void
}

export const useMSOChatStore = create<MSOChatState>((set) => ({
  messages: [],
  isLoading: false,
  agentSeat: 'mso',
  interactionMode: 'conversational',
  cognitionTier: 'economic',

  appendMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  updateMessage: (id, patch) =>
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),

  setLoading: (loading) => set({ isLoading: loading }),

  resetTranscript: () => set({ messages: [], isLoading: false }),

  setAgentSeat: (seat) => set({ agentSeat: seat }),

  setInteractionMode: (mode) => set({ interactionMode: mode }),

  setCognitionTier: (tier) => set({ cognitionTier: tier }),
}))
