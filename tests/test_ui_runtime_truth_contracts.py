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


class TestTopStatusBarMSOLabels(unittest.TestCase):
    """TopStatusBar must not render local-only MSO state as live backend truth.

    S-MSO-UI-01B invariants:
    - msoState.status must not drive colored authority badges.
    - StatusIndicator must not be rendered from msoState.status.
    - MSO section must show a static 'not wired' label.
    - executionState must not drive amber/red/pulse color semantics.
    - activeAgents must not be shown as '0/N' (hardcoded zero implies real data).
    """

    def setUp(self) -> None:
        self.src = _read("components/sovereign/TopStatusBar.tsx")

    def test_mso_status_not_displayed_as_live_authority(self) -> None:
        # msoState.status drives amber-400 in the pre-fix version.
        # After S-MSO-UI-01B this condition must not exist.
        self.assertNotIn(
            "msoState.status === 'active'",
            self.src,
            "TopStatusBar must not color-code msoState.status as live authority truth",
        )

    def test_no_status_indicator_from_local_mso_state(self) -> None:
        # StatusIndicator must not be rendered with msoState.status as its value.
        for line in self.src.splitlines():
            if "StatusIndicator" in line and "msoState.status" in line:
                self.fail(
                    f"TopStatusBar renders StatusIndicator with local msoState.status: {line.strip()}"
                )

    def test_mso_section_shows_static_unwired_label(self) -> None:
        # MSO section must display a static 'not wired' label — never a live status value.
        has_trace_na  = "TRACE N/A"  in self.src
        has_not_wired = "NOT WIRED"  in self.src
        has_unwired   = "UNWIRED"    in self.src
        self.assertTrue(
            has_trace_na or has_not_wired or has_unwired,
            "TopStatusBar MSO section must render a static 'TRACE N/A' / 'NOT WIRED' / 'UNWIRED' label",
        )

    def test_exec_state_no_animated_amber(self) -> None:
        # executionState must not drive animate-pulse + amber color simultaneously.
        # That combination implies live backend execution activity from local state.
        for line in self.src.splitlines():
            if "executionState" in line and "animate-pulse" in line and "amber" in line:
                self.fail(
                    f"TopStatusBar exec state uses animate-pulse amber from local-only executionState: "
                    f"{line.strip()}"
                )

    def test_active_agents_guarded_not_shown_as_zero(self) -> None:
        # activeAgents is hardcoded 0 with no backend source.
        # The safe pattern requires a '—' guard so '0/N' is never displayed.
        self.assertIn(
            "activeAgents === 0 ? '—'",
            self.src,
            "TopStatusBar must guard activeAgents with '—' when value is 0 (no backend source)",
        )


class TestReadinessPanelCognitionDisabled(unittest.TestCase):
    """ReadinessPanel must treat disabled cognition providers as neutral, not offline.

    S-COG-01B: when the backend returns status='disabled' (feature flag off),
    the UI must show a neutral idle indicator, not a red '0/1 online' error.
    Disabled is not offline — it means the feature is intentionally inactive.
    """

    def setUp(self) -> None:
        self.src = _read("components/sovereign/ReadinessPanel.tsx")

    def test_disabled_providers_filtered_before_counting(self) -> None:
        """Active-provider count must exclude disabled providers."""
        self.assertIn(
            "status !== 'disabled'",
            self.src,
            "ReadinessPanel must filter out providers with status='disabled' "
            "before computing the online/total count — disabled is not offline",
        )

    def test_all_disabled_renders_neutral_label(self) -> None:
        """All-disabled state must produce a neutral label, not an error count."""
        self.assertIn(
            "Cognition disabled",
            self.src,
            "ReadinessPanel must render 'Cognition disabled' (neutral, idle) when "
            "every provider has status='disabled' — not '0/1 online' with a red dot",
        )

    def test_no_unfiltered_providers_length_as_total(self) -> None:
        """totalProviders must not be assigned from unfiltered providers.length."""
        for line in self.src.splitlines():
            if re.search(r'\btotalProviders\b\s*=\s*providers\.length\b', line):
                self.fail(
                    "ReadinessPanel assigns totalProviders = providers.length without "
                    f"filtering disabled providers — disabled would render as offline: "
                    f"{line.strip()}",
                )

    def test_all_disabled_guard_present(self) -> None:
        """An explicit all-disabled guard must exist before the error branch."""
        has_guard = (
            "allDisabled" in self.src
            or (
                "totalActive === 0" in self.src
                and "allProviders.length" in self.src
            )
        )
        self.assertTrue(
            has_guard,
            "ReadinessPanel must define an explicit all-disabled guard "
            "(e.g. 'allDisabled' variable) so disabled providers never fall through "
            "to the '0/N online' error branch",
        )


