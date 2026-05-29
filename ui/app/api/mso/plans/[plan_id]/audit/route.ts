/**
 * GET /api/mso/plans/[plan_id]/audit — audit log for a Plan
 * Read-only. No execution.
 */
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

type Ctx = { params: Promise<{ plan_id: string }> }

export async function GET(_req: NextRequest, ctx: Ctx) {
  const { plan_id } = await ctx.params

  try {
    const base = getWebhookBaseUrl()
    const res = await fetch(
      `${base}/mso/plans/${encodeURIComponent(plan_id)}/audit`,
      {
        headers: getWebhookHeaders(),
        cache: 'no-store',
        signal: AbortSignal.timeout(4000),
      },
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.ok ? 200 : res.status })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ok: false, source: 'draft_store', error: `Audit log unavailable: ${msg}` },
      { status: 502 },
    )
  }
}
