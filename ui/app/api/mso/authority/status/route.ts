import { NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

const NOTE_POSTURE_ONLY = 'Authority status is posture, not execution permission.'

export async function GET() {
  const url = `${getWebhookBaseUrl()}/mso/authority/status`

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
        source: 'authority_status',
        capabilities: [],
        counts: {
          total: 0,
          allow: 0,
          confirm_only: 0,
          deny: 0,
          blocked: 0,
          active_grants: 0,
          active_revocations: 0,
        },
        error: `Authority status proxy error: ${message}`,
        note: NOTE_POSTURE_ONLY,
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
        source: 'authority_status',
        capabilities: [],
        counts: {
          total: 0,
          allow: 0,
          confirm_only: 0,
          deny: 0,
          blocked: 0,
          active_grants: 0,
          active_revocations: 0,
        },
        error: `Invalid JSON from upstream (${upstreamRes.status})`,
        note: NOTE_POSTURE_ONLY,
      },
      { status: 502 },
    )
  }

  if (!upstreamRes.ok) {
    return NextResponse.json(payload, { status: upstreamRes.status })
  }

  return NextResponse.json(payload, { status: 200 })
}
