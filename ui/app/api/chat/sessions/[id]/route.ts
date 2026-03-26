/**
 * GET    /api/chat/sessions/[id]  — session detail + messages
 * PATCH  /api/chat/sessions/[id]  — update title / context_id / messages
 * DELETE /api/chat/sessions/[id]  — remove session
 *
 * Server-side proxy that injects the webhook token.
 * Auth headers are resolved at request time (never cached as module-level consts).
 */
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders, logWebhookAuth } from '@/lib/server/webhook-auth'

// Force dynamic evaluation — never statically optimise this route handler.
export const dynamic = 'force-dynamic'

type Ctx = { params: Promise<{ id: string }> }

async function proxyToWebhook(
  method: string,
  path: string,
  body?: unknown,
): Promise<NextResponse> {
  const base    = getWebhookBaseUrl()
  const url     = `${base}${path}`
  const headers = getWebhookHeaders()

  logWebhookAuth(`chat/sessions/[id] ${method}`, url)

  let upstream: Response
  try {
    upstream = await fetch(url, {
      method,
      headers,
      body:  body !== undefined ? JSON.stringify(body) : undefined,
      cache: 'no-store',
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ ok: false, error: `Webhook unavailable: ${msg}` }, { status: 502 })
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

export async function GET(_req: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params
  return proxyToWebhook('GET', `/chat/sessions/${id}`)
}

export async function PATCH(req: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params
  let body: unknown
  try { body = await req.json() }
  catch { body = {} }
  return proxyToWebhook('PATCH', `/chat/sessions/${id}`, body)
}

export async function DELETE(_req: NextRequest, ctx: Ctx) {
  const { id } = await ctx.params
  return proxyToWebhook('DELETE', `/chat/sessions/${id}`)
}
