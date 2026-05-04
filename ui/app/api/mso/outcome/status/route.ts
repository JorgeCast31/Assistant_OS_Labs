import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

const NOTE_OBSERVATIONAL = 'Outcome status is observational; it does not grant execution permission.'

export async function GET(req: NextRequest) {
  const planId = req.nextUrl.searchParams.get('plan_id')
  const contextId = req.nextUrl.searchParams.get('context_id')
  const traceId = req.nextUrl.searchParams.get('trace_id')
  const executionId = req.nextUrl.searchParams.get('execution_id')

  const params = new URLSearchParams()
  if (planId) params.set('plan_id', planId)
  if (contextId) params.set('context_id', contextId)
  if (traceId) params.set('trace_id', traceId)
  if (executionId) params.set('execution_id', executionId)

  const querySuffix = params.toString()
  const url = querySuffix
    ? `${getWebhookBaseUrl()}/mso/outcome/status?${querySuffix}`
    : `${getWebhookBaseUrl()}/mso/outcome/status`

  const fallback = {
    ok: false,
    source: 'outcome_status',
    note: NOTE_OBSERVATIONAL,
    found: false,
    query: {
      plan_id: planId,
      context_id: contextId,
      trace_id: traceId,
      execution_id: executionId,
    },
    outcome: {
      status: 'unknown',
      result_type: null,
      execution_status: 'unknown',
      domain: null,
      action: null,
      message: 'Outcome status unavailable',
      error_type: 'proxy_error',
      error_message: 'Outcome status proxy unavailable',
    },
    correlation: {},
    sources: {},
    source_errors: [],
  }

  let upstreamRes: Response
  try {
    upstreamRes = await fetch(url, {
      method: 'GET',
      headers: getWebhookHeaders(),
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
  } catch {
    return NextResponse.json(fallback, { status: 502 })
  }

  let payload: unknown
  try {
    payload = await upstreamRes.json()
  } catch {
    return NextResponse.json(fallback, { status: 502 })
  }

  if (!upstreamRes.ok) {
    return NextResponse.json(payload, { status: upstreamRes.status })
  }

  return NextResponse.json(payload, { status: 200 })
}
