"""UI Runtime Truth Contract Tests — S-UI-02.

Scans frontend TypeScript/TSX source files for forbidden patterns that would
cause the UI to render false-positive runtime truth.  These are static text
checks; no browser or JS runtime is required.

Protected invariants:
1. TopHUD overallHealth must not return 'ok' when webhook is 'unknown'.
2. StatusIndicator health fallback must not default to 'healthy'.
3. Sovereign store initial system health must not default to 'healthy'.
4. Sovereign store initial agent counts must not be 1/1 (fabricated live count).
5. SystemChatView must not call execution/admin endpoints.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

# ── Helpers ───────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent
UI_ROOT = REPO_ROOT / "ui"


def _read(rel: str) -> str:
    return (UI_ROOT / rel).read_text(encoding="utf-8")


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestTopHUDOverallHealth(unittest.TestCase):
    """overallHealth() must not return 'ok' when webhook status is 'unknown'."""

    def setUp(self) -> None:
        self.src = _read("components/layout/top-hud.tsx")

    def test_no_ok_when_webhook_unknown(self) -> None:
        # The forbidden pattern: a single line (or inlined condition) that
        # treats webhook==='unknown' as acceptable for returning 'ok'.
        # e.g. the pre-fix version:
        #   if (api === 'ok' && (webhook === 'ok' || webhook === 'unknown')) return 'ok'
        # Checked line-by-line to avoid DOTALL false positives.
        for line in self.src.splitlines():
            if "return 'ok'" in line and "webhook === 'unknown'" in line:
                self.fail(
                    f"overallHealth returns 'ok' when webhook==='unknown' on line: {line.strip()}"
                )

    def test_ok_branch_requires_both_ok(self) -> None:
        # The correct guard: webhook must be explicitly 'ok', not merely not-down.
        self.assertIn(
            "webhook === 'ok'",
            self.src,
            "overallHealth ok-branch must require webhook === 'ok'",
        )


class TestStatusIndicatorHealthFallback(unittest.TestCase):
    """StatusIndicator health fallback must not default to 'healthy'."""

    def setUp(self) -> None:
        self.src = _read("components/sovereign/StatusIndicator.tsx")

    def test_fallback_is_unavailable_not_healthy(self) -> None:
        # After S-SOV-01B the fallback reads: ?? HEALTH_COLORS.unavailable
        self.assertNotIn(
            "HEALTH_COLORS.healthy",
            self.src,
            "StatusIndicator health fallback must not use HEALTH_COLORS.healthy — "
            "unknown status would appear as healthy",
        )

    def test_fallback_is_unavailable(self) -> None:
        self.assertIn(
            "HEALTH_COLORS.unavailable",
            self.src,
            "StatusIndicator health fallback must use HEALTH_COLORS.unavailable",
        )


class TestSovereignStoreInitialState(unittest.TestCase):
    """Sovereign store must not fabricate healthy/active initial state."""

    def setUp(self) -> None:
        self.src = _read("stores/sovereign-store.ts")

    def test_initial_health_is_unavailable(self) -> None:
        # After S-SOV-01C: health: 'unavailable'
        self.assertNotIn(
            "health: 'healthy'",
            self.src,
            "Sovereign store INITIAL_SYSTEM_STATE must not set health to 'healthy'",
        )
        self.assertIn(
            "health: 'unavailable'",
            self.src,
            "Sovereign store INITIAL_SYSTEM_STATE must set health to 'unavailable'",
        )

    def test_initial_active_agents_not_fabricated(self) -> None:
        # After S-SOV-01C: activeAgents: 0
        self.assertNotIn(
            "activeAgents: 1",
            self.src,
            "Sovereign store must not initialise activeAgents to 1 (fabricated live count)",
        )

    def test_initial_total_agents_not_fabricated(self) -> None:
        # After S-SOV-01C: totalAgents: 0
        self.assertNotIn(
            "totalAgents: 1",
            self.src,
            "Sovereign store must not initialise totalAgents to 1 (fabricated live count)",
        )


class TestSystemChatViewEndpoints(unittest.TestCase):
    """SystemChatView must only call read-only state endpoint, never execution endpoints."""

    def setUp(self) -> None:
        self.src = _read("components/sovereign/SystemChatView.tsx")

    def test_no_chat_process_endpoint(self) -> None:
        self.assertNotIn(
            "/api/chat/process",
            self.src,
            "SystemChatView must not call /api/chat/process",
        )

    def test_no_admin_endpoint(self) -> None:
        self.assertNotIn(
            "/admin",
            self.src,
            "SystemChatView must not call /admin endpoints",
        )

    def test_no_code_api_endpoint(self) -> None:
        self.assertNotIn(
            "/api/code",
            self.src,
            "SystemChatView must not call /api/code endpoints",
        )

    def test_no_mso_freeze_endpoint(self) -> None:
        self.assertNotIn(
            "/mso/freeze",
            self.src,
            "SystemChatView must not call /mso/freeze",
        )

    def test_uses_system_assistant_state(self) -> None:
        self.assertIn(
            "getSystemAssistantState",
            self.src,
            "SystemChatView must use getSystemAssistantState as its data source",
        )


class TestAgentPanelStaleHandling(unittest.TestCase):
    """AgentPanel must treat stale registry differently from empty/unavailable.

    Stale means a prior successful fetch exists but the latest check failed.
    Prior agent data must be kept visible with a clear warning — not silently
    shown as fresh and not erased.
    """

    def setUp(self) -> None:
        self.src = _read("components/sovereign/AgentPanel.tsx")

    def test_stale_with_data_detected_separately(self) -> None:
        # AgentPanel must define a separate variable for stale-with-data so it
        # can be rendered differently from both 'available' and 'unavailable'.
        self.assertIn(
            "registryStaleWithData",
            self.src,
            "AgentPanel must handle stale + agents > 0 as a distinct case",
        )

    def test_stale_not_rendered_silently_as_available(self) -> None:
        # A stale warning must be present so prior data is not shown as fresh.
        self.assertIn(
            "last known",
            self.src,
            "AgentPanel must render a 'last known data' warning for stale registry",
        )


class TestReadinessPanelGuardrails(unittest.TestCase):
    """ReadinessPanel must be read-only and honest about system state.

    No execution/admin endpoints.  UNKNOWN mode must not be coerced to NORMAL.
    Stale and UNKNOWN statuses must be handled explicitly.
    """

    def setUp(self) -> None:
        self.src = _read("components/sovereign/ReadinessPanel.tsx")

    def test_no_chat_process_endpoint(self) -> None:
        self.assertNotIn(
            "/api/chat/process",
            self.src,
            "ReadinessPanel must not call /api/chat/process",
        )

    def test_no_admin_endpoint(self) -> None:
        self.assertNotIn(
            "/admin",
            self.src,
            "ReadinessPanel must not call /admin endpoints",
        )

    def test_no_code_api_endpoint(self) -> None:
        self.assertNotIn(
            "/api/code",
            self.src,
            "ReadinessPanel must not call /api/code endpoints",
        )

    def test_no_mso_freeze_endpoint(self) -> None:
        self.assertNotIn(
            "/mso/freeze",
            self.src,
            "ReadinessPanel must not call /mso/freeze",
        )

    def test_no_system_healthy_fabrication(self) -> None:
        # Panel must not render a blanket "SYSTEM HEALTHY" label
        self.assertNotIn(
            "system healthy",
            self.src.lower(),
            "ReadinessPanel must not render a fabricated 'SYSTEM HEALTHY' label",
        )

    def test_unknown_mode_handled_explicitly(self) -> None:
        # UNKNOWN operational mode must appear as an explicit map key (TypeScript
        # records use unquoted uppercase keys, e.g. UNKNOWN: 'bg-idle').
        self.assertIn(
            "UNKNOWN:",
            self.src,
            "ReadinessPanel must handle UNKNOWN operational mode explicitly",
        )

    def test_stale_handled_explicitly(self) -> None:
        # 'stale' status must be present as an explicit case
        self.assertIn(
            "'stale'",
            self.src,
            "ReadinessPanel must handle 'stale' source status explicitly",
        )

    def test_webhook_ok_not_system_healthy(self) -> None:
        # webhook=ok must render as transport-only, not system health
        self.assertIn(
            "transport only",
            self.src,
            "ReadinessPanel must qualify webhook=ok as 'transport only', not system healthy",
        )


class TestSystemAssistantProxyAlignment(unittest.TestCase):
    """getSystemAssistantState must call the local proxy, not the webhook directly.

    The webhook URL requires a server-side token (X-Assistant-Token).
    Calling it from the browser produces 401. The proxy injects the token
    server-side; the browser never sees it.
    """

    def setUp(self) -> None:
        self.api_src    = _read("lib/api.ts")
        self.route_src  = _read("app/api/system-assistant/state/route.ts")

    def test_get_system_assistant_state_calls_local_proxy(self) -> None:
        # The function must call the local Next.js route, not the direct webhook URL.
        self.assertIn(
            "/api/system-assistant/state",
            self.api_src,
            "getSystemAssistantState must target the local proxy /api/system-assistant/state",
        )

    def test_get_system_assistant_state_not_direct_webhook(self) -> None:
        # Must not pass the raw webhook URL to fetch() inside getSystemAssistantState.
        # Scan only the function body (lines after its definition).
        lines = self.api_src.splitlines()
        in_fn = False
        for line in lines:
            if "getSystemAssistantState" in line and "export async function" in line:
                in_fn = True
            if in_fn and "webhookSystemAssistantState" in line and "fetch(" in line:
                self.fail(
                    "getSystemAssistantState must not pass webhookSystemAssistantState "
                    "directly to fetch() — use the local proxy instead"
                )

    def test_proxy_route_does_not_expose_token_string(self) -> None:
        # The proxy route must not contain the literal token variable names that
        # would be visible to the browser if the file were served as client code.
        self.assertNotIn(
            "WEBHOOK_TOKEN",
            self.route_src,
            "Proxy route must not reference WEBHOOK_TOKEN",
        )
        self.assertNotIn(
            "NEXT_PUBLIC_",
            self.route_src,
            "Proxy route must not use NEXT_PUBLIC_ env vars (would expose to browser)",
        )

    def test_proxy_route_is_get_only(self) -> None:
        # Only GET should be exported — no POST/PUT/DELETE mutation surfaces.
        self.assertIn(
            "export async function GET",
            self.route_src,
            "Proxy route must export a GET handler",
        )
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertNotIn(
                f"export async function {method}",
                self.route_src,
                f"Proxy route must not export {method} (read-only endpoint)",
            )


if __name__ == "__main__":
    unittest.main()