class TestGovernanceRecentProxyAlignment(unittest.TestCase):
    """getRecentGovernanceDecisions must call the local proxy, not the webhook directly.

    S-MSO-FE-01A: the proxy route injects the auth token server-side.
    The browser must never see the token. Calling the webhook directly would
    produce 401 from the browser.
    """

    def setUp(self) -> None:
        self.api_src   = _read("lib/api.ts")
        self.route_src = _read("app/api/mso/governance/recent/route.ts")
        self.types_src = _read("lib/types.ts")

    def test_get_recent_governance_decisions_calls_local_proxy(self) -> None:
        self.assertIn(
            "/api/mso/governance/recent",
            self.api_src,
            "getRecentGovernanceDecisions must target the local proxy /api/mso/governance/recent",
        )

    def test_get_recent_governance_decisions_not_direct_webhook(self) -> None:
        lines = self.api_src.splitlines()
        in_fn = False
        for line in lines:
            if "getRecentGovernanceDecisions" in line and "export async function" in line:
                in_fn = True
            if in_fn and "WEBHOOK_BASE_URL" in line and "fetch(" in line:
                self.fail(
                    "getRecentGovernanceDecisions must not call WEBHOOK_BASE_URL directly — "
                    "use the local proxy instead"
                )

    def test_proxy_route_does_not_expose_token(self) -> None:
        self.assertNotIn(
            "WEBHOOK_TOKEN",
            self.route_src,
            "Governance proxy route must not reference WEBHOOK_TOKEN",
        )
        self.assertNotIn(
            "NEXT_PUBLIC_",
            self.route_src,
            "Governance proxy route must not use NEXT_PUBLIC_ env vars (would expose to browser)",
        )

    def test_proxy_route_is_get_only(self) -> None:
        self.assertIn(
            "export async function GET",
            self.route_src,
            "Governance proxy route must export a GET handler",
        )
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertNotIn(
                f"export async function {method}",
                self.route_src,
                f"Governance proxy route must not export {method} (read-only endpoint)",
            )

    def test_proxy_route_is_force_dynamic(self) -> None:
        self.assertIn(
            "export const dynamic = 'force-dynamic'",
            self.route_src,
            "Governance proxy route must set dynamic = 'force-dynamic' to prevent caching",
        )

    def test_proxy_route_forwards_limit_param(self) -> None:
        self.assertIn(
            "limit",
            self.route_src,
            "Governance proxy route must forward the 'limit' query param to the backend",
        )

    def test_governance_types_exported(self) -> None:
        for name in ("GovernanceDecisionSummary", "GovernanceRecentResponse"):
            self.assertIn(
                f"export interface {name}",
                self.types_src,
                f"ui/lib/types.ts must export {name}",
            )


