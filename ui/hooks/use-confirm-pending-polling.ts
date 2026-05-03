'use client'

import { useCallback, useEffect, useRef } from 'react'
import { getConfirmPending } from '@/lib/api'
import { useConfirmPendingStore } from '@/stores/confirm-pending-store'

const POLL_MS = 30_000

let fetchInFlight = false

export function useConfirmPendingPolling() {
  const setConfirmPending = useConfirmPendingStore((s) => s.setConfirmPending)
  const setPolling = useConfirmPendingStore((s) => s.setPolling)
  const setPollError = useConfirmPendingStore((s) => s.setPollError)
  const refreshRef = useRef<() => Promise<void>>(async () => {})

  const refresh = useCallback(async () => {
    if (fetchInFlight) return
    fetchInFlight = true
    setPolling(true)
    try {
      const result = await getConfirmPending()
      setConfirmPending(result)
      if (!result.ok) setPollError(result.error ?? 'unavailable')
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setPollError(msg)
    } finally {
      fetchInFlight = false
      setPolling(false)
    }
  }, [setConfirmPending, setPolling, setPollError])

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
