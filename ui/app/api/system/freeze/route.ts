import { NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

/**
 * POST /api/system/freeze
 * 
 * Proxies the freeze request to the webhook backend's governance endpoint.
 * 
 * IMPORTANT: This is a FAIL-CLOSED placeholder.
 * The backend endpoint (/mso/freeze) has NOT been confirmed to exist.
 * This proxy route exists so the wiring is ready, but calling it will
 * return a clear error until the backend implements the endpoint.
 * 
 * TODO: Confirm backend endpoint exists before marking FREEZE_CONTROL.available = true
 * TODO: Verify exact endpoint path with backend team (/mso/freeze vs /governance/freeze)
 * 
 * This route handles authentication server-side so the ASSISTANT_TOKEN
 * never reaches the browser.
 */
export async function POST() {
  // Try the MSO governance freeze endpoint
  const url = `${getWebhookBaseUrl()}/mso/freeze`

  let upstreamRes: Response
  try {
    upstreamRes = await fetch(url, {
      method: 'POST',
      headers: getWebhookHeaders(),
      cache: 'no-store',
      body: JSON.stringify({ action: 'freeze', source: 'ui_operator' }),
      signal: AbortSignal.timeout(10000),
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      {
        ok: false,
        error: `Freeze endpoint unavailable: ${message}`,
      },
      { status: 502 },
    )
  }

  // Parse response
  let payload: Record<string, unknown>
  try {
    payload = await upstreamRes.json() as Record<string, unknown>
  } catch {
    // Non-JSON response - could be 404 HTML page or empty response
    if (upstreamRes.status === 404) {
      return NextResponse.json(
        {
          ok: false,
          error: 'Freeze endpoint not implemented on backend. Contact system administrator.',
        },
        { status: 501 },
      )
    }
    return NextResponse.json(
      {
        ok: false,
        error: `Freeze endpoint returned non-JSON (status ${upstreamRes.status})`,
      },
      { status: 502 },
    )
  }

  // Handle error responses
  if (!upstreamRes.ok || payload.ok === false) {
    const error =
      typeof payload.error === 'string'
        ? payload.error
        : typeof payload.message === 'string'
          ? payload.message
          : `Upstream error ${upstreamRes.status}`

    return NextResponse.json(
      {
        ok: false,
        error,
      },
      { status: upstreamRes.status >= 500 ? 502 : upstreamRes.status },
    )
  }

  // Success
  return NextResponse.json(
    {
      ok: true,
      message: typeof payload.message === 'string' 
        ? payload.message 
        : 'System freeze initiated',
      operational_mode: payload.operational_mode ?? 'FROZEN',
    },
    { status: 200 },
  )
}