class TestGovernanceRecentPanel(unittest.TestCase):
    """GovernanceRecentPanel invariants — S-MSO-UI-01C.

    1. Component file exists.
    2. Calls getRecentGovernanceDecisions, not direct webhook URL.
    3. Contains no mutation strings.
    4. Contains ephemeral warning and 'not MSO' qualifier.
    5. SystemView mounts GovernanceRecentPanel.
    6. No "MSO ACTIVE" string introduced.
    7. Panel not mounted inside ReadinessPanel.
    """

    def setUp(self) -> None:
        self.panel_src       = _read("components/sovereign/GovernanceRecentPanel.tsx")
        self.system_view_src = _read("components/views/system-view.tsx")
        self.readiness_src   = _read("components/sovereign/ReadinessPanel.tsx")

    def test_panel_file_exists(self) -> None:
        self.assertIn(
            "GovernanceRecentPanel",
            self.panel_src,
            "GovernanceRecentPanel.tsx must export GovernanceRecentPanel",
        )

    def test_calls_local_helper_not_direct_webhook(self) -> None:
        self.assertIn(
            "getRecentGovernanceDecisions",
            self.panel_src,
            "GovernanceRecentPanel must call getRecentGovernanceDecisions (local helper via proxy)",
        )
        self.assertNotIn(
            "8787",
            self.panel_src,
            "GovernanceRecentPanel must not call the webhook port directly",
        )
        self.assertNotIn(
            "WEBHOOK_BASE_URL",
            self.panel_src,
            "GovernanceRecentPanel must not reference WEBHOOK_BASE_URL (would bypass proxy)",
        )

    def test_no_mutation_strings(self) -> None:
        for forbidden in ("approve", "deny", "/admin", "/mso/freeze", "/api/code"):
            self.assertNotIn(
                forbidden,
                self.panel_src,
                f"GovernanceRecentPanel must not contain mutation/admin string: '{forbidden}'",
            )
        # POST must not appear as a fetch method (method: 'POST')
        self.assertNotIn(
            "method: 'POST'",
            self.panel_src,
            "GovernanceRecentPanel must not perform POST requests",
        )

    def test_contains_ephemeral_warning(self) -> None:
        self.assertIn(
            "phemeral",
            self.panel_src,
            "GovernanceRecentPanel must include the word 'ephemeral' to signal non-persistent data",
        )

    def test_contains_not_mso_health_qualifier(self) -> None:
        src_lower = self.panel_src.lower()
        has_qualifier = (
            "not mso health" in src_lower
            or "does not imply mso" in src_lower
            or "does not mean mso" in src_lower
        )
        self.assertTrue(
            has_qualifier,
            "GovernanceRecentPanel must include a qualifier clarifying this is "
            "not MSO health and does not imply MSO active",
        )

    def test_system_view_mounts_panel(self) -> None:
        self.assertIn(
            "GovernanceRecentPanel",
            self.system_view_src,
            "system-view.tsx must mount GovernanceRecentPanel",
        )

    def test_no_mso_active_fabrication(self) -> None:
        for src, name in (
            (self.panel_src,       "GovernanceRecentPanel.tsx"),
            (self.system_view_src, "system-view.tsx"),
        ):
            self.assertNotIn(
                "MSO ACTIVE",
                src,
                f"{name} must not render the string 'MSO ACTIVE' — "
                "governance decisions are not an authority badge",
            )

    def test_not_mounted_inside_readiness_panel(self) -> None:
        self.assertNotIn(
            "GovernanceRecentPanel",
            self.readiness_src,
            "GovernanceRecentPanel must not be mounted inside ReadinessPanel",
        )


