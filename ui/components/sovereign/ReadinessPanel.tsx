'use client'

import { useUIStore } from '@/stores/ui-store'
import { useSovereignStore } from '@/stores/sovereign-store'
import { useCognitionStore } from '@/stores/cognition-store'
import { useCodeReadinessStore } from '@/stores/code-readiness-store'
import { useCodeReadinessPolling } from '@/hooks/use-code-readiness-polling'
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

  // S-CODE-READINESS-01D: passive CODE readiness — read-only.
  useCodeReadinessPolling()
  const { readiness: codeReadiness } = useCodeReadinessStore()

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

  // Cognition row — explicit state machine across poll/error/provider combinations.
  // disabled providers are feature-flagged off — they are not offline failures.
  const allProviders    = providers
  const activeProviders = allProviders.filter(p => p.status !== 'disabled')
  const onlineProviders = activeProviders.filter(p => p.status === 'online').length
  const totalActive     = activeProviders.length
  const allDisabled     = allProviders.length > 0 && totalActive === 0

  const neverPolled = lastPolled == null && pollError == null
  const pollFailed  = pollError != null

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
    cogValue = totalActive === 0
      ? 'Poll error (no prior providers)'
      : `${onlineProviders}/${totalActive} online (stale)`
  } else if (allProviders.length === 0) {
    // Good poll — backend returned no providers at all
    cogDot   = 'bg-idle'
    cogText  = 'text-tx-muted'
    cogValue = 'No providers configured'
  } else if (allDisabled) {
    // All providers have status='disabled' — feature flag off, not a server failure
    cogDot   = 'bg-idle'
    cogText  = 'text-tx-muted'
    cogValue = 'Cognition disabled'
  } else if (onlineProviders === totalActive) {
    cogDot   = 'bg-ok'
    cogText  = 'text-ok'
    cogValue = `${onlineProviders}/${totalActive} online`
  } else if (onlineProviders > 0) {
    cogDot   = 'bg-warn'
    cogText  = 'text-warn'
    cogValue = `${onlineProviders}/${totalActive} online`
  } else {
    cogDot   = 'bg-err'
    cogText  = 'text-err'
    cogValue = `0/${totalActive} online`
  }

  // ── CODE Readiness rows (S-CODE-READINESS-01D) ────────────────────────────
  // Passive observability surface. NEVER renders authority or action affordances.
  // No buttons. No execution-claim wording. No apply-claim wording.
  // No permission-claim wording. Render only source/config state.
  let codeReadyApiDot   = 'bg-idle'
  let codeReadyApiText  = 'text-tx-muted'
  let codeReadyApiValue = 'Not yet polled'
  let codeApplyValue    = '—'
  let codeApplyText     = 'text-tx-muted'
  let codeRunnerValue   = '—'
  let codeRunnerText    = 'text-tx-muted'
  let codeCapsValue     = '—'
  let codeCapsText      = 'text-tx-muted'

  if (codeReadiness != null) {
    if (codeReadiness.code_api_reachable) {
      codeReadyApiDot   = 'bg-ok'
      codeReadyApiText  = 'text-ok'
      codeReadyApiValue = `Reachable (${codeReadiness.code_api_latency_ms} ms)`
    } else {
      codeReadyApiDot   = 'bg-err'
      codeReadyApiText  = 'text-err'
      codeReadyApiValue = 'Unavailable'
    }

    const mode = codeReadiness.apply_execution_mode || 'unknown'
    codeApplyText  = mode === 'real' ? 'text-warn' : 'text-tx-secondary'
    codeApplyValue = `${mode}${mode === 'stub' ? ' (no real apply)' : ''}`

    if (!codeReadiness.runner_backend_probed) {
      codeRunnerText  = 'text-tx-muted'
      codeRunnerValue = 'Not probed (apply mode stub)'
    } else if (codeReadiness.runner_backend_available === true) {
      codeRunnerText  = 'text-ok'
      codeRunnerValue = 'Daemon reachable (transport only)'
    } else if (codeReadiness.runner_backend_available === false) {
      codeRunnerText  = 'text-err'
      codeRunnerValue = 'Daemon unreachable'
    } else {
      codeRunnerText  = 'text-tx-muted'
      codeRunnerValue = 'Unknown'
    }

    const a = codeReadiness.code_capability_allowed_count
    const c = codeReadiness.code_capability_confirm_only_count
    const b = codeReadiness.code_capability_blocked_count
    codeCapsText  = 'text-tx-secondary'
    codeCapsValue = `${a} allow / ${c} confirm_only / ${b} blocked`
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
      {/* CODE Readiness — passive surface. Readiness is not authority. */}
      <Row label="CODE Readiness · API"        dotClass={codeReadyApiDot} value={codeReadyApiValue} textClass={codeReadyApiText} />
      <Row label="CODE Readiness · Apply mode" dotClass="bg-idle"          value={codeApplyValue}    textClass={codeApplyText} />
      <Row label="CODE Readiness · Runner"     dotClass="bg-idle"          value={codeRunnerValue}   textClass={codeRunnerText} />
      <Row label="CODE Readiness · Capabilities" dotClass="bg-idle"        value={codeCapsValue}     textClass={codeCapsText} />
      <div className="px-4 py-2 text-[10px] font-mono text-tx-muted">
        Readiness is not authority. CODE capabilities are governed by MSO.
      </div>
      <Row
        label="System Assistant"
        dotClass="bg-idle"
        value="See System Assistant panel"
        textClass="text-tx-muted"
      />
    </div>
  )
}
