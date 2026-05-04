from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "demo_backend_outcome_flow.py"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_backend_outcome_demo_script_exists() -> None:
    assert SCRIPT.exists()


def test_backend_outcome_demo_script_has_main_guard() -> None:
    text = _script_text()
    assert 'if __name__ == "__main__":' in text
    assert "sys.exit(main())" in text


def test_backend_outcome_demo_script_uses_required_backend_endpoints() -> None:
    text = _script_text()
    for endpoint in (
        "/host/action",
        "/confirm/pending",
        "/host/confirm",
        "/mso/outcome/status",
    ):
        assert endpoint in text


def test_backend_outcome_demo_script_avoids_external_and_ui_execution() -> None:
    text = _script_text().lower()
    forbidden = (
        "notion",
        "sheets",
        "webbrowser",
        "selenium",
        "playwright",
        "subprocess",
        "localhost:3000",
        "/api/mso/outcome/status",
        "systemview",
        "outcomestatuspanel",
    )
    for marker in forbidden:
        assert marker not in text
