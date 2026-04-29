// ── Agent Adapter ─────────────────────────────────────────────────────────────
// Real HTTP adapter for the Machine Operator agent.
// Replaces all mock logic — every call goes to /api/agent/execute → webhook.

import type {
  AgentCommandRequest,
  AgentCommandResponse,
  AgentState,
  AgentId,
  ExecutionStatus,
} from './types'

// ── Constants ─────────────────────────────────────────────────────────────────

const ALLOWED_CAPABILITIES = [
  'browser.navigate',
  'browser.snapshot',
  'browser.screenshot',
  'browser.read_visible_text',
] as const

// Short aliases → full capability names
const CAPABILITY_ALIASES: Record<string, string> = {
  navigate:   'browser.navigate',
  snapshot:   'browser.snapshot',
  screenshot: 'browser.screenshot',
  read:       'browser.read_visible_text',
}

// Static portion of the help text. The dynamic state line (registered /
// available / restricted) is prepended at help time after we query the live
// backend registry. We never fake registration state — if the registry is
// unreachable we say so rather than print a stale "registered: yes".
const HELP_TEXT_STATIC = `Machine Operator — browser capabilities
────────────────────────────────────────
browser.snapshot              DOM snapshot of the current page                 [read-only]
browser.screenshot            Screenshot of the current page                   [read-only]
browser.read_visible_text     Readable text from the current page              [read-only]
browser.navigate <url>        Navigate to URL                                  [requires approval]

Aliases: snapshot, screenshot, read, navigate

execution_status legend
  real         capability ran against the real backend
  unavailable  capability could not run (gateway down, missing config, blocked)
  stub         placeholder result; no real action took place
  partial      partial result (e.g. timeout mid-run)`

interface RegistryAgent {
  id?: string
  name?: string
  status?: string
  capabilities?: unknown
  requires_authority?: boolean
  requires_review?: boolean
}

/**
 * Fetch live Machine Operator state from the backend registry via the
 * /api/agents/registry proxy. Returns a multi-line block describing
 * registration status, capability count, and restriction reason. On any
 * failure path (network, non-ok payload) we say so explicitly — never lie
 * about registration state.
 */
async function buildLiveStatusBlock(): Promise<string> {
  try {
    const res = await fetch('/api/agents/registry', { cache: 'no-store' })
    const data = (await res.json()) as { ok?: boolean; agents?: RegistryAgent[]; error?: string }
    if (!res.ok || data.ok === false) {
      const reason = typeof data.error === 'string' ? data.error : `HTTP ${res.status}`
      return [
        'Machine Operator state — UNKNOWN',
        `  reason: registry unreachable (${reason})`,
        '  registered: unknown',
        '  capabilities: unknown',
      ].join('\n')
    }
    const agents = Array.isArray(data.agents) ? data.agents : []
    const mo = agents.find(a => a?.id === 'machine_operator')
    if (!mo) {
      return [
        'Machine Operator state — NOT REGISTERED',
        '  registered: no',
        '  reason: agent id "machine_operator" missing from /agents/registry response',
      ].join('\n')
    }
    const capList = Array.isArray(mo.capabilities)
      ? (mo.capabilities as unknown[]).filter(c => typeof c === 'string') as string[]
      : []
    const status = typeof mo.status === 'string' ? mo.status : 'unknown'
    const requiresAuthority = mo.requires_authority === true
    const requiresReview    = mo.requires_review === true
    const lines = [
      `Machine Operator state — ${status.toUpperCase()}`,
      `  registered: yes (id=machine_operator)`,
      `  capabilities (${capList.length}): ${capList.length > 0 ? capList.join(', ') : '—'}`,
    ]
    if (requiresAuthority) lines.push('  authority: required for write capabilities')
    if (requiresReview)    lines.push('  review: required after execution')
    if (status !== 'available' && status !== 'active' && status !== 'ok') {
      lines.push(`  restriction: status="${status}" — capability gating in effect`)
    }
    return lines.join('\n')
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return [
      'Machine Operator state — UNKNOWN',
      `  reason: registry fetch failed (${msg})`,
      '  registered: unknown',
      '  capabilities: unknown',
    ].join('\n')
  }
}

async function buildHelpText(): Promise<string> {
  const live = await buildLiveStatusBlock()
  return `${live}\n\n${HELP_TEXT_STATIC}`
}

const EXECUTION_STATUSES: ExecutionStatus[] = ['real', 'stub', 'unavailable', 'partial']