class TestGovernanceStatusBand(unittest.TestCase):
    """GovernanceStatusBand invariants — S-MSO-GS-01.

    1. Component file exists and calls getGovernanceStatus.
    2. Proxy route is GET-only, force-dynamic, no token exposure.
    3. Types export GovernanceStatusResponse.
    4. system-view mounts GovernanceStatusBand.
    5. Component contains no mutation strings.
    6. Component contains 'not MSO active or healthy' qualifier.
    """

    def setUp(self) -> None:
        self.band_src        = _read("components/sovereign/GovernanceStatusBand.tsx")
        self.route_src       = _read("app/api/mso/governance/status/route.ts")
        self.types_src       = _read("lib/types.ts")
        self.api_src         = _read("lib/api.ts")
        self.system_view_src = _read("components/views/system-view.tsx")

    def test_band_calls_get_governance_status(self) -> None:
        self.assertIn(
            "getGovernanceStatus",
            self.band_src,
            "GovernanceStatusBand must call getGovernanceStatus",
        )

    def test_band_calls_local_proxy(self) -> None:
        self.assertIn(
            "/api/mso/governance/status",
            self.api_src,
            "getGovernanceStatus must target the local proxy /api/mso/governance/status",
        )

    def test_proxy_route_is_get_only(self) -> None:
        self.assertIn(
            "export async function GET",
            self.route_src,
            "Governance status proxy must export a GET handler",
        )
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertNotIn(
                f"export async function {method}",
                self.route_src,
                f"Governance status proxy must not export {method} (read-only endpoint)",
            )

    def test_proxy_route_is_force_dynamic(self) -> None:
        self.assertIn(
            "export const dynamic = 'force-dynamic'",
            self.route_src,
            "Governance status proxy must set dynamic = 'force-dynamic'",
        )

    def test_proxy_route_does_not_expose_token(self) -> None:
        self.assertNotIn(
            "WEBHOOK_TOKEN",
            self.route_src,
            "Governance status proxy must not reference WEBHOOK_TOKEN",
        )
        self.assertNotIn(
            "NEXT_PUBLIC_",
            self.route_src,
            "Governance status proxy must not use NEXT_PUBLIC_ env vars",
        )

    def test_governance_status_type_exported(self) -> None:
        self.assertIn(
            "export interface GovernanceStatusResponse",
            self.types_src,
            "ui/lib/types.ts must export GovernanceStatusResponse",
        )

    def test_system_view_mounts_band(self) -> None:
        self.assertIn(
            "GovernanceStatusBand",
            self.system_view_src,
            "system-view.tsx must mount GovernanceStatusBand",
        )

    def test_band_contains_no_mutation(self) -> None:
        for forbidden in ("fetch(", "POST", "DELETE", "mutation"):
            if forbidden in self.band_src:
                self.fail(
                    f"GovernanceStatusBand must not contain '{forbidden}' — read-only component",
                )

    def test_band_contains_not_mso_qualifier(self) -> None:
        src_lower = self.band_src.lower()
        has_qualifier = (
            "not mso health" in src_lower
            or "does not imply mso" in src_lower
            or "does not mean mso" in src_lower
        )
        self.assertTrue(
            has_qualifier,
            "GovernanceStatusBand must include a qualifier clarifying this does "
            "not imply MSO active or healthy",
        )

    def test_band_no_mso_active_fabrication(self) -> None:
        self.assertNotIn(
            "MSO ACTIVE",
            self.band_src,
            "GovernanceStatusBand must not render 'MSO ACTIVE'",
        )


# ─────────────────────────────────────────────────────────────────────────────
# S-CODE-READINESS-01D — UI passive surface contracts.
# ─────────────────────────────────────────────────────────────────────────────


class TestCodeReadinessProxy(unittest.TestCase):
    """The Next.js proxy at /api/code/readiness must be GET-only and server-auth."""

    def setUp(self) -> None:
        self.src = _read("app/api/code/readiness/route.ts")

    def test_proxy_exists(self) -> None:
        self.assertTrue(self.src.strip(), "proxy route file must not be empty")

    def test_proxy_is_get_only(self) -> None:
        self.assertIn("export async function GET", self.src)
        for forbidden in (
            "export async function POST",
            "export async function PUT",
            "export async function DELETE",
            "export async function PATCH",
        ):
            self.assertNotIn(
                forbidden, self.src,
                f"CODE readiness proxy must not export {forbidden} — read-only surface",
            )

    def test_proxy_uses_server_side_auth(self) -> None:
        self.assertIn("getWebhookHeaders", self.src)
        self.assertNotIn("NEXT_PUBLIC_ASSISTANT_TOKEN", self.src)
        self.assertNotIn("NEXT_PUBLIC_WEBHOOK_TOKEN", self.src)

    def test_proxy_targets_code_readiness_path(self) -> None:
        self.assertIn("/code/readiness", self.src)

    def test_proxy_returns_not_authority_envelope_on_failure(self) -> None:
        self.assertIn("not authority", self.src.lower())


class TestCodeReadinessHelper(unittest.TestCase):
    """getCodeReadiness must call the LOCAL proxy, not the webhook directly."""

    def setUp(self) -> None:
        self.src = _read("lib/api.ts")

    def test_helper_exists(self) -> None:
        self.assertIn("export async function getCodeReadiness", self.src)

    def test_helper_calls_local_proxy_only(self) -> None:
        idx = self.src.find("export async function getCodeReadiness")
        self.assertNotEqual(idx, -1)
        body = self.src[idx: idx + 1500]
        self.assertIn("/api/code/readiness", body)
        self.assertNotIn("WEBHOOK_BASE_URL", body)
        self.assertNotIn("ASSISTANT_TOKEN", body)


