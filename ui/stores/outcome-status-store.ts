'use client'

import { create } from 'zustand'
import type { OutcomeStatusResponse } from '@/lib/types'

interface OutcomeStatusState {
  outcomeStatus: OutcomeStatusResponse | null
  lastPolled: string | null
  isPolling: boolean
  pollError: string | null

  setOutcomeStatus: (response: OutcomeStatusResponse) => void
  setPolling: (value: boolean) => void
  setPollError: (error: string | null) => void
}

export const useOutcomeStatusStore = create<OutcomeStatusState>((set) => ({
  outcomeStatus: null,
  lastPolled: null,
  isPolling: false,
  pollError: null,

  setOutcomeStatus: (response) =>
    set({
      outcomeStatus: response,
      lastPolled: new Date().toISOString(),
      pollError: response.ok ? null : (response.error ?? 'unavailable'),
    }),
  setPolling: (value) => set({ isPolling: value }),
  setPollError: (error) => set({ pollError: error }),
}))
