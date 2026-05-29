/**
 * GET  /api/mso/plans?operator_seat=...  — list Plans for operator seat
 * POST /api/mso/plans                    — create a new Plan draft
 *
 * Server-side proxy to the webhook backend. Auth headers injected server-side.
 *
 * Pre-authority surface:
 *   execution_allowed: false
 *   used_execution: false
 *   runner_reachable_from_ui: false
 *   source: draft_store
 *
 * Not connected to: Police, Runner, AuthorityArtifact, PreparedAction,
 * Machine Operator, or any execution authority path.
 */
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

const UNAVAILABLE = {
  ok: false,
  source: 'draft_store',
  execution_allowed: false,
  used_execution: false,
  runner_reachable_from_ui: false,
  count: 0,
  plans: [],
  error: 'Draft store backend unavailable',
}

export async function GET(req: NextRequest) {
  const operatorSeat = req.nextUrl.searchParams.get('operator_seat')
  if (!operatorSeat) {
    return NextResponse.json(
      { ok: false, error: 'operator_seat query parameter is required' },
      { status: 400 },
    )
  }

  try {
    const base = getWebhookBaseUrl()
    const url = `${base}/mso/plans?operator_seat=${encodeURIComponent(operatorSeat)}`
    const res = await fetch(url, {
      headers: getWebhookHeaders(),
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return NextResponse.json(UNAVAILABLE, { status: res.status })
    const data = await res.json()
    return NextResponse.json(data)
  } catch {
    return NextResponse.json(UNAVAILABLE, { status: 502 })
  }
}

export async function POST(req: NextRequest) {
  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ ok: false, error: 'Invalid JSON body' }, { status: 400 })
  }

  try {
    const base = getWebhookBaseUrl()
    const res = await fetch(`${base}/mso/plans`, {
      method: 'POST',
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
      { ok: false, error: `Draft store unavailable: ${msg}` },
      { status: 502 },
    )
  }
}