function executionStatusOf(value: unknown, fallback: ExecutionStatus): ExecutionStatus {
  return typeof value === 'string' && EXECUTION_STATUSES.includes(value as ExecutionStatus)
    ? value as ExecutionStatus
    : fallback
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDomainResult(
  capability: string,
  executionStatus: ExecutionStatus,
  data: Record<string, unknown>,
  message: string,
): string {
  const statusBadge = `[execution_status: ${executionStatus}]`
  const response = data.machine_operator_response as Record<string, unknown> | undefined
  const observation = response?.observation as Record<string, unknown> | undefined
  const summary = observation?.summary ? String(observation.summary) : ''
  const detail  = observation?.detail  ? String(observation.detail)  : ''

  const lines = [`${statusBadge} ${capability}`]
  if (message) lines.push(message)
  if (summary && summary !== message) lines.push(summary)
  if (detail)  lines.push(detail)
  return lines.filter(Boolean).join('\n')
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Execute a command on the Machine Operator agent via the real webhook backend.
 * Accepts full capability names (browser.*) or short aliases (snapshot, navigate…).
 */
export async function executeAgentCommand(
  request: AgentCommandRequest,
): Promise<AgentCommandResponse> {
  const cmd = request.command.trim()

  // Local meta-commands — not fake execution, just UI help.
  // The help block now leads with live registry state (registered, capabilities,
  // restriction reason) fetched from /api/agents/registry, then lists the
  // static capability table with approval markers. Never fake registration:
  // if the registry is unreachable, the live block says UNKNOWN explicitly.
  if (!cmd || cmd === 'help') {
    const output = await buildHelpText()
    return { ok: true, output, status: 'completed' }
  }

  // Parse: first token is capability/alias; remainder is inline argument
  const [rawCapability, ...rest] = cmd.split(/\s+/)
  const capability = CAPABILITY_ALIASES[rawCapability] ?? rawCapability

  if (!ALLOWED_CAPABILITIES.includes(capability as typeof ALLOWED_CAPABILITIES[number])) {
    const known = ALLOWED_CAPABILITIES.join(', ')
    return {
      ok: false,
      output: `Unknown capability: ${rawCapability}\nAllowed: ${known}\nType 'help' for usage.`,
      status: 'failed',
      error: `Unknown capability: ${rawCapability}`,
    }
  }

  const args: Record<string, string> = {}
  if (rest.length > 0 && capability === 'browser.navigate') {
    args.url = rest.join(' ')
  }

  let data: Record<string, unknown>
  try {
    const res = await fetch('/api/agent/execute', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ capability, arguments: args }),
    })
    data = (await res.json()) as Record<string, unknown>
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return {
      ok:     false,
      output: `[execution_status: unavailable] Network error: ${msg}`,
      status: 'failed',
      error:  `Network error: ${msg}`,
    }
  }

  const executionStatus = executionStatusOf(data.execution_status, 'unavailable')
  const domainData      = (data.data && typeof data.data === 'object')
    ? (data.data as Record<string, unknown>)
    : {}
  const message = String(data.message ?? '')

  if (!data.ok) {
    const rawErr = data.error
    const errMsg = (rawErr && typeof rawErr === 'object' && 'message' in rawErr)
      ? String((rawErr as Record<string, unknown>).message)
      : message || 'Execution failed'
    return {
      ok:     false,
      output: formatDomainResult(capability, executionStatus, domainData, errMsg),
      status: 'failed',
      error:  errMsg,
    }
  }

  return {
    ok:     true,
    output: formatDomainResult(capability, executionStatus, domainData, message),
    status: 'completed',
  }
}

/**
 * Return a snapshot of the agent state (non-reactive; for display only).
 */
export function getAgentState(agentId: AgentId): AgentState {
  return {
    id:                 agentId,
    name:               'Machine Operator',
    status:             'idle',
    commandHistory:     [],
    pendingEscalations: [],
  }
}

/**
 * List available agents from the backend registry.
 */
export async function getAvailableAgents(): Promise<Array<{ id: AgentId; name: string; status: string }>> {
  try {
    const res = await fetch('/api/agents/registry')
    const data = (await res.json()) as { ok?: boolean; agents?: Array<{ id: string; name: string; status: string }> }
    if (data.ok && Array.isArray(data.agents)) {
      return data.agents.map(a => ({ id: a.id, name: a.name ?? a.id, status: a.status ?? 'unknown' }))
    }
  } catch {
    // Fall through to empty on fetch failure
  }
  return []
}
