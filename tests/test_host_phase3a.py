"""
Tests — Phase 3A: read-only filesystem for HOST (OpenClaw)

Coverage
--------
A. validate_allowed_file_path
B. list_directory — allowed, not allowed, not found, limit
C. open_file — valid, ext not allowed, path not allowed, file not found
D. read_text_file — valid, too large, ext not allowed, encoding error
E. Audit: intent BEFORE execution, outcome AFTER
F. Gates still block all new actions (confirmed, control plane)
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, call, patch

import pytest

from assistant_os.agents.host_agent import (
    ALLOWED_DIRECTORIES,
    ALLOWED_EXTENSIONS,
    HOST_AGENT_ID,
    LIST_DIRECTORY_LIMIT,
    MAX_READ_SIZE_BYTES,
    HostActionRequest,
    HostActionResult,
    _reset_host_agent_state_for_tests,
    execute_host_action,
    validate_allowed_file_path,
)
from assistant_os.agents.host_audit import (
    HOST_AUDIT_LOG,
    HostAuditEventType,
    HostErrorCode,
)
from assistant_os.core.control_plane import (
    _reset_state_for_tests,
    activate_agent,
)


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


def _req(action: str, path: str = "", confirmed: bool = True, execution_id: str = "x-01") -> HostActionRequest:
    activate_agent(HOST_AGENT_ID)
    return HostActionRequest(action=action, path=path, confirmed=confirmed, execution_id=execution_id)


_ALLOWED_DIR = ALLOWED_DIRECTORIES[0]   # e.g. C:\Users\Jorge\Desktop
_ALLOWED_FILE = _ALLOWED_DIR + r"\notes.txt"
_ALLOWED_PDF  = _ALLOWED_DIR + r"\report.pdf"
_DISALLOWED_FILE = r"C:\Windows\System32\secret.txt"


def _scandir_cm(entries):
    """Wrap a list of mock DirEntry objects as a context manager for os.scandir."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=iter(entries))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ===========================================================================
# A. validate_allowed_file_path
# ===========================================================================


class TestValidateAllowedFilePath:
    def test_file_inside_allowed_dir_passes(self):
        ok, reason = validate_allowed_file_path(_ALLOWED_FILE)
        assert ok is True
        assert reason == ""

    def test_file_in_subdirectory_passes(self):
        path = _ALLOWED_DIR + r"\sub\deep\file.txt"
        ok, _ = validate_allowed_file_path(path)
        assert ok is True

    def test_empty_path_rejected(self):
        ok, reason = validate_allowed_file_path("")
        assert ok is False
        assert "empty" in reason

    def test_path_outside_allowed_dirs_rejected(self):
        ok, reason = validate_allowed_file_path(r"C:\Windows\System32\evil.txt")
        assert ok is False
        assert "ALLOWED_DIRECTORIES" in reason

    def test_traversal_blocked(self):
        # Attempt to escape: C:\Users\Jorge\Desktop\..\..\..\Windows\evil.txt
        traversal = _ALLOWED_DIR + r"\..\..\evil.txt"
        ok, _ = validate_allowed_file_path(traversal)
        assert ok is False

    def test_adjacent_prefix_blocked(self):
        # C:\Users\JorgeEvil should NOT match C:\Users\Jorge
        ok, _ = validate_allowed_file_path(r"C:\Users\JorgeEvil\file.txt")
        assert ok is False


# ===========================================================================
# B. list_directory
# ===========================================================================


