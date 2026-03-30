/**
 * POST /api/chat/process
 *
 * Server-side proxy for the AssistantOS webhook server.
 * The browser calls this route — it injects the token server-side.
 * ASSISTANT_TOKEN never reaches the client bundle.
 *
 * Auth headers are resolved at request time (never cached as module-level consts).
 */
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

// Force dynamic evaluation — never statically optimise this route handler.
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
  const text   = body?.text
  const action = body?.action
  // Accept: non-empty text, or structured action (M12+)
  if ((typeof text !== 'string' || !text.trim()) && !action) {
    return NextResponse.json(
      { ok: false, error: 'Missing required field: text or action' },
      { status: 400 },
    )
  }

  // ── Build forwarded payload — text + all M17/M23 fields ──────────────────
  const payload: Record<string, unknown> = {
    text: typeof text === 'string' ? text.trim() : '',
  }
  if (body.session_context)  payload.session_context  = body.session_context
  if (body.conversation_id)  payload.conversation_id  = body.conversation_id
  if (body.action)           payload.action           = body.action   // M12+ structured actions
  if (body.session_id)       payload.session_id       = body.session_id  // M17 persistence

  // ── Call upstream webhook (auth resolved at call time) ────────────────────
  const base    = getWebhookBaseUrl()
  const url     = `${base}/chat/process`
  const headers = getWebhookHeaders()

  let upstreamRes: Response
  try {
    upstreamRes = await fetch(url, {
      method:  'POST',
      headers,
      body:    JSON.stringify(payload),
      cache:   'no-store',
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ok: false, error: `Webhook server unavailable: ${msg}` },
      { status: 502 },
    )
  }

  // ── Forward upstream response ─────────────────────────────────────────────
  let data: unknown
  try {
    data = await upstreamRes.json()
  } catch {
    return NextResponse.json(
      { ok: false, error: `Webhook returned non-JSON (status ${upstreamRes.status})` },
      { status: 502 },
    )
  }

  // Surface upstream errors without leaking internal details
  if (!upstreamRes.ok) {
    const errMsg =
      (data && typeof data === 'object' && 'error' in data)
        ? String((data as Record<string, unknown>).error)
        : `Upstream error ${upstreamRes.status}`
    return NextResponse.json(
      { ok: false, error: errMsg },
      { status: upstreamRes.status >= 500 ? 502 : upstreamRes.status },
    )
  }

  return NextResponse.json(data, { status: 200 })
}
