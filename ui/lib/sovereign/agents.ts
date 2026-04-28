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

const HELP_TEXT = `Machine Operator — browser capabilities
────────────────────────────────────────
browser.snapshot              DOM snapshot of the current page
browser.screenshot            Screenshot of the current page
browser.read_visible_text     Readable text from the current page
browser.navigate <url>        Navigate to URL

Aliases: snapshot, screenshot, read, navigate`

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

  // Local meta-commands — not fake execution, just UI help
  if (!cmd || cmd === 'help') {
    return { ok: true, output: HELP_TEXT, status: 'completed' }
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