class TestListDirectory:
    def _scandir_entries(self, names_types):
        """Build list of mock DirEntry objects."""
        entries = []
        for name, kind in names_types:
            e = MagicMock()
            e.name = name
            e.is_dir.return_value = kind == "dir"
            e.stat.return_value = MagicMock(st_size=512 if kind == "file" else 0)
            entries.append(e)
        return entries

    def test_valid_directory_returns_entries(self):
        mock_entries = self._scandir_entries([("file.txt", "file"), ("subdir", "dir")])
        req = _req("list_directory", path=_ALLOWED_DIR)
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm(mock_entries)):
            result = execute_host_action(req)
        assert result.ok is True
        assert result.action == "list_directory"
        assert len(result.entries) == 2

    def test_entries_contain_expected_fields(self):
        mock_entries = self._scandir_entries([("readme.md", "file")])
        req = _req("list_directory", path=_ALLOWED_DIR)
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm(mock_entries)):
            result = execute_host_action(req)
        entry = result.entries[0]
        assert entry["name"] == "readme.md"
        assert entry["type"] == "file"
        assert entry["extension"] == ".md"
        assert entry["size"] == 512

    def test_dir_entry_has_no_size_or_extension(self):
        mock_entries = self._scandir_entries([("mydir", "dir")])
        req = _req("list_directory", path=_ALLOWED_DIR)
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm(mock_entries)):
            result = execute_host_action(req)
        entry = result.entries[0]
        assert entry["type"] == "dir"
        assert entry["size"] is None
        assert entry["extension"] is None

    def test_directory_not_in_allowlist_rejected(self):
        req = _req("list_directory", path=r"C:\Windows\System32")
        result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.DIRECTORY_NOT_ALLOWED

    def test_directory_not_found(self):
        req = _req("list_directory", path=_ALLOWED_DIR)
        with patch("os.path.isdir", return_value=False):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.DIRECTORY_NOT_FOUND

    def test_limit_respected(self):
        # Create LIST_DIRECTORY_LIMIT + 5 entries; expect exactly LIST_DIRECTORY_LIMIT returned
        over_limit = self._scandir_entries(
            [("f{}.txt".format(i), "file") for i in range(LIST_DIRECTORY_LIMIT + 5)]
        )
        req = _req("list_directory", path=_ALLOWED_DIR)
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm(over_limit)):
            result = execute_host_action(req)
        assert result.ok is True
        assert len(result.entries) == LIST_DIRECTORY_LIMIT

    def test_intent_audit_emitted_before_scandir(self):
        mock_entries = self._scandir_entries([("a.txt", "file")])
        req = _req("list_directory", path=_ALLOWED_DIR)
        call_order = []

        def fake_intent(**kwargs):
            call_order.append("intent")

        def fake_scandir(path):
            call_order.append("scandir")
            return _scandir_cm(mock_entries)

        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", side_effect=fake_scandir), \
             patch("assistant_os.agents.host_agent.emit_action_intent", side_effect=fake_intent):
            execute_host_action(req)

        assert call_order == ["intent", "scandir"]

    def test_outcome_audit_emitted(self):
        mock_entries = self._scandir_entries([("a.txt", "file")])
        req = _req("list_directory", path=_ALLOWED_DIR)
        with patch("os.path.isdir", return_value=True), \
             patch("os.scandir", return_value=_scandir_cm(mock_entries)):
            execute_host_action(req)
        events = HOST_AUDIT_LOG.events()
        outcome = [e for e in events if e.event_type == HostAuditEventType.HOST_ACTION_OUTCOME]
        assert len(outcome) == 1
        assert outcome[0].action == "list_directory"


# ===========================================================================
# C. open_file
# ===========================================================================


