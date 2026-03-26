import type { SystemState, HudIndicator } from './types'

// ── System state (mock — M3 will connect to real health endpoint) ─────────────

export const MOCK_SYSTEM: SystemState = {
  assistantStatus: 'ok',
  runnerStatus: 'ok',
  apiStatus: 'ok',
  dbStatus: 'degraded',
  uptimeSeconds: 86400 * 3 + 7200 + 1440, // ~3d 2h 24m
  activeExecutions: 2,
  totalExecutions: 247,
  lastChecked: new Date().toISOString(),
  metrics: [
    { label: 'CPU',           value: '12',  unit: '%',  status: 'ok' },
    { label: 'Memory',        value: '1.4', unit: 'GB', status: 'ok' },
    { label: 'DB latency',    value: '420', unit: 'ms', status: 'degraded' },
    { label: 'API latency',   value: '88',  unit: 'ms', status: 'ok' },
    { label: 'Queue depth',   value: '3',   unit: '',   status: 'ok' },
    { label: 'Error rate 1h', value: '2.1', unit: '%',  status: 'warn' },
  ],
}

// ── HUD indicators (mock — M3 will connect to real health endpoint) ───────────

export const MOCK_HUD_INDICATORS: HudIndicator[] = [
  { id: 'assistant', label: 'Assistant', value: 'online',   status: 'ok' },
  { id: 'runner',    label: 'Runner',    value: 'ready',    status: 'ok' },
  { id: 'db',        label: 'DB',        value: 'degraded', status: 'degraded' },
  { id: 'active',    label: 'Active',    value: 2,          status: 'ok' },
]
