/**
 * GET /api/cognition/providers
 *
 * Server-side proxy for GET /cognition/providers on the webhook backend.
 * Returns provider list, health, and UI feature flag state.
 *
 * The UI must NEVER call the webhook directly — auth is injected here.
 */
import { NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

export async function GET() {
  const url     = `${getWebhookBaseUrl()}/cognition/providers`
  const headers = getWebhookHeaders()

  let upstream: Response
  try {
    upstream = await fetch(url, {
      method:  'GET',
      headers,
      cache:   'no-store',
      signal:  AbortSignal.timeout(8000),
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ok: false, error: `Cognition backend unavailable: ${msg}`, providers: [] },
      { status: 502 },
    )
  }

  let data: unknown
  try {
    data = await upstream.json()
  } catch {
    return NextResponse.json(
      { ok: false, error: `Cognition backend returned non-JSON (${upstream.status})`, providers: [] },
      { status: 502 },
    )
  }

  return NextResponse.json(data, { status: upstream.ok ? 200 : upstream.status })
}
