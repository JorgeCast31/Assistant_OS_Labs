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


class TestSovereignNavigationContracts(unittest.TestCase):
    """Sovereign view IDs must match across types, sidebar, shell and store."""

    def setUp(self) -> None:
        self.types_src = _read("lib/sovereign/types.ts")
        self.sidebar_src = _read("components/sovereign/SidebarNavigation.tsx")
        self.shell_src = _read("components/sovereign/SovereignShell.tsx")
        self.store_src = _read("stores/sovereign-store.ts")

    def test_view_ids_present_in_type_union(self) -> None:
        for view_id in ("'system'", "'sovereign-status'", "'security'", "'mso'", "'agents'"):
            self.assertIn(view_id, self.types_src)

    def test_sidebar_declares_expected_zone_ids(self) -> None:
        for view_id in ("id: 'system'", "id: 'sovereign-status'", "id: 'security'", "id: 'mso'", "id: 'agents'"):
            self.assertIn(view_id, self.sidebar_src)

    def test_shell_switch_handles_expected_view_ids(self) -> None:
        for view_id in ("case 'system'", "case 'sovereign-status'", "case 'security'", "case 'mso'", "case 'agents'"):
            self.assertIn(view_id, self.shell_src)

    def test_store_initial_view_is_valid(self) -> None:
        self.assertIn("activeView: 'sovereign-status'", self.store_src)

    def test_unknown_view_has_safe_fallback(self) -> None:
        self.assertIn("default:", self.shell_src)
        self.assertIn("return <SystemChatView />", self.shell_src)


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


