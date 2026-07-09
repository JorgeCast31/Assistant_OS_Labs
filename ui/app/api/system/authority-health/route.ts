/**
 * GET /api/system/authority-health
 *
 * Server-side proxy for GET /system/authority-health on the webhook server.
 * Read-only. Auth headers injected server-side (never reach the client bundle).
 *
 * Fail-closed: if the backend is unreachable or returns non-JSON, this route
 * returns overall="NO_VERIFICADO" with can_execute_now=false. It NEVER
 * fabricates readiness and NEVER reports GO on failure.
 */
import { NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

const UNAVAILABLE = {
  ok: false,
  surface: 'authority_health',
  version: 'v0',
  overall: 'NO_VERIFICADO',
  authority_granted: false,
  execution_allowed: false,
  can_execute_now: false,
  read_only: true,
  observer: true,
  runner_available: false,
  durable_queue_present: false,
  backend_deploy_enabled: false,
  ui_is_observational: true,
  checks: [] as unknown[],
  blockers: [] as unknown[],
  warnings: [] as unknown[],
}

export async function GET() {
  const url = `${getWebhookBaseUrl()}/system/authority-health`

  let upstreamRes: Response
  try {
    upstreamRes = await fetch(url, {
      method: 'GET',
      headers: getWebhookHeaders(),
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ...UNAVAILABLE, error: `Authority-health backend unavailable: ${message}` },
      { status: 502 },
    )
  }

  let payload: Record<string, unknown>
  try {
    payload = (await upstreamRes.json()) as Record<string, unknown>
  } catch {
    return NextResponse.json(
      { ...UNAVAILABLE, error: `Authority-health backend returned non-JSON (${upstreamRes.status})` },
      { status: 502 },
    )
  }

  if (!upstreamRes.ok) {
    return NextResponse.json(
      { ...UNAVAILABLE, error: `Upstream error ${upstreamRes.status}`, upstream: payload },
      { status: upstreamRes.status >= 500 ? 502 : upstreamRes.status },
    )
  }

  // Defense-in-depth: never let a compromised/confused upstream flip execution
  // flags on. This surface is observational by contract.
  return NextResponse.json(
    {
      ok: true,
      ...payload,
      authority_granted: false,
      execution_allowed: false,
      can_execute_now: false,
    },
    { status: 200 },
  )
}
