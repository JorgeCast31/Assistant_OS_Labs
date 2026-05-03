import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

const NOTE_OBSERVABILITY_ONLY =
  'Confirm queue is observability only; confirmation remains governed.'

export async function GET(req: NextRequest) {
  const limitParam = req.nextUrl.searchParams.get('limit')
  const url = limitParam
    ? `${getWebhookBaseUrl()}/confirm/pending?limit=${encodeURIComponent(limitParam)}`
    : `${getWebhookBaseUrl()}/confirm/pending`

  let upstreamRes: Response
  try {
    upstreamRes = await fetch(url, {
      method: 'GET',
      headers: getWebhookHeaders(),
      cache: 'no-store',
      signal: AbortSignal.timeout(8000),
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      {
        ok: false,
        source: 'confirm_flow',
        pending_count: 0,
        expired_pending_count: 0,
        pending: [],
        note: NOTE_OBSERVABILITY_ONLY,
        error: `Confirm pending backend unavailable: ${message}`,
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
        ok: false,
        source: 'confirm_flow',
        pending_count: 0,
        expired_pending_count: 0,
        pending: [],
        note: NOTE_OBSERVABILITY_ONLY,
        error: `Confirm pending backend returned non-JSON (${upstreamRes.status})`,
      },
      { status: 502 },
    )
  }

  if (!upstreamRes.ok) {
    return NextResponse.json(payload, { status: upstreamRes.status })
  }

  return NextResponse.json(payload, { status: 200 })
}
