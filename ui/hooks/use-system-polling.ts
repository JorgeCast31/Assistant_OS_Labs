'use client'

import { useEffect, useRef, useCallback } from 'react'
import { useUIStore } from '@/stores/ui-store'
import { getSystemHealth, checkWebhookHealth, getExecutions } from '@/lib/api'
import type { SystemData } from '@/lib/types'

const POLL_MS = 20_000
const ACTIVE_STATUSES = new Set(['running', 'pending'])

// Module-level mutex — shared across all hook instances.
// Prevents concurrent fetches even if the hook is called in multiple components.
let _fetchInFlight = false

async function fetchSystemData(): Promise<SystemData> {
  const [apiResult, webhookResult, execsResult] = await Promise.allSettled([
    getSystemHealth(),
    checkWebhookHealth(),
    getExecutions(),
  ])

  const apiStatus     = apiResult.status     === 'fulfilled' ? apiResult.value     : ('down' as const)
  const webhookStatus = webhookResult.status === 'fulfilled' ? webhookResult.value : ('down' as const)
  const execs         = execsResult.status   === 'fulfilled' ? execsResult.value   : null
  const prev          = useUIStore.getState().systemData

  return {
    apiStatus,
    webhookStatus,
    activeExecutions: execs !== null
      ? execs.filter(e => ACTIVE_STATUSES.has(e.final_status)).length
      : prev.activeExecutions,
    needsReview: execs !== null
      ? execs.filter(e => e.final_status === 'needs_review').length
      : prev.needsReview,
    lastUpdated: new Date().toISOString(),
    error: execs === null ? 'No se pudo obtener lista de ejecuciones' : null,
  }
}

/**
 * Polls system health every POLL_MS.
 * Writes to Zustand systemData + isSystemRefreshing.
 * Both TopHUD and SystemView read from the store.
 *
 * Safe to call in multiple components — module-level mutex prevents duplicate fetches.
 * AppShell calls it to keep polling alive regardless of active view.
 * SystemView also calls it to access refresh() for the manual Refresh button.
 */
export function useSystemPolling() {
  const setSystemData       = useUIStore(s => s.setSystemData)
  const setSystemRefreshing = useUIStore(s => s.setSystemRefreshing)
  const refreshRef          = useRef<() => Promise<void>>(async () => {})

  const refresh = useCallback(async () => {
    if (_fetchInFlight) return
    _fetchInFlight = true
    setSystemRefreshing(true)
    try {
      const data = await fetchSystemData()
      setSystemData(data)
    } catch {
      const prev = useUIStore.getState().systemData
      setSystemData({
        ...prev,
        error:       'Error al obtener estado del sistema',
        lastUpdated: new Date().toISOString(),
      })
    } finally {
      _fetchInFlight = false
      setSystemRefreshing(false)
    }
  }, [setSystemData, setSystemRefreshing])

  // Keep ref always pointing to latest refresh (stable interval callback)
  useEffect(() => { refreshRef.current = refresh })

  // Fetch on mount (only the first mounted instance will actually run)
  useEffect(() => { void refreshRef.current() }, [])

  // Polling interval
  useEffect(() => {
    const id = setInterval(() => { void refreshRef.current() }, POLL_MS)
    return () => clearInterval(id)
  }, [])

  return { refresh }
}