class TestReadinessPanelCodeReadinessRender(unittest.TestCase):
    """ReadinessPanel must render CODE readiness without authority/action affordances."""

    def setUp(self) -> None:
        self.src = _read("components/sovereign/ReadinessPanel.tsx")

    def test_imports_code_readiness_store(self) -> None:
        self.assertIn("useCodeReadinessStore", self.src)

    def test_imports_polling_hook(self) -> None:
        self.assertIn("useCodeReadinessPolling", self.src)

    def test_renders_code_readiness_section(self) -> None:
        self.assertIn("CODE Readiness", self.src)

    def test_no_action_buttons(self) -> None:
        for forbidden in (
            "<button",
            "onClick",
            "fetch(",
            "POST",
            "DELETE",
        ):
            self.assertNotIn(
                forbidden, self.src,
                f"ReadinessPanel must not contain '{forbidden}' — passive read-only surface",
            )

    def test_no_authority_wording(self) -> None:
        lowered = self.src.lower()
        for forbidden in (
            "ready to execute",
            "safe to apply",
            "authorized",
            "execution enabled",
            "mso active",
            "mso healthy",
        ):
            self.assertNotIn(
                forbidden, lowered,
                f"ReadinessPanel must not render authority wording: '{forbidden}'",
            )

    def test_includes_not_authority_qualifier(self) -> None:
        self.assertIn("not authority", self.src.lower())


# ─────────────────────────────────────────────────────────────────────────────
# S-CONFIRM-UI-01 — Confirm queue passive observability contracts.
# ─────────────────────────────────────────────────────────────────────────────


class TestConfirmPendingProxy(unittest.TestCase):
    """The Next.js proxy at /api/confirm/pending must be GET-only and server-auth."""

    def setUp(self) -> None:
        self.src = _read("app/api/confirm/pending/route.ts")

    def test_proxy_route_exists(self) -> None:
        self.assertTrue(self.src.strip(), "confirm pending proxy route must exist and not be empty")

    def test_proxy_is_get_only(self) -> None:
        self.assertIn("export async function GET", self.src)
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertNotIn(
                f"export async function {method}",
                self.src,
                f"confirm pending proxy must not export {method}",
            )

    def test_proxy_uses_server_auth_headers(self) -> None:
        self.assertIn("getWebhookHeaders", self.src)

    def test_proxy_no_next_public_secret_usage(self) -> None:
        self.assertNotIn("NEXT_PUBLIC_ASSISTANT_TOKEN", self.src)
        self.assertNotIn("NEXT_PUBLIC_WEBHOOK_TOKEN", self.src)


class TestConfirmPendingHelper(unittest.TestCase):
    """getConfirmPending must call local /api/confirm/pending, never webhook directly."""

    def setUp(self) -> None:
        self.src = _read("lib/api.ts")

    def test_helper_exists(self) -> None:
        self.assertIn("export async function getConfirmPending", self.src)

    def test_helper_calls_local_proxy_only(self) -> None:
        idx = self.src.find("export async function getConfirmPending")
        self.assertNotEqual(idx, -1)
        body = self.src[idx: idx + 1500]
        self.assertIn("/api/confirm/pending", body)
        self.assertNotIn("WEBHOOK_BASE_URL", body)
        self.assertNotIn("ASSISTANT_TOKEN", body)


