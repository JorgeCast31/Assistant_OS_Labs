"""
Tests — Phase 3C: unified confirmation flow via orchestrator

Coverage
--------
A. RISK_LOW: auto-execute (no confirmation needed)
B. RISK_MEDIUM: plan_confirmation_required + plan stored with plan_id
C. Confirm path: retrieve stored plan → execute pipeline
D. Error: confirm non-existent / expired plan_id
E. Single-use protection: second confirm → error
F. plan_id preserved across both passes
G. domain_payload intact between pre-confirm and post-confirm
H. control_plane blocks after confirmation (Gate 2 still fires)
I. NL path also stores plan on confirmation_required
J. No domain_payload → pipeline rejects (not orchestrator bug)
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from assistant_os.contracts import (
    ACTION_HOST_OPEN_APP,
    ACTION_HOST_LIST_DIRECTORY,
    RESULT_TYPE_HOST_ACTION,
    RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED,
    RESULT_TYPE_CONFIRM_ERROR,
    RISK_LOW,
    RISK_MEDIUM,
    normalize_request,
)
from assistant_os.core.orchestrator import handle_request
from assistant_os.agents.host_agent import (
    ALLOWED_DIRECTORIES,
    HOST_AGENT_ID,
    _reset_host_agent_state_for_tests,
)
from assistant_os.agents.host_audit import HOST_AUDIT_LOG, HostErrorCode
from assistant_os.context_store import clear_store, get_pending_plan
from assistant_os.core.control_plane import (
    _reset_state_for_tests,
    activate_agent,
    quarantine_agent,
)
from assistant_os.mso.capability_registry import reset_dynamic_capabilities
from assistant_os.mso.system_state import clear_operational_mode_override
from assistant_os.mso.task_registry import reset_task_registry
from assistant_os.mso.trace_aggregator import reset_trace_aggregator
from assistant_os.storage.mso_store import clear_mso_store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset():
    reset_task_registry()
    reset_trace_aggregator()
    clear_operational_mode_override()
    reset_dynamic_capabilities()
    clear_mso_store()
    _reset_state_for_tests()
    _reset_host_agent_state_for_tests()
    HOST_AUDIT_LOG.clear()
    clear_store()
    yield
    reset_task_registry()
    reset_trace_aggregator()
    clear_operational_mode_override()
    reset_dynamic_capabilities()
    clear_mso_store()
    _reset_state_for_tests()
    _reset_host_agent_state_for_tests()
    HOST_AUDIT_LOG.clear()
    clear_store()


_ALLOWED_DIR  = ALLOWED_DIRECTORIES[0]
_ALLOWED_FILE = _ALLOWED_DIR + r"\notes.txt"


def _scandir_cm(entries):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=iter(entries))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def _req_list_dir(confirmed: bool = True) -> dict:
    """Build a CanonicalRequest for list_directory (RISK_LOW → auto-execute)."""
    return normalize_request(
        text="",
        metadata={
            "action": ACTION_HOST_LIST_DIRECTORY,
            "domain": "HOST",
            "risk_level": RISK_LOW,
            "requires_confirmation": False,
            "domain_payload": {
                "action": "list_directory",
                "confirmed": confirmed,
                "path": _ALLOWED_DIR,
            },
        },
    )


def _req_open_app(app_name: str = "notepad") -> dict:
    """Build a CanonicalRequest for open_app (RISK_MEDIUM → confirmation required)."""
    return normalize_request(
        text="",
        metadata={
            "action": ACTION_HOST_OPEN_APP,
            "domain": "HOST",
            "risk_level": RISK_MEDIUM,
            "requires_confirmation": True,
            "domain_payload": {
                "action": "open_app",
                "confirmed": True,
                "app_name": app_name,
            },
        },
    )


def _req_confirm(plan_id: str) -> dict:
    """Build a CanonicalRequest to confirm an existing plan."""
    return normalize_request(
        text="",
        metadata={"confirm_plan_id": plan_id},
    )


# ---------------------------------------------------------------------------
# A. RISK_LOW auto-executes
# ---------------------------------------------------------------------------


class TestAutoExecute:
    def test_list_directory_auto_executes(self):
        """RISK_LOW HOST_LIST_DIRECTORY must not require confirmation."""
        activate_agent(HOST_AGENT_ID)
        mock_e = MagicMock()
        mock_e.name = "x.txt"
        mock_e.is_dir.return_value = False
        mock_e.stat.return_value = MagicMock(st_size=10)

        req = _req_list_dir()
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm([mock_e])):
            result = handle_request(req)

        assert result["result_type"] == RESULT_TYPE_HOST_ACTION
        assert result["ok"] is True
        assert result["domain"] == "HOST"

    def test_risk_low_does_not_store_plan(self):
        """Auto-executed plans must NOT be stored in context_store."""
        activate_agent(HOST_AGENT_ID)
        req = _req_list_dir()
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm([])):
            result = handle_request(req)

        plan_id = result.get("plan_id") or result.get("data", {}).get("plan_id")
        # Nothing should be stored for auto-executed plans
        from assistant_os.context_store import get_store_size
        assert get_store_size() == 0


# ---------------------------------------------------------------------------
# B. RISK_MEDIUM: plan_confirmation_required + plan stored
# ---------------------------------------------------------------------------


class TestConfirmationRequired:
    def test_open_app_returns_confirmation_required(self):
        """open_app (RISK_MEDIUM) must return plan_confirmation_required."""
        req = _req_open_app()
        result = handle_request(req)
        assert result["ok"] is True
        assert result["result_type"] == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED

    def test_confirmation_result_contains_plan_id(self):
        """plan_confirmation_required result must include plan_id in data."""
        req = _req_open_app()
        result = handle_request(req)
        assert "plan_id" in result["data"]
        assert result["data"]["plan_id"]  # non-empty

    def test_plan_stored_in_context_store(self):
        """After returning confirmation_required, plan must be in context_store."""
        req = _req_open_app()
        result = handle_request(req)
        plan_id = result["data"]["plan_id"]
        stored = get_pending_plan(plan_id)
        assert stored is not None
        assert stored["plan"]["action"] == ACTION_HOST_OPEN_APP

    def test_domain_payload_preserved_in_store(self):
        """Stored plan must contain the original domain_payload."""
        req = _req_open_app(app_name="calc")
        result = handle_request(req)
        plan_id = result["data"]["plan_id"]
        stored = get_pending_plan(plan_id)
        payload = stored["plan"].get("domain_payload", {})
        assert payload["app_name"] == "calc"
        assert payload["confirmed"] is True


# ---------------------------------------------------------------------------
# C. Confirm path: retrieve stored plan → execute pipeline
# ---------------------------------------------------------------------------


class TestConfirmExecution:
    def test_confirm_executes_stored_plan(self):
        """After plan_confirmation_required, confirm_plan_id must execute pipeline."""
        activate_agent(HOST_AGENT_ID)
        # Pass 1: get confirmation_required
        result1 = handle_request(_req_open_app("notepad"))
        plan_id = result1["data"]["plan_id"]

        # Pass 2: confirm
        mock_proc = MagicMock()
        mock_proc.pid = 4242
        req2 = _req_confirm(plan_id)
        with patch("subprocess.Popen", return_value=mock_proc):
            result2 = handle_request(req2)

        assert result2["ok"] is True
        assert result2["result_type"] == RESULT_TYPE_HOST_ACTION
        assert result2["domain"] == "HOST"
        assert result2["data"]["action"] == "open_app"
        assert result2["data"]["pid"] == 4242

    def test_confirm_preserves_plan_id(self):
        """plan_id in DomainResult after confirm must match original plan_id."""
        activate_agent(HOST_AGENT_ID)
        result1 = handle_request(_req_open_app())
        plan_id = result1["data"]["plan_id"]

        mock_proc = MagicMock()
        mock_proc.pid = 1
        with patch("subprocess.Popen", return_value=mock_proc):
            result2 = handle_request(_req_confirm(plan_id))

        assert result2.get("plan_id") == plan_id

    def test_confirm_execution_id_equals_plan_id(self):
        """HOST audit execution_id must equal the original plan_id."""
        activate_agent(HOST_AGENT_ID)
        result1 = handle_request(_req_open_app())
        plan_id = result1["data"]["plan_id"]

        mock_proc = MagicMock()
        mock_proc.pid = 1
        with patch("subprocess.Popen", return_value=mock_proc):
            result2 = handle_request(_req_confirm(plan_id))

        assert result2["data"]["execution_id"] == plan_id


# ---------------------------------------------------------------------------
# D. Error: confirm non-existent / expired plan_id
# ---------------------------------------------------------------------------


class TestConfirmErrors:
    def test_nonexistent_plan_id_returns_error(self):
        """confirm_plan_id with no matching plan must return ok=False, confirm_error."""
        req = _req_confirm("00000000-0000-0000-0000-000000000000")
        result = handle_request(req)
        assert result["ok"] is False
        assert result["result_type"] == RESULT_TYPE_CONFIRM_ERROR
        assert result["error"]["type"] == "PlanNotFound"


# ---------------------------------------------------------------------------
# E. Single-use protection
# ---------------------------------------------------------------------------


class TestSingleUse:
    def test_second_confirm_returns_error(self):
        """A plan_id must be usable exactly once."""
        activate_agent(HOST_AGENT_ID)
        result1 = handle_request(_req_open_app())
        plan_id = result1["data"]["plan_id"]

        mock_proc = MagicMock()
        mock_proc.pid = 1
        with patch("subprocess.Popen", return_value=mock_proc):
            handle_request(_req_confirm(plan_id))  # first use

        # Second use must fail
        result3 = handle_request(_req_confirm(plan_id))
        assert result3["ok"] is False
        assert result3["result_type"] == RESULT_TYPE_CONFIRM_ERROR

    def test_plan_removed_from_store_after_confirm(self):
        """context_store must be empty after a successful confirm."""
        activate_agent(HOST_AGENT_ID)
        result1 = handle_request(_req_open_app())
        plan_id = result1["data"]["plan_id"]

        mock_proc = MagicMock()
        mock_proc.pid = 1
        with patch("subprocess.Popen", return_value=mock_proc):
            handle_request(_req_confirm(plan_id))

        assert get_pending_plan(plan_id) is None


# ---------------------------------------------------------------------------
# F. plan_id preserved across both passes
# ---------------------------------------------------------------------------


class TestPlanIdPreservation:
    def test_plan_id_same_in_both_passes(self):
        """plan_id must not change between pre-confirm and post-confirm."""
        activate_agent(HOST_AGENT_ID)
        result1 = handle_request(_req_open_app())
        plan_id_pass1 = result1["data"]["plan_id"]

        # plan_id in stored plan matches
        stored = get_pending_plan(plan_id_pass1)
        assert stored["plan"]["plan_id"] == plan_id_pass1

        mock_proc = MagicMock()
        mock_proc.pid = 1
        with patch("subprocess.Popen", return_value=mock_proc):
            result2 = handle_request(_req_confirm(plan_id_pass1))

        assert result2.get("plan_id") == plan_id_pass1


# ---------------------------------------------------------------------------
# G. domain_payload intact between pre-confirm and post-confirm
# ---------------------------------------------------------------------------


class TestDomainPayloadIntact:
    def test_domain_payload_unchanged_at_execution(self):
        """The domain_payload sent in pass 1 must be the one used in pass 2."""
        activate_agent(HOST_AGENT_ID)
        result1 = handle_request(_req_open_app("calc"))
        plan_id = result1["data"]["plan_id"]

        captured_request = []

        # Patch the reference used inside host_pipeline (the import target)
        from assistant_os.agents.host_agent import execute_host_action as _real
        from assistant_os.pipelines import host_pipeline as _hp

        def capturing_execute(request):
            captured_request.append(request)
            return _real(request)

        with patch.object(_hp, "execute_host_action", side_effect=capturing_execute), \
             patch("subprocess.Popen", return_value=MagicMock(pid=99)):
            handle_request(_req_confirm(plan_id))

        assert len(captured_request) == 1
        assert captured_request[0].app_name == "calc"


# ---------------------------------------------------------------------------
# H. control_plane blocks after confirmation (Gate 2 still fires)
# ---------------------------------------------------------------------------


class TestControlPlanePostConfirm:
    def test_quarantine_between_passes_blocks_execution(self):
        """If HOST_AGENT_ID is quarantined between pass 1 and pass 2, execution is blocked."""
        activate_agent(HOST_AGENT_ID)
        result1 = handle_request(_req_open_app())
        plan_id = result1["data"]["plan_id"]

        # Quarantine the agent between passes
        quarantine_agent(HOST_AGENT_ID)

        with patch("subprocess.Popen") as mock_popen:
            result2 = handle_request(_req_confirm(plan_id))

        assert result2["ok"] is False
        assert result2["data"]["error_code"] == HostErrorCode.CONTROL_PLANE_BLOCKED.value
        mock_popen.assert_not_called()

    def test_inactive_agent_blocks_confirm_execution(self):
        """If HOST_AGENT_ID is never activated, confirm must be blocked by agent Gate 2."""
        # No activate_agent call
        result1 = handle_request(_req_open_app())
        plan_id = result1["data"]["plan_id"]

        with patch("subprocess.Popen") as mock_popen:
            result2 = handle_request(_req_confirm(plan_id))

        assert result2["ok"] is False
        assert result2["data"]["error_code"] == HostErrorCode.CONTROL_PLANE_BLOCKED.value
        mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# I. Both paths (structured + NL) store plan
# ---------------------------------------------------------------------------


class TestStorageAcrossPaths:
    def test_structured_path_stores_plan(self):
        """Structured path (metadata.action) must store on confirm_required."""
        req = _req_open_app()
        result = handle_request(req)
        assert result["result_type"] == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED
        plan_id = result["data"]["plan_id"]
        stored = get_pending_plan(plan_id)
        assert stored is not None

    @patch("assistant_os.classifier.classify_text",
           return_value={
               "domain": "WORK", "operation": "WORK_CREATE", "confidence": 0.9,
               "alternatives": [], "needs_confirmation": True, "reason": "test",
               "type": "", "cognitive_load": "", "impact": "", "next_action": "",
           })
    def test_nl_path_stores_plan_on_confirmation(self, _mock_classify):
        """NL path (text classification) must also store on confirm_required."""
        from assistant_os.context_store import get_store_size
        initial_size = get_store_size()
        req = normalize_request(text="crear tarea nueva: implementar feature X")
        result = handle_request(req)
        assert result["result_type"] == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED
        assert "plan_id" in result["data"]
        # Store grew by 1
        assert get_store_size() == initial_size + 1


# ---------------------------------------------------------------------------
# J. Confirm with corrupt / missing domain_payload → pipeline rejects cleanly
# ---------------------------------------------------------------------------


class TestConfirmEdgeCases:
    def test_confirm_with_missing_payload_returns_pipeline_error(self):
        """
        If stored plan has no domain_payload, the HOST pipeline must reject it
        cleanly (InvalidHostPayload) — not an orchestrator crash.
        """
        from unittest.mock import patch as _patch
        activate_agent(HOST_AGENT_ID)
        # Store a plan manually without domain_payload
        from assistant_os.context_store import store_pending_plan
        from assistant_os.contracts import make_plan
        plan = make_plan(
            domain="HOST",
            action=ACTION_HOST_OPEN_APP,
            target="test",
            risk_level=RISK_MEDIUM,
        )
        # No domain_payload
        store_pending_plan(
            context_id=plan["plan_id"],
            plan=plan,
            operation=ACTION_HOST_OPEN_APP,
            raw_text="",
        )

        with _patch("assistant_os.police.enforcement.check") as mock_police:
            mock_police.return_value.permitted = True
            result = handle_request(_req_confirm(plan["plan_id"]))
        assert result["ok"] is False
        assert result["error"]["type"] == "InvalidHostPayload"

    def test_confirm_path_takes_priority_over_action(self):
        """
        If both confirm_plan_id and action are present in metadata,
        confirm path must win.
        """
        result1 = handle_request(_req_open_app())
        plan_id = result1["data"]["plan_id"]

        # Remove from store so confirm would fail (testing routing priority)
        from assistant_os.context_store import remove_pending_plan
        remove_pending_plan(plan_id)

        req = normalize_request(
            text="",
            metadata={
                "confirm_plan_id": plan_id,
                "action": ACTION_HOST_LIST_DIRECTORY,  # would auto-execute if confirm path lost
                "domain": "HOST",
                "risk_level": RISK_LOW,
                "requires_confirmation": False,
                "domain_payload": {
                    "action": "list_directory",
                    "confirmed": True,
                    "path": _ALLOWED_DIR,
                },
            },
        )
        result = handle_request(req)
        # Confirm path took priority; plan was removed → PlanNotFound
        assert result["result_type"] == RESULT_TYPE_CONFIRM_ERROR
