import { create } from 'zustand'
import type { SovereignMessage } from '@/lib/sovereign/types'

interface MSOChatState {
  messages: SovereignMessage[]
  isLoading: boolean
  appendMessage: (message: SovereignMessage) => void
  updateMessage: (id: string, patch: Partial<SovereignMessage>) => void
  setLoading: (loading: boolean) => void
  resetTranscript: () => void
}

export const useMSOChatStore = create<MSOChatState>((set) => ({
  messages: [],
  isLoading: false,

  appendMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  updateMessage: (id, patch) =>
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),

  setLoading: (loading) => set({ isLoading: loading }),

  resetTranscript: () => set({ messages: [], isLoading: false }),
}))
