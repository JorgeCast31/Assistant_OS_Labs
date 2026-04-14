from assistant_os.contracts import ACTION_CODE_FIX, ACTION_CODE_REVIEW, make_plan
from assistant_os.pipelines.code_pipeline import execute, register_propose_executor, register_review_executor


def _make_code_plan(action: str, *, raw_text: str, workspace: str, target_file: str) -> dict:
    plan = make_plan(
        "CODE",
        action,
        target=target_file,
        raw_text=raw_text,
        requires_confirmation=action == ACTION_CODE_FIX,
    )
    payload = dict(plan.get("domain_payload") or {})
    payload["workspace"] = workspace
    payload["target_file"] = target_file
    payload["_mso_code_package"] = {
        "task_summary": "Fix startup crash in the target file.",
        "repo_context": "Startup path bug in the main application module.",
        "constraints": ["Do not redesign startup flow."],
        "expected_artifact": "Minimal patch touching only the target file.",
        "risk_notes": ["Avoid widening write scope."],
    }
    plan["domain_payload"] = payload
    return plan


def test_code_fix_preview_uses_advisory_packaging_in_executor_context(tmp_path):
    captured = {}

    def executor(inp: dict) -> dict:
        captured["context"] = inp["context"]
        return {
            "ok": True,
            "summary": "minimal fix",
            "patch_preview": "--- a/src/main.py\n+++ b/src/main.py\n@@\n-fail\n+pass\n",
            "affected_files": ["src/main.py"],
            "write_intent_summary": "Modify src/main.py",
            "operation_types": ["modify"],
            "risk_level": "medium",
        }

    register_propose_executor(executor)
    try:
        plan = _make_code_plan(
            ACTION_CODE_FIX,
            raw_text="fix the crash in src/main.py",
            workspace=str(tmp_path),
            target_file="src/main.py",
        )
        result = execute(plan, "ctx-code-packaging-preview")
    finally:
        register_propose_executor(None)

    assert result["ok"] is True
    assert "[MSO advisory package - non-authoritative]" in captured["context"]
    assert "Do not redesign startup flow." in captured["context"]


def test_code_review_uses_advisory_packaging_in_executor_context(tmp_path):
    captured = {}

    def executor(inp: dict) -> dict:
        captured["context"] = inp["context"]
        return {"ok": True, "analysis": "review ok"}

    register_review_executor(executor)
    try:
        plan = _make_code_plan(
            ACTION_CODE_REVIEW,
            raw_text="review src/main.py",
            workspace=str(tmp_path),
            target_file="src/main.py",
        )
        result = execute(plan, "ctx-code-packaging-review")
    finally:
        register_review_executor(None)

    assert result["ok"] is True
    assert "Expected artifact: Minimal patch touching only the target file." in captured["context"]
