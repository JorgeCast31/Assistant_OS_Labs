import { NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

const NOTE =
  'MSO Seat provider metadata is read-only. Provider availability is config-derived — no network calls are made. This surface does not execute, approve, or issue tokens. Cognitive only. Used execution: false.'

const UNAVAILABLE_RESPONSE = {
  ok: false,
  seat_provider: null,
  description: 'MSO Seat provider metadata unavailable.',
  execution_allowed: false,
  can_execute_now: false,
  note: NOTE,
}

export async function GET() {
  const url = `${getWebhookBaseUrl()}/mso/seat/provider`

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
        ...UNAVAILABLE_RESPONSE,
        error: `MSO seat provider backend unavailable: ${message}`,
      },
      { status: 502 },
    )
  }

  let payload: unknown
  try {
    payload = await upstreamRes.json()
  } catch {
    return NextResponse.json(
      {
        ...UNAVAILABLE_RESPONSE,
        error: `MSO seat provider backend returned non-JSON (${upstreamRes.status})`,
      },
      { status: 502 },
    )
  }

  if (!upstreamRes.ok) {
    return NextResponse.json(payload, { status: upstreamRes.status })
  }

  return NextResponse.json(payload, { status: 200 })
}
