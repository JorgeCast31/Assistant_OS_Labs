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
 * Admin token for privileged operations (governance mode, schema ops).
 * Must match WEBHOOK_ADMIN_TOKEN on the backend.
 *
 * Returns null if ASSISTANT_ADMIN_TOKEN is not configured.
 * Callers must fail-closed when null — never attempt admin ops without it.
 * This value is never exposed to the browser.
 */
export function getWebhookAdminToken(): string | null {
  const token = process.env.ASSISTANT_ADMIN_TOKEN
  return token && token.trim() ? token.trim() : null
}

