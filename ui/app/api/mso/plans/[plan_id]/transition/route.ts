/**
 * POST /api/mso/plans/[plan_id]/transition
 *
 * Transition a Plan's state. Operator-initiated only.
 * D-04: Escalation to mso_review requires explicit operator confirmation — this
 * endpoint is the server-side gate. The UI must show a confirmation dialog
 * before calling this with to_state='mso_review'.
 *
 * Body: { operator_seat, from_state, to_state, notes? }
 * Pre-authority. No execution. No tokens. No AuthorityArtifact.
 */
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

export async function POST(
  req: NextRequest,
  { params }: { params: { plan_id: string } },
) {
  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ ok: false, error: 'Invalid JSON body' }, { status: 400 })
  }

  try {
    const base = getWebhookBaseUrl()
    const res = await fetch(
      `${base}/mso/plans/${encodeURIComponent(params.plan_id)}/transition`,
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
        source: 'draft_store',
        execution_allowed: false,
        error: `Draft store unavailable: ${msg}`,
      },
      { status: 502 },
    )
  }
}
