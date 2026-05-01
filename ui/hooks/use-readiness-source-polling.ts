'use client'

// Polls agent registry and capabilities; writes sources to sovereign-store.
import { useEffect, useRef, useCallback } from 'react'
import { useSovereignStore } from '@/stores/sovereign-store'
import { fetchAgentRegistryWithMeta } from '@/lib/sovereign/agents'
import { getSystemCapabilities } from '@/lib/api'
import type { ReadinessSourceState } from '@/lib/sovereign/types'

const POLL_MS = 20_000

// Module-level mutex — shared across all hook instances.
// Prevents concurrent fetches even if the hook is called in multiple components.
let _fetchInFlight = false

export function useReadinessSourcePolling() {
  const setSystemState      = useSovereignStore(s => s.setSystemState)
  const setRegisteredAgents = useSovereignStore(s => s.setRegisteredAgents)
  const refreshRef          = useRef<() => Promise<void>>(async () => {})

  const refresh = useCallback(async () => {
    if (_fetchInFlight) return
    _fetchInFlight = true
    try {
      // Read current source states to pass prevSource for stale detection
      const currentState = useSovereignStore.getState().systemState
      const prevAgentSrc = currentState.agentRegistrySource
      const prevCapSrc   = currentState.capabilitiesSource

      const checkedAt = new Date().toISOString()

      const [agentSettled, capSettled] = await Promise.allSettled([
        fetchAgentRegistryWithMeta(prevAgentSrc),
        getSystemCapabilities(),
      ])

      const agentResult = agentSettled.status === 'fulfilled'
        ? agentSettled.value
        : { agents: [], source: { status: 'unavailable' as const, lastCheckedAt: checkedAt, lastSuccessfulAt: prevAgentSrc.lastSuccessfulAt, error: 'fetch rejected' } }

      const capResult = capSettled.status === 'fulfilled'
        ? capSettled.value
        : { ok: false as const, capabilities: [], domains: [], error: 'fetch rejected' }

      const hadPriorCapSuccess = prevCapSrc.lastSuccessfulAt != null
      let capabilitiesSource: ReadinessSourceState

      if (!capResult.ok) {
        capabilitiesSource = {
          status: hadPriorCapSuccess ? 'stale' : 'unavailable',
          lastCheckedAt: checkedAt,
          lastSuccessfulAt: prevCapSrc.lastSuccessfulAt,
          error: capResult.error ?? 'Capabilities unavailable',
        }
      } else {
        const hasData = capResult.capabilities.length > 0 || capResult.domains.length > 0
        capabilitiesSource = {
          status: hasData ? 'available' : 'empty',
          lastCheckedAt: checkedAt,
          lastSuccessfulAt: checkedAt,
          error: null,
        }
      }

      // blanking agents on transient failure would erase visible UI data
      if (agentResult.source.status !== 'stale') {
        setRegisteredAgents(agentResult.agents)
      }
      setSystemState({
        agentRegistrySource: agentResult.source,
        capabilitiesSource,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      const checkedAt = new Date().toISOString()
      const { agentRegistrySource: prevAgentSrc, capabilitiesSource: prevCapSrc } =
        useSovereignStore.getState().systemState
      setSystemState({
        agentRegistrySource: {
          status: prevAgentSrc.lastSuccessfulAt != null ? 'stale' : 'unavailable',
          lastCheckedAt: checkedAt,
          lastSuccessfulAt: prevAgentSrc.lastSuccessfulAt,
          error: msg,
        },
        capabilitiesSource: {
          status: prevCapSrc.lastSuccessfulAt != null ? 'stale' : 'unavailable',
          lastCheckedAt: checkedAt,
          lastSuccessfulAt: prevCapSrc.lastSuccessfulAt,
          error: msg,
        },
      })
    } finally {
      _fetchInFlight = false
    }
  }, [setSystemState, setRegisteredAgents])

  // Keep ref always pointing to latest refresh (stable interval callback)
  useEffect(() => { refreshRef.current = refresh })

  // Fetch on mount (only the first mounted instance will actually run due to mutex)
  useEffect(() => { void refreshRef.current() }, [])

  // Polling interval
  useEffect(() => {
    const id = setInterval(() => { void refreshRef.current() }, POLL_MS)
    return () => clearInterval(id)
  }, [])

  return { refresh }
}
