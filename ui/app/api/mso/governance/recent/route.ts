import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const limitParam = req.nextUrl.searchParams.get('limit')
  const url = limitParam
    ? `${getWebhookBaseUrl()}/mso/governance/recent?limit=${encodeURIComponent(limitParam)}`
    : `${getWebhookBaseUrl()}/mso/governance/recent`

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
      { ok: false, source: 'mso_governance', error: `Governance proxy error: ${message}`, decisions: [], count: 0, limit: 20, ephemeral: true },
      { status: 502 },
    )
  }

  let payload: unknown
  try {
    payload = await upstreamRes.json()
  } catch {
    return NextResponse.json(
      { ok: false, source: 'mso_governance', error: 'Invalid JSON from upstream', decisions: [], count: 0, limit: 20, ephemeral: true },
      { status: 502 },
    )
  }

  if (!upstreamRes.ok) {
    return NextResponse.json(payload, { status: upstreamRes.status })
  }

  return NextResponse.json(payload, { status: 200 })
}
