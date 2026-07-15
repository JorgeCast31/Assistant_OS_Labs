"""Config startup output hygiene (PR #270).

Imports of assistant_os must not write to stdout; JSON CLIs must emit pure JSON.
Uses subprocesses because the (previous) prints happened at import time.
"""
import json
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXAMPLE = os.path.join(_ROOT, "docs", "mission", "examples",
                        "orchestration-preview-bundle.example.json")


def _env(**over):
    e = dict(os.environ)
    e.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
             NOTION_TOKEN="t", NOTION_WORK_DB_ID="t",
             WEBHOOK_TOKEN="t", SHEETS_SPREADSHEET_ID="t")
    e.pop("ASSISTANT_OS_CONFIG_DEBUG", None)
    e.update(over)
    return e


def _run(args, **over):
    return subprocess.run([sys.executable, *args], cwd=_ROOT, env=_env(**over),
                          capture_output=True, text=True)


def test_import_package_emits_no_stdout():
    r = _run(["-c", "import assistant_os"])
    assert r.returncode == 0, r.stderr
    assert r.stdout == "", repr(r.stdout)


def test_import_config_emits_no_stdout():
    r = _run(["-c", "import assistant_os.config"])
    assert r.returncode == 0, r.stderr
    assert r.stdout == "", repr(r.stdout)


def test_cli_stdout_starts_with_brace_and_parses():
    r = _run(["-m", "assistant_os.mso.orchestration_preview_io", _EXAMPLE])
    assert r.returncode == 0, r.stderr
    assert r.stdout.lstrip().startswith("{"), repr(r.stdout[:40])
    d = json.loads(r.stdout)
    assert d["can_execute"] is False and d["can_dispatch"] is False


def test_debug_flag_uses_stderr_not_stdout():
    r = _run(["-m", "assistant_os.mso.orchestration_preview_io", _EXAMPLE],
             ASSISTANT_OS_CONFIG_DEBUG="1")
    assert r.returncode == 0, r.stderr
    # stdout stays pure JSON even with debug on
    assert r.stdout.lstrip().startswith("{")
    json.loads(r.stdout)
    # debug diagnostics go to stderr
    assert "[CONFIG]" in r.stderr


def test_debug_flag_does_not_print_full_notion_db_id():
    secret_like = "SUPER_SENSITIVE_DB_ID_VALUE_123"
    r = _run(["-c", "import assistant_os.config"],
             ASSISTANT_OS_CONFIG_DEBUG="1", NOTION_WORK_DB_ID=secret_like)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""                     # never stdout
    assert secret_like not in r.stderr        # never full value
    assert "NOTION_WORK_DB_ID = <set>" in r.stderr


def test_debug_off_is_silent_on_stderr_for_config_lines():
    r = _run(["-c", "import assistant_os.config"])
    assert r.returncode == 0
    assert "[CONFIG]" not in r.stdout
    assert "[CONFIG]" not in r.stderr


def test_basic_config_behavior_unchanged():
    # Config still reads env values (semantics unchanged); stdout stays clean.
    r = _run(["-c",
              "import assistant_os.config as c,sys; "
              "sys.stdout.write('OK' if c.NOTION_WORK_DB_ID=='THEVAL' else 'BAD')"],
             NOTION_WORK_DB_ID="THEVAL")
    assert r.returncode == 0, r.stderr
    assert r.stdout == "OK"


def test_no_token_or_capability_minting():
    import assistant_os.config as config
    for a in ("issue_token", "mint", "grant_authority", "capability_token"):
        assert not hasattr(config, a)
