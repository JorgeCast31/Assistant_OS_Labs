'use client'

import { useCallback, useEffect, useRef } from 'react'
import { getOutcomeStatus } from '@/lib/api'
import { useOutcomeStatusStore } from '@/stores/outcome-status-store'

const POLL_MS = 30_000

let fetchInFlight = false

export function useOutcomeStatusPolling() {
  const setOutcomeStatus = useOutcomeStatusStore((s) => s.setOutcomeStatus)
  const setPolling = useOutcomeStatusStore((s) => s.setPolling)
  const setPollError = useOutcomeStatusStore((s) => s.setPollError)
  const refreshRef = useRef<() => Promise<void>>(async () => {})

  const refresh = useCallback(async () => {
    if (fetchInFlight) return
    fetchInFlight = true
    setPolling(true)
    try {
      const result = await getOutcomeStatus()
      setOutcomeStatus(result)
      if (!result.ok) setPollError(result.error ?? 'unavailable')
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setPollError(msg)
    } finally {
      fetchInFlight = false
      setPolling(false)
    }
  }, [setOutcomeStatus, setPolling, setPollError])

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
