'use client'

import { create } from 'zustand'
import type { PreparedActionsQueueResponse } from '@/lib/types'

interface PreparedActionsState {
  preparedActions: PreparedActionsQueueResponse | null
  lastPolled: string | null
  isPolling: boolean
  pollError: string | null

  setPreparedActions: (response: PreparedActionsQueueResponse) => void
  setPolling: (value: boolean) => void
  setPollError: (error: string | null) => void
}

export const usePreparedActionsStore = create<PreparedActionsState>((set) => ({
  preparedActions: null,
  lastPolled: null,
  isPolling: false,
  pollError: null,

  setPreparedActions: (response) =>
    set({
      preparedActions: response,
      lastPolled: new Date().toISOString(),
      pollError: response.ok ? null : (response.error ?? 'unavailable'),
    }),
  setPolling: (value) => set({ isPolling: value }),
  setPollError: (error) => set({ pollError: error }),
}))
