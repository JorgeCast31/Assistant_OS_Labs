import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

const UNAVAILABLE_RESPONSE = {
  ok: false,
  error: 'Confirm endpoint unavailable',
  execution_allowed: false,
  can_execute_now: false,
}

export async function POST(req: NextRequest) {
  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ ok: false, error: 'Invalid JSON body' }, { status: 400 })
  }

  const url = `${getWebhookBaseUrl()}/mso/prepared-actions/confirm`

  let upstreamRes: Response
  try {
    upstreamRes = await fetch(url, {
      method: 'POST',
      headers: { ...getWebhookHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ...UNAVAILABLE_RESPONSE, error: `Confirm backend unavailable: ${message}` },
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
        error: `Confirm backend returned non-JSON (${upstreamRes.status})`,
      },
      { status: 502 },
    )
  }

  return NextResponse.json(payload, { status: upstreamRes.status })
}
