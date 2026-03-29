/**
 * GET /api/chat/search?q=...  — M21
 *
 * Server-side proxy for full-text message search.
 * Auth headers are resolved at request time (never cached as module-level consts).
 */
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

// Force dynamic evaluation — never statically optimise this route handler.
export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const q    = req.nextUrl.searchParams.get('q') ?? ''
  const base = getWebhookBaseUrl()
  const url  = `${base}/chat/search?q=${encodeURIComponent(q)}`

  let upstream: Response
  try {
    upstream = await fetch(url, {
      headers: getWebhookHeaders(),
      cache:   'no-store',
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ok: false, error: `Search unavailable: ${msg}` },
      { status: 502 },
    )
  }

  let data: unknown
  try { data = await upstream.json() }
  catch {
    return NextResponse.json(
      { ok: false, error: `Non-JSON from webhook (${upstream.status})` },
      { status: 502 },
    )
  }

  return NextResponse.json(
    data,
    { status: upstream.ok ? upstream.status : (upstream.status >= 500 ? 502 : upstream.status) },
  )
}
