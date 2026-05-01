'use client'

import { useUIStore } from '@/stores/ui-store'
import { useSovereignStore } from '@/stores/sovereign-store'
import { useCognitionStore } from '@/stores/cognition-store'
import type { ReadinessSourceStatus } from '@/lib/sovereign/types'
import type { HealthStatus, OperationalMode } from '@/lib/types'

// ── Color maps ────────────────────────────────────────────────────────────────

const HEALTH_DOT: Record<HealthStatus, string> = {
  ok:       'bg-ok',
  warn:     'bg-warn',
  degraded: 'bg-warn',
  down:     'bg-err',
  unknown:  'bg-idle',
}

const HEALTH_TEXT: Record<HealthStatus, string> = {
  ok:       'text-ok',
  warn:     'text-warn',
  degraded: 'text-warn',
  down:     'text-err',
  unknown:  'text-tx-muted',
}

const HEALTH_LABEL: Record<HealthStatus, string> = {
  ok:       'Online',
  warn:     'Warning',
  degraded: 'Degraded',
  down:     'Offline',
  unknown:  'Unknown',
}

const MODE_DOT: Record<OperationalMode, string> = {
  NORMAL:   'bg-ok',
  DEGRADED: 'bg-warn',
  FROZEN:   'bg-err',
  UNKNOWN:  'bg-idle',
}

const MODE_TEXT: Record<OperationalMode, string> = {
  NORMAL:   'text-ok',
  DEGRADED: 'text-warn',
  FROZEN:   'text-err',
  UNKNOWN:  'text-tx-muted',
}

const SOURCE_DOT: Record<ReadinessSourceStatus, string> = {
  available:   'bg-ok',
  empty:       'bg-idle',
  loading:     'bg-idle animate-pulse',
  stale:       'bg-warn',
  unavailable: 'bg-err',
  unknown:     'bg-idle',
}

const SOURCE_TEXT: Record<ReadinessSourceStatus, string> = {
  available:   'text-ok',
  empty:       'text-tx-muted',
  loading:     'text-tx-muted',
  stale:       'text-warn',
  unavailable: 'text-err',
  unknown:     'text-tx-muted',
}

// ── Row ───────────────────────────────────────────────────────────────────────

