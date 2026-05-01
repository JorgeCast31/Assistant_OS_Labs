import { NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

export async function GET() {
  const url = `${getWebhookBaseUrl()}/system-assistant/state`

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
        snapshot: { status: 'unavailable', warnings: [`System Assistant unreachable: ${message}`] },
        interpretation: null,
        error: `System Assistant endpoint unavailable: ${message}`,
      },
      { status: 502 },
    )
  }

  let payload: Record<string, unknown>
  try {
    payload = await upstreamRes.json() as Record<string, unknown>
  } catch {
    return NextResponse.json(
      {
        ok: false,
        snapshot: { status: 'unavailable', warnings: [`Non-JSON response (status ${upstreamRes.status})`] },
        interpretation: null,
        error: `System Assistant endpoint returned non-JSON (status ${upstreamRes.status})`,
      },
      { status: 502 },
    )
  }

  if (!upstreamRes.ok || payload.ok === false) {
    const error = typeof payload.error === 'string'
      ? payload.error
      : `Upstream error ${upstreamRes.status}`
    return NextResponse.json(
      {
        ok: false,
        snapshot: { status: 'unavailable', warnings: [error] },
        interpretation: null,
        error,
      },
      { status: upstreamRes.status >= 500 ? 502 : upstreamRes.status },
    )
  }

  return NextResponse.json(payload, { status: 200 })
}
