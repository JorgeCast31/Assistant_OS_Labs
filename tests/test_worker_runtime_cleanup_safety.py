"""Tests that cognitive_worker_runner temp directory cleanup is Windows/fuse safe.

These tests MUST fail (ImportError on _cleanup_temp_dir_safe) until the helper
is implemented in assistant_os/executors/cognitive_worker_runner.py.
"""
import logging
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest


def test_cleanup_temp_dir_safe_removes_directory(tmp_path):
    """_cleanup_temp_dir_safe removes the directory when no error occurs."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "file.txt").write_text("data", encoding="utf-8")

    from assistant_os.executors.cognitive_worker_runner import _cleanup_temp_dir_safe

    _cleanup_temp_dir_safe(work_dir)

    assert not work_dir.exists()


def test_cleanup_temp_dir_safe_retries_on_permission_error(tmp_path):
    """_cleanup_temp_dir_safe retries on PermissionError and succeeds eventually."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    from assistant_os.executors.cognitive_worker_runner import _cleanup_temp_dir_safe

    call_count = {"n": 0}
    original_rmtree = shutil.rmtree

    def flaky_rmtree(path, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise PermissionError("simulated Windows file lock")
        original_rmtree(path, **kwargs)

    with patch("shutil.rmtree", side_effect=flaky_rmtree):
        _cleanup_temp_dir_safe(work_dir)

    assert call_count["n"] == 2, "Expected exactly 2 rmtree attempts (1 fail + 1 success)"


def test_cleanup_temp_dir_safe_logs_warning_after_max_retries(tmp_path, caplog):
    """_cleanup_temp_dir_safe logs a warning when all retry attempts are exhausted."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    from assistant_os.executors.cognitive_worker_runner import _cleanup_temp_dir_safe

    with patch("shutil.rmtree", side_effect=PermissionError("always locked")):
        with caplog.at_level(logging.WARNING, logger="assistant_os.executors.cognitive_worker_runner"):
            _cleanup_temp_dir_safe(work_dir)

    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_messages, "Expected at least one WARNING after exhausted cleanup retries"


def test_cleanup_temp_dir_safe_does_not_raise_on_persistent_failure(tmp_path):
    """_cleanup_temp_dir_safe never raises; a cleanup failure must not propagate."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    from assistant_os.executors.cognitive_worker_runner import _cleanup_temp_dir_safe

    with patch("shutil.rmtree", side_effect=PermissionError("always locked")):
        _cleanup_temp_dir_safe(work_dir)  # must not raise
