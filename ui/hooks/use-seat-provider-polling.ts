'use client'

import { useCallback, useEffect, useRef } from 'react'
import { getMSOSeatProvider } from '@/lib/api'
import { useSeatProviderStore } from '@/stores/seat-provider-store'

const POLL_MS = 30_000

let fetchInFlight = false

export function useSeatProviderPolling() {
  const setSeatProvider = useSeatProviderStore((s) => s.setSeatProvider)
  const setPolling = useSeatProviderStore((s) => s.setPolling)
  const setLastPolled = useSeatProviderStore((s) => s.setLastPolled)
  const setPollError = useSeatProviderStore((s) => s.setPollError)
  const refreshRef = useRef<() => Promise<void>>(async () => {})

  const refresh = useCallback(async () => {
    if (fetchInFlight) return
    fetchInFlight = true
    setPolling(true)
    try {
      const result = await getMSOSeatProvider()
      setSeatProvider(result)
      setLastPolled(new Date().toISOString())
      if (!result.ok) {
        setPollError(result.error ?? 'unavailable')
      } else {
        setPollError(null)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setPollError(msg)
    } finally {
      fetchInFlight = false
      setPolling(false)
    }
  }, [setSeatProvider, setPolling, setLastPolled, setPollError])

  refreshRef.current = refresh

  useEffect(() => {
    void refreshRef.current()
    const id = setInterval(() => {
      void refreshRef.current()
    }, POLL_MS)
    return () => clearInterval(id)
  }, [])

  return refresh
}
