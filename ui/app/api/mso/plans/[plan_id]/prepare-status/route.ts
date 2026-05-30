/**
 * GET /api/mso/plans/[plan_id]/prepare-status?operator_seat=...
 *
 * Read-only correlated prepare status: Plan → ACK → PrepareRequest → PreparedAction.
 * Answers: where is this plan in the prepare lifecycle?
 *
 * Does NOT execute. Does NOT emit tokens. Does NOT create AuthorityArtifact.
 *
 * Response always includes:
 *   execution_allowed: false
 *   used_execution: false
 *   runner_reachable_from_ui: false
 *
 * Status values (never execution-implying):
 *   no_plan | draft | planning | mso_review_ack_pending | mso_review_ack_rejected
 *   acked_prepare_not_requested | prepared_awaiting_confirmation
 *   prepare_rejected | requires_review | unknown | operator_seat_mismatch
 */
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

type Ctx = { params: Promise<{ plan_id: string }> }

export async function GET(req: NextRequest, ctx: Ctx) {
  const { plan_id } = await ctx.params

  const operatorSeat = req.nextUrl.searchParams.get('operator_seat') ?? ''
  if (!operatorSeat.trim()) {
    return NextResponse.json(
      { ok: false, error: 'operator_seat query param is required' },
      { status: 400 },
    )
  }

  try {
    const base = getWebhookBaseUrl()
    const url = `${base}/mso/plans/${encodeURIComponent(plan_id)}/prepare-status?operator_seat=${encodeURIComponent(operatorSeat)}`
    const res = await fetch(url, {
      method: 'GET',
      headers: getWebhookHeaders(),
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.ok ? 200 : res.status })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      {
        ok: false,
        source: 'prepare_status',
        status: 'unknown',
        execution_allowed: false,
        used_execution: false,
        runner_reachable_from_ui: false,
        error: `Prepare status backend unavailable: ${msg}`,
      },
      { status: 502 },
    )
  }
}
