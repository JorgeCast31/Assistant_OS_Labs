'use client'

import { useCallback, useEffect, useRef } from 'react'
import { getAuthorityStatus } from '@/lib/api'
import { useAuthorityStatusStore } from '@/stores/authority-status-store'

const POLL_MS = 30_000

let fetchInFlight = false

export function useAuthorityStatusPolling() {
  const setAuthorityStatus = useAuthorityStatusStore((s) => s.setAuthorityStatus)
  const setPolling = useAuthorityStatusStore((s) => s.setPolling)
  const setPollError = useAuthorityStatusStore((s) => s.setPollError)
  const refreshRef = useRef<() => Promise<void>>(async () => {})

  const refresh = useCallback(async () => {
    if (fetchInFlight) return
    fetchInFlight = true
    setPolling(true)
    try {
      const result = await getAuthorityStatus()
      setAuthorityStatus(result)
      if (!result.ok) setPollError(result.error ?? 'unavailable')
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setPollError(msg)
    } finally {
      fetchInFlight = false
      setPolling(false)
    }
  }, [setAuthorityStatus, setPolling, setPollError])

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
