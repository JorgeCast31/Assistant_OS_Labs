/**
 * POST /api/mso/plans/[plan_id]/abandon
 *
 * Abandon a Plan. Draft: silent. Planning: audited. mso_review: 403.
 * Body: { operator_seat }
 */
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

type Ctx = { params: Promise<{ plan_id: string }> }

export async function POST(req: NextRequest, ctx: Ctx) {
  const { plan_id } = await ctx.params

  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ ok: false, error: 'Invalid JSON body' }, { status: 400 })
  }

  try {
    const base = getWebhookBaseUrl()
    const res = await fetch(
      `${base}/mso/plans/${encodeURIComponent(plan_id)}/abandon`,
      {
        method: 'POST',
        headers: { ...getWebhookHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        cache: 'no-store',
        signal: AbortSignal.timeout(4000),
      },
    )
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
