/**
 * GET /api/mso/plans/[plan_id]?operator_seat=...  — get a specific Plan
 * PUT /api/mso/plans/[plan_id]                    — update Plan fields
 *
 * Pre-authority surface. No execution. No tokens. No AuthorityArtifact.
 */
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

type Ctx = { params: Promise<{ plan_id: string }> }

export async function GET(req: NextRequest, ctx: Ctx) {
  const { plan_id } = await ctx.params

  const operatorSeat = req.nextUrl.searchParams.get('operator_seat')
  if (!operatorSeat) {
    return NextResponse.json(
      { ok: false, error: 'operator_seat query parameter is required' },
      { status: 400 },
    )
  }

  try {
    const base = getWebhookBaseUrl()
    const url = `${base}/mso/plans/${encodeURIComponent(plan_id)}?operator_seat=${encodeURIComponent(operatorSeat)}`
    const res = await fetch(url, {
      headers: getWebhookHeaders(),
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.ok ? 200 : res.status })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ok: false, source: 'draft_store', error: `Draft store unavailable: ${msg}` },
      { status: 502 },
    )
  }
}

export async function PUT(req: NextRequest, ctx: Ctx) {
  const { plan_id } = await ctx.params

  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ ok: false, error: 'Invalid JSON body' }, { status: 400 })
  }

  try {
    const base = getWebhookBaseUrl()
    const res = await fetch(`${base}/mso/plans/${encodeURIComponent(plan_id)}`, {
      method: 'PUT',
      headers: { ...getWebhookHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.ok ? 200 : res.status })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ok: false, source: 'draft_store', error: `Draft store unavailable: ${msg}` },
      { status: 502 },
    )
  }
}
