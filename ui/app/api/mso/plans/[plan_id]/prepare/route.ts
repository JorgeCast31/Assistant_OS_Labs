/**
 * POST /api/mso/plans/[plan_id]/prepare
 *
 * Prepare contract — Plan → PrepareRequest → PreparedAction (review-only).
 * No execution. No tokens. No AuthorityArtifact from UI. Runner stays closed.
 *
 * Requires:
 *   - Plan in mso_review state
 *   - Valid PlanMSOAck (ack_status=acknowledged) — POST /ack first
 *   - confirmation_acknowledged: true (explicit operator confirmation)
 *
 * Body: { operator_seat, requested_by?, confirmation_acknowledged: true, notes? }
 *
 * Response always includes:
 *   execution_allowed: false
 *   used_execution: false
 *   runner_reachable_from_ui: false
 *
 * On success: prepare_status = "prepared", prepared_action_id present
 * On failure: ok = false, fail_closed_reason explains why
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
      `${base}/mso/plans/${encodeURIComponent(plan_id)}/prepare`,
      {
        method: 'POST',
        headers: { ...getWebhookHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        cache: 'no-store',
        signal: AbortSignal.timeout(8000),
      },
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.ok ? 200 : res.status })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      {
        ok: false,
        source: 'prepare_contract',
        prepare_status: 'rejected',
        execution_allowed: false,
        used_execution: false,
        runner_reachable_from_ui: false,
        fail_closed_reason: `Prepare backend unavailable: ${msg}`,
        error: `Prepare backend unavailable: ${msg}`,
      },
      { status: 502 },
    )
  }
}
