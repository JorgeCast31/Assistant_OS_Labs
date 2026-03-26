/**
 * Server-side helper for all chat proxy routes.
 *
 * WHY functions instead of module-level consts:
 *   process.env is read at CALL TIME, not at module-init time.
 *   In Next.js 15 dev mode (Turbopack), module-level consts are evaluated once
 *   per worker when the module first loads.  If the dev server hot-reloads a
 *   route module but the env var was captured before the reload, subsequent
 *   requests from other workers still use the stale value.  Reading inside a
 *   function avoids this entirely — the env var is always fresh.
 *
 * NEVER import this file in client components (it reads server-only env vars).
 */

/** URL of the AssistantOS webhook server. Resolved at call time. */
export function getWebhookBaseUrl(): string {
  return (
    process.env.WEBHOOK_BASE_URL ??
    process.env.NEXT_PUBLIC_WEBHOOK_BASE_URL ??
    'http://localhost:8787'
  )
}

/**
 * Authentication + content-type headers for all proxied webhook calls.
 * Reads ASSISTANT_TOKEN at call time — never cached at module level.
 */
export function getWebhookHeaders(): { 'Content-Type': string; 'X-Assistant-Token': string } {
  return {
    'Content-Type':      'application/json',
    'X-Assistant-Token': process.env.ASSISTANT_TOKEN ?? '',
  }
}

/**
 * Log auth metadata to the server console.
 * Prints token length and 4-char prefix so you can verify the right secret
 * is loaded without exposing the full value.
 *
 * Remove all [AUTH][…] calls once the auth issues are confirmed resolved.
 */
export function logWebhookAuth(label: string, targetUrl: string): void {
  const token  = process.env.ASSISTANT_TOKEN ?? ''
  const prefix = token.length >= 4 ? token.slice(0, 4) + '…' : '(empty)'
  console.log(
    `[AUTH][${label}] → ${targetUrl}` +
    ` | hasToken=${token.length > 0}` +
    ` | tokenLen=${token.length}` +
    ` | header=X-Assistant-Token` +
    ` | prefix=${prefix}`,
  )
}