class TestPreparedActionsQueueUIContracts(unittest.TestCase):
    """ConfirmFlowQueuePanel must display prepared actions with review-only semantics.

    S-PREPARED-ACTIONS-01 invariants:
    1. Panel must render 'Manual review only' or equivalent copy.
    2. Panel must not render approve/execute controls.
    3. Panel must not expose execution affordance.
    4. Panel must remain mounted in SovereignStatusView.
    5. Panel must show prepared actions section.
    6. Panel must poll prepared actions endpoint.
    """

    def setUp(self) -> None:
        self.panel_src = _read("components/sovereign/ConfirmFlowQueuePanel.tsx")
        self.sovereign_src = _read("components/sovereign/SovereignStatusView.tsx")

    def test_panel_mounted_in_sovereign_status_view(self) -> None:
        self.assertIn(
            "ConfirmFlowQueuePanel",
            self.sovereign_src,
            "ConfirmFlowQueuePanel must remain mounted in SovereignStatusView",
        )

    def test_panel_renders_review_only_copy(self) -> None:
        panel_lower = self.panel_src.lower()
        has_review_only = "manual review only" in panel_lower or "review only" in panel_lower
        self.assertTrue(
            has_review_only,
            "ConfirmFlowQueuePanel must render 'manual review only' or 'review only' copy",
        )

    def test_panel_renders_not_execution_copy(self) -> None:
        panel_lower = self.panel_src.lower()
        has_not_execution = "not execution" in panel_lower or "no execution" in panel_lower
        self.assertTrue(
            has_not_execution,
            "ConfirmFlowQueuePanel must render copy clarifying this is not execution",
        )

    def test_panel_shows_prepared_actions_section(self) -> None:
        self.assertIn(
            "Prepared Actions",
            self.panel_src,
            "ConfirmFlowQueuePanel must render a 'Prepared Actions' section",
        )

    def test_panel_polls_prepared_actions_endpoint(self) -> None:
        self.assertIn(
            "usePreparedActionsPolling",
            self.panel_src,
            "ConfirmFlowQueuePanel must invoke usePreparedActionsPolling hook",
        )

    def test_panel_no_approve_button(self) -> None:
        panel_lower = self.panel_src.lower()
        self.assertNotIn(
            "approve",
            panel_lower,
            "ConfirmFlowQueuePanel must not render an approve button or control",
        )

    def test_panel_no_execute_button(self) -> None:
        for line in self.panel_src.splitlines():
            line_lower = line.lower()
            if "button" in line_lower and "execut" in line_lower:
                self.fail(
                    f"ConfirmFlowQueuePanel must not render an execute button: {line.strip()}"
                )

    def test_panel_no_confirm_mutation(self) -> None:
        self.assertNotIn(
            "POST",
            self.panel_src,
            "ConfirmFlowQueuePanel must not make POST requests (read-only surface)",
        )

    def test_panel_no_runner_endpoint(self) -> None:
        panel_lower = self.panel_src.lower()
        self.assertNotIn(
            "/agent/execute",
            panel_lower,
            "ConfirmFlowQueuePanel must not call /agent/execute",
        )

    def test_prepared_actions_proxy_route_is_get_only(self) -> None:
        route_src = _read("app/api/mso/prepared-actions/pending/route.ts")
        self.assertIn(
            "export async function GET",
            route_src,
            "Prepared actions proxy route must export a GET handler",
        )
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertNotIn(
                f"export async function {method}",
                route_src,
                f"Prepared actions proxy route must not export {method}",
            )

    def test_prepared_actions_proxy_review_only_in_unavailable(self) -> None:
        route_src = _read("app/api/mso/prepared-actions/pending/route.ts")
        self.assertIn(
            "review_only",
            route_src,
            "Prepared actions proxy must include review_only in its fallback response",
        )
        self.assertIn(
            "execution_allowed",
            route_src,
            "Prepared actions proxy must include execution_allowed in its fallback response",
        )

    def test_prepared_actions_store_read_only_defaults(self) -> None:
        store_src = _read("stores/prepared-actions-store.ts")
        self.assertIn(
            "preparedActions",
            store_src,
            "prepared-actions-store must define preparedActions state",
        )

    def test_prepared_actions_api_fn_calls_local_proxy(self) -> None:
        api_src = _read("lib/api.ts")
        self.assertIn(
            "/api/mso/prepared-actions/pending",
            api_src,
            "getPreparedActionsPending must call the local Next.js proxy",
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

    def test_panel_avoids_object_literal_store_selector(self) -> None:
        self.assertNotIn(
            "useConfirmPendingStore((s) => ({",
            self.src,
            "ConfirmFlowQueuePanel must avoid object-literal Zustand selectors to prevent unstable snapshots",
        )


class TestSovereignStatusMountsConfirmFlowQueuePanel(unittest.TestCase):
    """ConfirmFlowQueuePanel belongs to Sovereign Status, not SystemView."""

    def setUp(self) -> None:
        self.status_src = _read("components/sovereign/SovereignStatusView.tsx")
        self.system_src = _read("components/views/system-view.tsx")

    def test_status_view_imports_and_renders_panel(self) -> None:
        self.assertIn("ConfirmFlowQueuePanel", self.status_src)
        self.assertIn("<ConfirmFlowQueuePanel />", self.status_src)

    def test_system_view_does_not_mount_panel(self) -> None:
        self.assertNotIn("ConfirmFlowQueuePanel", self.system_src)


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


class TestSecurityViewMountsAuthorityMatrixPanel(unittest.TestCase):
    """AuthorityMatrixPanel belongs to Sovereign Security, not SystemView."""

    def setUp(self) -> None:
        self.security_src = _read("components/sovereign/SecurityView.tsx")
        self.system_src = _read("components/views/system-view.tsx")

    def test_security_view_imports_and_renders_panel(self) -> None:
        self.assertIn("AuthorityMatrixPanel", self.security_src)
        self.assertIn("<AuthorityMatrixPanel />", self.security_src)

    def test_system_view_does_not_mount_panel(self) -> None:
        self.assertNotIn("AuthorityMatrixPanel", self.system_src)


class TestOutcomeStatusProxyContracts(unittest.TestCase):
    """Outcome status proxy must be GET-only, server-auth, and read-only."""

    def setUp(self) -> None:
        self.src = _read("app/api/mso/outcome/status/route.ts")

    def test_proxy_route_exists(self) -> None:
        self.assertTrue(self.src.strip(), "outcome status proxy route must exist and not be empty")

    def test_proxy_uses_server_side_auth(self) -> None:
        self.assertIn("getWebhookHeaders", self.src)

    def test_proxy_no_next_public_tokens(self) -> None:
        self.assertNotIn("NEXT_PUBLIC_ASSISTANT_TOKEN", self.src)
        self.assertNotIn("NEXT_PUBLIC_WEBHOOK_TOKEN", self.src)

    def test_proxy_is_get_only(self) -> None:
        self.assertIn("export async function GET", self.src)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertNotIn(
                f"export async function {method}",
                self.src,
                f"outcome status proxy must not export {method}",
            )

    def test_proxy_forwards_supported_query_params(self) -> None:
        for name in ("plan_id", "context_id", "trace_id", "execution_id"):
            self.assertIn(name, self.src, f"outcome status proxy must forward query param: {name}")

    def test_proxy_targets_backend_outcome_status(self) -> None:
        self.assertIn("/mso/outcome/status", self.src)

    def test_proxy_contains_no_mutation_affordances(self) -> None:
        for forbidden in ("<button", "onClick", "method: 'POST'", "method: \"POST\""):
            self.assertNotIn(
                forbidden,
                self.src,
                f"outcome status proxy must not include mutation affordance: {forbidden}",
            )


class TestOutcomeStatusTypesAndHelperContracts(unittest.TestCase):
    """Outcome status types/helper must stay local-proxy based and read-only."""

    def setUp(self) -> None:
        self.types_src = _read("lib/types.ts")
        self.api_src = _read("lib/api.ts")

    def test_types_include_outcome_status_response(self) -> None:
        self.assertIn("export interface OutcomeStatusResponse", self.types_src)

    def test_helper_exists(self) -> None:
        self.assertIn("export async function getOutcomeStatus", self.api_src)

    def test_helper_calls_local_proxy(self) -> None:
        idx = self.api_src.find("export async function getOutcomeStatus")
        self.assertNotEqual(idx, -1)
        body = self.api_src[idx: idx + 2000]
        self.assertIn("/api/mso/outcome/status", body)

    def test_helper_does_not_call_backend_directly(self) -> None:
        idx = self.api_src.find("export async function getOutcomeStatus")
        self.assertNotEqual(idx, -1)
        body = self.api_src[idx: idx + 2000]
        self.assertNotIn("WEBHOOK_BASE_URL", body)
        self.assertNotIn("getWebhookBaseUrl", body)
        self.assertNotIn("http://localhost:8787", body)

    def test_semantic_copy_present_in_fallback(self) -> None:
        copy = "Outcome status is observational; it does not grant execution permission."
        self.assertTrue(copy in self.api_src or copy in _read("app/api/mso/outcome/status/route.ts"))

    def test_helper_contains_no_mutation_affordances(self) -> None:
        idx = self.api_src.find("export async function getOutcomeStatus")
        self.assertNotEqual(idx, -1)
        body = self.api_src[idx: idx + 2000].lower()
        self.assertNotIn("method: 'post'", body)
        self.assertNotIn('method: "post"', body)
        self.assertNotIn("<button", body)
        self.assertNotIn("onclick", body)

    def test_no_action_keywords_as_controls(self) -> None:
        route_src = _read("app/api/mso/outcome/status/route.ts").lower()
        idx = self.api_src.find("export async function getOutcomeStatus")
        helper_src = self.api_src[idx: idx + 2000].lower() if idx != -1 else ""
        for keyword in ("execute", "approve", "confirm", "apply", "retry"):
            self.assertNotIn(f"{keyword}</button", route_src)
            self.assertNotIn(f"{keyword}</button", helper_src)
            self.assertNotIn(f"on{keyword}", route_src)
            self.assertNotIn(f"on{keyword}", helper_src)


class TestOutcomeStatusPanelContracts(unittest.TestCase):
    """OutcomeStatusPanel must remain passive observability-only UI."""

    def setUp(self) -> None:
        self.panel_src = _read("components/sovereign/OutcomeStatusPanel.tsx")
        self.store_src = _read("stores/outcome-status-store.ts")
        self.hook_src = _read("hooks/use-outcome-status-polling.ts")
        self.system_view_src = _read("components/views/system-view.tsx")
        self.status_view_src = _read("components/sovereign/SovereignStatusView.tsx")
        self.proxy_src = _read("app/api/mso/outcome/status/route.ts")

    def test_panel_exists(self) -> None:
        self.assertIn("export function OutcomeStatusPanel", self.panel_src)

    def test_panel_contains_semantic_copy(self) -> None:
        self.assertIn(
            "Outcome status is observational; it does not grant execution permission.",
            self.panel_src,
        )

    def test_panel_has_no_buttons_or_click_handlers(self) -> None:
        self.assertNotIn("<button", self.panel_src)
        self.assertNotIn("onClick", self.panel_src)

    def test_panel_has_no_post_or_mutation(self) -> None:
        self.assertNotIn("method: \"POST\"", self.panel_src)
        self.assertNotIn("method: 'POST'", self.panel_src)
        self.assertNotIn("fetch(", self.panel_src)

    def test_panel_has_no_action_affordance_keywords(self) -> None:
        lowered = self.panel_src.lower()
        for keyword in ("approve", "confirm", "execute", "apply", "retry"):
            self.assertNotIn(f"{keyword}</button", lowered)
            self.assertNotIn(f"on{keyword}", lowered)

    def test_store_exists(self) -> None:
        self.assertIn("export const useOutcomeStatusStore", self.store_src)

    def test_panel_avoids_object_literal_store_selector(self) -> None:
        self.assertNotIn(
            "useOutcomeStatusStore((s) => ({",
            self.panel_src,
            "OutcomeStatusPanel must avoid object-literal Zustand selectors to prevent unstable snapshots",
        )

    def test_hook_exists(self) -> None:
        self.assertIn("export function useOutcomeStatusPolling", self.hook_src)

    def test_hook_calls_get_outcome_status(self) -> None:
        self.assertIn("getOutcomeStatus", self.hook_src)

    def test_store_and_hook_use_no_post(self) -> None:
        self.assertNotIn("POST", self.store_src)
        self.assertNotIn("method: 'POST'", self.hook_src)
        self.assertNotIn("method: \"POST\"", self.hook_src)

    def test_sovereign_status_imports_and_renders_panel(self) -> None:
        self.assertIn("OutcomeStatusPanel", self.status_view_src)
        self.assertIn("<OutcomeStatusPanel />", self.status_view_src)

    def test_system_view_does_not_mount_panel(self) -> None:
        self.assertNotIn("OutcomeStatusPanel", self.system_view_src)

    def test_no_direct_backend_webhook_usage_in_panel_store_hook(self) -> None:
        merged = "\n".join([self.panel_src, self.store_src, self.hook_src])
        self.assertNotIn("WEBHOOK_BASE_URL", merged)
        self.assertNotIn("getWebhookBaseUrl", merged)
        self.assertNotIn("http://localhost:8787", merged)

    def test_no_new_endpoint_or_proxy_mutation_surface(self) -> None:
        # UI-B must not add write operations to the existing outcome proxy route.
        self.assertIn("export async function GET", self.proxy_src)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertNotIn(f"export async function {method}", self.proxy_src)


class TestChatSurfacePropagation(unittest.TestCase):
    """S-CHAT-01B — surface='assistant_chat' must be wired end-to-end in the main chat."""

    def setUp(self) -> None:
        self.types_src    = _read("lib/types.ts")
        self.api_src      = _read("lib/api.ts")
        self.chat_src     = _read("components/views/chat-view.tsx")
        self.route_src    = _read("app/api/chat/process/route.ts")

    # 1. SendChatRequest must declare surface as an optional field.
    def test_send_chat_request_has_surface_field(self) -> None:
        self.assertIn(
            "surface?: string",
            self.types_src,
            "SendChatRequest in types.ts must declare 'surface?: string'",
        )

    # 2. sendChatMessage must forward req.surface to the request body.
    def test_send_chat_message_propagates_surface(self) -> None:
        self.assertIn(
            "req.surface",
            self.api_src,
            "sendChatMessage in api.ts must reference req.surface",
        )
        self.assertIn(
            "body.surface",
            self.api_src,
            "sendChatMessage in api.ts must assign body.surface",
        )

    # 3. chat-view.tsx call site must pass surface: 'assistant_chat'.
    def test_chat_view_sends_assistant_chat_surface(self) -> None:
        self.assertIn(
            "surface: 'assistant_chat'",
            self.chat_src,
            "chat-view.tsx must pass surface: 'assistant_chat' to sendChatMessage",
        )

    # 4. Proxy route must still propagate body.surface (regression guard).
    def test_route_propagates_body_surface(self) -> None:
        self.assertIn(
            "body.surface",
            self.route_src,
            "app/api/chat/process/route.ts must propagate body.surface to upstream payload",
        )

    # 5. UI must not contain semantic routing logic (no if-text-includes checks).
    def test_no_semantic_logic_in_chat_view(self) -> None:
        forbidden_patterns = [
            r"text\.includes\(",
            r"text\.startsWith\(",
            r"\.toLowerCase\(\).*hola",
            r"\.toLowerCase\(\).*status",
        ]
        for pattern in forbidden_patterns:
            self.assertIsNone(
                re.search(pattern, self.chat_src),
                f"chat-view.tsx must not contain semantic routing pattern: {pattern}",
            )

    # 6. No new buttons or action surfaces added (structural guard).
    def test_no_new_action_buttons_in_chat_view(self) -> None:
        # Count <button elements — file should not have grown by a surface-adding block.
        # This is a regression floor: if the count exceeds a reasonable cap the
        # test will prompt review. Current cap is 20 (generous ceiling).
        button_count = self.chat_src.count("<button")
        self.assertLessEqual(
            button_count,
            20,
            f"chat-view.tsx contains {button_count} <button elements — review for unintended UI additions",
        )


# ─────────────────────────────────────────────────────────────────────────────
# S-POLICE-SURFACE-00A — Static UI truth contracts for Police/Candidate terms.
# ─────────────────────────────────────────────────────────────────────────────

# Future vocabulary contract (test-local only):
# - PoliceEvaluation: ALLOW / DENY / REQUIRES_CONFIRMATION
# - PoliceDecision: permitted / denied / deferred
# - MissionExecutionCandidate: pending_gate
POLICE_EVALUATION_VOCAB = ("ALLOW", "DENY", "REQUIRES_CONFIRMATION")
POLICE_DECISION_VOCAB = ("permitted", "denied", "deferred")
MISSION_EXECUTION_CANDIDATE_GATE = ("pending_gate",)

POLICE_SURFACE_CURRENT_FILES = (
    "lib/types.ts",
    "components/sovereign/SecurityView.tsx",
    "components/sovereign/AuthorityMatrixPanel.tsx",
    "components/sovereign/GovernanceStatusBand.tsx",
    "components/sovereign/GovernanceRecentPanel.tsx",
)

POLICE_SURFACE_FUTURE_FILES = (
    "components/sovereign/PoliceSurfacePanel.tsx",
    "components/sovereign/PoliceDecisionPanel.tsx",
    "components/sovereign/PoliceEvaluationPanel.tsx",
    "components/sovereign/MissionExecutionCandidatePanel.tsx",
    "components/sovereign/CandidateAuditRecordPanel.tsx",
    "components/sovereign/AgentPermissionProfilePanel.tsx",
)


def _iter_lines(rel: str):
    for idx, line in enumerate(_read(rel).splitlines(), start=1):
        yield idx, line


def _existing_future_surface_files() -> list[str]:
    return [rel for rel in POLICE_SURFACE_FUTURE_FILES if (UI_ROOT / rel).exists()]


class TestPoliceDecisionVocabularyNotCollapsed(unittest.TestCase):
    """Police/Candidate authority vocabularies must remain semantically separated."""

    def test_police_decision_and_evaluation_vocabulary_separation(self) -> None:
        for rel in POLICE_SURFACE_CURRENT_FILES:
            for line_no, line in _iter_lines(rel):
                lowered = line.lower()

                if "policedecision" in lowered:
                    for forbidden in ("allow", "deny", "requires_confirmation"):
                        if forbidden in lowered:
                            self.fail(
                                f"{rel}:{line_no} collapses PoliceDecision with PoliceEvaluation term '{forbidden}': "
                                f"{line.strip()}"
                            )

                if "policeevaluation" in lowered:
                    for forbidden in ("permitted", "denied", "deferred"):
                        if forbidden in lowered:
                            self.fail(
                                f"{rel}:{line_no} collapses PoliceEvaluation with PoliceDecision term '{forbidden}': "
                                f"{line.strip()}"
                            )

                if "pending_gate" in lowered and any(
                    term in lowered for term in ("authorized", "approved", "execution enabled")
                ):
                    self.fail(
                        f"{rel}:{line_no} collapses pending_gate with authorization wording: {line.strip()}"
                    )


class TestPoliceEvaluationAllowNotAuthorization(unittest.TestCase):
    """PoliceEvaluation.ALLOW must not be represented as execution authorization."""

    def test_allow_not_mapped_to_authorization_language(self) -> None:
        forbidden = (
            "authorized",
            "authorization",
            "execution enabled",
            "ready to execute",
            "permitted",
        )
        for rel in POLICE_SURFACE_CURRENT_FILES:
            for line_no, line in _iter_lines(rel):
                lowered = line.lower()
                if "policeevaluation" in lowered and "allow" in lowered:
                    for word in forbidden:
                        if word in lowered:
                            self.fail(
                                f"{rel}:{line_no} maps PoliceEvaluation.ALLOW to authorization '{word}': "
                                f"{line.strip()}"
                            )


class TestMissionExecutionCandidatePendingGateNotApproved(unittest.TestCase):
    """MissionExecutionCandidate pending_gate must not be shown as approved/authorized."""

    def test_pending_gate_not_approved_authorized_or_permitted(self) -> None:
        forbidden = ("authorized", "approved", "permitted", "ready to execute", "execution enabled")
        for rel in POLICE_SURFACE_CURRENT_FILES:
            for line_no, line in _iter_lines(rel):
                lowered = line.lower()
                if ("pending_gate" in lowered or "pending_gate" in line) and any(
                    word in lowered for word in forbidden
                ):
                    self.fail(
                        f"{rel}:{line_no} maps pending_gate to authorization semantics: {line.strip()}"
                    )


class TestPoliceSurfaceNoMutationAffordances(unittest.TestCase):
    """Police/Candidate terms must not carry action or mutation affordances in UI text."""

    def test_model_mentions_are_read_only(self) -> None:
        subject_terms = (
            "policeevaluation",
            "policedecision",
            "missionexecutioncandidate",
            "pending_gate",
            "candidateauditrecord",
            "agentpermissionprofile",
        )
        forbidden = (
            "onclick",
            "button",
            "approve",
            "deny",
            "authorize",
            "execute",
            "launch",
            "post",
            "put",
            "patch",
            "delete",
        )
        scan_files = _existing_future_surface_files() or list(POLICE_SURFACE_CURRENT_FILES)

        for rel in scan_files:
            for line_no, line in _iter_lines(rel):
                lowered = line.lower()
                if any(term in lowered for term in subject_terms) and any(
                    token in lowered for token in forbidden
                ):
                    self.fail(
                        f"{rel}:{line_no} combines model term with mutation/action affordance: {line.strip()}"
                    )


class TestAgentPermissionProfileScopeOnly(unittest.TestCase):
    """AgentPermissionProfile must remain scope-only and non-executional."""

    def test_agent_permission_profile_has_no_execution_language(self) -> None:
        forbidden = (
            "execute",
            "launch",
            "authorize execution",
            "runner",
            "pipeline",
            "machine operator",
        )
        for rel in POLICE_SURFACE_CURRENT_FILES:
            for line_no, line in _iter_lines(rel):
                lowered = line.lower()
                if "agentpermissionprofile" in lowered and any(word in lowered for word in forbidden):
                    self.fail(
                        f"{rel}:{line_no} mixes AgentPermissionProfile with execution wording: {line.strip()}"
                    )


class TestPoliceSurfaceFutureVocabularyDocumentedInComments(unittest.TestCase):
    """Positive guard: future vocabulary is documented in this test module."""

    def test_expected_vocab_constants_are_present(self) -> None:
        self.assertEqual(POLICE_EVALUATION_VOCAB, ("ALLOW", "DENY", "REQUIRES_CONFIRMATION"))
        self.assertEqual(POLICE_DECISION_VOCAB, ("permitted", "denied", "deferred"))
        self.assertEqual(MISSION_EXECUTION_CANDIDATE_GATE, ("pending_gate",))


class TestMSOViewLiveSeatReconciliation(unittest.TestCase):
    """MSOView must display live seat provider data and honest posture.

    S-MSO-SEAT-PROVIDER-01 invariants:
    1. MSOView imports useSeatProviderPolling hook.
    2. MSOView imports useSeatProviderStore store.
    3. MSOView does not contain 'Current Seat Actor: Unknown' static string.
    4. MSOView does not contain 'Pending harness' text.
    5. MSOView contains 'read-only' copy.
    6. MSOView contains 'non-executing' or 'does not execute' copy.
    7. MSOView does not render approve/execute controls.
    8. MSOView does not claim execution is open.
    9. MSOView displays provider availability labels (live rows).
    10. MSOView displays Orchestration Capability section.
    11. MSOView displays CODE/docs posture section.
    12. Proxy route is GET-only, force-dynamic, server-auth.
    13. API helper calls local proxy, not webhook directly.
    14. Types export MSOSeatProviderResponse.
    """

    def setUp(self) -> None:
        self.mso_src = _read("components/sovereign/MSOView.tsx")
        self.route_src = _read("app/api/mso/seat/provider/route.ts")
        self.api_src = _read("lib/api.ts")
        self.types_src = _read("lib/types.ts")

    def test_mso_view_imports_seat_provider_polling(self) -> None:
        self.assertIn(
            "useSeatProviderPolling",
            self.mso_src,
            "MSOView must import useSeatProviderPolling hook",
        )

    def test_mso_view_imports_seat_provider_store(self) -> None:
        self.assertIn(
            "useSeatProviderStore",
            self.mso_src,
            "MSOView must import useSeatProviderStore",
        )

    def test_no_hardcoded_current_seat_actor_unknown(self) -> None:
        self.assertNotIn(
            "Current Seat Actor",
            self.mso_src,
            "MSOView must not contain stale 'Current Seat Actor: Unknown' static string",
        )

    def test_no_pending_harness(self) -> None:
        self.assertNotIn(
            "Pending harness",
            self.mso_src,
            "MSOView must not contain outdated 'Pending harness' text — "
            "CODE/docs preparation chain is live",
        )

    def test_contains_read_only_copy(self) -> None:
        self.assertIn(
            "read-only",
            self.mso_src.lower(),
            "MSOView must contain 'read-only' copy",
        )

    def test_contains_non_executing_copy(self) -> None:
        src_lower = self.mso_src.lower()
        has_non_executing = (
            "non-executing" in src_lower
            or "does not execute" in src_lower
            or "not execute" in src_lower
        )
        self.assertTrue(
            has_non_executing,
            "MSOView must contain 'non-executing' or 'does not execute' copy",
        )

    def test_no_approve_button(self) -> None:
        self.assertNotIn(
            "<button",
            self.mso_src,
            "MSOView must not render any buttons (no approve/execute controls)",
        )

    def test_no_execution_open_claim(self) -> None:
        lowered = self.mso_src.lower()
        for forbidden in ("execution open", "execution enabled", "ready to execute"):
            self.assertNotIn(
                forbidden,
                lowered,
                f"MSOView must not claim execution is open: '{forbidden}'",
            )

    def test_contains_provider_availability_label(self) -> None:
        self.assertIn(
            "Provider Availability",
            self.mso_src,
            "MSOView must display a live 'Provider Availability' label",
        )

    def test_contains_orchestration_capability_section(self) -> None:
        self.assertIn(
            "Orchestration Capability",
            self.mso_src,
            "MSOView must contain 'Orchestration Capability' section",
        )

    def test_contains_code_docs_posture_section(self) -> None:
        src_lower = self.mso_src.lower()
        has_code_docs = "code/docs" in src_lower or "code / docs" in src_lower
        self.assertTrue(
            has_code_docs,
            "MSOView must contain 'CODE/docs' posture section",
        )

    def test_proxy_route_is_get_only(self) -> None:
        self.assertIn(
            "export async function GET",
            self.route_src,
            "MSO seat provider proxy must export a GET handler",
        )
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertNotIn(
                f"export async function {method}",
                self.route_src,
                f"MSO seat provider proxy must not export {method}",
            )

    def test_proxy_route_is_force_dynamic(self) -> None:
        self.assertIn(
            "export const dynamic = 'force-dynamic'",
            self.route_src,
            "MSO seat provider proxy must set dynamic = 'force-dynamic'",
        )

    def test_proxy_route_uses_server_side_auth(self) -> None:
        self.assertIn(
            "getWebhookHeaders",
            self.route_src,
            "MSO seat provider proxy must use getWebhookHeaders (server-side injection)",
        )
        self.assertNotIn("NEXT_PUBLIC_ASSISTANT_TOKEN", self.route_src)
        self.assertNotIn("NEXT_PUBLIC_WEBHOOK_TOKEN", self.route_src)

    def test_proxy_route_never_exposes_token(self) -> None:
        self.assertNotIn(
            "WEBHOOK_TOKEN",
            self.route_src,
            "MSO seat provider proxy must not reference WEBHOOK_TOKEN",
        )

    def test_proxy_route_execution_allowed_false_in_unavailable(self) -> None:
        self.assertIn(
            "execution_allowed",
            self.route_src,
            "MSO seat provider proxy must include execution_allowed in its fallback response",
        )

    def test_proxy_route_can_execute_now_false_in_unavailable(self) -> None:
        self.assertIn(
            "can_execute_now",
            self.route_src,
            "MSO seat provider proxy must include can_execute_now in its fallback response",
        )

    def test_api_helper_calls_local_proxy(self) -> None:
        self.assertIn(
            "/api/mso/seat/provider",
            self.api_src,
            "getMSOSeatProvider must call the local Next.js proxy /api/mso/seat/provider",
        )

    def test_api_helper_not_direct_webhook(self) -> None:
        idx = self.api_src.find("export async function getMSOSeatProvider")
        self.assertNotEqual(idx, -1, "getMSOSeatProvider must be defined in api.ts")
        body = self.api_src[idx: idx + 1500]
        self.assertNotIn(
            "WEBHOOK_BASE_URL",
            body,
            "getMSOSeatProvider must not call WEBHOOK_BASE_URL directly",
        )

    def test_types_export_mso_seat_provider_response(self) -> None:
        self.assertIn(
            "export interface MSOSeatProviderResponse",
            self.types_src,
            "ui/lib/types.ts must export MSOSeatProviderResponse",
        )

    def test_types_export_mso_seat_provider_detail(self) -> None:
        self.assertIn(
            "export interface MSOSeatProviderDetail",
            self.types_src,
            "ui/lib/types.ts must export MSOSeatProviderDetail",
        )

    # ── Post-PR#178 reconciliation additions ────────────────────────────────

    def test_mso_view_imports_prepared_actions_polling(self) -> None:
        self.assertIn(
            "usePreparedActionsPolling",
            self.mso_src,
            "MSOView must import usePreparedActionsPolling after PR#178 queue is active",
        )

    def test_mso_view_imports_confirm_pending_polling(self) -> None:
        self.assertIn(
            "useConfirmPendingPolling",
            self.mso_src,
            "MSOView must import useConfirmPendingPolling",
        )

    def test_mso_view_imports_prepared_actions_store(self) -> None:
        self.assertIn(
            "usePreparedActionsStore",
            self.mso_src,
            "MSOView must import usePreparedActionsStore",
        )

    def test_mso_view_imports_confirm_pending_store(self) -> None:
        self.assertIn(
            "useConfirmPendingStore",
            self.mso_src,
            "MSOView must import useConfirmPendingStore",
        )

    def test_mso_view_queue_timeline_section(self) -> None:
        has_section = (
            "Queue" in self.mso_src and "Timeline" in self.mso_src
        )
        self.assertTrue(
            has_section,
            "MSOView must contain a Queue & Timeline Summary section",
        )

    def test_mso_view_references_authority_timeline(self) -> None:
        self.assertIn(
            "authority timeline",
            self.mso_src.lower(),
            "MSOView must reference 'authority timeline' in its queue section",
        )

    def test_mso_view_references_eleven_stages(self) -> None:
        self.assertIn(
            "11",
            self.mso_src,
            "MSOView queue section must reference the 11-stage authority timeline",
        )

    def test_mso_view_next_safe_step_section(self) -> None:
        self.assertIn(
            "Next Safe Step",
            self.mso_src,
            "MSOView must contain a 'Next Safe Step' section",
        )

    def test_mso_view_next_step_references_plan_request(self) -> None:
        self.assertIn(
            "plan_request",
            self.mso_src,
            "MSOView Next Safe Step must reference 'plan_request'",
        )

    def test_mso_view_execution_remains_closed(self) -> None:
        self.assertIn(
            "execution remains closed",
            self.mso_src.lower(),
            "MSOView must state 'execution remains closed'",
        )

    def test_mso_view_references_mission_control(self) -> None:
        self.assertIn(
            "Mission Control",
            self.mso_src,
            "MSOView queue section must point to Mission Control",
        )


# ---------------------------------------------------------------------------
# TestMissionControlV1 — Mission Control v1 Read-only Situation Room
# ---------------------------------------------------------------------------


class TestMissionControlV1(unittest.TestCase):
    """
    Contract tests for Mission Control v1 read-only composite panel.
    """

    COMPONENT_PATH = Path(__file__).parent.parent / "ui" / "components" / "sovereign" / "MissionControlView.tsx"
    SHELL_PATH = Path(__file__).parent.parent / "ui" / "components" / "sovereign" / "SovereignShell.tsx"
    SIDEBAR_PATH = Path(__file__).parent.parent / "ui" / "components" / "sovereign" / "SidebarNavigation.tsx"
    INDEX_PATH = Path(__file__).parent.parent / "ui" / "components" / "sovereign" / "index.ts"
    TYPES_PATH = Path(__file__).parent.parent / "ui" / "lib" / "sovereign" / "types.ts"

    def setUp(self) -> None:
        self.assertTrue(self.COMPONENT_PATH.exists(), "MissionControlView.tsx must exist")
        self.component_src = self.COMPONENT_PATH.read_text()
        self.shell_src = self.SHELL_PATH.read_text()
        self.sidebar_src = self.SIDEBAR_PATH.read_text()
        self.index_src = self.INDEX_PATH.read_text()
        self.types_src = self.TYPES_PATH.read_text()

    def test_mission_control_file_exists(self) -> None:
        self.assertTrue(self.COMPONENT_PATH.exists(), "MissionControlView.tsx must exist")

    def test_mission_control_exported_from_index(self) -> None:
        self.assertIn("MissionControlView", self.index_src)

    def test_mission_control_imported_in_shell(self) -> None:
        self.assertIn("MissionControlView", self.shell_src)

    def test_mission_control_case_in_shell(self) -> None:
        self.assertIn("mission-control", self.shell_src)

    def test_sovereign_view_id_includes_mission_control(self) -> None:
        self.assertIn("mission-control", self.types_src)

    def test_sidebar_includes_mission_control_zone(self) -> None:
        self.assertIn("mission-control", self.sidebar_src)

    def test_sidebar_includes_mission_control_label(self) -> None:
        self.assertIn("Mission Control", self.sidebar_src)

    def test_contains_read_only_copy(self) -> None:
        self.assertIn("Read-only", self.component_src)

    def test_contains_does_not_execute_copy(self) -> None:
        self.assertIn("does not execute", self.component_src)

    def test_contains_execution_remains_closed_copy(self) -> None:
        self.assertIn("execution remains", self.component_src.lower())

    def test_no_approve_button(self) -> None:
        # Component may mention "approves" in safety copy — check for mutation handlers only
        self.assertNotIn("handleApprove", self.component_src)
        self.assertNotIn("onApprove", self.component_src)
        self.assertNotIn("postApprove", self.component_src)

    def test_no_handle_execute(self) -> None:
        self.assertNotIn("handleExecute", self.component_src)

    def test_no_post_confirm_mutation(self) -> None:
        self.assertNotIn("postConfirm", self.component_src)

    def test_no_issue_token(self) -> None:
        self.assertNotIn("issueToken", self.component_src)

    def test_no_authorized_plan_creation(self) -> None:
        # Component may reference "AuthorizedPlan" in read-only posture copy.
        # Check that it is NOT imported as a TypeScript type (i.e., not used as a constructor).
        self.assertNotIn("import.*AuthorizedPlan", self.component_src)
        self.assertNotIn("new AuthorizedPlan", self.component_src)

    def test_references_mso_seat_section(self) -> None:
        self.assertIn("MSO Seat", self.component_src)

    def test_imports_seat_provider_store(self) -> None:
        self.assertIn("useSeatProviderStore", self.component_src)

    def test_imports_seat_provider_polling(self) -> None:
        self.assertIn("useSeatProviderPolling", self.component_src)

    def test_references_prepared_actions_store(self) -> None:
        self.assertIn("preparedActions", self.component_src)

    def test_references_manual_review(self) -> None:
        self.assertIn("manual review", self.component_src)

    def test_imports_prepared_actions_polling(self) -> None:
        self.assertIn("usePreparedActionsPolling", self.component_src)

    def test_references_police_gate(self) -> None:
        self.assertIn("Police Gate", self.component_src)

    def test_references_governed_execution(self) -> None:
        self.assertIn("Governed Execution", self.component_src)

    def test_imports_authority_status_polling(self) -> None:
        self.assertIn("useAuthorityStatusPolling", self.component_src)

    def test_references_next_safe_step(self) -> None:
        self.assertIn("Next Safe Step", self.component_src)

    def test_next_step_references_plan_request(self) -> None:
        self.assertIn("plan_request", self.component_src)

    def test_imports_confirm_pending_polling(self) -> None:
        self.assertIn("useConfirmPendingPolling", self.component_src)

    def test_imports_authority_status_store(self) -> None:
        self.assertIn("useAuthorityStatusStore", self.component_src)

    def test_imports_ui_store(self) -> None:
        self.assertIn("useUIStore", self.component_src)

    def test_queue_snapshot_section(self) -> None:
        self.assertIn("Queue Snapshot", self.component_src)

    def test_runtime_snapshot_section(self) -> None:
        self.assertIn("Runtime Snapshot", self.component_src)

    def test_authority_posture_section(self) -> None:
        self.assertIn("Authority Posture", self.component_src)

    def test_agents_destinations_section(self) -> None:
        self.assertIn("Agents / Destinations", self.component_src)

    def test_mission_control_references_authority_timeline(self) -> None:
        self.assertIn(
            "authority timeline",
            self.component_src.lower(),
            "MissionControlView Queue Snapshot must reference authority timeline",
        )


# ---------------------------------------------------------------------------
# TestAuthorityTimeline — read-only 11-stage authority timeline per action
# ---------------------------------------------------------------------------


class TestAuthorityTimeline(unittest.TestCase):
    """
    Contract tests for AuthorityTimeline component and deriveAuthorityTimeline.

    Validates:
    1. AuthorityTimeline.tsx file exists.
    2. Component is exported from sovereign/index.ts.
    3. deriveAuthorityTimeline is exported.
    4. ConfirmFlowQueuePanel imports and renders AuthorityTimeline.
    5. Component contains all 11 expected stage names.
    6. Component uses 'created', 'pending_review', 'pending', 'closed' status labels.
    7. No approve/execute controls in AuthorityTimeline.
    8. Timeline is read-only (copy present).
    9. deriveAuthorityTimeline derivation logic is present (proposal_id, preparation_id, etc.).
    10. MissionControlView references authority timeline in queue snapshot.
    """

    TIMELINE_PATH = Path(__file__).parent.parent / "ui" / "components" / "sovereign" / "AuthorityTimeline.tsx"
    INDEX_PATH = Path(__file__).parent.parent / "ui" / "components" / "sovereign" / "index.ts"
    QUEUE_PANEL_PATH = Path(__file__).parent.parent / "ui" / "components" / "sovereign" / "ConfirmFlowQueuePanel.tsx"
    MISSION_CONTROL_PATH = Path(__file__).parent.parent / "ui" / "components" / "sovereign" / "MissionControlView.tsx"

    EXPECTED_STAGES = [
        'Proposal',
        'AuthorityPreparation',
        'ConfirmableAction',
        'ManualReviewQueue',
        'HumanConfirmation',
        'PolicyDecision',
        'CapabilityToken',
        'OperationBinding',
        'AuthorizedPlan',
        'PoliceGate',
        'Execution',
    ]

    def setUp(self) -> None:
        self.assertTrue(self.TIMELINE_PATH.exists(), "AuthorityTimeline.tsx must exist")
        self.timeline_src = self.TIMELINE_PATH.read_text()
        self.index_src = self.INDEX_PATH.read_text()
        self.queue_panel_src = self.QUEUE_PANEL_PATH.read_text()
        self.mission_control_src = self.MISSION_CONTROL_PATH.read_text()

    # ── 1. File existence ────────────────────────────────────────────────────

    def test_authority_timeline_file_exists(self) -> None:
        self.assertTrue(self.TIMELINE_PATH.exists())

    # ── 2–3. Exports ─────────────────────────────────────────────────────────

    def test_authority_timeline_exported_from_index(self) -> None:
        self.assertIn("AuthorityTimeline", self.index_src)

    def test_derive_authority_timeline_exported_from_index(self) -> None:
        self.assertIn("deriveAuthorityTimeline", self.index_src)

    def test_authority_timeline_component_exported(self) -> None:
        self.assertIn("export function AuthorityTimeline", self.timeline_src)

    def test_derive_authority_timeline_function_exported(self) -> None:
        self.assertIn("export function deriveAuthorityTimeline", self.timeline_src)

    # ── 4. ConfirmFlowQueuePanel wiring ──────────────────────────────────────

    def test_queue_panel_imports_authority_timeline(self) -> None:
        self.assertIn("AuthorityTimeline", self.queue_panel_src)

    def test_queue_panel_renders_authority_timeline(self) -> None:
        self.assertIn("<AuthorityTimeline", self.queue_panel_src)

    def test_queue_panel_passes_item_to_timeline(self) -> None:
        self.assertIn("item={item}", self.queue_panel_src)

    # ── 5. All 11 stages present ─────────────────────────────────────────────

    def test_stage_proposal_present(self) -> None:
        self.assertIn("Proposal", self.timeline_src)

    def test_stage_authority_preparation_present(self) -> None:
        self.assertIn("AuthorityPreparation", self.timeline_src)

    def test_stage_confirmable_action_present(self) -> None:
        self.assertIn("ConfirmableAction", self.timeline_src)

    def test_stage_manual_review_queue_present(self) -> None:
        self.assertIn("ManualReviewQueue", self.timeline_src)

    def test_stage_human_confirmation_present(self) -> None:
        self.assertIn("HumanConfirmation", self.timeline_src)

    def test_stage_policy_decision_present(self) -> None:
        self.assertIn("PolicyDecision", self.timeline_src)

    def test_stage_capability_token_present(self) -> None:
        self.assertIn("CapabilityToken", self.timeline_src)

    def test_stage_operation_binding_present(self) -> None:
        self.assertIn("OperationBinding", self.timeline_src)

    def test_stage_authorized_plan_present(self) -> None:
        self.assertIn("AuthorizedPlan", self.timeline_src)

    def test_stage_police_gate_present(self) -> None:
        self.assertIn("PoliceGate", self.timeline_src)

    def test_stage_execution_present(self) -> None:
        self.assertIn("Execution", self.timeline_src)

    def test_all_expected_stages_present(self) -> None:
        for stage in self.EXPECTED_STAGES:
            self.assertIn(stage, self.timeline_src, f"Stage '{stage}' must be present in AuthorityTimeline")

    # ── 6. Status labels ──────────────────────────────────────────────────────

    def test_status_created_present(self) -> None:
        self.assertIn("created", self.timeline_src)

    def test_status_pending_review_present(self) -> None:
        self.assertIn("pending_review", self.timeline_src)

    def test_status_pending_present(self) -> None:
        self.assertIn("'pending'", self.timeline_src)

    def test_status_closed_present(self) -> None:
        self.assertIn("'closed'", self.timeline_src)

    # ── 7. No approve/execute controls ───────────────────────────────────────

    def test_no_approve_handler_in_timeline(self) -> None:
        self.assertNotIn("handleApprove", self.timeline_src)
        self.assertNotIn("onApprove", self.timeline_src)

    def test_no_execute_handler_in_timeline(self) -> None:
        self.assertNotIn("handleExecute", self.timeline_src)

    def test_no_post_confirm_in_timeline(self) -> None:
        self.assertNotIn("postConfirm", self.timeline_src)

    def test_no_mutation_in_timeline(self) -> None:
        self.assertNotIn("fetch(", self.timeline_src)
        self.assertNotIn("axios", self.timeline_src)

    # ── 8. Read-only copy ────────────────────────────────────────────────────

    def test_contains_read_only_copy(self) -> None:
        self.assertIn("read-only", self.timeline_src)

    def test_contains_execution_closed_copy(self) -> None:
        self.assertIn("Execution is closed", self.timeline_src)

    def test_no_approve_copy_in_timeline(self) -> None:
        # Timeline must not claim it approves or enables anything
        self.assertNotIn("handleApprove", self.timeline_src)

    # ── 9. Derivation logic uses correct fields ───────────────────────────────

    def test_derives_from_proposal_id(self) -> None:
        self.assertIn("proposal_id", self.timeline_src)

    def test_derives_from_preparation_id(self) -> None:
        self.assertIn("preparation_id", self.timeline_src)

    def test_derives_from_prepared_action_id(self) -> None:
        self.assertIn("prepared_action_id", self.timeline_src)

    def test_derives_from_queue_entry_id(self) -> None:
        self.assertIn("queue_entry_id", self.timeline_src)

    def test_derives_from_human_confirmation_status(self) -> None:
        self.assertIn("human_confirmation_status", self.timeline_src)

    def test_execution_always_closed(self) -> None:
        self.assertIn("'closed'", self.timeline_src)

    def test_derive_function_returns_array(self) -> None:
        self.assertIn("TimelineStage[]", self.timeline_src)

    # ── 10. MissionControl references timeline ────────────────────────────────

    def test_mission_control_references_authority_timeline(self) -> None:
        self.assertIn("authority timeline", self.mission_control_src.lower())


# ---------------------------------------------------------------------------
# TestPreparedActionDetailInspector — S-PREPARED-ACTION-INSPECTOR-01
# ---------------------------------------------------------------------------


class TestPreparedActionDetailInspector(unittest.TestCase):
    """
    Contract tests for PreparedActionDetailPanel — read-only operational dossier.

    S-PREPARED-ACTION-INSPECTOR-01 invariants:
    1. File exists.
    2. Component is exported from sovereign/index.ts.
    3. Imports PreparedActionQueueEntry.
    4. Renders all required fields (intent, domain, action, capability, provider, IDs, review state).
    5. Reuses AuthorityTimeline.
    6. Contains inspection-only copy.
    7. Contains no approve/execute/reject mutation controls.
    8. ConfirmFlowQueuePanel imports and renders PreparedActionDetailPanel.
    9. MissionControlView remains present.
    """

    PANEL_PATH = Path(__file__).parent.parent / "ui" / "components" / "sovereign" / "PreparedActionDetailPanel.tsx"
    INDEX_PATH = Path(__file__).parent.parent / "ui" / "components" / "sovereign" / "index.ts"
    QUEUE_PANEL_PATH = Path(__file__).parent.parent / "ui" / "components" / "sovereign" / "ConfirmFlowQueuePanel.tsx"
    MISSION_CONTROL_PATH = Path(__file__).parent.parent / "ui" / "components" / "sovereign" / "MissionControlView.tsx"

    def setUp(self) -> None:
        self.assertTrue(self.PANEL_PATH.exists(), "PreparedActionDetailPanel.tsx must exist")
        self.panel_src = self.PANEL_PATH.read_text()
        self.index_src = self.INDEX_PATH.read_text()
        self.queue_panel_src = self.QUEUE_PANEL_PATH.read_text()
        self.mission_control_src = self.MISSION_CONTROL_PATH.read_text()

    # ── 1. File existence ────────────────────────────────────────────────────

    def test_file_exists(self) -> None:
        self.assertTrue(self.PANEL_PATH.exists(), "PreparedActionDetailPanel.tsx must exist")

    # ── 2. Export ────────────────────────────────────────────────────────────

    def test_component_exported_from_index(self) -> None:
        self.assertIn(
            "PreparedActionDetailPanel",
            self.index_src,
            "PreparedActionDetailPanel must be exported from sovereign/index.ts",
        )

    def test_component_export_function_present(self) -> None:
        self.assertIn(
            "export function PreparedActionDetailPanel",
            self.panel_src,
            "PreparedActionDetailPanel must be exported as a named function",
        )

    # ── 3. Type import ───────────────────────────────────────────────────────

    def test_imports_prepared_action_queue_entry(self) -> None:
        self.assertIn(
            "PreparedActionQueueEntry",
            self.panel_src,
            "PreparedActionDetailPanel must import PreparedActionQueueEntry",
        )

    # ── 4. Field rendering ───────────────────────────────────────────────────

    def test_renders_user_intent(self) -> None:
        self.assertIn("user_intent", self.panel_src)

    def test_renders_domain(self) -> None:
        self.assertIn("domain", self.panel_src)

    def test_renders_requested_action(self) -> None:
        self.assertIn("requested_action", self.panel_src)

    def test_renders_capability_name(self) -> None:
        self.assertIn("capability_name", self.panel_src)

    def test_renders_capability_scope(self) -> None:
        self.assertIn("capability_scope", self.panel_src)

    def test_renders_provider_name(self) -> None:
        self.assertIn("provider_name", self.panel_src)

    def test_renders_model_name(self) -> None:
        self.assertIn("model_name", self.panel_src)

    def test_renders_delegated_seat_ref(self) -> None:
        self.assertIn("delegated_seat_ref", self.panel_src)

    def test_renders_proposal_id(self) -> None:
        self.assertIn("proposal_id", self.panel_src)

    def test_renders_preparation_id(self) -> None:
        self.assertIn("preparation_id", self.panel_src)

    def test_renders_prepared_action_id(self) -> None:
        self.assertIn("prepared_action_id", self.panel_src)

    def test_renders_queue_entry_id(self) -> None:
        self.assertIn("queue_entry_id", self.panel_src)

    def test_renders_human_confirmation_status(self) -> None:
        self.assertIn("human_confirmation_status", self.panel_src)

    def test_renders_review_only(self) -> None:
        self.assertIn("review_only", self.panel_src)

    def test_renders_execution_allowed(self) -> None:
        self.assertIn("execution_allowed", self.panel_src)

    def test_renders_can_execute_now(self) -> None:
        self.assertIn("can_execute_now", self.panel_src)

    # ── 5. AuthorityTimeline reuse ───────────────────────────────────────────

    def test_reuses_authority_timeline(self) -> None:
        self.assertIn(
            "AuthorityTimeline",
            self.panel_src,
            "PreparedActionDetailPanel must reuse AuthorityTimeline",
        )

    def test_authority_timeline_renders_with_item(self) -> None:
        self.assertIn(
            "<AuthorityTimeline",
            self.panel_src,
            "PreparedActionDetailPanel must render <AuthorityTimeline",
        )

    # ── 6. Inspection-only copy ──────────────────────────────────────────────

    def test_mentions_inspection_only(self) -> None:
        self.assertIn(
            "Inspection only",
            self.panel_src,
            "PreparedActionDetailPanel must state it is inspection only",
        )

    def test_mentions_does_not_execute(self) -> None:
        self.assertIn(
            "does not execute",
            self.panel_src,
            "PreparedActionDetailPanel must state it does not execute",
        )

    def test_mentions_does_not_approve(self) -> None:
        self.assertIn("approve", self.panel_src)
        self.assertIn("does not", self.panel_src)

    def test_mentions_does_not_issue_tokens(self) -> None:
        self.assertIn(
            "issue tokens",
            self.panel_src,
            "PreparedActionDetailPanel must state it does not issue tokens",
        )

    def test_mentions_does_not_create_authorized_plan(self) -> None:
        self.assertIn(
            "AuthorizedPlan",
            self.panel_src,
            "PreparedActionDetailPanel must mention AuthorizedPlan in execution boundary",
        )

    def test_mentions_does_not_call_police_gate(self) -> None:
        self.assertIn(
            "PoliceGate",
            self.panel_src,
            "PreparedActionDetailPanel must mention PoliceGate in execution boundary",
        )

    # ── 7. No mutation controls ──────────────────────────────────────────────

    def test_contains_no_approve_button(self) -> None:
        self.assertNotIn("onApprove", self.panel_src)
        self.assertNotIn("handleApprove", self.panel_src)
        self.assertNotIn("<button", self.panel_src)

    def test_contains_no_execute_button(self) -> None:
        self.assertNotIn("handleExecute", self.panel_src)
        self.assertNotIn("onExecute", self.panel_src)

    def test_contains_no_reject_mutation(self) -> None:
        self.assertNotIn("handleReject", self.panel_src)
        self.assertNotIn("onReject", self.panel_src)
        self.assertNotIn("POST", self.panel_src)

    # ── 8. ConfirmFlowQueuePanel wiring ──────────────────────────────────────

    def test_confirm_queue_panel_imports_detail_panel(self) -> None:
        self.assertIn(
            "PreparedActionDetailPanel",
            self.queue_panel_src,
            "ConfirmFlowQueuePanel must import PreparedActionDetailPanel",
        )

    def test_confirm_queue_panel_renders_detail_panel(self) -> None:
        self.assertIn(
            "<PreparedActionDetailPanel",
            self.queue_panel_src,
            "ConfirmFlowQueuePanel must render <PreparedActionDetailPanel",
        )

    # ── 9. MissionControlView remains present ────────────────────────────────

    def test_mission_control_file_exists(self) -> None:
        self.assertTrue(
            self.MISSION_CONTROL_PATH.exists(),
            "MissionControlView.tsx must still exist after inspector sprint",
        )

    def test_mission_control_source_nonempty(self) -> None:
        self.assertTrue(
            self.mission_control_src.strip(),
            "MissionControlView.tsx must have content",
        )

    def test_mission_control_references_inspect_copy(self) -> None:
        self.assertIn(
            "inspect prepared action",
            self.mission_control_src.lower(),
            "MissionControlView must reference inspecting prepared actions",
        )


if __name__ == "__main__":
    unittest.main()
