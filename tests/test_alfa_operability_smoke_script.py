from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "alfa_operability_smoke.py"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_alfa_operability_smoke_script_exists() -> None:
    assert SCRIPT.exists()


def test_alfa_operability_smoke_script_has_main_guard() -> None:
    text = _script_text()
    assert 'if __name__ == "__main__":' in text
    assert "sys.exit(main())" in text


def test_alfa_operability_smoke_has_explicit_confirm_flow_flag() -> None:
    text = _script_text()
    assert "--exercise-confirm-flow" in text
    assert "args.exercise_confirm_flow" in text


def test_alfa_operability_smoke_default_read_only_checks_are_get_only() -> None:
    module = ast.parse(_script_text())
    checks_node = next(
        node for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "READ_ONLY_CHECKS" for target in node.targets)
    )
    for call in checks_node.value.elts:
        assert isinstance(call, ast.Call)
        assert call.args[1].value == "GET"


def _read_only_check_paths() -> list[str]:
    module = ast.parse(_script_text())
    checks_node = next(
        node for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "READ_ONLY_CHECKS" for target in node.targets)
    )
    paths: list[str] = []
    for call in checks_node.value.elts:
        assert isinstance(call, ast.Call)
        assert len(call.args) >= 3
        path_arg = call.args[2]
        assert isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str)
        paths.append(path_arg.value)
    return paths


def test_alfa_operability_smoke_read_only_paths_include_required_eight() -> None:
    required = {
        "/health",
        "/mso/state",
        "/mso/governance/status",
        "/mso/governance/recent?limit=10",
        "/mso/authority/status",
        "/confirm/pending?limit=10",
        "/mso/outcome/status",
        "/code/readiness",
    }
    paths = set(_read_only_check_paths())
    assert required.issubset(paths), (
        "READ_ONLY_CHECKS must include the 8 required read-only endpoints; "
        f"missing={sorted(required - paths)}"
    )


def test_alfa_operability_smoke_read_only_paths_required_count_is_eight() -> None:
    required = {
        "/health",
        "/mso/state",
        "/mso/governance/status",
        "/mso/governance/recent?limit=10",
        "/mso/authority/status",
        "/confirm/pending?limit=10",
        "/mso/outcome/status",
        "/code/readiness",
    }
    assert len(required) == 8


def test_alfa_operability_smoke_does_not_confirm_without_flag() -> None:
    text = _script_text()
    assert "run_confirm_flow(args, token)" in text
    assert "if args.exercise_confirm_flow:" in text


def test_alfa_operability_smoke_full_flow_endpoints_are_explicitly_present() -> None:
    text = _script_text()
    assert '"/host/action"' in text
    assert '"/host/confirm"' in text
    assert '"/mso/outcome/status?" + urlencode({"plan_id": plan_id})' in text


def test_alfa_operability_smoke_keeps_exercise_flag_and_create_directory_payload() -> None:
    text = _script_text()
    assert "--exercise-confirm-flow" in text
    assert '"action": "create_directory"' in text


def test_alfa_operability_smoke_avoids_prohibited_endpoints_and_services() -> None:
    text = _script_text().lower()
    forbidden = (
        "/shutdown",
        "/mso/freeze",
        "/admin/governance/mode",
        "notion",
        "sheets",
        "google",
        "webbrowser",
        "selenium",
        "playwright",
        "subprocess",
    )
    for marker in forbidden:
        assert marker not in text


def test_alfa_operability_smoke_uses_token_env_not_hardcoded_token() -> None:
    text = _script_text()
    assert "DEFAULT_TOKEN_ENV = \"WEBHOOK_TOKEN\"" in text
    assert "os.environ.get(args.token_env)" in text
    assert "TEST_TOKEN_NOT_FOR_PRODUCTION_USE" not in text


def test_alfa_operability_smoke_has_local_only_url_guard() -> None:
    text = _script_text()
    assert "LOCAL_HOSTS" in text
    assert "127.0.0.1" in text
    assert "localhost" in text
    assert "::1" in text
    assert "must target local backend only" in text
