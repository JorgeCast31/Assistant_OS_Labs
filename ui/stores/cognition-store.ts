'use client'

/**
 * M29: Cognition store — tracks provider health and cognitive usage policy.
 *
 * All state derives from backend polls — nothing is invented here.
 * The local LLM is represented as a bounded cognitive backend,
 * not as an autonomous agent.
 */
import { create } from 'zustand'
import type {
  CognitionProvider,
  CognitionPolicy,
  CognitionProvidersResponse,
} from '@/lib/types'

interface CognitionState {
  /** True when the backend reports ui_cognition_enabled = true */
  uiEnabled: boolean
  providers: CognitionProvider[]
  policy: CognitionPolicy
  policySetBy: 'user' | 'default'
  /** ISO 8601 timestamp of last successful provider poll, or null */
  lastPolled: string | null
  /** True while a provider health fetch is in-flight */
  isPolling: boolean
  /** Non-fatal error from last poll attempt */
  pollError: string | null

  // Actions
  setProvidersResponse: (res: CognitionProvidersResponse) => void
  setPolicy: (policy: CognitionPolicy) => void
  setPolicySetBy: (by: 'user' | 'default') => void
  setPolling: (v: boolean) => void
  setPollError: (err: string | null) => void
}

export const useCognitionStore = create<CognitionState>((set) => ({
  uiEnabled:    false,
  providers:    [],
  policy:       'auto',
  policySetBy:  'default',
  lastPolled:   null,
  isPolling:    false,
  pollError:    null,

  setProvidersResponse: (res) =>
    set({
      uiEnabled:  res.ui_cognition_enabled,
      providers:  res.providers,
      policy:     res.default_policy,
      lastPolled: new Date().toISOString(),
      pollError:  null,
    }),

  setPolicy:      (policy) => set({ policy }),
  setPolicySetBy: (by)     => set({ policySetBy: by }),
  setPolling:     (v)      => set({ isPolling: v }),
  setPollError:   (err)    => set({ pollError: err }),
}))

// ---------------------------------------------------------------------------
// Derived selectors
// ---------------------------------------------------------------------------

/** Returns the primary local_llm provider entry, or undefined if none. */
export function selectLocalProvider(state: CognitionState): CognitionProvider | undefined {
  return state.providers.find((p) => p.provider_id === 'local_llm')
}