class TestOpenFile:
    def test_valid_file_calls_popen(self):
        req = _req("open_file", path=_ALLOWED_FILE)
        with patch("os.path.isfile", return_value=True), \
             patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is True
        assert result.action == "open_file"
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "rundll32.exe" in args[0]
        assert _ALLOWED_FILE in args[2] or _ALLOWED_DIR in args[2]

    def test_extension_not_allowed_rejected(self):
        bad_path = _ALLOWED_DIR + r"\malware.exe"
        req = _req("open_file", path=bad_path)
        with patch("os.path.isfile", return_value=True), \
             patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.EXTENSION_NOT_ALLOWED
        mock_popen.assert_not_called()

    def test_ps1_blocked(self):
        bad_path = _ALLOWED_DIR + r"\script.ps1"
        req = _req("open_file", path=bad_path)
        with patch("os.path.isfile", return_value=True), \
             patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.EXTENSION_NOT_ALLOWED
        mock_popen.assert_not_called()

    def test_path_outside_allowlist_rejected(self):
        req = _req("open_file", path=_DISALLOWED_FILE)
        with patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_NOT_ALLOWED
        mock_popen.assert_not_called()

    def test_file_not_found(self):
        req = _req("open_file", path=_ALLOWED_FILE)
        with patch("os.path.isfile", return_value=False), \
             patch("subprocess.Popen") as mock_popen:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_NOT_FOUND
        mock_popen.assert_not_called()

    def test_intent_before_popen(self):
        call_order = []

        def fake_intent(**kwargs):
            call_order.append("intent")

        def fake_popen(args):
            call_order.append("popen")
            return MagicMock()

        req = _req("open_file", path=_ALLOWED_FILE)
        with patch("os.path.isfile", return_value=True), \
             patch("assistant_os.agents.host_agent.emit_action_intent", side_effect=fake_intent), \
             patch("subprocess.Popen", side_effect=fake_popen):
            execute_host_action(req)

        assert call_order == ["intent", "popen"]

    def test_outcome_audit_emitted(self):
        req = _req("open_file", path=_ALLOWED_FILE)
        with patch("os.path.isfile", return_value=True), \
             patch("subprocess.Popen"):
            execute_host_action(req)
        events = HOST_AUDIT_LOG.events()
        outcome = [e for e in events if e.event_type == HostAuditEventType.HOST_ACTION_OUTCOME]
        assert len(outcome) == 1
        assert outcome[0].action == "open_file"


# ===========================================================================
# D. read_text_file
# ===========================================================================


class TestReadTextFile:
    def test_valid_small_file_returns_content(self):
        req = _req("read_text_file", path=_ALLOWED_FILE)
        with patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=100), \
             patch("builtins.open", return_value=io.StringIO("hello world")):
            result = execute_host_action(req)
        assert result.ok is True
        assert result.content == "hello world"

    def test_file_too_large_rejected(self):
        req = _req("read_text_file", path=_ALLOWED_FILE)
        with patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=MAX_READ_SIZE_BYTES + 1), \
             patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_TOO_LARGE
        mock_open.assert_not_called()

    def test_extension_not_allowed_rejected(self):
        bad_path = _ALLOWED_DIR + r"\data.bin"
        req = _req("read_text_file", path=bad_path)
        with patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=10), \
             patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.EXTENSION_NOT_ALLOWED
        mock_open.assert_not_called()

    def test_path_outside_allowlist_rejected(self):
        req = _req("read_text_file", path=_DISALLOWED_FILE)
        with patch("builtins.open") as mock_open:
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_NOT_ALLOWED
        mock_open.assert_not_called()

    def test_file_not_found(self):
        req = _req("read_text_file", path=_ALLOWED_FILE)
        with patch("os.path.isfile", return_value=False):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.FILE_NOT_FOUND

    def test_invalid_encoding_returns_error_code(self):
        req = _req("read_text_file", path=_ALLOWED_FILE)

        def bad_open(path, encoding):
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "invalid byte")

        with patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=100), \
             patch("builtins.open", side_effect=bad_open):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.INVALID_ENCODING
        assert result.content is None

    def test_intent_before_open(self):
        call_order = []

        def fake_intent(**kwargs):
            call_order.append("intent")

        def fake_open(path, encoding):
            call_order.append("open")
            return io.StringIO("data")

        req = _req("read_text_file", path=_ALLOWED_FILE)
        with patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=50), \
             patch("assistant_os.agents.host_agent.emit_action_intent", side_effect=fake_intent), \
             patch("builtins.open", side_effect=fake_open):
            execute_host_action(req)

        assert call_order == ["intent", "open"]

    def test_outcome_audit_emitted_on_success(self):
        req = _req("read_text_file", path=_ALLOWED_FILE)
        with patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=50), \
             patch("builtins.open", return_value=io.StringIO("text")):
            execute_host_action(req)
        events = HOST_AUDIT_LOG.events()
        outcome = [e for e in events if e.event_type == HostAuditEventType.HOST_ACTION_OUTCOME]
        assert len(outcome) == 1
        assert outcome[0].action == "read_text_file"
        assert outcome[0].result == "read"

    def test_outcome_audit_emitted_on_encoding_error(self):
        req = _req("read_text_file", path=_ALLOWED_FILE)

        def bad_open(path, encoding):
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "x")

        with patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=50), \
             patch("builtins.open", side_effect=bad_open):
            execute_host_action(req)
        events = HOST_AUDIT_LOG.events()
        outcome = [e for e in events if e.event_type == HostAuditEventType.HOST_ACTION_OUTCOME]
        assert len(outcome) == 1
        assert outcome[0].result == "encoding_error"


