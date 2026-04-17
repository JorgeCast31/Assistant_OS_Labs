'use client'

/**
 * M29: useCognitionPolling
 *
 * Polls /api/cognition/providers on an interval and writes to cognition-store.
 * Follows the exact pattern of use-system-polling.ts:
 * - Module-level mutex prevents duplicate fetches.
 * - Safe to call in multiple components.
 * - Returns a manual refresh function.
 */
import { useEffect, useRef, useCallback } from 'react'
import { useCognitionStore } from '@/stores/cognition-store'
import type { CognitionProvidersResponse } from '@/lib/types'

const POLL_MS = 30_000

let _fetchInFlight = false

async function fetchProviders(): Promise<CognitionProvidersResponse> {
  const res = await fetch('/api/cognition/providers', { cache: 'no-store' })
  if (!res.ok) throw new Error(`Cognition providers ${res.status}`)
  return res.json() as Promise<CognitionProvidersResponse>
}

export function useCognitionPolling() {
  const setProvidersResponse = useCognitionStore((s) => s.setProvidersResponse)
  const setPolling           = useCognitionStore((s) => s.setPolling)
  const setPollError         = useCognitionStore((s) => s.setPollError)
  const refreshRef           = useRef<() => Promise<void>>(async () => {})

  const refresh = useCallback(async () => {
    if (_fetchInFlight) return
    _fetchInFlight = true
    setPolling(true)
    try {
      const data = await fetchProviders()
      setProvidersResponse(data)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setPollError(msg)
    } finally {
      _fetchInFlight = false
      setPolling(false)
    }
  }, [setProvidersResponse, setPolling, setPollError])

  useEffect(() => { refreshRef.current = refresh })
  useEffect(() => { void refreshRef.current() }, [])
  useEffect(() => {
    const id = setInterval(() => { void refreshRef.current() }, POLL_MS)
    return () => clearInterval(id)
  }, [])

  return { refresh }
}
