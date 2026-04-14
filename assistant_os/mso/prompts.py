"""Prompt builders for internal MSO advisory roles."""

from __future__ import annotations

from .contracts import LocalLlmRequest


def build_orchestrator_advisory_prompt(req: LocalLlmRequest) -> str:
    """Build the combined advisory prompt used by the orchestrator seam."""
    metadata = req.get("metadata") or {}
    action = req.get("planned_action", "")
    is_code = action.startswith("CODE_") or req.get("classifier_domain", "") == "CODE"
    code_clause = (
        '"code_task_summary":"one-sentence CODE task summary or empty string",'
        '"repo_context":"short repo/workspace context or empty string",'
        '"constraints":["constraint 1"],'
        '"expected_artifact":"expected artifact or empty string",'
        '"risk_notes":["risk 1"]'
        if is_code
        else
        '"code_task_summary":"",'
        '"repo_context":"",'
        '"constraints":[],'
        '"expected_artifact":"",'
        '"risk_notes":[]'
    )

    return (
        "You are an internal advisory model for AssistantOS.\n"
        "You are advisory only. You must not claim authority, execution, or final control.\n\n"
        "Return ONLY valid JSON with this exact shape:\n"
        "{"
        '"reasoning_summary":"short assistant-side interpretation",'
        '"routing_hint":"brief route hint or empty string",'
        '"suggested_domain":"domain label or empty string",'
        '"suggested_action":"action label or empty string",'
        '"execution_posture_hint":"auto|confirm|clarify|blocked|empty",'
        '"confidence_note":"short certainty note",'
        f"{code_clause}"
        "}\n\n"
        "Rules:\n"
        "- Be concise and structured.\n"
        "- Treat deterministic planning as source of truth.\n"
        "- Do not invent files, tools, side effects, or permissions.\n"
        "- If uncertain, leave fields empty instead of guessing.\n\n"
        f"User text: {req.get('text', '')}\n"
        f"Deterministic classifier operation: {req.get('classifier_operation', '')}\n"
        f"Deterministic classifier domain: {req.get('classifier_domain', '')}\n"
        f"Deterministic planned action: {action}\n"
        f"Deterministic plan preview: {req.get('plan_preview', '')}\n"
        f"Workspace target file: {metadata.get('target_file', '')}\n"
        f"Workspace root: {metadata.get('workspace', '')}\n"
        f"Allowed write scope: {metadata.get('allowed_write_scope', [])}\n"
    )
