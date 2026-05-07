import ast
import inspect

from assistant_os.police.gate_models import PoliceDecision, PoliceOutcome, PoliceReason
from assistant_os.police.harness import apply_police_gate
import assistant_os.police.harness as harness


def _decision(**overrides):
    values = {
        "decision_id": "decision-1",
        "execution_id": "exec-1",
        "trace_id": "trace-1",
        "outcome": PoliceOutcome.PERMITTED,
        "reason": PoliceReason.ALLOWED,
        "detail": "Allowed by future token-bound gate.",
        "permitted": True,
    }
    values.update(overrides)
    return PoliceDecision(**values)


def test_apply_police_gate_allow_returns_would_continue_and_does_not_execute():
    result = apply_police_gate(_decision())

    assert result == {
        "ok": True,
        "status": "would_continue",
        "police_decision_ref": "decision-1",
    }


def test_apply_police_gate_deny_returns_blocked_and_why_blocked():
    decision = _decision(
        outcome=PoliceOutcome.DENIED,
        reason=PoliceReason.TOKEN_INVALID,
        detail="Token is invalid.",
        permitted=False,
    )

    result = apply_police_gate(decision)

    assert result == {
        "ok": False,
        "status": "blocked",
        "reason": "token_invalid",
        "why_blocked": "Token is invalid.",
        "police_decision_ref": "decision-1",
    }


def test_apply_police_gate_requires_confirmation_returns_confirmation_reason():
    decision = _decision(
        outcome=PoliceOutcome.DEFERRED,
        reason=PoliceReason.CONFIRMATION_REQUIRED,
        detail="Confirmation is required.",
        permitted=False,
    )

    result = apply_police_gate(decision)

    assert result == {
        "ok": False,
        "status": "requires_confirmation",
        "reason": "confirmation_required",
        "required_confirmation_reason": "Confirmation is required.",
        "police_decision_ref": "decision-1",
    }


def test_harness_source_contains_no_runtime_boundary_imports():
    source = inspect.getsource(harness)

    assert "runner" not in source
    assert "pipeline" not in source
    assert "CODE" not in source
    assert "sandbox" not in source


def test_harness_source_contains_no_execute_run_dispatch_methods():
    tree = ast.parse(inspect.getsource(harness))
    forbidden_names = {"execute", "run", "dispatch"}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in forbidden_names
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_names


def test_harness_does_not_import_forbidden_runtime_modules():
    tree = ast.parse(inspect.getsource(harness))
    forbidden_modules = {
        "assistant_os.pipelines",
        "assistant_os.runners",
        "assistant_os.executors",
        "assistant_os.sandbox",
        "assistant_os.missions",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue

        for name in names:
            assert name not in forbidden_modules


def test_apply_police_gate_does_not_call_enforcement_check():
    tree = ast.parse(inspect.getsource(apply_police_gate))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id != "check"
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr != "check"
