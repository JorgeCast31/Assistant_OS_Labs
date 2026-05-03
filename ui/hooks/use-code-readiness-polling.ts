'use client'

/**
 * S-CODE-READINESS-01D — polls /api/code/readiness on an interval.
 *
 * Writes the result into useCodeReadinessStore. Read-only — never triggers
 * mutation, never executes code. Errors are surfaced via pollError, never thrown.
 */
import { useEffect, useRef, useCallback } from 'react'
import { useCodeReadinessStore } from '@/stores/code-readiness-store'
import { getCodeReadiness } from '@/lib/api'

const POLL_MS = 20_000

let _fetchInFlight = false

export function useCodeReadinessPolling() {
  const setReadiness = useCodeReadinessStore(s => s.setReadiness)
  const setPolling   = useCodeReadinessStore(s => s.setPolling)
  const setPollError = useCodeReadinessStore(s => s.setPollError)
  const refreshRef   = useRef<() => Promise<void>>(async () => {})

  const refresh = useCallback(async () => {
    if (_fetchInFlight) return
    _fetchInFlight = true
    setPolling(true)
    try {
      const result = await getCodeReadiness()
      setReadiness(result)
      if (!result.ok) setPollError(result.error ?? 'unavailable')
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setPollError(msg)
    } finally {
      _fetchInFlight = false
      setPolling(false)
    }
  }, [setReadiness, setPolling, setPollError])

  refreshRef.current = refresh

  useEffect(() => {
    void refreshRef.current()
    const id = setInterval(() => { void refreshRef.current() }, POLL_MS)
    return () => clearInterval(id)
  }, [])

  return refresh
}
