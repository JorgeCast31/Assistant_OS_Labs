"""
Tests — Phase 3B: HOST domain pipeline integration

Coverage
--------
A. host_pipeline.execute dispatch — known/unknown actions
B. domain_payload validation — missing, wrong type, missing fields
C. open_app via pipeline — success, registry miss, CP blocked, confirmed=False
D. list_directory via pipeline — success, not allowed, not found
E. read_text_file via pipeline — success, too large, ext not allowed
F. open_url via pipeline — success, bad domain
G. close_pid via pipeline — success, pid not owned
H. open_directory via pipeline — success
I. open_file via pipeline — success, ext not allowed
J. DomainResult structure invariants
K. Routing: action_domain / get_pipeline
L. End-to-end: CanonicalRequest → orchestrator → host_pipeline
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from assistant_os.contracts import (
    ACTION_HOST_OPEN_APP,
    ACTION_HOST_CLOSE_PID,
    ACTION_HOST_OPEN_DIRECTORY,
    ACTION_HOST_OPEN_URL,
    ACTION_HOST_LIST_DIRECTORY,
    ACTION_HOST_OPEN_FILE,
    ACTION_HOST_READ_TEXT_FILE,
    RESULT_TYPE_HOST_ACTION,
    make_plan,
    normalize_request,
    RISK_LOW,
    RISK_MEDIUM,
)
from assistant_os.pipelines.host_pipeline import execute as host_execute
from assistant_os.agents.host_agent import (
    ALLOWED_DIRECTORIES,
    HOST_AGENT_ID,
    _reset_host_agent_state_for_tests,
)
from assistant_os.agents.host_audit import HOST_AUDIT_LOG, HostErrorCode
from assistant_os.core.control_plane import (
    _reset_state_for_tests,
    activate_agent,
)
from assistant_os.core.routing import action_domain, get_pipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset():
    _reset_state_for_tests()
    _reset_host_agent_state_for_tests()
    HOST_AUDIT_LOG.clear()
    yield
    _reset_state_for_tests()
    _reset_host_agent_state_for_tests()
    HOST_AUDIT_LOG.clear()


_ALLOWED_DIR  = ALLOWED_DIRECTORIES[0]
_ALLOWED_FILE = _ALLOWED_DIR + r"\notes.txt"


def _plan(action: str, payload: dict, *, risk: str = RISK_MEDIUM) -> dict:
    """Build a minimal plan with domain_payload for pipeline tests."""
    p = make_plan(
        domain="HOST",
        action=action,
        target=action,
        risk_level=risk,
    )
    p["domain_payload"] = payload
    return p


def _active(plan: dict) -> dict:
    """Activate HOST_AGENT_ID and return plan unchanged."""
    activate_agent(HOST_AGENT_ID)
    return plan


# ---------------------------------------------------------------------------
# A. Dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_unknown_action_returns_error(self):
        plan = {"action": "HOST_UNKNOWN_XYZ", "domain_payload": {"confirmed": True}}
        result = host_execute(plan, "ctx-1")
        assert result["ok"] is False
        assert result["result_type"] == RESULT_TYPE_HOST_ACTION
        assert result["domain"] == "HOST"
        assert "HOST_UNKNOWN_XYZ" in result["message"]
        assert result["error"]["type"] == "UnknownHostAction"

    def test_missing_action_key_returns_error(self):
        plan = {"domain_payload": {"confirmed": True}}
        result = host_execute(plan, "ctx-1")
        assert result["ok"] is False
        assert result["error"]["type"] == "UnknownHostAction"

    def test_known_actions_are_dispatched(self):
        """All 7 ACTION_HOST_* constants must be recognized (smoke)."""
        activate_agent(HOST_AGENT_ID)
        known_actions = [
            ACTION_HOST_OPEN_APP,
            ACTION_HOST_CLOSE_PID,
            ACTION_HOST_OPEN_DIRECTORY,
            ACTION_HOST_OPEN_URL,
            ACTION_HOST_LIST_DIRECTORY,
            ACTION_HOST_OPEN_FILE,
            ACTION_HOST_READ_TEXT_FILE,
        ]
        for action in known_actions:
            plan = {"action": action, "domain_payload": {"confirmed": True}}
            result = host_execute(plan, "ctx")
            # Must not return UnknownHostAction — the action is known
            assert result.get("error", {}).get("type") != "UnknownHostAction", action


# ---------------------------------------------------------------------------
# B. domain_payload validation
# ---------------------------------------------------------------------------


class TestPayloadValidation:
    def test_missing_domain_payload_returns_error(self):
        plan = {"action": ACTION_HOST_OPEN_APP}
        result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["error"]["type"] == "InvalidHostPayload"

    def test_non_dict_domain_payload_returns_error(self):
        plan = {"action": ACTION_HOST_OPEN_APP, "domain_payload": "not-a-dict"}
        result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["error"]["type"] == "InvalidHostPayload"

    def test_missing_confirmed_field_returns_error(self):
        plan = {"action": ACTION_HOST_OPEN_APP, "domain_payload": {"app_name": "notepad"}}
        result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert "confirmed" in result["data"].get("missing_fields", [])

    def test_open_app_missing_app_name_returns_error(self):
        plan = _plan(ACTION_HOST_OPEN_APP, {"confirmed": True})
        result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert "app_name" in result["data"].get("missing_fields", [])

    def test_close_pid_missing_pid_returns_error(self):
        plan = _plan(ACTION_HOST_CLOSE_PID, {"confirmed": True})
        result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert "pid" in result["data"].get("missing_fields", [])

    def test_open_url_missing_url_returns_error(self):
        plan = _plan(ACTION_HOST_OPEN_URL, {"confirmed": True})
        result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert "url" in result["data"].get("missing_fields", [])

    def test_path_actions_missing_path_returns_error(self):
        for action in (
            ACTION_HOST_OPEN_DIRECTORY,
            ACTION_HOST_LIST_DIRECTORY,
            ACTION_HOST_OPEN_FILE,
            ACTION_HOST_READ_TEXT_FILE,
        ):
            plan = _plan(action, {"confirmed": True})
            result = host_execute(plan, "ctx")
            assert result["ok"] is False, f"Expected error for {action}"
            assert "path" in result["data"].get("missing_fields", []), action


# ---------------------------------------------------------------------------
# C. open_app via pipeline
# ---------------------------------------------------------------------------


class TestOpenApp:
    def test_success(self):
        mock_proc = MagicMock()
        mock_proc.pid = 9001
        plan = _active(_plan(ACTION_HOST_OPEN_APP, {"confirmed": True, "app_name": "notepad"}))
        with patch("subprocess.Popen", return_value=mock_proc):
            result = host_execute(plan, "ctx")
        assert result["ok"] is True
        assert result["domain"] == "HOST"
        assert result["result_type"] == RESULT_TYPE_HOST_ACTION
        assert result["data"]["action"] == "open_app"
        assert result["data"]["pid"] == 9001

    def test_unknown_app_returns_error(self):
        plan = _active(_plan(ACTION_HOST_OPEN_APP, {"confirmed": True, "app_name": "virus.exe"}))
        with patch("subprocess.Popen") as mock_popen:
            result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["data"]["error_code"] == HostErrorCode.INVALID_APP_NAME.value
        mock_popen.assert_not_called()

    def test_confirmed_false_rejected(self):
        plan = _active(_plan(ACTION_HOST_OPEN_APP, {"confirmed": False, "app_name": "notepad"}))
        with patch("subprocess.Popen") as mock_popen:
            result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["data"]["error_code"] == HostErrorCode.CONFIRMED_REQUIRED.value
        mock_popen.assert_not_called()

    def test_agent_not_active_rejected(self):
        # HOST_AGENT_ID NOT activated
        plan = _plan(ACTION_HOST_OPEN_APP, {"confirmed": True, "app_name": "notepad"})
        with patch("subprocess.Popen") as mock_popen:
            result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["data"]["error_code"] == HostErrorCode.CONTROL_PLANE_BLOCKED.value
        mock_popen.assert_not_called()

    def test_plan_id_in_domain_result(self):
        mock_proc = MagicMock()
        mock_proc.pid = 1
        plan = _active(_plan(ACTION_HOST_OPEN_APP, {"confirmed": True, "app_name": "notepad"}))
        plan_id = plan["plan_id"]
        with patch("subprocess.Popen", return_value=mock_proc):
            result = host_execute(plan, "ctx")
        assert result.get("plan_id") == plan_id


# ---------------------------------------------------------------------------
# D. list_directory via pipeline
# ---------------------------------------------------------------------------


class TestListDirectory:
    def _entries(self, names):
        entries = []
        for name in names:
            e = MagicMock()
            e.name = name
            e.is_dir.return_value = False
            e.stat.return_value = MagicMock(st_size=100)
            entries.append(e)
        return entries

    def _scandir_cm(self, entries):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=iter(entries))
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    def test_success_returns_entries(self):
        mock_entries = self._entries(["a.txt", "b.md"])
        plan = _active(_plan(ACTION_HOST_LIST_DIRECTORY,
                             {"confirmed": True, "path": _ALLOWED_DIR},
                             risk=RISK_LOW))
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=self._scandir_cm(mock_entries)):
            result = host_execute(plan, "ctx")
        assert result["ok"] is True
        assert len(result["data"]["entries"]) == 2

    def test_path_not_allowed_returns_error(self):
        plan = _active(_plan(ACTION_HOST_LIST_DIRECTORY,
                             {"confirmed": True, "path": r"C:\Windows\System32"},
                             risk=RISK_LOW))
        result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["data"]["error_code"] == HostErrorCode.DIRECTORY_NOT_ALLOWED.value

    def test_directory_not_found_returns_error(self):
        plan = _active(_plan(ACTION_HOST_LIST_DIRECTORY,
                             {"confirmed": True, "path": _ALLOWED_DIR},
                             risk=RISK_LOW))
        with patch("os.path.isdir", return_value=False):
            result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["data"]["error_code"] == HostErrorCode.DIRECTORY_NOT_FOUND.value


# ---------------------------------------------------------------------------
# E. read_text_file via pipeline
# ---------------------------------------------------------------------------


class TestReadTextFile:
    def test_success_returns_content(self):
        plan = _active(_plan(ACTION_HOST_READ_TEXT_FILE,
                             {"confirmed": True, "path": _ALLOWED_FILE},
                             risk=RISK_LOW))
        with patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=100), \
             patch("builtins.open", return_value=io.StringIO("hello")):
            result = host_execute(plan, "ctx")
        assert result["ok"] is True
        assert result["data"]["content"] == "hello"

    def test_file_too_large_returns_error(self):
        from assistant_os.agents.host_agent import MAX_READ_SIZE_BYTES
        plan = _active(_plan(ACTION_HOST_READ_TEXT_FILE,
                             {"confirmed": True, "path": _ALLOWED_FILE},
                             risk=RISK_LOW))
        with patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=MAX_READ_SIZE_BYTES + 1):
            result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["data"]["error_code"] == HostErrorCode.FILE_TOO_LARGE.value

    def test_extension_not_allowed_returns_error(self):
        bad_path = _ALLOWED_DIR + r"\data.exe"
        plan = _active(_plan(ACTION_HOST_READ_TEXT_FILE,
                             {"confirmed": True, "path": bad_path},
                             risk=RISK_LOW))
        result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["data"]["error_code"] == HostErrorCode.EXTENSION_NOT_ALLOWED.value


# ---------------------------------------------------------------------------
# F. open_url via pipeline
# ---------------------------------------------------------------------------


class TestOpenUrl:
    def test_success(self):
        plan = _active(_plan(ACTION_HOST_OPEN_URL,
                             {"confirmed": True, "url": "https://github.com/foo"}))
        with patch("subprocess.Popen"):
            result = host_execute(plan, "ctx")
        assert result["ok"] is True
        assert result["data"]["action"] == "open_url"

    def test_bad_domain_returns_error(self):
        plan = _active(_plan(ACTION_HOST_OPEN_URL,
                             {"confirmed": True, "url": "https://evil.com/x"}))
        with patch("subprocess.Popen") as mock_popen:
            result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["data"]["error_code"] == HostErrorCode.URL_DOMAIN_NOT_ALLOWED.value
        mock_popen.assert_not_called()

    def test_http_scheme_returns_error(self):
        plan = _active(_plan(ACTION_HOST_OPEN_URL,
                             {"confirmed": True, "url": "http://github.com/foo"}))
        with patch("subprocess.Popen") as mock_popen:
            result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["data"]["error_code"] == HostErrorCode.URL_SCHEME_NOT_ALLOWED.value
        mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# G. close_pid via pipeline
# ---------------------------------------------------------------------------


class TestClosePid:
    def test_pid_not_owned_returns_error(self):
        plan = _active(_plan(ACTION_HOST_CLOSE_PID, {"confirmed": True, "pid": 9999}))
        with patch("os.kill") as mock_kill:
            result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["data"]["error_code"] == HostErrorCode.PID_NOT_OWNED.value
        mock_kill.assert_not_called()


# ---------------------------------------------------------------------------
# H. open_directory via pipeline
# ---------------------------------------------------------------------------


class TestOpenDirectory:
    def test_success(self):
        mock_proc = MagicMock()
        mock_proc.pid = 42
        plan = _active(_plan(ACTION_HOST_OPEN_DIRECTORY,
                             {"confirmed": True, "path": _ALLOWED_DIR}))
        with patch("subprocess.Popen", return_value=mock_proc):
            result = host_execute(plan, "ctx")
        assert result["ok"] is True
        assert result["data"]["action"] == "open_directory"


# ---------------------------------------------------------------------------
# I. open_file via pipeline
# ---------------------------------------------------------------------------


class TestOpenFile:
    def test_success(self):
        plan = _active(_plan(ACTION_HOST_OPEN_FILE,
                             {"confirmed": True, "path": _ALLOWED_FILE}))
        with patch("os.path.isfile", return_value=True), \
             patch("subprocess.Popen"):
            result = host_execute(plan, "ctx")
        assert result["ok"] is True
        assert result["data"]["action"] == "open_file"

    def test_extension_not_allowed_returns_error(self):
        bad_path = _ALLOWED_DIR + r"\run.ps1"
        plan = _active(_plan(ACTION_HOST_OPEN_FILE,
                             {"confirmed": True, "path": bad_path}))
        with patch("subprocess.Popen") as mock_popen:
            result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert result["data"]["error_code"] == HostErrorCode.EXTENSION_NOT_ALLOWED.value
        mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# J. DomainResult structure invariants
# ---------------------------------------------------------------------------


class TestDomainResultStructure:
    def test_success_result_has_required_fields(self):
        mock_proc = MagicMock()
        mock_proc.pid = 1
        plan = _active(_plan(ACTION_HOST_OPEN_APP, {"confirmed": True, "app_name": "calc"}))
        with patch("subprocess.Popen", return_value=mock_proc):
            result = host_execute(plan, "ctx")
        assert "ok" in result
        assert "result_type" in result
        assert "domain" in result
        assert "message" in result
        assert "data" in result
        assert result["error"] is None

    def test_failure_result_has_error_field(self):
        plan = _plan(ACTION_HOST_OPEN_APP, {"confirmed": True, "app_name": "notepad"})
        # Agent not activated
        result = host_execute(plan, "ctx")
        assert result["ok"] is False
        assert isinstance(result["error"], dict)
        assert "type" in result["error"]
        assert "message" in result["error"]

    def test_data_always_dict(self):
        plan = {"action": "HOST_GARBAGE", "domain_payload": {"confirmed": True}}
        result = host_execute(plan, "ctx")
        assert isinstance(result["data"], dict)


# ---------------------------------------------------------------------------
# K. Routing: action_domain / get_pipeline
# ---------------------------------------------------------------------------


class TestRouting:
    def test_action_domain_host(self):
        for action in (
            ACTION_HOST_OPEN_APP,
            ACTION_HOST_CLOSE_PID,
            ACTION_HOST_LIST_DIRECTORY,
            ACTION_HOST_READ_TEXT_FILE,
        ):
            assert action_domain(action) == "HOST", f"action_domain({action!r}) != 'HOST'"

    def test_get_pipeline_host_returns_callable(self):
        pipeline = get_pipeline("HOST")
        assert callable(pipeline)

    def test_get_pipeline_host_is_host_execute(self):
        from assistant_os.pipelines import host_pipeline
        assert get_pipeline("HOST") is host_pipeline.execute

    def test_non_host_actions_not_routed_to_host(self):
        assert action_domain("WORK_QUERY") != "HOST"
        assert action_domain("CODE_FIX") != "HOST"
        assert action_domain("UNKNOWN_X") != "HOST"


# ---------------------------------------------------------------------------
# L. End-to-end: CanonicalRequest → orchestrator → host_pipeline
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """
    Tests the full path:
      CanonicalRequest → orchestrator structured path → host_pipeline → DomainResult

    Uses the structured path (metadata.action set) to skip NL classification.
    domain_payload is passed via metadata.domain_payload and propagated by the
    orchestrator into the plan before pipeline dispatch.
    """

    def test_list_directory_end_to_end(self):
        from assistant_os.core.orchestrator import handle_request
        activate_agent(HOST_AGENT_ID)

        req = normalize_request(
            text="",
            metadata={
                "action": ACTION_HOST_LIST_DIRECTORY,
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

        mock_entry = MagicMock()
        mock_entry.name = "file.txt"
        mock_entry.is_dir.return_value = False
        mock_entry.stat.return_value = MagicMock(st_size=50)

        def _fresh_scandir_cm(*_args, **_kwargs):
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=iter([mock_entry]))
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", side_effect=_fresh_scandir_cm):
            result = handle_request(req)

        assert result["ok"] is True
        assert result["domain"] == "HOST"
        assert result["result_type"] == RESULT_TYPE_HOST_ACTION
        assert len(result["data"]["entries"]) == 1

    def test_open_app_returns_confirmation_required(self):
        """
        open_app is RISK_MEDIUM and not in _AUTO_EXECUTE_WHITELIST.
        The orchestrator must return plan_confirmation_required — it MUST NOT
        call the pipeline directly on first pass.
        """
        from assistant_os.core.orchestrator import handle_request
        from assistant_os.contracts import RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED
        activate_agent(HOST_AGENT_ID)

        req = normalize_request(
            text="",
            metadata={
                "action": ACTION_HOST_OPEN_APP,
                "domain": "HOST",
                "risk_level": RISK_MEDIUM,
                "requires_confirmation": True,
                "domain_payload": {
                    "action": "open_app",
                    "confirmed": True,
                    "app_name": "notepad",
                },
            },
        )

        with patch("subprocess.Popen") as mock_popen:
            result = handle_request(req)

        # Kernel returns confirmation_required — pipeline is never reached
        assert result["ok"] is True
        assert result["result_type"] == RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED
        mock_popen.assert_not_called()

    def test_end_to_end_blocked_without_active_agent_read_only(self):
        """
        list_directory (RISK_LOW, whitelisted) with inactive HOST_AGENT_ID.
        Orchestrator auto-executes → pipeline → agent Gate 2 blocks → DomainResult ok=False.
        """
        from assistant_os.core.orchestrator import handle_request
        # Agent NOT activated

        req = normalize_request(
            text="",
            metadata={
                "action": ACTION_HOST_LIST_DIRECTORY,
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

        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir"):
            result = handle_request(req)

        assert result["ok"] is False
        assert result["data"]["error_code"] == HostErrorCode.CONTROL_PLANE_BLOCKED.value
