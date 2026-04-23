// ── Agent Mock Adapter ────────────────────────────────────────────────────────
// Mock implementation for Machine Operator agent until /api/agents/* exists

import type {
  AgentCommand,
  AgentCommandRequest,
  AgentCommandResponse,
  AgentState,
  EscalationRequest,
  AgentId,
} from './types'

// ── Mock State ────────────────────────────────────────────────────────────────

const MOCK_AGENT_STATE: AgentState = {
  id: 'machine_operator',
  name: 'Machine Operator',
  status: 'idle',
  commandHistory: [],
  pendingEscalations: [],
}

// Commands that require authority escalation
const AUTHORITY_COMMANDS = [
  'deploy',
  'execute',
  'run',
  'delete',
  'remove',
  'modify',
  'update',
  'restart',
  'shutdown',
  'kill',
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function genId(): string {
  return `cmd_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
}

function requiresEscalation(command: string): boolean {
  const cmd = command.toLowerCase().trim()
  return AUTHORITY_COMMANDS.some(auth => cmd.startsWith(auth))
}

function generateMockOutput(command: string): string {
  const cmd = command.toLowerCase().trim()
  
  if (cmd.startsWith('status')) {
    return `[Machine Operator] System Status Report
────────────────────────────────────
Core Services:    OPERATIONAL
Memory Usage:     42.3%
CPU Load:         18.7%
Active Processes: 127
Last Health Check: ${new Date().toISOString()}
────────────────────────────────────
All systems nominal.`
  }
  
  if (cmd.startsWith('ls') || cmd.startsWith('list')) {
    return `[Machine Operator] Directory Listing
────────────────────────────────────
drwxr-xr-x  system/
drwxr-xr-x  agents/
drwxr-xr-x  policies/
-rw-r--r--  config.yaml
-rw-r--r--  state.json
────────────────────────────────────
5 items total`
  }
  
  if (cmd.startsWith('health') || cmd.startsWith('check')) {
    return `[Machine Operator] Health Check
────────────────────────────────────
API Gateway:     OK (12ms)
Database:        OK (8ms)
Cache Layer:     OK (3ms)
Message Queue:   OK (5ms)
MSO Authority:   ACTIVE
────────────────────────────────────
All endpoints responding.`
  }
  
  if (cmd.startsWith('logs') || cmd.startsWith('log')) {
    return `[Machine Operator] Recent Logs
────────────────────────────────────
[${new Date(Date.now() - 5000).toISOString()}] INFO  Request processed
[${new Date(Date.now() - 3000).toISOString()}] INFO  Cache refreshed
[${new Date(Date.now() - 1000).toISOString()}] INFO  Health check passed
[${new Date().toISOString()}] INFO  Command received
────────────────────────────────────`
  }
  
  if (cmd.startsWith('help')) {
    return `[Machine Operator] Available Commands
────────────────────────────────────
status    - System status overview
health    - Health check all services
list      - List directory contents
logs      - View recent log entries
info      - Agent information

Commands requiring MSO authorization:
  deploy, execute, run, delete, modify,
  update, restart, shutdown
────────────────────────────────────`
  }
  
  if (cmd.startsWith('info')) {
    return `[Machine Operator] Agent Information
────────────────────────────────────
Agent ID:     machine_operator
Version:      1.0.0-alpha
Uptime:       4h 23m 17s
Authority:    DELEGATED (MSO)
Capabilities: read, query, monitor
────────────────────────────────────`
  }
  
  return `[Machine Operator] Command executed: ${command}
Output: Operation completed successfully.`
}

function generateEscalation(command: string): EscalationRequest {
  const cmd = command.toLowerCase().trim()
  const action = cmd.split(' ')[0]
  
  let riskLevel: EscalationRequest['riskLevel'] = 'medium'
  if (['delete', 'remove', 'shutdown', 'kill'].some(r => cmd.includes(r))) {
    riskLevel = 'high'
  } else if (['deploy', 'execute', 'run'].some(r => cmd.includes(r))) {
    riskLevel = 'medium'
  }
  
  return {
    id: genId(),
    agentId: 'machine_operator',
    reason: `Command "${action}" requires MSO authorization to proceed.`,
    suggestedCommand: `authorize agent:machine_operator action:${action} ${command.slice(action.length).trim()}`,
    riskLevel,
    timestamp: new Date().toISOString(),
  }
}

// ── Mock API ──────────────────────────────────────────────────────────────────

/**
 * Execute a command on the Machine Operator agent (mock)
 */
export async function executeAgentCommand(
  request: AgentCommandRequest
): Promise<AgentCommandResponse> {
  // Simulate network delay
  await new Promise(resolve => setTimeout(resolve, 300 + Math.random() * 400))
  
  const { command } = request
  
  // Check if command requires escalation
  if (requiresEscalation(command)) {
    const escalation = generateEscalation(command)
    return {
      ok: true,
      output: `[Machine Operator] Authorization required.
This command requires MSO approval before execution.`,
      status: 'escalated',
      escalation,
    }
  }
  
  // Execute mock command
  const output = generateMockOutput(command)
  
  return {
    ok: true,
    output,
    status: 'completed',
  }
}

/**
 * Get current agent state (mock)
 */
export function getAgentState(agentId: AgentId): AgentState {
  if (agentId === 'machine_operator') {
    return { ...MOCK_AGENT_STATE }
  }
  throw new Error(`Unknown agent: ${agentId}`)
}

/**
 * Get list of available agents (mock)
 */
export function getAvailableAgents(): Array<{ id: AgentId; name: string; status: string }> {
  return [
    { id: 'machine_operator', name: 'Machine Operator', status: 'idle' },
  ]
}
