import { NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'
import type { OperationalMode, SystemEvent } from '@/lib/types'

export const dynamic = 'force-dynamic'

type UpstreamEvent = Record<string, unknown>

interface UpstreamStateResponse {
  ok: boolean
  operational_mode?: OperationalMode
  recent_events?: UpstreamEvent[]
}

function eventMessage(event: UpstreamEvent): string {
  const rawType = String(event.type ?? '')
  if (rawType === 'task_transition') {
    const domain = typeof event.domain === 'string' ? event.domain : 'SYSTEM'
    const action = typeof event.action === 'string' ? event.action : 'task'
    const status = typeof event.status === 'string' ? event.status : 'unknown'
    const reason = typeof event.reason === 'string' && event.reason.trim()
      ? ` (${event.reason})`
      : ''
    return `${domain} ${action} -> ${status}${reason}`
  }

  if (rawType === 'governance') {
    const action = typeof event.action === 'string' ? event.action : 'governance'
    const domain = typeof event.domain === 'string' ? event.domain : 'system'
    const executionMode = typeof event.execution_mode === 'string' ? event.execution_mode : 'unknown'
    const justification = typeof event.justification === 'string' && event.justification.trim()
      ? ` (${event.justification})`
      : ''
    return `${domain} ${action} -> ${executionMode}${justification}`
  }

  return 'System event'
}

function normalizeEvent(event: UpstreamEvent, index: number): SystemEvent {
  const rawType = String(event.type ?? '')
  const timestamp =
    typeof event.ts === 'string' && event.ts.trim()
      ? event.ts
      : new Date().toISOString()

  const type: SystemEvent['type'] =
    rawType === 'task_transition' || rawType === 'governance'
      ? rawType
      : 'system_normal'

  return {
    id: `${type}-${index}-${timestamp}`,
    type,
    message: eventMessage(event),
    timestamp,
    metadata: event,
  }
}

export async function GET() {
  const url = `${getWebhookBaseUrl()}/mso/state`

  let upstreamRes: Response
  try {
    upstreamRes = await fetch(url, {
      method: 'GET',
      headers: getWebhookHeaders(),
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      {
        ok: false,
        error: `Webhook operability endpoint unavailable: ${message}`,
        operational_mode: 'UNKNOWN',
        events: [],
      },
      { status: 502 },
    )
  }

  let payload: UpstreamStateResponse
  try {
    payload = await upstreamRes.json() as UpstreamStateResponse
  } catch {
    return NextResponse.json(
      {
        ok: false,
        error: `Webhook operability endpoint returned non-JSON (status ${upstreamRes.status})`,
        operational_mode: 'UNKNOWN',
        events: [],
      },
      { status: 502 },
    )
  }

  if (!upstreamRes.ok || payload.ok === false) {
    const body = payload as unknown as Record<string, unknown>
    const error =
      typeof body.error === 'string'
        ? body.error
        : `Upstream error ${upstreamRes.status}`

    return NextResponse.json(
      {
        ok: false,
        error,
        operational_mode: 'UNKNOWN',
        events: [],
      },
      { status: upstreamRes.status >= 500 ? 502 : upstreamRes.status },
    )
  }

  return NextResponse.json(
    {
      ok: true,
      operational_mode: payload.operational_mode ?? 'UNKNOWN',
      events: (payload.recent_events ?? []).map(normalizeEvent),
    },
    { status: 200 },
  )
}
