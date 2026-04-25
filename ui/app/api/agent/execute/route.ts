/**
 * POST /api/agent/execute
 *
 * Server-side proxy for POST /machine_operator/execute on the webhook server.
 * The browser calls this route — auth headers are injected server-side.
 * ASSISTANT_TOKEN never reaches the client bundle.
 */
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  // ── Parse body ────────────────────────────────────────────────────────────
  let body: Record<string, unknown>
  try {
    body = await req.json()
  } catch {
    return NextResponse.json(
      { ok: false, error: 'Invalid JSON body' },
      { status: 400 },
    )
  }

  // ── Minimal validation ────────────────────────────────────────────────────
  const capability = body?.capability
  if (typeof capability !== 'string' || !capability.trim()) {
    return NextResponse.json(
      { ok: false, error: 'Missing required field: capability' },
      { status: 400 },
    )
  }

  const payload: Record<string, unknown> = { capability: capability.trim() }
  if (body.arguments && typeof body.arguments === 'object') {
    payload.arguments = body.arguments
  }

  // ── Call upstream webhook (auth resolved at call time) ────────────────────
  const base    = getWebhookBaseUrl()
  const url     = `${base}/machine_operator/execute`
  const headers = getWebhookHeaders()

  let upstreamRes: Response
  try {
    upstreamRes = await fetch(url, {
      method:  'POST',
      headers,
      body:    JSON.stringify(payload),
      cache:   'no-store',
      signal:  AbortSignal.timeout(45000),
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ok: false, error: `Webhook server unavailable: ${msg}`, execution_status: 'unavailable' },
      { status: 502 },
    )
  }

  // ── Forward upstream response ─────────────────────────────────────────────
  let data: unknown
  try {
    data = await upstreamRes.json()
  } catch {
    return NextResponse.json(
      { ok: false, error: `Webhook returned non-JSON (status ${upstreamRes.status})`, execution_status: 'unavailable' },
      { status: 502 },
    )
  }

  if (!upstreamRes.ok) {
    const errMsg =
      (data && typeof data === 'object' && 'error' in data)
        ? String((data as Record<string, unknown>).error)
        : `Upstream error ${upstreamRes.status}`
    return NextResponse.json(
      { ok: false, error: errMsg, execution_status: 'unavailable' },
      { status: upstreamRes.status >= 500 ? 502 : upstreamRes.status },
    )
  }

  return NextResponse.json(data, { status: 200 })
}
