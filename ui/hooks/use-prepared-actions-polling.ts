'use client'

import { useCallback, useEffect, useRef } from 'react'
import { getPreparedActionsPending } from '@/lib/api'
import { usePreparedActionsStore } from '@/stores/prepared-actions-store'

const POLL_MS = 30_000

let fetchInFlight = false

export function usePreparedActionsPolling() {
  const setPreparedActions = usePreparedActionsStore((s) => s.setPreparedActions)
  const setPolling = usePreparedActionsStore((s) => s.setPolling)
  const setPollError = usePreparedActionsStore((s) => s.setPollError)
  const refreshRef = useRef<() => Promise<void>>(async () => {})

  const refresh = useCallback(async () => {
    if (fetchInFlight) return
    fetchInFlight = true
    setPolling(true)
    try {
      const result = await getPreparedActionsPending()
      setPreparedActions(result)
      if (!result.ok) setPollError(result.error ?? 'unavailable')
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setPollError(msg)
    } finally {
      fetchInFlight = false
      setPolling(false)
    }
  }, [setPreparedActions, setPolling, setPollError])

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
