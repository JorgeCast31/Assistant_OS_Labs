/**
 * GET  /api/cognition/preferences  — read cognitive usage policy
 * POST /api/cognition/preferences  — update cognitive usage policy
 *
 * Server-side proxy. Auth injected here; never reaches the client bundle.
 */
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

export async function GET() {
  const url     = `${getWebhookBaseUrl()}/cognition/preferences`
  const headers = getWebhookHeaders()

  let upstream: Response
  try {
    upstream = await fetch(url, {
      method:  'GET',
      headers,
      cache:   'no-store',
      signal:  AbortSignal.timeout(5000),
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ok: false, error: `Cognition preferences unavailable: ${msg}` },
      { status: 502 },
    )
  }

  let data: unknown
  try {
    data = await upstream.json()
  } catch {
    return NextResponse.json(
      { ok: false, error: `Cognition preferences returned non-JSON (${upstream.status})` },
      { status: 502 },
    )
  }

  return NextResponse.json(data, { status: upstream.ok ? 200 : upstream.status })
}

export async function POST(req: NextRequest) {
  let body: Record<string, unknown>
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ ok: false, error: 'Invalid JSON body' }, { status: 400 })
  }

  const policy = body?.policy
  if (typeof policy !== 'string' || !policy) {
    return NextResponse.json(
      { ok: false, error: 'Missing required field: policy' },
      { status: 400 },
    )
  }

  const url     = `${getWebhookBaseUrl()}/cognition/preferences`
  const headers = getWebhookHeaders()

  let upstream: Response
  try {
    upstream = await fetch(url, {
      method:  'POST',
      headers,
      body:    JSON.stringify({ policy }),
      cache:   'no-store',
      signal:  AbortSignal.timeout(5000),
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ok: false, error: `Cognition preferences update failed: ${msg}` },
      { status: 502 },
    )
  }

  let data: unknown
  try {
    data = await upstream.json()
  } catch {
    return NextResponse.json(
      { ok: false, error: `Cognition preferences update returned non-JSON (${upstream.status})` },
      { status: 502 },
    )
  }

  return NextResponse.json(data, { status: upstream.ok ? 200 : upstream.status })
}
