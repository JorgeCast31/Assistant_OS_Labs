"""
Kernel Enrichment — Non-authoritative RouteDecision computation.

Derives semantic enrichment signals from a CanonicalRequest and a classified
Intent. Output is a RouteDecision — a non-authoritative artifact that carries
signals for operator guidance and surface rendering only.

INVARIANT: This module MUST NOT read or write execution_mode, PolicyDecision,
GovernanceVerdict, or capability grants. It must not gate execution. It must
not be consulted by any component that makes authority decisions.

Enrichment is deterministic: same inputs always produce the same RouteDecision.
No LLM calls are made here. All derivations use keyword rules and lookup tables.
"""

from __future__ import annotations

from ..contracts import (
    RouteDecision,
    make_route_decision,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_HIGH,
    RISK_HINT_NONE,
    RISK_HINT_LOW,
    RISK_HINT_MEDIUM,
    RISK_HINT_HIGH,
)

# ---------------------------------------------------------------------------
# Lookup tables — deterministic, no side effects
# ---------------------------------------------------------------------------

_RISK_LEVEL_TO_HINT: dict[str, str] = {
    RISK_LOW:    RISK_HINT_LOW,
    RISK_MEDIUM: RISK_HINT_MEDIUM,
    RISK_HIGH:   RISK_HINT_HIGH,
}

# Direct operation → risk_hint mapping.
# Used when risk_level is not available in the intent dict (typical classifier output).
_RISK_HINT_BY_OPERATION: dict[str, str] = {
    "WORK_QUERY":   RISK_HINT_LOW,
    "WORK_CREATE":  RISK_HINT_MEDIUM,
    "WORK_UPDATE":  RISK_HINT_MEDIUM,
    "WORK_DELETE":  RISK_HINT_HIGH,
    "FIN_EXPENSE":  RISK_HINT_MEDIUM,
    "FIN_BATCH":    RISK_HINT_MEDIUM,
    "FIN_PLAN":     RISK_HINT_LOW,
    "FIN_COMMIT":   RISK_HINT_MEDIUM,
    "FIN_CONFIRM":  RISK_HINT_MEDIUM,
    "FIN_CHAPERON": RISK_HINT_LOW,
    "CODE_EXPLAIN": RISK_HINT_LOW,
    "CODE_REVIEW":  RISK_HINT_LOW,
    "CODE_FIX":     RISK_HINT_MEDIUM,
    "CODE_CREATE":  RISK_HINT_MEDIUM,
    "HOST_OPEN_APP":        RISK_HINT_MEDIUM,
    "HOST_CLOSE_PID":       RISK_HINT_HIGH,
    "HOST_OPEN_DIRECTORY":  RISK_HINT_MEDIUM,
    "HOST_OPEN_URL":        RISK_HINT_MEDIUM,
    "HOST_LIST_DIRECTORY":  RISK_HINT_LOW,
    "HOST_OPEN_FILE":       RISK_HINT_MEDIUM,
    "HOST_READ_TEXT_FILE":  RISK_HINT_LOW,
    "HOST_WRITE_TEXT_FILE":  RISK_HINT_MEDIUM,
    "HOST_APPEND_TEXT_FILE": RISK_HINT_MEDIUM,
    "HOST_CREATE_DIRECTORY": RISK_HINT_MEDIUM,
    "MACHINE_OPERATOR_EXECUTE": RISK_HINT_LOW,
    "BASIC_COGNITIVE_EXECUTION": RISK_HINT_LOW,
}

