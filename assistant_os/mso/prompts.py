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


def build_mso_chat_system_prompt(grounding_context: dict) -> str:
    """Build the system prompt for MSO conversational generation.

    Injects the full economic perception frame (SPRINT-ALPHA-02) so the LLM
    is anchored to real system state. Sections are rendered only when non-empty;
    each section falls back to an explicit 'No data currently visible.' line.

    Never grants execution authority — the prompt hard-codes the execution
    boundary and instructs the model that it cannot execute, issue tokens,
    or approve plans. Do-not-invent rules cover all perception frame fields.
    """
    operational_mode = grounding_context.get("operational_mode", "UNKNOWN")
    seat_provider = grounding_context.get("seat_provider", "not configured")
    prepared_count = grounding_context.get("prepared_actions_count", 0)
    next_safe_step = grounding_context.get("next_safe_step", "")
    authority_posture = grounding_context.get("authority_posture", "")
    limitations = grounding_context.get("limitations", "")
    version = grounding_context.get("version", "")
    generated_at = grounding_context.get("generated_at", "")

    capabilities = grounding_context.get("capabilities_summary") or {}
    recent_governance = grounding_context.get("recent_governance") or []
    active_tasks = grounding_context.get("active_tasks_brief") or []
    recent_failures = grounding_context.get("recent_failures") or []
    prepared_summary = grounding_context.get("prepared_actions_summary") or []
    perception_warnings = grounding_context.get("perception_warnings") or []

    def _fmt_capabilities(caps: dict) -> str:
        if not caps:
            return "  No data currently visible."
        lines: list[str] = []
        if caps.get("domains"):
            lines.append(f"  Domains: {', '.join(caps['domains'])}")
        if caps.get("active_capabilities"):
            lines.append(f"  Active capabilities: {', '.join(caps['active_capabilities'])}")
        if caps.get("machine_operator"):
            lines.append(f"  Machine Operator: {caps['machine_operator']}")
        if caps.get("runner_enforced"):
            lines.append("  Runner: enforced")
        return "\n".join(lines) if lines else "  No data currently visible."

    def _fmt_governance(decisions: list) -> str:
        if not decisions:
            return "  No data currently visible."
        lines: list[str] = []
        for d in decisions[:5]:
            if isinstance(d, dict):
                outcome = d.get("outcome") or d.get("decision") or "?"
                domain = d.get("domain") or d.get("classifier_domain") or "?"
                did = d.get("decision_id") or d.get("id") or "?"
                lines.append(f"  [{did}] domain={domain} outcome={outcome}")
            else:
                lines.append(f"  {d}")
        return "\n".join(lines)

    def _fmt_tasks(tasks: list) -> str:
        if not tasks:
            return "  No data currently visible."
        lines: list[str] = []
        for t in tasks[:5]:
            if isinstance(t, dict):
                lines.append(
                    f"  [{t.get('task_id', '?')}] domain={t.get('domain', '?')} "
                    f"status={t.get('status', '?')} action={t.get('last_known_action', '?')}"
                )
            else:
                lines.append(f"  {t}")
        return "\n".join(lines)

    def _fmt_failures(failures: list) -> str:
        if not failures:
            return "  No data currently visible."
        lines: list[str] = []
        for f in failures[:5]:
            if isinstance(f, dict):
                lines.append(
                    f"  [{f.get('task_id', '?')}] domain={f.get('domain', '?')} "
                    f"error={f.get('error_type', '?')}: "
                    f"{str(f.get('error_message', ''))[:60]}"
                )
            else:
                lines.append(f"  {f}")
        return "\n".join(lines)

    def _fmt_prepared(items: list, count: int) -> str:
        if count == 0 or not items:
            return "  None."
        lines: list[str] = [f"  Total waiting for human review: {count}"]
        for item in items[:5]:
            if isinstance(item, dict):
                lines.append(
                    f"  [{item.get('queue_entry_id', '?')}] "
                    f"domain={item.get('domain', '?')} "
                    f"action={item.get('requested_action', '?')} "
                    f"status={item.get('human_confirmation_status', '?')} "
                    f"execution_allowed={item.get('execution_allowed', False)}"
                )
            else:
                lines.append(f"  {item}")
        return "\n".join(lines)

    warnings_section = ""
    if perception_warnings:
        joined = "; ".join(perception_warnings[:5])
        warnings_section = (
            f"\nPERCEPTION WARNINGS (some data sources unavailable):\n  {joined}\n"
        )

    frame_meta = (
        f"perception frame v{version} generated_at={generated_at}" if version else ""
    )

    return (
        "You are the MSO — the Machine Sovereign Operator, the cognitive layer "
        "of AssistantOS. You reason, explain, inspect system state, and propose "
        "actions on behalf of the governed execution system.\n\n"
        "HARD RULES:\n"
        f"- {limitations}\n"
        "- Do not claim you have executed, run, deployed, completed, or started "
        "any action — even if asked to confirm.\n"
        "- Do not invent capabilities, tokens, plans, tasks, failures, or agents "
        "not listed in the perception frame below.\n"
        "- If a field shows 'No data currently visible', report that — "
        "do not invent values.\n"
        "- Any real execution requires explicit human confirmation through a "
        "governed pipeline.\n\n"
        "CURRENT SYSTEM CONTEXT (grounded, read-only):\n"
        f"- Operational mode: {operational_mode}\n"
        f"- Cognitive provider: {seat_provider}\n"
        f"- Authority chain: {authority_posture}\n"
        f"- Next safe step: {next_safe_step}\n"
        "- Execution boundary: execution_allowed=false, can_execute_now=false\n"
        f"{f'- {frame_meta}' if frame_meta else ''}\n"
        "\nCAPABILITIES (from live capability registry):\n"
        f"{_fmt_capabilities(capabilities)}\n"
        "\nPREPARED ACTIONS AWAITING HUMAN REVIEW:\n"
        f"{_fmt_prepared(prepared_summary, prepared_count)}\n"
        "\nRECENT GOVERNANCE DECISIONS (last 5):\n"
        f"{_fmt_governance(recent_governance)}\n"
        "\nACTIVE TASKS (last 5):\n"
        f"{_fmt_tasks(active_tasks)}\n"
        "\nRECENT FAILURES (last 5):\n"
        f"{_fmt_failures(recent_failures)}\n"
        f"{warnings_section}"
        "\nRESPONSE RULES:\n"
        "- Answer in the same language as the user's message.\n"
        "- Be concise and operationally grounded.\n"
        "- Use only the system context above — do not invent additional state.\n"
        "- When uncertain, say so rather than fabricating details.\n"
    )
