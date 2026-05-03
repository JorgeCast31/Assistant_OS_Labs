'use client'

import { create } from 'zustand'
import type { ConfirmPendingResponse } from '@/lib/types'

interface ConfirmPendingState {
  confirmPending: ConfirmPendingResponse | null
  lastPolled: string | null
  isPolling: boolean
  pollError: string | null

  setConfirmPending: (response: ConfirmPendingResponse) => void
  setPolling: (value: boolean) => void
  setPollError: (error: string | null) => void
}

export const useConfirmPendingStore = create<ConfirmPendingState>((set) => ({
  confirmPending: null,
  lastPolled: null,
  isPolling: false,
  pollError: null,

  setConfirmPending: (response) =>
    set({
      confirmPending: response,
      lastPolled: new Date().toISOString(),
      pollError: response.ok ? null : (response.error ?? 'unavailable'),
    }),
  setPolling: (value) => set({ isPolling: value }),
  setPollError: (error) => set({ pollError: error }),
}))
