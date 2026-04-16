"""
Contratos formales de entrada/salida para Assistant OS.
TypedDicts + helpers para Request/Response.
"""
from typing import TypedDict, Optional, Any
from datetime import datetime, timezone
import uuid


class Request(TypedDict):
    """Contrato de entrada para todos los agentes."""
    context_id: str       # uuid4
    agent: str            # "code"|"doc"|"jobs"|"biz"|"unknown"
    action: str           # p.ej. "run_task"
    payload: dict         # datos del task (incluye "raw" para el texto original)
    ts: str               # ISO8601


class ErrorDetail(TypedDict):
    """Detalle de error estructurado."""
    type: str
    message: str


class Response(TypedDict):
    """Contrato de salida para todos los agentes."""
    context_id: str
    agent: str
    status: str           # "ok"|"error"|"pending"
    output: dict          # contenido específico
    error: Optional[ErrorDetail]
    ts: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_context_id() -> str:
    """Genera un nuevo UUID4 como string."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Retorna timestamp actual en ISO8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def make_error(
    agent: str,
    context_id: str,
    message: str,
    err_type: str = "BadRequest"
) -> Response:
    """Construye una Response de error."""
    return Response(
        context_id=context_id,
        agent=agent,
        status="error",
        output={},
        error=ErrorDetail(type=err_type, message=message),
        ts=now_iso(),
    )


def make_ok(
    agent: str,
    context_id: str,
    output: dict[str, Any]
) -> Response:
    """Construye una Response exitosa."""
    return Response(
        context_id=context_id,
        agent=agent,
        status="ok",
        output=output,
        error=None,
        ts=now_iso(),
    )


def make_pending(
    agent: str,
    context_id: str,
    output: dict[str, Any]
) -> Response:
    """Construye una Response pending (para tareas async)."""
    return Response(
        context_id=context_id,
        agent=agent,
        status="pending",
        output=output,
        error=None,
        ts=now_iso(),
    )


# ---------------------------------------------------------------------------
# Classifier Contracts
# ---------------------------------------------------------------------------

class ClassifyRequest(TypedDict, total=False):
    """Request body para POST /classify."""
    text: str                    # Requerido
    mode: str                    # "auto"|"chat"|"action"|"work" (opcional, default "auto")
    conversation_id: str         # Opcional
    context: dict                # Opcional, para futuro


class IntentAlternative(TypedDict):
    """Alternativa de dominio con su confidence."""
    domain: str
    confidence: float


# Operational intent constants
OP_WORK_QUERY = "WORK_QUERY"      # Query tasks from Notion
OP_WORK_CREATE = "WORK_CREATE"    # Create task in Notion (write)
OP_WORK_UPDATE = "WORK_UPDATE"    # Update existing task in Notion (write)
OP_WORK_DELETE = "WORK_DELETE"    # Delete/archive tasks from Notion (write)
OP_FIN_EXPENSE = "FIN_EXPENSE"    # Financial expense tracking
OP_COMMAND = "COMMAND"            # Default command execution
# CODE domain operational intent constants
OP_CODE_EXPLAIN = "CODE_EXPLAIN"  # Read-only: explain / describe code
OP_CODE_REVIEW  = "CODE_REVIEW"   # Read-only: review / audit code
OP_CODE_FIX     = "CODE_FIX"      # Mutating: fix a bug / correct code
OP_CODE_CREATE  = "CODE_CREATE"   # Mutating: create a new file / class / function


class Intent(TypedDict):
    """Resultado de clasificación de intent."""
    domain: str                  # WORK|PRO_DIAG|FIN|REL|HEALTH|EIPROTA|ENERGY
    operation: str               # WORK_QUERY|WORK_CREATE|WORK_UPDATE|WORK_DELETE|FIN_EXPENSE|COMMAND
    type: str                    # Idea|Tarea|Reflexión|Proyecto|Ajuste
    cognitive_load: str          # Alta|Media|Baja
    impact: str                  # Estructural|Económico|Emocional|Intelectual|Operativo
    next_action: str             # string corto accionable
    confidence: float            # 0..1
    alternatives: list           # list[IntentAlternative]
    needs_confirmation: bool
    reason: str                  # debug info


class ClassifyResponse(TypedDict):
    """Response para POST /classify."""
    ok: bool
    intent: Optional[Intent]     # None si ok=False


# ---------------------------------------------------------------------------
# Layer 1: Chat Core Response (Deterministic)
# ---------------------------------------------------------------------------

class UIAction(TypedDict, total=False):
    """Action that UI should execute (confirm button, form, etc.)."""
    type: str               # "confirm" | "form" | "select"
    label: str              # Button/field label
    fields: list[str]       # For forms: list of field names
    options: list[str]      # For select: list of options
    values: dict[str, str]  # For forms: pre-filled field values (M27)


class ChatSession(TypedDict, total=False):
    """Session state for multi-turn flows."""
    pending_flow: Optional[str]   # Flow type if waiting for user input
    pending_data: dict[str, Any]  # Data for pending flow resolver
    context_id: str               # ID to pass on next turn
    last_domain: Optional[str]    # Last classified domain
    last_action_type: Optional[str]


class ChatAction(TypedDict, total=False):
    """
    Structured action sent by the frontend as first-class intent (M11+).

    Introduced in M11 on the frontend; M12 makes the backend process it
    explicitly instead of relying on text heuristics.

    Fields:
        type    — Intent identifier:
                  'confirm' | 'cancel' | 'select' | 'form_submit' |
                  'plan_item_execute' | 'chip'
        target  — trace_id of the originating assistant message (for
                  correlation; optional)
        id      — Item identifier / index (used by plan_item_execute)
        payload — Type-specific structured data:
                    confirm:           { choice: 'confirm' }
                    cancel:            { choice: 'cancel' }
                    select:            { choice: <selected_value> }
                    form_submit:       { field1: val1, field2: val2, ... }
                    plan_item_execute: PlanItem dict (monto, categoria, ...)
                    chip:              { text: <command_text> }
    """
    type: str
    target: Optional[str]
    id: Optional[str]
    payload: dict[str, Any]


class ChatCoreResponse(TypedDict):
    """
    Layer 1 output: Structured response from deterministic core.
    No natural language here - just structured data.
    """
    trace_id: str                    # Short UUID for request tracing (8 chars)
    domain: str                      # WORK|FIN|PRO_DIAG|...
    intent: str                      # query|add|confirm|cancel|UNKNOWN
    mode: str                        # chat|action|passthrough|answer
    needs_confirmation: bool         # True if user must confirm
    missing_fields: list[str]        # Fields that need clarification
    plan: list[dict[str, Any]]       # Items/actions to execute (FinItem, etc.)
    ui_actions: list[UIAction]       # Actions for UI to render
    session: ChatSession             # Session state for continuity
    audit: dict[str, Any]            # Debug/audit info


def _short_trace_id() -> str:
    """Generate short 8-char trace ID for logging."""
    return str(uuid.uuid4())[:8]


def make_chat_core_response(
    domain: str,
    intent: str,
    *,
    mode: str = "chat",
    needs_confirmation: bool = False,
    missing_fields: Optional[list[str]] = None,
    plan: Optional[list[dict[str, Any]]] = None,
    ui_actions: Optional[list[UIAction]] = None,
    session: Optional[ChatSession] = None,
    audit: Optional[dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> ChatCoreResponse:
    """Factory for ChatCoreResponse with sensible defaults."""
    return ChatCoreResponse(
        trace_id=trace_id or _short_trace_id(),
        domain=domain,
        intent=intent,
        mode=mode,
        needs_confirmation=needs_confirmation,
        missing_fields=missing_fields or [],
        plan=plan or [],
        ui_actions=ui_actions or [],
        session=session or ChatSession(context_id=new_context_id()),
        audit=audit or {},
    )


def make_chip_action(label: str, command: str) -> UIAction:
    """
    Create a UIAction chip for suggested commands.
    
    Uses the existing UIAction contract without modification:
    - type="chip" identifies this as a command suggestion
    - label is the display text
    - options[0] contains the command to send
    
    Frontend should check: if action.type == "chip", send options[0] as new message.
    
    Args:
        label: Display text for the chip (e.g., "⚡ NEXT")
        command: Command to send when clicked (e.g., "tareas status NEXT")
    
    Returns:
        UIAction with type="chip", label, and command in options[0]
    """
    return UIAction(
        type="chip",
        label=label,
        options=[command],
    )


# ---------------------------------------------------------------------------
# Plan-first Architecture: Interpreter → Confirm → Execute
# ---------------------------------------------------------------------------

# Action types (operations the system can perform)
ACTION_WORK_QUERY = "WORK_QUERY"          # Query tasks from Notion (read-only)
ACTION_WORK_CREATE = "WORK_CREATE"        # Create a new task in Notion (write)
ACTION_WORK_CREATE_TEST = "WORK_CREATE_TEST"  # Create task in test DB
ACTION_WORK_TEST_RESET = "WORK_TEST_RESET"    # Reset/wipe test DB tasks
ACTION_WORK_UPDATE = "WORK_UPDATE"        # Update existing task in Notion (single match)
ACTION_WORK_UPDATE_BULK = "WORK_UPDATE_BULK"  # Update multiple tasks in Notion (multiple matches)
ACTION_WORK_DELETE = "WORK_DELETE"        # Delete/archive tasks from work DB
ACTION_WORK_DELETE_TEST = "WORK_DELETE_TEST"  # Delete/archive tasks from test DB
ACTION_FIN_EXPENSE  = "FIN_EXPENSE"         # Register financial expense
ACTION_FIN_BATCH    = "FIN_BATCH"           # Register multiple expenses (batch)
ACTION_FIN_PLAN     = "FIN_PLAN"            # Generate fin plan from text (analysis-only)
ACTION_FIN_COMMIT   = "FIN_COMMIT"          # Commit (store) one expense to Sheets
ACTION_FIN_CONFIRM  = "FIN_CONFIRM"         # Confirm and store expense to Sheets
ACTION_FIN_CHAPERON = "FIN_CHAPERON"        # Run chaperon analysis on text
# CODE domain action constants
ACTION_CODE_EXPLAIN = "CODE_EXPLAIN"      # Explain / describe code (read-only)
ACTION_CODE_REVIEW  = "CODE_REVIEW"       # Review / audit code (read-only)
ACTION_CODE_FIX     = "CODE_FIX"          # Fix a bug (mutating: preview → confirm → apply)
ACTION_CODE_CREATE  = "CODE_CREATE"       # Create a new file / class / function (mutating)
ACTION_BASIC_COGNITIVE_EXECUTION = "BASIC_COGNITIVE_EXECUTION"  # Bounded cognitive worker dispatch
ACTION_COMMAND = "COMMAND"                # Generic prefixed command (CODE/DOC/JOBS/BIZ)
ACTION_CLASSIFY = "CLASSIFY"              # Classification only (no execution)
ACTION_UNKNOWN = "UNKNOWN"                # Unknown action
# HOST domain action constants (OpenClaw / host_launcher)
ACTION_HOST_OPEN_APP        = "HOST_OPEN_APP"        # Launch app from APP_REGISTRY
ACTION_HOST_CLOSE_PID       = "HOST_CLOSE_PID"       # SIGTERM a managed process
ACTION_HOST_OPEN_DIRECTORY  = "HOST_OPEN_DIRECTORY"  # Open allowed directory in explorer
ACTION_HOST_OPEN_URL        = "HOST_OPEN_URL"        # Open allowed URL (https only)
ACTION_HOST_LIST_DIRECTORY  = "HOST_LIST_DIRECTORY"  # List contents of allowed directory (read-only)
ACTION_HOST_OPEN_FILE       = "HOST_OPEN_FILE"       # Open file with default app (allowlisted ext)
ACTION_HOST_READ_TEXT_FILE   = "HOST_READ_TEXT_FILE"   # Read text file content (read-only, ≤1 MB)
# Phase 5A/5B — sandboxed write actions (require confirmation; never auto-execute)
ACTION_HOST_WRITE_TEXT_FILE  = "HOST_WRITE_TEXT_FILE"  # Write/create text file in write sandbox
ACTION_HOST_APPEND_TEXT_FILE = "HOST_APPEND_TEXT_FILE" # Append to existing text file in write sandbox
ACTION_HOST_CREATE_DIRECTORY = "HOST_CREATE_DIRECTORY" # Create single directory in write sandbox

# Target database constants
TARGET_DB_WORK = "work"                   # Main production work database
TARGET_DB_WORK_TEST = "work_test"         # Test database for UI/smoke tests
TARGET_DB_WORK_TRASH = "work_trash"       # Trash database for soft-deleted items

# Delete mode constants
DELETE_MODE_TRASH = "trash"               # Move to trash DB (soft delete)
DELETE_MODE_ARCHIVE = "archive"           # Archive in place (Notion archive)

# Risk levels
RISK_LOW = "low"        # Read-only, idempotent (auto-execute OK)
RISK_MEDIUM = "medium"  # Creates data, reversible (prompt once)
RISK_HIGH = "high"      # Destructive, irreversible (require explicit confirm)


class MutationPlan(TypedDict, total=False):
    """
    Structured payload for bulk/filtered mutation operations.

    Stored in Plan.filters for WORK_UPDATE_BULK and combined WORK_DELETE
    operations. Separates query criteria (filters) from mutation payload
    (changes) and encodes safety metadata.

    Fields:
        action      — ACTION_WORK_UPDATE_BULK, ACTION_WORK_DELETE, etc.
        filters     — Query criteria: {project?, status?, keywords?}
        changes     — Mutation payload: {status?, project?, domain?}
        requires_confirmation — Always True for mutations with N > 0 matches
        risk_level  — RISK_MEDIUM for N ≤ 10; RISK_HIGH for N > 10
        bulk        — True → "todas las tareas" mode (no keyword search)
        preview_items — Populated after find-matches: [{title, notion_page_id}]
    """
    action: str
    filters: dict
    changes: dict
    requires_confirmation: bool
    risk_level: str
    bulk: bool
    preview_items: list


class Plan(TypedDict, total=False):
    """
    Plan-first architecture: The Interpreter produces a Plan, not immediate execution.
    
    The Plan describes WHAT should happen, not HOW it happens.
    
    Flow:
    1. Interpreter: text → Plan (no side effects)
    2. Confirm: If requires_confirmation, return plan to UI for approval
    3. Execute (Kernel): Plan → side effects
    
    Auto-execute rules:
    - action=WORK_QUERY and risk_level=low → execute directly
    - requires_confirmation=True → return plan for user approval
    """
    # Required fields
    domain: str                     # Semantic domain: WORK|FIN|PRO_DIAG|REL|HEALTH|EIPROTA|ENERGY
    action: str                     # ACTION_* constant
    target: str                     # Human-readable target description
    
    # Execution control
    requires_confirmation: bool     # True if user must confirm before execution
    risk_level: str                 # RISK_* constant: low|medium|high
    
    # For display
    preview: str                    # Human-readable preview of what will happen
    
    # Idempotency
    idempotency_key: str            # UUID to prevent duplicate executions
    
    # Query/filter details
    filters: dict                   # Structured filters for queries
    
    # Audit/trace
    trace_id: str                   # Short trace ID for logging
    raw_text: str                   # Original user input

    # ExecutionPlan v1 identity fields
    plan_id: str                    # Stable UUID generated at plan creation. Never changes.
    schema_version: str             # Plan schema version. Fixed at "1" for v1.
    origin: str                     # "canonical" | "legacy_adapter". Source of plan creation.

    # Metadata
    confidence: float               # Classification confidence (0-1)
    alternatives: list              # Alternative interpretations

    # Domain-specific payload (CODE and future domains use this to carry
    # domain-specific data without polluting top-level Plan fields)
    domain_payload: dict            # Arbitrary domain data (e.g. CODE target_file, workspace, phase)


def make_plan(
    domain: str,
    action: str,
    target: str,
    *,
    requires_confirmation: bool = False,
    risk_level: str = RISK_MEDIUM,
    preview: str = "",
    filters: Optional[dict] = None,
    raw_text: str = "",
    confidence: float = 1.0,
    alternatives: Optional[list] = None,
    idempotency_key: Optional[str] = None,
    trace_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    origin: str = "canonical",
    target_db: Optional[str] = None,
    validation_error: Optional[str] = None,
) -> Plan:
    """
    Factory for Plan with sensible defaults.

    ExecutionPlan v1 fields always present:
      plan_id        — stable UUID, never changes after creation
      schema_version — "1" for v1; used by context_store loader to detect stale formats
      origin         — "canonical" (default) or "legacy_adapter"
      trace_id       — propagated from CanonicalRequest if provided, else auto-generated
    """
    plan = Plan(
        domain=domain,
        action=action,
        target=target,
        requires_confirmation=requires_confirmation,
        risk_level=risk_level,
        preview=preview or f"{action}: {target}",
        filters=filters or {},
        raw_text=raw_text,
        confidence=confidence,
        alternatives=alternatives or [],
        idempotency_key=idempotency_key or str(uuid.uuid4()),
        trace_id=trace_id or _short_trace_id(),
        # ExecutionPlan v1 identity
        plan_id=plan_id or str(uuid.uuid4()),
        schema_version="1",
        origin=origin,
    )
    if target_db is not None:
        plan["target_db"] = target_db
    if validation_error is not None:
        plan["validation_error"] = validation_error
    return plan


# Explicit whitelist of (action, risk_level) pairs that are safe to auto-execute.
#
# Using a whitelist rather than a generic "if risk == RISK_LOW" rule prevents
# future actions from being auto-executed just because they were incorrectly
# labeled as low-risk. Every action that should skip confirmation must be
# explicitly listed here with its expected risk level.
#
# Every entry here corresponds exactly to a case in _create_plan_from_intent
# where requires_confirmation=False is set intentionally for auto-execution.
# This whitelist is the single source of truth that PolicyDecision.execution_mode
# and should_auto_execute() both consult.
#
# Auto-execute rules:
#   WORK_QUERY / RISK_LOW    — read-only Notion query, no side effects
#   WORK_UPDATE / RISK_LOW   — Phase 1 is read-only preview; no mutation occurs
#   WORK_CREATE / RISK_MEDIUM — Post-confirmation: handler is called after user approval
#   WORK_DELETE / RISK_HIGH   — Post-confirmation: handler is called after user approval
#   FIN_EXPENSE / RISK_MEDIUM — single expense auto-executes per design intent
#   CODE_EXPLAIN / RISK_LOW  — read-only: no side effects
#   CODE_REVIEW / RISK_LOW   — read-only: no side effects
_AUTO_EXECUTE_WHITELIST: frozenset[tuple[str, str]] = frozenset({
    (ACTION_WORK_QUERY,    RISK_LOW),
    (ACTION_WORK_UPDATE,   RISK_LOW),     # Phase 1: read-only preview, no mutation side effects
    (ACTION_WORK_CREATE,   RISK_MEDIUM),  # Post-confirmation: user already approved
    (ACTION_WORK_DELETE,   RISK_HIGH),    # Post-confirmation: user already approved
    (ACTION_FIN_EXPENSE,   RISK_MEDIUM),  # Single expense auto-executes by design
    (ACTION_FIN_PLAN,      RISK_LOW),     # Analysis-only, no side effects
    (ACTION_FIN_CHAPERON,  RISK_LOW),     # Analysis-only, no side effects
    (ACTION_FIN_COMMIT,    RISK_MEDIUM),  # Post-confirmation: user already approved
    (ACTION_FIN_CONFIRM,   RISK_MEDIUM),  # Post-confirmation: user already approved
    (ACTION_FIN_BATCH,     RISK_MEDIUM),  # Post-confirmation batch store
    (ACTION_CODE_EXPLAIN,        RISK_LOW),    # Read-only: no side effects
    (ACTION_CODE_REVIEW,         RISK_LOW),    # Read-only: no side effects
    # HOST domain — read-only actions (no process launch, no side effects)
    (ACTION_HOST_LIST_DIRECTORY, RISK_LOW),    # Read-only directory scan
    (ACTION_HOST_READ_TEXT_FILE, RISK_LOW),    # Read-only file read
    # HOST domain — process-launching actions require explicit user confirmation
    # ACTION_HOST_OPEN_APP, ACTION_HOST_OPEN_DIRECTORY, ACTION_HOST_OPEN_URL,
    # ACTION_HOST_OPEN_FILE → RISK_MEDIUM, confirm required (not whitelisted)
    # ACTION_HOST_CLOSE_PID → RISK_MEDIUM, confirm required (not whitelisted)
    (ACTION_BASIC_COGNITIVE_EXECUTION, RISK_LOW),  # Bounded cognitive execution, no persistent mutation
})


def should_auto_execute(plan: Plan) -> bool:
    """
    Determine if a plan should auto-execute without confirmation.

    Rules:
    - requires_confirmation=True → never auto-execute (explicit override)
    - (action, risk_level) in _AUTO_EXECUTE_WHITELIST → auto-execute
    - everything else → require confirmation

    To add a new auto-executable action, add it to _AUTO_EXECUTE_WHITELIST
    above. Do NOT add a generic risk-level rule — whitelist only.
    """
    if plan.get("requires_confirmation", False):
        return False

    action = plan.get("action", "")
    risk = plan.get("risk_level", RISK_MEDIUM)

    return (action, risk) in _AUTO_EXECUTE_WHITELIST


# ---------------------------------------------------------------------------
# PolicyDecision v1
#
# Canonical intermediate contract between interpretation and plan creation.
# Produced by the interpretation layer (classifier + parser).
# Consumed exclusively by the planner (make_plan call site).
#
# Separation of concerns:
#   routing_action  → machine routing signal (ACTION_* constant)
#   ui_intent       → UI interaction label (never used for backend routing)
#   execution_mode  → canonical policy verdict (replaces scattered booleans)
# ---------------------------------------------------------------------------

# Execution mode constants — the canonical policy verdict.
EXECUTION_MODE_AUTO    = "auto"     # Safe to execute without user interaction
EXECUTION_MODE_CONFIRM = "confirm"  # Must present to user before execution
EXECUTION_MODE_CLARIFY = "clarify"  # Missing required info; ask user first
EXECUTION_MODE_BLOCKED = "blocked"  # Unsupported or invalid action


# Canonical ACTION_* → ui_intent mapping.
# This is the authoritative source for UI interaction labels.
# Backend routing NEVER reads this — it reads routing_action directly.
UI_INTENT_MAP: dict[str, str] = {
    ACTION_WORK_QUERY:       "query",
    ACTION_WORK_CREATE:      "create",
    ACTION_WORK_CREATE_TEST: "create",
    ACTION_WORK_UPDATE:      "update",
    ACTION_WORK_UPDATE_BULK: "bulk_update",
    ACTION_WORK_DELETE:      "delete",
    ACTION_WORK_DELETE_TEST: "delete",
    ACTION_WORK_TEST_RESET:  "delete",
    ACTION_FIN_EXPENSE:      "expense",
    ACTION_FIN_BATCH:        "expense",
    ACTION_FIN_PLAN:         "plan",
    ACTION_FIN_COMMIT:       "commit",
    ACTION_FIN_CONFIRM:      "confirm",
    ACTION_FIN_CHAPERON:     "chaperon",
    ACTION_CODE_EXPLAIN:         "explain",
    ACTION_CODE_REVIEW:          "review",
    ACTION_CODE_FIX:             "fix",
    ACTION_CODE_CREATE:          "create",
    ACTION_COMMAND:              "command",
    ACTION_CLASSIFY:             "classify",
    ACTION_UNKNOWN:              "unknown",
    # HOST domain
    ACTION_HOST_OPEN_APP:        "open_app",
    ACTION_HOST_CLOSE_PID:       "close_pid",
    ACTION_HOST_OPEN_DIRECTORY:  "open_directory",
    ACTION_HOST_OPEN_URL:        "open_url",
    ACTION_HOST_LIST_DIRECTORY:  "list_directory",
    ACTION_HOST_OPEN_FILE:       "open_file",
    ACTION_HOST_READ_TEXT_FILE:  "read_text_file",
    # Phase 5A/5B — sandboxed write
    ACTION_HOST_WRITE_TEXT_FILE:  "write_text_file",
    ACTION_HOST_APPEND_TEXT_FILE: "append_text_file",
    ACTION_HOST_CREATE_DIRECTORY: "create_directory",
    ACTION_BASIC_COGNITIVE_EXECUTION: "delegate",
}


def ui_intent_for_action(action: str) -> str:
    """Return the canonical UI intent label for a given ACTION_* constant."""
    return UI_INTENT_MAP.get(action, "unknown")


class PolicyDecision(TypedDict, total=False):
    """
    Canonical intermediate contract: interpretation layer → planner.

    The planner (make_plan call site) must only read PolicyDecision fields.
    It must not read raw classifier Intent, parser output, or session state.

    Key design decisions:
    - execution_mode is the canonical policy signal. No equivalent booleans.
    - routing_action and ui_intent are separate fields for separate consumers.
    - context_id, plan_id, idempotency_key do NOT belong here (planner concern).
    """
    # Core routing (required)
    trace_id: str               # Propagated from CanonicalRequest
    domain: str                 # WORK | FIN | CODE | DOC | UNKNOWN
    routing_action: str         # ACTION_* constant — authoritative for backend routing
    ui_intent: str              # "query"|"create"|"update"|... — for UI display only
    confidence: float           # Classifier confidence score (0.0–1.0)
    risk_level: str             # RISK_* constant
    execution_mode: str         # EXECUTION_MODE_* — canonical policy verdict

    # Payload (required)
    parsed_payload: dict        # Domain-specific parsed intent for the planner
    raw_text: str               # Original user utterance

    # Clarification (optional — only when execution_mode == "clarify")
    clarification_reason: Optional[str]   # "missing_required_field" | "ambiguous_target" | ...
    missing_fields: Optional[list[str]]   # Fields that prevented plan creation

    # Audit (optional)
    policy_explanation: Optional[str]     # Debug explanation of the policy verdict
    classifier_intent: Optional[str]      # Raw classifier operation field (audit only)


def determine_execution_mode(
    action: str,
    risk_level: str,
    requires_confirmation: bool,
    missing_fields: Optional[list[str]] = None,
) -> str:
    """
    Determine the canonical execution mode for a given action and policy state.

    Decision rules (in priority order):
    1. missing_fields present → "clarify" (cannot build a valid plan)
    2. (action, risk_level) in _AUTO_EXECUTE_WHITELIST → "auto"
    3. ACTION_UNKNOWN / ACTION_CLASSIFY / ACTION_COMMAND → "blocked"
       (no registered pipeline; fall through to plan_generated in orchestrator)
    4. requires_confirmation → "confirm"
    5. default → "confirm" (safe conservative fallback)

    This function is the single source of truth for execution_mode.
    It uses _AUTO_EXECUTE_WHITELIST directly to stay consistent with
    should_auto_execute(), which also reads the whitelist.
    """
    if missing_fields:
        return EXECUTION_MODE_CLARIFY

    if not requires_confirmation and (action, risk_level) in _AUTO_EXECUTE_WHITELIST:
        return EXECUTION_MODE_AUTO

    if action in (ACTION_UNKNOWN, ACTION_CLASSIFY, ACTION_COMMAND):
        return EXECUTION_MODE_BLOCKED

    return EXECUTION_MODE_CONFIRM


# ---------------------------------------------------------------------------
# DomainResult v1
#
# Canonical output contract produced by domain pipelines after execution.
# Sits between domain execution and the transport/rendering layer.
#
# Design principles (from spec):
#   - ok=True  → error is None. No exceptions.
#   - ok=False → error is a non-None ErrorDetail dict. No exceptions.
#   - data is always a dict (never None, never a list). Empty {} on failure.
#   - result_type is always a non-empty string (RESULT_TYPE_* constant).
#   - message is always a non-empty string.
#   - partial success (e.g. bulk with some failures) → ok=True, error=None,
#     details in data.failed_items.
#   - plan, context_id, ts, agent do NOT belong here (transport concerns).
# ---------------------------------------------------------------------------

# Canonical result_type strings for WORK domain.
# These are stable identifiers for domain outputs — distinct from the legacy
# "type" strings kept in output dicts for backward transport compatibility.
RESULT_TYPE_WORK_QUERY          = "work_query"           # Query results
RESULT_TYPE_WORK_CREATE         = "work_create"          # Create outcome
RESULT_TYPE_WORK_UPDATE         = "work_update"          # Singular update outcome
RESULT_TYPE_WORK_UPDATE_PREVIEW = "work_update_preview"  # Preview/proposal (all match counts)
RESULT_TYPE_WORK_UPDATE_BULK    = "work_update_bulk"     # Bulk execution outcome
RESULT_TYPE_WORK_DELETE         = "work_delete"          # Delete outcome

# Non-WORK domain result types
RESULT_TYPE_FIN_EXPENSE  = "fin_expense"   # FIN expense parse result
RESULT_TYPE_FIN_BATCH    = "fin_batch"     # FIN batch store result
RESULT_TYPE_FIN_PLAN     = "fin_plan"      # FIN plan analysis result
RESULT_TYPE_FIN_COMMIT   = "fin_commit"    # FIN commit (store) result
RESULT_TYPE_FIN_CONFIRM  = "fin_confirm"   # FIN confirm (store) result
RESULT_TYPE_FIN_CHAPERON = "fin_chaperon"  # FIN chaperon analysis result
RESULT_TYPE_PLAN_CONFIRMATION_REQUIRED = "plan_confirmation_required"  # Interpreter: awaiting user confirm
RESULT_TYPE_PLAN_GENERATED             = "plan_generated"           # Classifier: plan produced, no execution
RESULT_TYPE_CONFIRM_ERROR              = "confirm_error"            # Confirm path: plan not found or expired

# CODE domain result types
RESULT_TYPE_CODE_EXPLAIN = "code_explain"  # Read-only: code explanation
RESULT_TYPE_CODE_REVIEW  = "code_review"   # Read-only: code review / audit
RESULT_TYPE_CODE_PREVIEW = "code_preview"  # Mutating: change proposal preview (pre-confirm)
RESULT_TYPE_CODE_APPLY   = "code_apply"    # Mutating: change applied (post-confirm)
# HOST domain result types (OpenClaw)
RESULT_TYPE_HOST_ACTION  = "host_action"   # All HOST domain actions (action in data["action"])
RESULT_TYPE_COGNITIVE_EXECUTION = "cognitive_execution"  # Bounded cognitive worker result



class CodeProposalEnvelope(TypedDict, total=False):
    """
    Canonical proposal structure for CODE mutating previews.

    Produced by propose_change_tool, consumed by the confirm flow and
    apply_change_tool.  proposal_id is required for all mutations and
    must not be re-used (single-use enforcement in code_pipeline).
    """
    proposal_id: str            # UUID — single-use identifier
    action: str                 # ACTION_CODE_FIX | ACTION_CODE_CREATE
    summary: str                # Human-readable summary of the proposed change
    affected_files: list        # list[str] of relative file paths
    write_intent_summary: str   # "Creates X; modifies Y" — free-text summary
    patch_preview: str          # UI-safe diff (capped at 150 lines / 8 192 chars)
    patch_preview_truncated: bool  # True when patch_preview was trimmed from original
    risk_level: str             # RISK_LOW | RISK_MEDIUM | RISK_HIGH
    proposal_artifacts: dict    # Optional implementation metadata (operation_types, etc.)
    requires_confirmation: bool # Always True for mutations
    workspace_hash: str         # Integrity hash of workspace at proposal time
    allowed_write_scope: list   # Allowed relative file paths for this proposal


class DomainResult(TypedDict, total=False):
    """
    DomainResult v1: canonical output contract for domain pipelines.

    Produced after domain execution completes, consumed by:
    - summary renderer (summary.py)
    - transport wrapper (webhook_server → Response)
    - future orchestrator

    Invariants enforced by make_domain_result():
    - ok=True  → error is None
    - ok=False → error is a non-None ErrorDetail
    - data is always a dict (never None, empty {} on failure)
    - result_type is always a non-empty string
    - message is always a non-empty string
    """
    # Required canonical wrapper fields (enforced by make_domain_result)
    ok: bool                       # True if operation completed its primary intent
    result_type: str               # RESULT_TYPE_* constant — stable semantic discriminator
    domain: str                    # "WORK" | "FIN" | "KERNEL"
    message: str                   # Human-readable outcome (non-empty, always present)
    data: dict                     # Domain-specific payload (always a dict, {} on failure)
    error: Optional[ErrorDetail]   # Structured error: None on success, ErrorDetail on failure

    # Optional fields
    warnings: Optional[list]      # Non-fatal issues during execution
    trace_id: Optional[str]        # Propagated from ExecutionPlan for end-to-end tracing
    plan_id: Optional[str]         # plan_id from ExecutionPlan (audit link, not embedded plan)


def make_domain_result(
    ok: bool,
    result_type: str,
    domain: str,
    message: str,
    data: Optional[dict] = None,
    error: Optional[ErrorDetail] = None,
    warnings: Optional[list] = None,
    trace_id: Optional[str] = None,
    plan_id: Optional[str] = None,
) -> "DomainResult":
    """
    Factory for DomainResult with enforced invariants.

    Invariants enforced:
    - ok=True  → error forced to None (even if caller provides one)
    - ok=False → error must be an ErrorDetail dict (raises ValueError if missing)
    - data normalized to {} if None

    Args:
        ok:          True if operation completed its primary intent.
        result_type: RESULT_TYPE_* constant.
        domain:      Domain string ("WORK", "FIN", ...).
        message:     Human-readable outcome description (non-empty).
        data:        Domain-specific payload dict. None → {}.
        error:       ErrorDetail on failure. Must be provided when ok=False.
        warnings:    Optional list of non-fatal issue strings.
        trace_id:    Optional trace ID from ExecutionPlan.
        plan_id:     Optional plan_id from ExecutionPlan (audit link).

    Returns:
        DomainResult with all required fields populated and invariants satisfied.

    Raises:
        ValueError: If ok=False and error is None or not a dict.
    """
    if ok:
        error = None  # Invariant: ok=True → error must be None
    else:
        if not error or not isinstance(error, dict):
            raise ValueError(
                "make_domain_result: ok=False requires a non-None ErrorDetail dict"
            )

    dr: DomainResult = {
        "ok": ok,
        "result_type": result_type,
        "domain": domain,
        "message": message,
        "data": data if data is not None else {},
        "error": error,
    }
    if warnings is not None:
        dr["warnings"] = warnings
    if trace_id is not None:
        dr["trace_id"] = trace_id
    if plan_id is not None:
        dr["plan_id"] = plan_id
    return dr


# ---------------------------------------------------------------------------
# CanonicalRequest v1
#
# Normalized entry-point contract for raw user input.
# Produced once at the request boundary, before any classification or planning.
# All downstream consumers (classifier, parser, PolicyDecision) receive
# normalized fields — never raw HTTP body values directly.
# ---------------------------------------------------------------------------

class CanonicalRequest(TypedDict):
    """Normalized entry-point contract for all user inputs."""
    text: str        # Normalized user utterance (stripped, always str, never None)
    context_id: str  # Request context UUID (generated if absent)
    filters: dict    # Pre-parsed filter hints (always dict, {} if absent)
    metadata: dict   # Caller metadata (always dict, {} if absent)


def normalize_request(
    text: Optional[str] = None,
    context_id: Optional[str] = None,
    filters: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> "CanonicalRequest":
    """
    Normalize raw user input into a CanonicalRequest.

    Applies consistent normalization at the request boundary before any
    classification or planning:
    - text: stripped of leading/trailing whitespace; None → ""
    - context_id: generated if absent or blank
    - filters: any non-dict value → {}
    - metadata: any non-dict value → {}

    Args:
        text:       Raw user utterance (may be None or have surrounding whitespace)
        context_id: Optional request context ID; generated UUID4 if absent
        filters:    Optional pre-parsed filter hints
        metadata:   Optional caller metadata

    Returns:
        CanonicalRequest with all fields present and safe defaults applied.
    """
    return CanonicalRequest(
        text=(text or "").strip(),
        context_id=context_id if (context_id and isinstance(context_id, str)) else new_context_id(),
        filters=filters if isinstance(filters, dict) else {},
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def build_policy_decision(
    text: str,
    action: str,
    domain: str,
    risk_level: str,
    requires_confirmation: bool,
    confidence: float,
    *,
    classifier_intent: Optional[str] = None,
    parsed_payload: Optional[dict] = None,
    trace_id: Optional[str] = None,
    missing_fields: Optional[list[str]] = None,
    policy_explanation: Optional[str] = None,
) -> "PolicyDecision":
    """
    Build a PolicyDecision from interpretation layer outputs.

    This is the canonical factory for PolicyDecision in v1.
    Called after the classifier + parser have resolved action, domain,
    risk level, and payload. Before make_plan() is called.

    Args:
        text:                  Original user utterance
        action:                Resolved ACTION_* constant
        domain:                Domain string (WORK, FIN, ...)
        risk_level:            RISK_* constant
        requires_confirmation: Whether the action requires user confirmation
        confidence:            Classifier confidence (0.0–1.0)
        classifier_intent:     Raw classifier operation (for audit)
        parsed_payload:        Domain-specific parsed fields (becomes plan.filters in v1)
        trace_id:              Propagated trace ID from upstream request
        missing_fields:        Fields that could not be resolved (triggers "clarify")
        policy_explanation:    Optional debug explanation

    Returns:
        PolicyDecision with all required fields populated.
    """
    execution_mode = determine_execution_mode(
        action, risk_level, requires_confirmation, missing_fields
    )
    clarification_reason: Optional[str] = None
    if execution_mode == EXECUTION_MODE_CLARIFY:
        clarification_reason = "missing_required_field" if missing_fields else "low_confidence"

    pd: PolicyDecision = {
        "trace_id": trace_id or _short_trace_id(),
        "domain": domain,
        "routing_action": action,
        "ui_intent": ui_intent_for_action(action),
        "confidence": confidence,
        "risk_level": risk_level,
        "execution_mode": execution_mode,
        "parsed_payload": parsed_payload or {},
        "raw_text": text,
        "clarification_reason": clarification_reason,
        "missing_fields": missing_fields,
        "policy_explanation": policy_explanation,
        "classifier_intent": classifier_intent,
    }
    return pd