# ===========================================================================
# E. Existing gates still block new actions
# ===========================================================================


class TestGatesBlockNewActions:
    @pytest.mark.parametrize("action,path", [
        ("list_directory", _ALLOWED_DIR),
        ("open_file",      _ALLOWED_FILE),
        ("read_text_file", _ALLOWED_FILE),
    ])
    def test_confirmed_false_blocks_all_new_actions(self, action, path):
        activate_agent(HOST_AGENT_ID)
        req = HostActionRequest(action=action, path=path, confirmed=False, execution_id="t")
        with patch("subprocess.Popen") as mock_popen, \
             patch("builtins.open") as mock_open, \
             patch("os.scandir") as mock_scan, \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=10):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.CONFIRMED_REQUIRED
        mock_popen.assert_not_called()
        mock_open.assert_not_called()
        mock_scan.assert_not_called()

    @pytest.mark.parametrize("action,path", [
        ("list_directory", _ALLOWED_DIR),
        ("open_file",      _ALLOWED_FILE),
        ("read_text_file", _ALLOWED_FILE),
    ])
    def test_inactive_agent_blocks_all_new_actions(self, action, path):
        # Agent not activated — PAUSED by default
        req = HostActionRequest(action=action, path=path, confirmed=True, execution_id="t")
        with patch("subprocess.Popen") as mock_popen, \
             patch("builtins.open") as mock_open, \
             patch("os.scandir") as mock_scan, \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=10):
            result = execute_host_action(req)
        assert result.ok is False
        assert result.error_code == HostErrorCode.CONTROL_PLANE_BLOCKED
        mock_popen.assert_not_called()
        mock_open.assert_not_called()
        mock_scan.assert_not_called()


# ===========================================================================
# F. No write / no exec surface
# ===========================================================================


class TestNoWriteNoExec:
    """Structural checks: new handlers never use shell=True and never open for write."""

    def test_open_file_popen_args_no_shell(self):
        """subprocess.Popen must never be called with shell=True."""
        req = _req("open_file", path=_ALLOWED_FILE)
        with patch("os.path.isfile", return_value=True), \
             patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            execute_host_action(req)
        _, kwargs = mock_popen.call_args
        assert kwargs.get("shell", False) is False

    def test_read_text_file_open_mode_is_readonly(self):
        """builtins.open must never be called with a write mode."""
        req = _req("read_text_file", path=_ALLOWED_FILE)
        with patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=20), \
             patch("builtins.open", return_value=io.StringIO("x")) as mock_open:
            execute_host_action(req)
        args, kwargs = mock_open.call_args
        mode = kwargs.get("mode", args[1] if len(args) > 1 else "r")
        assert "w" not in mode
        assert "a" not in mode
        assert "+" not in mode
