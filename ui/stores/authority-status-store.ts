'use client'

import { create } from 'zustand'
import type { AuthorityStatusResponse } from '@/lib/types'

interface AuthorityStatusState {
  authorityStatus: AuthorityStatusResponse | null
  lastPolled: string | null
  isPolling: boolean
  pollError: string | null

  setAuthorityStatus: (response: AuthorityStatusResponse) => void
  setPolling: (value: boolean) => void
  setPollError: (error: string | null) => void
}

export const useAuthorityStatusStore = create<AuthorityStatusState>((set) => ({
  authorityStatus: null,
  lastPolled: null,
  isPolling: false,
  pollError: null,

  setAuthorityStatus: (response) =>
    set({
      authorityStatus: response,
      lastPolled: new Date().toISOString(),
      pollError: response.ok ? null : (response.error ?? 'unavailable'),
    }),
  setPolling: (value) => set({ isPolling: value }),
  setPollError: (error) => set({ pollError: error }),
}))
