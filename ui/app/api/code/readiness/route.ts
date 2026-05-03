/**
 * GET /api/code/readiness
 *
 * Server-side proxy for GET /code/readiness on the webhook backend.
 *
 * S-CODE-READINESS-01D — read-only passive surface.
 *
 *   - The browser MUST NEVER call the webhook backend directly: auth is
 *     injected here on the server.
 *   - This proxy is GET-only; it does NOT issue mutations and never proxies
 *     POST/PUT/DELETE.
 *   - Returns the producer's stable envelope { ok, source, ...summary }.
 *   - Fail-soft: backend unreachable / non-JSON yields ok:false envelope, never
 *     leaks server tokens or stack traces.
 *
 * Readiness is source availability and configuration only — it is NOT
 * authority. CODE capabilities are governed by MSO.
 */
import { NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

const NOTE_NOT_AUTHORITY =
  'Readiness is source availability and configuration only — it is not authority. ' +
  'Capabilities are governed by MSO.'

export async function GET() {
  const url     = `${getWebhookBaseUrl()}/code/readiness`
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
      {
        ok: false,
        source: 'code_readiness',
        domain: 'CODE',
        error: `CODE readiness backend unavailable: ${msg}`,
        note: NOTE_NOT_AUTHORITY,
      },
      { status: 502 },
    )
  }

  let data: unknown
  try {
    data = await upstream.json()
  } catch {
    return NextResponse.json(
      {
        ok: false,
        source: 'code_readiness',
        domain: 'CODE',
        error: `CODE readiness backend returned non-JSON (${upstream.status})`,
        note: NOTE_NOT_AUTHORITY,
      },
      { status: 502 },
    )
  }

  return NextResponse.json(data, { status: upstream.ok ? 200 : upstream.status })
}