class TestConfirmFlowQueuePanelContracts(unittest.TestCase):
    """ConfirmFlowQueuePanel must be passive observability-only UI."""

    def setUp(self) -> None:
        self.src = _read("components/sovereign/ConfirmFlowQueuePanel.tsx")

    def test_panel_exists(self) -> None:
        self.assertTrue(self.src.strip(), "ConfirmFlowQueuePanel source must exist")

    def test_panel_has_observability_governed_note(self) -> None:
        self.assertIn(
            "observability only; confirmation remains governed",
            self.src.lower(),
        )

    def test_panel_has_no_buttons_or_mutation_affordances(self) -> None:
        for forbidden in ("<button", "onClick", "POST", "DELETE"):
            self.assertNotIn(
                forbidden,
                self.src,
                f"ConfirmFlowQueuePanel must not include {forbidden}",
            )

    def test_forbidden_authority_strings_absent(self) -> None:
        lowered = self.src.lower()
        for forbidden in ("approve", "execute", "safe_to_apply", "ready_to_confirm", "authorized"):
            self.assertNotIn(
                forbidden,
                lowered,
                f"ConfirmFlowQueuePanel must not include forbidden authority wording: {forbidden}",
            )

    def test_panel_does_not_render_payload_or_authority_fields(self) -> None:
        lowered = self.src.lower()
        for forbidden in (
            "plan",
            "raw_text",
            "execution_plan",
            "policy_decision",
            "governance_verdict",
        ):
            self.assertNotIn(
                forbidden,
                lowered,
                f"ConfirmFlowQueuePanel must not render forbidden field: {forbidden}",
            )


class TestSystemViewMountsConfirmFlowQueuePanel(unittest.TestCase):
    """SystemView must import and render ConfirmFlowQueuePanel."""

    def setUp(self) -> None:
        self.src = _read("components/views/system-view.tsx")

    def test_system_view_imports_panel(self) -> None:
        self.assertIn("ConfirmFlowQueuePanel", self.src)

    def test_system_view_renders_panel(self) -> None:
        self.assertIn("<ConfirmFlowQueuePanel />", self.src)


class TestAuthorityStatusProxyContracts(unittest.TestCase):
    """Authority status proxy must remain GET-only, server-auth, and read-only."""

    def setUp(self) -> None:
        self.src = _read("app/api/mso/authority/status/route.ts")

    def test_proxy_exists(self) -> None:
        self.assertTrue(self.src.strip(), "authority status proxy route must exist and not be empty")

    def test_no_next_public_token(self) -> None:
        self.assertNotIn("NEXT_PUBLIC_", self.src)

    def test_proxy_uses_server_side_auth(self) -> None:
        self.assertIn(
            "getWebhookHeaders",
            self.src,
            "Authority status proxy must use getWebhookHeaders (server-side injection)",
        )
        self.assertNotIn("NEXT_PUBLIC_ASSISTANT_TOKEN", self.src)
        self.assertNotIn("NEXT_PUBLIC_WEBHOOK_TOKEN", self.src)

    def test_proxy_is_get_only(self) -> None:
        self.assertIn("export async function GET", self.src)
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertNotIn(
                f"export async function {method}",
                self.src,
                f"authority status proxy must not export {method}",
            )


class TestAuthorityMatrixPanelContracts(unittest.TestCase):
    """AuthorityMatrixPanel must be passive and posture-only."""

    def setUp(self) -> None:
        self.src = _read("components/sovereign/AuthorityMatrixPanel.tsx")

    def test_panel_has_mandatory_posture_copy(self) -> None:
        self.assertIn(
            "Authority status is posture, not execution permission.",
            self.src,
        )

    def test_panel_does_not_use_police_word(self) -> None:
        self.assertNotIn("Police", self.src)
        self.assertNotIn("police", self.src)

    def test_panel_has_no_mutation_affordances(self) -> None:
        for forbidden in ("<button", "onClick", "method: 'POST'", "method: \"POST\""):
            self.assertNotIn(
                forbidden,
                self.src,
                f"AuthorityMatrixPanel must not include mutation affordance: {forbidden}",
            )

    def test_panel_has_no_approve_deny_execute_buttons(self) -> None:
        # Keep this strict to button affordances only; backend posture words may include deny.
        lowered = self.src.lower()
        self.assertNotIn("approve</button", lowered)
        self.assertNotIn("deny</button", lowered)
        self.assertNotIn("execute</button", lowered)


class TestSystemViewMountsAuthorityMatrixPanel(unittest.TestCase):
    """SystemView must import and render AuthorityMatrixPanel."""

    def setUp(self) -> None:
        self.src = _read("components/views/system-view.tsx")

    def test_system_view_imports_panel(self) -> None:
        self.assertIn("AuthorityMatrixPanel", self.src)

    def test_system_view_renders_panel(self) -> None:
        self.assertIn("<AuthorityMatrixPanel />", self.src)


if __name__ == "__main__":
    unittest.main()
