/**
 * POST /api/mso/plans/[plan_id]/ack
 *
 * Operator-simulated MSO read receipt (D-23 — ALPHA 1).
 * Records that MSO has read the Plan. Does NOT authorize. Does NOT prepare.
 * Does NOT execute. Does NOT emit tokens. Does NOT create AuthorityArtifact.
 *
 * Requires Plan in mso_review state.
 * Body: { operator_seat, acknowledged_by, ack_status, note? }
 * ack_status: "acknowledged" | "rejected_for_review"
 *
 * Response always includes:
 *   execution_allowed: false
 *   used_execution: false
 *   runner_reachable_from_ui: false
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
      `${base}/mso/plans/${encodeURIComponent(plan_id)}/ack`,
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
      {
        ok: false,
        source: 'plan_mso_ack',
        execution_allowed: false,
        used_execution: false,
        runner_reachable_from_ui: false,
        error: `ACK backend unavailable: ${msg}`,
      },
      { status: 502 },
    )
  }
}