_SEMANTIC_SUMMARY: dict[str, str] = {
    "WORK_QUERY":   "Work domain: read-only query of task records",
    "WORK_CREATE":  "Work domain: create a new task record",
    "WORK_UPDATE":  "Work domain: update an existing task record",
    "WORK_DELETE":  "Work domain: delete or archive a task record",
    "FIN_EXPENSE":  "Finance domain: register a single expense",
    "FIN_BATCH":    "Finance domain: register multiple expenses in batch",
    "FIN_PLAN":     "Finance domain: analyze financial plan (read-only)",
    "FIN_COMMIT":   "Finance domain: commit expense to store",
    "FIN_CONFIRM":  "Finance domain: confirm and store expense",
    "FIN_CHAPERON": "Finance domain: run chaperon analysis (read-only)",
    "CODE_EXPLAIN": "Code domain: explain code (read-only)",
    "CODE_REVIEW":  "Code domain: review and audit code (read-only)",
    "CODE_FIX":     "Code domain: propose a code fix (mutating, preview first)",
    "CODE_CREATE":  "Code domain: create new code artifact (mutating)",
    "HOST_OPEN_APP":        "Host domain: launch a registered application",
    "HOST_CLOSE_PID":       "Host domain: terminate a managed process",
    "HOST_OPEN_DIRECTORY":  "Host domain: open a directory in explorer",
    "HOST_OPEN_URL":        "Host domain: open an allowed URL",
    "HOST_LIST_DIRECTORY":  "Host domain: list directory contents (read-only)",
    "HOST_OPEN_FILE":       "Host domain: open a file with default application",
    "HOST_READ_TEXT_FILE":  "Host domain: read text file content (read-only)",
    "HOST_WRITE_TEXT_FILE":  "Host domain: write text file in write sandbox",
    "HOST_APPEND_TEXT_FILE": "Host domain: append to text file in write sandbox",
    "HOST_CREATE_DIRECTORY": "Host domain: create directory in write sandbox",
    "MACHINE_OPERATOR_EXECUTE": "Machine operator domain: bounded lane dispatch",
    "BASIC_COGNITIVE_EXECUTION": "Cognitive domain: bounded cognitive worker dispatch",
}

_CONTEXT_REQUIREMENTS: dict[str, list[str]] = {
    "WORK_QUERY":   [],
    "WORK_CREATE":  ["task_title"],
    "WORK_UPDATE":  ["task_target"],
    "WORK_DELETE":  ["task_target"],
    "FIN_EXPENSE":  ["amount", "category"],
    "FIN_BATCH":    ["items"],
    "FIN_PLAN":     [],
    "FIN_COMMIT":   ["expense_data"],
    "FIN_CONFIRM":  ["expense_data"],
    "FIN_CHAPERON": [],
    "CODE_EXPLAIN": ["target_file"],
    "CODE_REVIEW":  ["target_file"],
    "CODE_FIX":     ["target_file", "workspace"],
    "CODE_CREATE":  ["target_file", "workspace"],
    "HOST_OPEN_APP":        ["app_name"],
    "HOST_CLOSE_PID":       ["pid"],
    "HOST_OPEN_DIRECTORY":  ["directory_path"],
    "HOST_OPEN_URL":        ["url"],
    "HOST_LIST_DIRECTORY":  ["directory_path"],
    "HOST_OPEN_FILE":       ["file_path"],
    "HOST_READ_TEXT_FILE":  ["file_path"],
    "HOST_WRITE_TEXT_FILE":  ["file_path", "content"],
    "HOST_APPEND_TEXT_FILE": ["file_path", "content"],
    "HOST_CREATE_DIRECTORY": ["directory_path"],
    "MACHINE_OPERATOR_EXECUTE": ["directive"],
    "BASIC_COGNITIVE_EXECUTION": [],
}

