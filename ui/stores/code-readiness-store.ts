'use client'

/**
 * S-CODE-READINESS-01D — CODE readiness store.
 *
 * Read-only passive state derived from backend polls of /api/code/readiness.
 * Nothing is invented here. Readiness is NOT authority.
 */
import { create } from 'zustand'
import type { CodeReadinessResponse } from '@/lib/types'

interface CodeReadinessState {
  /** Last full readiness payload from the backend, or null until first poll. */
  readiness: CodeReadinessResponse | null
  /** ISO 8601 timestamp of last successful poll, or null. */
  lastPolled: string | null
  /** True while a fetch is in-flight. */
  isPolling: boolean
  /** Non-fatal error from last poll attempt, or null. */
  pollError: string | null

  // Actions
  setReadiness: (r: CodeReadinessResponse) => void
  setPolling: (v: boolean) => void
  setPollError: (err: string | null) => void
}

export const useCodeReadinessStore = create<CodeReadinessState>((set) => ({
  readiness:  null,
  lastPolled: null,
  isPolling:  false,
  pollError:  null,

  setReadiness: (r) =>
    set({
      readiness:  r,
      lastPolled: new Date().toISOString(),
      pollError:  r.ok ? null : (r.error ?? 'unavailable'),
    }),
  setPolling:   (v)   => set({ isPolling: v }),
  setPollError: (err) => set({ pollError: err }),
}))
