import { NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

const NOTE_REVIEW_ONLY =
  'Prepared action review queue is read-only. Human confirmation and the full authority chain are still pending. This surface does not execute, approve, or issue tokens.'

const UNAVAILABLE_RESPONSE = {
  ok: false,
  source: 'prepared_action_queue',
  count: 0,
  items: [],
  review_only: true,
  execution_allowed: false,
  can_execute_now: false,
  note: NOTE_REVIEW_ONLY,
}

export async function GET() {
  const url = `${getWebhookBaseUrl()}/mso/prepared-actions/pending`

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
        error: `Prepared actions backend unavailable: ${message}`,
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
        error: `Prepared actions backend returned non-JSON (${upstreamRes.status})`,
      },
      { status: 502 },
    )
  }

  if (!upstreamRes.ok) {
    return NextResponse.json(payload, { status: upstreamRes.status })
  }

  return NextResponse.json(payload, { status: 200 })
}