_SUGGESTED_NEXT_STEP: dict[str, str] = {
    "WORK_QUERY":   "Review the returned task list.",
    "WORK_CREATE":  "Confirm the new task details before creating.",
    "WORK_UPDATE":  "Review the proposed changes before confirming.",
    "WORK_DELETE":  "Confirm deletion — this action is destructive.",
    "FIN_EXPENSE":  "Verify the expense details before committing.",
    "FIN_BATCH":    "Review all items in the batch before committing.",
    "FIN_PLAN":     "Review the generated financial plan.",
    "FIN_COMMIT":   "Verify before storing — commit is irreversible.",
    "FIN_CONFIRM":  "Confirm storage of the expense.",
    "FIN_CHAPERON": "Review the chaperon analysis output.",
    "CODE_EXPLAIN": "Review the code explanation.",
    "CODE_REVIEW":  "Review the audit findings.",
    "CODE_FIX":     "Review the proposed fix before applying.",
    "CODE_CREATE":  "Review the proposed new file before applying.",
    "HOST_OPEN_APP":        "Confirm the application to launch.",
    "HOST_CLOSE_PID":       "Confirm process termination — this cannot be undone.",
    "HOST_OPEN_DIRECTORY":  "Confirm the directory to open.",
    "HOST_OPEN_URL":        "Confirm the URL to open.",
    "HOST_LIST_DIRECTORY":  "Review the directory listing.",
    "HOST_OPEN_FILE":       "Confirm the file to open.",
    "HOST_READ_TEXT_FILE":  "Review the file content.",
    "HOST_WRITE_TEXT_FILE":  "Confirm the write operation before proceeding.",
    "HOST_APPEND_TEXT_FILE": "Confirm the append operation before proceeding.",
    "HOST_CREATE_DIRECTORY": "Confirm the directory path before creating.",
    "MACHINE_OPERATOR_EXECUTE": "Review the machine operator directive.",
    "BASIC_COGNITIVE_EXECUTION": "Review the cognitive worker output.",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_enrichment(req: dict, intent: dict) -> RouteDecision:
    """
    Derive a RouteDecision from a CanonicalRequest and a classified Intent.

    Deterministic: same inputs always produce the same output.
    No LLM calls, no side effects, no state mutations.

    Args:
        req:    CanonicalRequest dict (normalized, from normalize_request)
        intent: Classified Intent dict (from semantic.classify or classify_text)

    Returns:
        RouteDecision with all enrichment fields populated from lookup tables.
        Falls back gracefully when operation is unrecognized.
    """
    operation: str = intent.get("operation", "") or ""
    domain: str = intent.get("domain", "") or ""
    # risk_level is not part of the classifier Intent output; derive risk_hint
    # from the operation lookup table (deterministic, no side effects).
    risk_level: str = intent.get("risk_level", "") or ""
    risk_hint: str | None = _risk_hint_for(operation, risk_level)

    operator_goal: str | None = _operator_goal(req, intent)
    semantic_summary: str | None = _SEMANTIC_SUMMARY.get(operation)
    context_requirements: list[str] = list(_CONTEXT_REQUIREMENTS.get(operation, []))
    suggested_next_step: str | None = _SUGGESTED_NEXT_STEP.get(operation)

    return make_route_decision(
        intent_type=operation,
        domain=domain,
        operator_goal=operator_goal,
        semantic_summary=semantic_summary,
        risk_hint=risk_hint,
        context_requirements=context_requirements,
        suggested_next_step=suggested_next_step,
    )


# ---------------------------------------------------------------------------
# Internal derivation helpers
# ---------------------------------------------------------------------------

def _risk_hint_for(operation: str, risk_level: str) -> str | None:
    """Derive risk_hint from operation and (optionally) risk_level.

    Priority:
    1. Direct operation lookup (_RISK_HINT_BY_OPERATION) — most precise.
    2. Explicit risk_level mapping — used when caller provides it.
    3. Suffix-based keyword inference — coarse fallback.
    """
    # 1. Direct operation lookup (most precise, covers all known operations).
    if operation in _RISK_HINT_BY_OPERATION:
        return _RISK_HINT_BY_OPERATION[operation]
    # 2. Explicit risk_level mapping.
    if risk_level in _RISK_LEVEL_TO_HINT:
        return _RISK_LEVEL_TO_HINT[risk_level]
    # 3. Suffix-based keyword inference (coarse fallback for unknown operations).
    if operation.endswith(("_QUERY", "_EXPLAIN", "_REVIEW", "_PLAN",
                           "_CHAPERON", "_LIST_DIRECTORY", "_READ_TEXT_FILE")):
        return RISK_HINT_LOW
    if operation.endswith(("_DELETE", "_CLOSE_PID")):
        return RISK_HINT_HIGH
    if operation:
        return RISK_HINT_MEDIUM
    return None


def _operator_goal(req: dict, intent: dict) -> str | None:
    """Derive a normalized operator goal from the request text and intent."""
    text: str = req.get("text", "") or ""
    operation: str = intent.get("operation", "") or ""
    if not text:
        return None
    # Normalize: strip and truncate to a single-line summary
    goal = text.strip()
    if len(goal) > 200:
        goal = goal[:197] + "..."
    return goal if goal else None