function Row({
  label,
  dotClass,
  value,
  textClass,
}: {
  label: string
  dotClass: string
  value: string
  textClass?: string
}) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5">
      <span className="text-xs font-mono text-tx-secondary">{label}</span>
      <div className="flex items-center gap-2">
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotClass}`} />
        <span className={`text-xs font-mono ${textClass ?? 'text-tx-secondary'}`}>{value}</span>
      </div>
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ReadinessPanel() {
  const { systemData } = useUIStore()
  const { systemState } = useSovereignStore()
  const { providers, pollError, lastPolled } = useCognitionStore()

  const { apiStatus, webhookStatus, operationalMode, activeExecutions } = systemData
  const { agentRegistrySource, capabilitiesSource, registeredAgents } = systemState

  // Code API row
  const codeApiDot   = HEALTH_DOT[apiStatus]
  const codeApiText  = HEALTH_TEXT[apiStatus]
  const codeApiValue = HEALTH_LABEL[apiStatus]

  // Webhook row — transport reachability only; ok does not mean system is healthy
  const webhookDot   = HEALTH_DOT[webhookStatus]
  const webhookText  = HEALTH_TEXT[webhookStatus]
  const webhookValue = webhookStatus === 'ok'
    ? 'Reachable (transport only)'
    : HEALTH_LABEL[webhookStatus]

  // Operational Mode row — UNKNOWN stays UNKNOWN, never coerced to NORMAL
  const modeDot   = MODE_DOT[operationalMode]
  const modeText  = MODE_TEXT[operationalMode]
  const modeValue = operationalMode

  // Agent Registry row — source status drives the value; count only when meaningful
  const regStatus = agentRegistrySource.status
  const regDot    = SOURCE_DOT[regStatus]
  const regText   = SOURCE_TEXT[regStatus]
  const regCount  = registeredAgents.length
  const regValue  =
    regStatus === 'available'   ? `${regCount} registered` :
    regStatus === 'empty'       ? 'Confirmed empty (0 agents)' :
    regStatus === 'stale'       ? `${regCount} last known (stale — check failed)` :
    regStatus === 'unavailable' ? 'Unavailable' :
    regStatus === 'loading'     ? 'Loading…' :
                                  'Unknown'

  // Capabilities row — source status only; payload is not stored in the frontend
  const capStatus = capabilitiesSource.status
  const capDot    = SOURCE_DOT[capStatus]
  const capText   = SOURCE_TEXT[capStatus]
  const capValue  =
    capStatus === 'available'   ? 'Source reachable' :
    capStatus === 'empty'       ? 'Source empty' :
    capStatus === 'stale'       ? 'Source stale' :
    capStatus === 'unavailable' ? 'Source unreachable' :
    capStatus === 'loading'     ? 'Loading…' :
                                  'Source unknown'

  // Executions row — qualify with Code API state; avoid calling it "stale" when never fetched
  const execDot   = apiStatus === 'ok' ? 'bg-ok' : HEALTH_DOT[apiStatus]
  const execText  = apiStatus === 'ok' ? 'text-ok' : HEALTH_TEXT[apiStatus]
  const execValue = apiStatus === 'ok'
    ? String(activeExecutions)
    : `${activeExecutions} — Code API ${HEALTH_LABEL[apiStatus].toLowerCase()}`

  // Cognition row — explicit state machine across poll/error/provider combinations
  const onlineProviders = providers.filter(p => p.status === 'online').length
  const totalProviders  = providers.length
  const neverPolled     = lastPolled == null && pollError == null
  const pollFailed      = pollError != null

  let cogDot: string
  let cogText: string
  let cogValue: string

  if (neverPolled) {
    // No poll attempt yet — genuinely unknown
    cogDot   = 'bg-idle'
    cogText  = 'text-tx-muted'
    cogValue = 'Not yet polled'
  } else if (pollFailed && lastPolled == null) {
    // Failed on first attempt — no prior data
    cogDot   = 'bg-err'
    cogText  = 'text-err'
    cogValue = 'Poll failed — no data'
  } else if (pollFailed) {
    // Failed but have prior provider list — stale
    cogDot   = 'bg-warn'
    cogText  = 'text-warn'
    cogValue = totalProviders === 0
      ? 'Poll error (no prior providers)'
      : `${onlineProviders}/${totalProviders} online (stale)`
  } else if (totalProviders === 0) {
    // Good poll, no providers configured
    cogDot   = 'bg-idle'
    cogText  = 'text-tx-muted'
    cogValue = 'No providers configured'
  } else if (onlineProviders === totalProviders) {
    cogDot   = 'bg-ok'
    cogText  = 'text-ok'
    cogValue = `${onlineProviders}/${totalProviders} online`
  } else if (onlineProviders > 0) {
    cogDot   = 'bg-warn'
    cogText  = 'text-warn'
    cogValue = `${onlineProviders}/${totalProviders} online`
  } else {
    cogDot   = 'bg-err'
    cogText  = 'text-err'
    cogValue = `0/${totalProviders} online`
  }

  return (
    <div className="bg-os-surface border border-os-border rounded-lg divide-y divide-os-border">
      <Row label="Code API"          dotClass={codeApiDot} value={codeApiValue} textClass={codeApiText} />
      <Row label="Webhook"           dotClass={webhookDot} value={webhookValue} textClass={webhookText} />
      <Row label="Operational Mode"  dotClass={modeDot}    value={modeValue}    textClass={modeText} />
      <Row label="Agent Registry"    dotClass={regDot}     value={regValue}     textClass={regText} />
      <Row label="Capabilities"      dotClass={capDot}     value={capValue}     textClass={capText} />
      <Row label="Executions"        dotClass={execDot}    value={execValue}    textClass={execText} />
      <Row label="Cognition"         dotClass={cogDot}     value={cogValue}     textClass={cogText} />
      <Row
        label="System Assistant"
        dotClass="bg-idle"
        value="See System Assistant panel"
        textClass="text-tx-muted"
      />
    </div>
  )
}
