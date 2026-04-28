import { NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders, getWebhookAdminToken } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

/**
 * POST /api/system/freeze
 *
 * Proxies the operator freeze command to the canonical backend governance
 * endpoint: POST /admin/governance/mode.
 *
 * Authentication (server-side only — tokens never reach the browser):
 *   X-Assistant-Token       → ASSISTANT_TOKEN env var
 *   X-Assistant-Admin-Token → ASSISTANT_ADMIN_TOKEN env var
 *
 * Fail-closed: if ASSISTANT_ADMIN_TOKEN is not configured, this route
 * returns 503 immediately — no request is sent to the backend.
 *
 * Backend request:
 *   POST /admin/governance/mode
 *   { "mode": "FROZEN", "reason": "ui_operator_freeze" }
 *
 * Backend success response:
 *   { "ok": true, "mode": "FROZEN", "cleared": false, ... }
 */
export async function POST() {
  // Fail-closed: admin token is required to activate the kill switch.
  const adminToken = getWebhookAdminToken()
  if (!adminToken) {
    return NextResponse.json(
      {
        ok: false,
        error:
          'ASSISTANT_ADMIN_TOKEN is not configured on the UI server. ' +
          'Freeze control is fail-closed at the proxy layer until this is set.',
        // Operability hints — surfaced verbatim by the system view.
        domain: 'SYSTEM',
        action: 'governance.freeze',
        reason: 'missing_ui_admin_token',
        suggestion:
          'Set ASSISTANT_ADMIN_TOKEN in ui/.env.local (must match WEBHOOK_ADMIN_TOKEN ' +
          'in the backend .env). Restart the UI dev server. See docs/LOCAL_RUNBOOK.md.',
      },
      { status: 503 },
    )
  }

  const url = `${getWebhookBaseUrl()}/admin/governance/mode`

  let upstreamRes: Response
  try {
    upstreamRes = await fetch(url, {
      method: 'POST',
      headers: {
        ...getWebhookHeaders(),
        'X-Assistant-Admin-Token': adminToken,
      },
      cache: 'no-store',
      body: JSON.stringify({
        mode: 'FROZEN',
        reason: 'ui_operator_freeze',
      }),
      signal: AbortSignal.timeout(10000),
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ok: false, error: `Governance endpoint unreachable: ${message}` },
      { status: 502 },
    )
  }

  let payload: Record<string, unknown>
  try {
    payload = (await upstreamRes.json()) as Record<string, unknown>
  } catch {
    return NextResponse.json(
      {
        ok: false,
        error: `Governance endpoint returned non-JSON (status ${upstreamRes.status})`,
      },
      { status: 502 },
    )
  }

  // 401/403 → auth problem — surface clearly
  if (upstreamRes.status === 401 || upstreamRes.status === 403) {
    return NextResponse.json(
      {
        ok: false,
        error:
          upstreamRes.status === 403
            ? 'Admin token rejected by backend. Verify ASSISTANT_ADMIN_TOKEN matches WEBHOOK_ADMIN_TOKEN.'
            : 'Webhook token rejected by backend. Verify ASSISTANT_TOKEN matches WEBHOOK_TOKEN.',
      },
      { status: upstreamRes.status },
    )
  }

  // Other upstream errors (400, 5xx)
  if (!upstreamRes.ok || payload.ok === false) {
    const error =
      typeof payload.message === 'string'
        ? payload.message
        : typeof payload.error === 'string'
          ? payload.error
          : `Upstream error ${upstreamRes.status}`
    return NextResponse.json(
      { ok: false, error },
      { status: upstreamRes.status >= 500 ? 502 : upstreamRes.status },
    )
  }

  // Success — backend returns { ok: true, mode: "FROZEN", cleared: false, ... }
  const mode = typeof payload.mode === 'string' ? payload.mode : 'FROZEN'
  return NextResponse.json(
    {
      ok: true,
      mode,
      message: `System is now ${mode}. All new executions are blocked.`,
    },
    { status: 200 },
  )
}
