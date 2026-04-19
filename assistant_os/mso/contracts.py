"""Typed contracts for the local LLM/MSO seam."""

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional, TypeAlias, TypedDict


class LocalLlmRequest(TypedDict, total=False):
    """Advisory request sent to the local LLM adapter."""

    task: str
    advisory_role: str
    text: str
    classifier_operation: str
    classifier_domain: str
    planned_action: str
    plan_preview: str
    metadata: dict[str, Any]


class LocalLlmAdvisory(TypedDict, total=False):
    """Raw structured advisory result from the local model."""

    reasoning_summary: str
    routing_hint: str
    suggested_domain: str
    suggested_action: str
    execution_posture_hint: str
    confidence_note: str
    code_task_summary: str
    repo_context: str
    constraints: list[str]
    expected_artifact: str
    risk_notes: list[str]


class LocalLlmResponse(TypedDict, total=False):
    """Non-fatal advisory call result."""

    status: str  # "disabled" | "ok" | "error"
    provider: str
    model: str
    advisory: LocalLlmAdvisory
    latency_ms: int
    error: Optional[str]


class LocalLlmStatus(TypedDict, total=False):
    """Reachability / probe result for the configured local provider."""

    enabled: bool
    provider: str
    base_url: str
    model: str
    reachable: bool
    model_available: bool
    roundtrip_ok: bool
    latency_ms: int
    error: Optional[str]


class AdvisorySummary(TypedDict, total=False):
    """Compact assistant-side interpretation."""

    text: str
    confidence_note: str


class RoutingHint(TypedDict, total=False):
    """Non-authoritative route/posture suggestion."""

    summary: str
    suggested_domain: str
    suggested_action: str
    execution_posture_hint: str
    confidence_note: str


class CodePackagingHint(TypedDict, total=False):
    """Optional CODE-focused packaging metadata."""

    task_summary: str
    repo_context: str
    constraints: list[str]
    expected_artifact: str
    risk_notes: list[str]


class OrchestratorAdvisory(TypedDict, total=False):
    """Structured advisory bundle normalized for orchestrator use."""

    consulted_roles: list[str]
    status: str
    provider: str
    model: str
    latency_ms: int
    error: Optional[str]
    summary: AdvisorySummary
    routing_hint: RoutingHint
    code_package: CodePackagingHint
    raw_advisory: LocalLlmAdvisory


class AdvisoryDecisionTrace(TypedDict, total=False):
    """Inspectable trace of advisory suggestion vs deterministic decision."""

    consulted: bool
    consulted_roles: list[str]
    status: str
    provider: str
    model: str
    latency_ms: int
    final_domain: str
    final_action: str
    final_execution_mode: str
    routing_hint_action: str
    routing_hint_domain: str
    reasoning_summary: str
    code_packaged: bool
    error: Optional[str]


TaskStatus = Literal["active", "pending", "completed", "failed", "blocked"]
RiskLevel = Literal["low", "medium", "high"]
GovernanceAction = Literal["ALLOW", "REQUIRE_CONFIRMATION", "BLOCK", "DEGRADE"]
CapabilityMode = Literal["allow", "confirm_only", "plan_only", "deny"]
OperationalMode = Literal["NORMAL", "RESTRICTED", "DEGRADED"]
AnomalySeverity = Literal["low", "medium", "high"]
ExecutionClass = Literal["BASIC_COGNITIVE_EXECUTION"]
RuntimeDecisionType = Literal["respond", "delegate", "execute_through_kernel", "persist_only", "reject"]
RestrictionStatus = Literal["ACTIVE", "EXPIRED", "CLEARED", "EXTENDED", "OVERRIDDEN"]
RestrictionType = Literal["REQUIRE_CONFIRMATION", "REVOKE_CAPABILITY"]
OperatorActionType = Literal["acknowledge_restriction", "clear_restriction", "extend_restriction", "override_restriction"]
OperatorRole = Literal["viewer", "reviewer", "admin"]
RestrictionReviewState = Literal["unreviewed", "acknowledged", "actioned"]
OperationalSignalSeverity = Literal["info", "warning", "critical"]
WorkerSecurityEventType = Literal[
    "os_hardening_applied",
    "worker_started",
    "worker_completed",
    "worker_timeout",
    "worker_crash",
    "worker_forced_kill",
    "invalid_input_ref",
    "scope_violation",
    "network_denied",
    "resource_limit_exceeded",
]
WorkerLifecycleState = Literal["starting", "running", "completed", "timeout", "crashed", "killed", "blocked"]


@dataclass(slots=True)
class DeterministicDecisionTrace:
    """Deterministic decision record emitted by the canonical orchestrator."""

    decision_ref: str
    context_id: str
    trace_id: str
    plan_id: str
    domain: str
    action: str
    execution_mode: str
    operation: str
    preview: str
    created_at: str
    advisory_trace_ref: str = ""
    governance_trace_ref: str = ""


@dataclass(slots=True)
class SovereignIntent:
    """Interpretive sovereign-layer intent. Never execution authority."""

    intent_id: str
    session_id: str
    user_request_ref: str
    interpreted_goal: str
    priority: str
    persistence_recommendation: str
    risk_posture_hint: str
    delegation_recommendation: str
    justification_summary: str
    timestamp: str


@dataclass(slots=True)
class DelegationTask:
    """Structured delegation payload for bounded worker execution."""

    task_id: str
    origin_intent_id: str
    task_type: ExecutionClass
    task_goal: str
    allowed_operations: list[str]
    input_refs: list[str]
    scope: dict[str, Any]
    requires_capability: str
    expected_output_schema: dict[str, Any]
    expiry: str
    trace_id: str


@dataclass(slots=True)
class ExecutionCapability:
    """Kernel-issued execution capability for bounded worker execution."""

    capability_id: str
    task_id: str
    execution_class: ExecutionClass
    allowed_operations: list[str]
    scope: dict[str, Any]
    issued_at: str
    expires_at: str
    issued_by: str
    trace_id: str


@dataclass(slots=True)
class ExecutionReport:
    """Worker execution output contract."""

    report_id: str
    task_id: str
    worker_id: str
    status: str
    operations_performed: list[str]
    artifacts: dict[str, Any]
    findings_summary: str
    confidence: float
    requires_escalation: bool
    trace_id: str
    completed_at: str


MachineOperatorStatus = Literal["ok", "partial", "failed", "aborted", "denied"]
MachineOperatorCapabilityTier = Literal["read_only", "interactive", "mutating"]
MachineOperatorApprovalMode = Literal["none", "required"]
MachineOperatorPolicyLevel = Literal["N0", "N1", "N2"]
MachineOperatorLaneOutcome = Literal[
    "invalid_request",
    "policy_violation",
    "backend_unavailable",
    "execution_aborted",
    "execution_partial",
    "execution_failed",
    "success",
]
MachineOperatorTransitionState = Literal[
    "requested",
    "invalid_request",
    "policy_violation",
    "backend_unavailable",
    "execution_aborted",
    "execution_partial",
    "execution_failed",
    "success",
]
MachineOperatorRequestKind = Literal["single_step", "workflow"]
MachineOperatorScalar: TypeAlias = None | bool | int | float | str
MachineOperatorValue: TypeAlias = (
    MachineOperatorScalar
    | list["MachineOperatorValue"]
    | dict[str, "MachineOperatorValue"]
)

CAPABILITY_BROWSER_NAVIGATE = "browser.navigate"
CAPABILITY_BROWSER_SNAPSHOT = "browser.snapshot"
CAPABILITY_BROWSER_SCREENSHOT = "browser.screenshot"
CAPABILITY_BROWSER_READ_VISIBLE_TEXT = "browser.read_visible_text"
MACHINE_OPERATOR_ALLOWED_CAPABILITIES: frozenset[str] = frozenset(
    {
        CAPABILITY_BROWSER_NAVIGATE,
        CAPABILITY_BROWSER_SNAPSHOT,
        CAPABILITY_BROWSER_SCREENSHOT,
        CAPABILITY_BROWSER_READ_VISIBLE_TEXT,
    }
)
MACHINE_OPERATOR_MAX_WORKFLOW_STEPS = 5

MACHINE_OPERATOR_STATE_REQUESTED = "requested"
MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST = "invalid_request"
MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION = "policy_violation"
MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE = "backend_unavailable"
MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED = "execution_aborted"
MACHINE_OPERATOR_OUTCOME_EXECUTION_PARTIAL = "execution_partial"
MACHINE_OPERATOR_OUTCOME_EXECUTION_FAILED = "execution_failed"
MACHINE_OPERATOR_OUTCOME_SUCCESS = "success"
MACHINE_OPERATOR_CANONICAL_OUTCOMES: frozenset[MachineOperatorLaneOutcome] = frozenset(
    {
        MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST,
        MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION,
        MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE,
        MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED,
        MACHINE_OPERATOR_OUTCOME_EXECUTION_PARTIAL,
        MACHINE_OPERATOR_OUTCOME_EXECUTION_FAILED,
        MACHINE_OPERATOR_OUTCOME_SUCCESS,
    }
)
MACHINE_OPERATOR_ALLOWED_STATE_TRANSITIONS: dict[
    MachineOperatorTransitionState,
    frozenset[MachineOperatorTransitionState],
] = {
    MACHINE_OPERATOR_STATE_REQUESTED: frozenset(MACHINE_OPERATOR_CANONICAL_OUTCOMES),
    MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST: frozenset(),
    MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION: frozenset(),
    MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE: frozenset(),
    MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED: frozenset(),
    MACHINE_OPERATOR_OUTCOME_EXECUTION_PARTIAL: frozenset(),
    MACHINE_OPERATOR_OUTCOME_EXECUTION_FAILED: frozenset(),
    MACHINE_OPERATOR_OUTCOME_SUCCESS: frozenset(),
}

_MACHINE_OPERATOR_STATUS_VALUES = {"ok", "partial", "failed", "aborted", "denied"}
_MACHINE_OPERATOR_CAPABILITY_TIER_VALUES = {"read_only", "interactive", "mutating"}
_MACHINE_OPERATOR_APPROVAL_MODE_VALUES = {"none", "required"}
_MACHINE_OPERATOR_POLICY_LEVEL_VALUES = {"N0", "N1", "N2"}
_MACHINE_OPERATOR_REQUEST_KIND_VALUES = {"single_step", "workflow"}
_MACHINE_OPERATOR_LEGACY_REQUEST_FIELDS = {
    "intent_id",
    "correlation_id",
    "capability_name",
    "capability_tier",
    "arguments",
    "policy_context",
    "budget",
    "requested_side_effects",
    "approval",
}
_MACHINE_OPERATOR_WORKFLOW_REQUEST_FIELDS = {
    "intent_id",
    "correlation_id",
    "workflow_steps",
    "policy_context",
    "budget",
    "requested_side_effects",
    "approval",
}
_MACHINE_OPERATOR_WORKFLOW_STEP_FIELDS = {
    "capability_name",
    "capability_tier",
    "arguments",
}
_MACHINE_OPERATOR_POLICY_CONTEXT_FIELDS = {
    "policy_decision_ref",
    "governance_ref",
    "execution_mode",
    "approval_mode",
    "constraints",
    "allowlist_refs",
    "secret_refs",
}
_MACHINE_OPERATOR_BUDGET_FIELDS = {
    "max_steps",
    "max_duration_ms",
    "max_output_bytes",
    "max_side_effects",
}
_MACHINE_OPERATOR_RESPONSE_FIELDS = {
    "intent_id",
    "correlation_id",
    "status",
    "observation",
    "evidence_refs",
    "consumed_budget",
    "side_effects_declared",
    "audit_event_ids",
}
_MACHINE_OPERATOR_WORKFLOW_RESPONSE_FIELDS = _MACHINE_OPERATOR_RESPONSE_FIELDS | {"step_results"}
_MACHINE_OPERATOR_WORKFLOW_STEP_RESULT_FIELDS = {
    "step_index",
    "capability_name",
    "capability_tier",
    "status",
    "lane_outcome",
    "backend_status",
    "backend_execution_attempted",
    "backend_execution_performed",
    "machine_action_performed",
    "observation",
    "evidence_refs",
    "consumed_budget",
    "side_effects_declared",
    "audit_event_ids",
}
_MACHINE_OPERATOR_OBSERVATION_FIELDS = {"summary", "detail", "structured_data"}
_MACHINE_OPERATOR_EVIDENCE_FIELDS = {
    "ref_id",
    "evidence_type",
    "uri",
    "description",
    "media_type",
    "digest",
}
_MACHINE_OPERATOR_BUDGET_USAGE_FIELDS = {
    "steps",
    "duration_ms",
    "output_bytes",
    "side_effects",
}
_MACHINE_OPERATOR_SIDE_EFFECT_FIELDS = {
    "effect_type",
    "target_domain",
    "description",
    "target_ref",
}
_MACHINE_OPERATOR_APPROVAL_REQUIRED_FIELDS = {
    "approval_id",
    "approved_for",
    "capability_scope",
    "expires_at",
    "issued_by",
}
_MACHINE_OPERATOR_APPROVAL_OPTIONAL_FIELDS = {"reason"}


def is_machine_operator_lane_outcome(value: str) -> bool:
    return value in MACHINE_OPERATOR_CANONICAL_OUTCOMES


def is_machine_operator_transition_allowed(
    source_state: MachineOperatorTransitionState,
    target_state: MachineOperatorTransitionState,
) -> bool:
    return target_state in MACHINE_OPERATOR_ALLOWED_STATE_TRANSITIONS.get(source_state, frozenset())


@dataclass(slots=True)
class MachineOperatorBudget:
    """Execution budget declared by the sovereign layer for MACHINE_OPERATOR work."""

    max_steps: int
    max_duration_ms: int
    max_output_bytes: int = 0
    max_side_effects: int = 0


@dataclass(slots=True)
class MachineOperatorBudgetUsage:
    """Observed budget consumption reported by a MACHINE_OPERATOR executor."""

    steps: int = 0
    duration_ms: int = 0
    output_bytes: int = 0
    side_effects: int = 0


@dataclass(slots=True)
class MachineOperatorEvidenceRef:
    """Backend-agnostic reference to supporting execution evidence."""

    ref_id: str
    evidence_type: str
    uri: str
    description: str = ""
    media_type: str = ""
    digest: str = ""


@dataclass(slots=True)
class MachineOperatorObservation:
    """Structured execution observation returned to the sovereign layer."""

    summary: str
    detail: str = ""
    structured_data: dict[str, MachineOperatorValue] = field(default_factory=dict)


@dataclass(slots=True)
class MachineOperatorPolicyContext:
    """Policy envelope attached to one MACHINE_OPERATOR intent."""

    policy_decision_ref: str
    governance_ref: str = ""
    execution_mode: str = ""
    approval_mode: MachineOperatorApprovalMode = "none"
    constraints: list[str] = field(default_factory=list)
    allowlist_refs: list[str] = field(default_factory=list)
    secret_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MachineOperatorApprovalArtifact:
    """Deterministic local approval artifact for guarded MACHINE_OPERATOR execution."""

    approval_id: str
    approved_for: MachineOperatorRequestKind
    capability_scope: list[str]
    expires_at: str
    issued_by: str
    reason: str = ""


@dataclass(slots=True)
class MachineOperatorCapabilityPolicy:
    """Static, backend-agnostic policy entry for one MACHINE_OPERATOR capability."""

    capability_name: str
    capability_tier: MachineOperatorCapabilityTier
    policy_level: MachineOperatorPolicyLevel
    approval_mode: MachineOperatorApprovalMode
    requires_allowlist: bool
    allows_side_effects: bool
    requires_secrets: bool
    max_steps: int
    max_duration_ms: int
    allowed_by_default: bool = True


@dataclass(slots=True)
class MachineOperatorSideEffectDeclaration:
    """Declared execution side effect, independent of backend wire semantics."""

    effect_type: str
    target_domain: str
    description: str
    target_ref: str = ""


@dataclass(slots=True)
class MachineOperatorIntentRequest:
    """Typed sovereign request issued toward the MACHINE_OPERATOR lane."""

    intent_id: str
    correlation_id: str
    capability_name: str
    capability_tier: MachineOperatorCapabilityTier
    arguments: dict[str, MachineOperatorValue]
    policy_context: MachineOperatorPolicyContext
    budget: MachineOperatorBudget
    requested_side_effects: list[str] = field(default_factory=list)
    approval: Optional[MachineOperatorApprovalArtifact] = None


@dataclass(slots=True)
class MachineOperatorWorkflowStep:
    """One deterministic step inside a bounded MACHINE_OPERATOR workflow."""

    capability_name: str
    capability_tier: MachineOperatorCapabilityTier
    arguments: dict[str, MachineOperatorValue]


@dataclass(slots=True)
class MachineOperatorWorkflowRequest:
    """Workflow extension for MACHINE_OPERATOR without replacing single-step requests."""

    intent_id: str
    correlation_id: str
    workflow_steps: list[MachineOperatorWorkflowStep]
    policy_context: MachineOperatorPolicyContext
    budget: MachineOperatorBudget
    requested_side_effects: list[str] = field(default_factory=list)
    approval: Optional[MachineOperatorApprovalArtifact] = None


@dataclass(slots=True)
class MachineOperatorIntentResponse:
    """Typed executor response returned from the MACHINE_OPERATOR lane."""

    intent_id: str
    correlation_id: str
    status: MachineOperatorStatus
    observation: MachineOperatorObservation
    evidence_refs: list[MachineOperatorEvidenceRef]
    consumed_budget: MachineOperatorBudgetUsage
    side_effects_declared: list[MachineOperatorSideEffectDeclaration]
    audit_event_ids: list[str]


@dataclass(slots=True)
class MachineOperatorWorkflowStepResult:
    """Canonical outcome for one workflow step."""

    step_index: int
    capability_name: str
    capability_tier: MachineOperatorCapabilityTier
    status: MachineOperatorStatus
    lane_outcome: MachineOperatorLaneOutcome
    backend_status: str
    backend_execution_attempted: bool
    backend_execution_performed: bool
    machine_action_performed: bool
    observation: MachineOperatorObservation
    evidence_refs: list[MachineOperatorEvidenceRef]
    consumed_budget: MachineOperatorBudgetUsage
    side_effects_declared: list[MachineOperatorSideEffectDeclaration]
    audit_event_ids: list[str]


@dataclass(slots=True)
class MachineOperatorWorkflowResponse:
    """Workflow response contract with explicit step-level outcomes."""

    intent_id: str
    correlation_id: str
    status: MachineOperatorStatus
    observation: MachineOperatorObservation
    evidence_refs: list[MachineOperatorEvidenceRef]
    consumed_budget: MachineOperatorBudgetUsage
    side_effects_declared: list[MachineOperatorSideEffectDeclaration]
    audit_event_ids: list[str]
    step_results: list[MachineOperatorWorkflowStepResult]


def _as_contract_dict(payload: Any, *, contract_name: str) -> tuple[dict[str, Any] | None, str]:
    if is_dataclass(payload):
        return asdict(payload), ""
    if isinstance(payload, dict):
        return payload, ""
    return None, f"{contract_name} must be a dict or dataclass instance"


def _validate_exact_fields(
    payload: dict[str, Any],
    *,
    field_names: set[str],
    contract_name: str,
) -> str:
    missing_fields = sorted(field_name for field_name in field_names if field_name not in payload)
    if missing_fields:
        return f"{contract_name} is missing required fields: {missing_fields}"

    unknown_fields = sorted(field_name for field_name in payload if field_name not in field_names)
    if unknown_fields:
        return f"{contract_name} contains unknown fields: {unknown_fields}"

    return ""


def _validate_structured_fields(
    payload: dict[str, Any],
    *,
    required_fields: set[str],
    optional_fields: set[str],
    contract_name: str,
) -> str:
    missing_fields = sorted(field_name for field_name in required_fields if field_name not in payload)
    if missing_fields:
        return f"{contract_name} is missing required fields: {missing_fields}"

    allowed_fields = required_fields | optional_fields
    unknown_fields = sorted(field_name for field_name in payload if field_name not in allowed_fields)
    if unknown_fields:
        return f"{contract_name} contains unknown fields: {unknown_fields}"
    return ""


def _validate_non_empty_str(payload: dict[str, Any], field_name: str, contract_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        return f"{contract_name} field '{field_name}' must be a non-empty string"
    return ""


def _validate_str(payload: dict[str, Any], field_name: str, contract_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str):
        return f"{contract_name} field '{field_name}' must be a string"
    return ""


def _validate_non_negative_int(payload: dict[str, Any], field_name: str, contract_name: str) -> str:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return f"{contract_name} field '{field_name}' must be a non-negative integer"
    return ""


def _validate_bool(payload: dict[str, Any], field_name: str, contract_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, bool):
        return f"{contract_name} field '{field_name}' must be a bool"
    return ""


def _is_machine_operator_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_machine_operator_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and bool(key.strip()) and _is_machine_operator_value(item)
            for key, item in value.items()
        )
    return False


def _validate_json_object(payload: Any, *, field_name: str, contract_name: str) -> str:
    if not isinstance(payload, dict):
        return f"{contract_name} field '{field_name}' must be a dict[str, MachineOperatorValue]"
    for key, value in payload.items():
        if not isinstance(key, str) or not key.strip():
            return f"{contract_name} field '{field_name}' must use non-empty string keys"
        if not _is_machine_operator_value(value):
            return (
                f"{contract_name} field '{field_name}' must contain only "
                "JSON-like scalar/list/dict values"
            )
    return ""


def _validate_string_list(payload: Any, *, field_name: str, contract_name: str) -> str:
    if not isinstance(payload, list) or any(not isinstance(item, str) or not item.strip() for item in payload):
        return f"{contract_name} field '{field_name}' must be a list[str]"
    return ""


def parse_machine_operator_approval_expiry(value: str) -> tuple[datetime | None, str]:
    if not isinstance(value, str) or not value.strip():
        return None, "MachineOperatorApprovalArtifact field 'expires_at' must be a non-empty string"

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        return None, (
            "MachineOperatorApprovalArtifact field 'expires_at' must be an ISO-8601 timestamp: "
            f"{exc}"
        )

    if parsed.tzinfo is None:
        return None, "MachineOperatorApprovalArtifact field 'expires_at' must include a timezone offset"
    return parsed.astimezone(timezone.utc), ""


def _validate_approval_dict(approval: Any) -> str:
    if not isinstance(approval, dict):
        return "MachineOperatorApprovalArtifact must be a dict"

    error = _validate_structured_fields(
        approval,
        required_fields=_MACHINE_OPERATOR_APPROVAL_REQUIRED_FIELDS,
        optional_fields=_MACHINE_OPERATOR_APPROVAL_OPTIONAL_FIELDS,
        contract_name="MachineOperatorApprovalArtifact",
    )
    if error:
        return error

    for field_name in ("approval_id", "expires_at", "issued_by"):
        error = _validate_non_empty_str(approval, field_name, "MachineOperatorApprovalArtifact")
        if error:
            return error

    approved_for = approval.get("approved_for")
    if approved_for not in _MACHINE_OPERATOR_REQUEST_KIND_VALUES:
        return (
            "MachineOperatorApprovalArtifact field 'approved_for' must be one of "
            f"{sorted(_MACHINE_OPERATOR_REQUEST_KIND_VALUES)}"
        )

    error = _validate_string_list(
        approval.get("capability_scope"),
        field_name="capability_scope",
        contract_name="MachineOperatorApprovalArtifact",
    )
    if error:
        return error
    if not approval["capability_scope"]:
        return "MachineOperatorApprovalArtifact field 'capability_scope' must be a non-empty list[str]"

    if "reason" in approval:
        error = _validate_str(approval, "reason", "MachineOperatorApprovalArtifact")
        if error:
            return error

    _, error = parse_machine_operator_approval_expiry(str(approval["expires_at"]))
    if error:
        return error
    return ""


def normalize_machine_operator_approval(payload: Any) -> tuple[dict[str, Any] | None, str]:
    if payload is None:
        return None, ""

    approval, error = _as_contract_dict(payload, contract_name="MachineOperatorApprovalArtifact")
    if approval is None:
        return None, error

    error = _validate_approval_dict(approval)
    if error:
        return None, error

    return (
        {
            "approval_id": str(approval["approval_id"]).strip(),
            "approved_for": str(approval["approved_for"]),
            "capability_scope": [str(item).strip() for item in approval["capability_scope"]],
            "expires_at": str(approval["expires_at"]).strip(),
            "issued_by": str(approval["issued_by"]).strip(),
            "reason": str(approval.get("reason", "")).strip(),
        },
        "",
    )


def _validate_optional_approval(payload: Any, *, contract_name: str) -> str:
    _, error = normalize_machine_operator_approval(payload)
    if error:
        return f"{contract_name} field 'approval' is invalid: {error}"
    return ""


def _validate_policy_context_dict(policy_context: Any, *, contract_name: str) -> str:
    if not isinstance(policy_context, dict):
        return f"{contract_name} field 'policy_context' must be a dict"

    error = _validate_exact_fields(
        policy_context,
        field_names=_MACHINE_OPERATOR_POLICY_CONTEXT_FIELDS,
        contract_name="MachineOperatorPolicyContext",
    )
    if error:
        return error

    error = _validate_non_empty_str(policy_context, "policy_decision_ref", "MachineOperatorPolicyContext")
    if error:
        return error

    for field_name in ("governance_ref", "execution_mode"):
        error = _validate_str(policy_context, field_name, "MachineOperatorPolicyContext")
        if error:
            return error

    approval_mode = policy_context.get("approval_mode")
    if approval_mode not in _MACHINE_OPERATOR_APPROVAL_MODE_VALUES:
        return (
            "MachineOperatorPolicyContext field 'approval_mode' must be one of "
            f"{sorted(_MACHINE_OPERATOR_APPROVAL_MODE_VALUES)}"
        )

    for field_name in ("constraints", "allowlist_refs", "secret_refs"):
        error = _validate_string_list(
            policy_context.get(field_name),
            field_name=field_name,
            contract_name="MachineOperatorPolicyContext",
        )
        if error:
            return error
    return ""


def _validate_budget_dict(budget: Any, *, contract_name: str) -> str:
    if not isinstance(budget, dict):
        return f"{contract_name} field 'budget' must be a dict"

    error = _validate_exact_fields(
        budget,
        field_names=_MACHINE_OPERATOR_BUDGET_FIELDS,
        contract_name="MachineOperatorBudget",
    )
    if error:
        return error

    for field_name in ("max_steps", "max_duration_ms", "max_output_bytes", "max_side_effects"):
        error = _validate_non_negative_int(budget, field_name, "MachineOperatorBudget")
        if error:
            return error

    if budget["max_steps"] <= 0:
        return "MachineOperatorBudget field 'max_steps' must be greater than zero"
    if budget["max_duration_ms"] <= 0:
        return "MachineOperatorBudget field 'max_duration_ms' must be greater than zero"
    return ""


def _validate_observation_dict(observation: Any, *, contract_name: str) -> str:
    if not isinstance(observation, dict):
        return f"{contract_name} field 'observation' must be a dict"

    error = _validate_exact_fields(
        observation,
        field_names=_MACHINE_OPERATOR_OBSERVATION_FIELDS,
        contract_name="MachineOperatorObservation",
    )
    if error:
        return error

    error = _validate_non_empty_str(observation, "summary", "MachineOperatorObservation")
    if error:
        return error

    error = _validate_str(observation, "detail", "MachineOperatorObservation")
    if error:
        return error

    return _validate_json_object(
        observation.get("structured_data"),
        field_name="structured_data",
        contract_name="MachineOperatorObservation",
    )


def _validate_evidence_refs(evidence_refs: Any, *, contract_name: str) -> str:
    if not isinstance(evidence_refs, list):
        return f"{contract_name} field 'evidence_refs' must be a list"
    for evidence in evidence_refs:
        if not isinstance(evidence, dict):
            return "MachineOperatorEvidenceRef entries must be dicts"
        error = _validate_exact_fields(
            evidence,
            field_names=_MACHINE_OPERATOR_EVIDENCE_FIELDS,
            contract_name="MachineOperatorEvidenceRef",
        )
        if error:
            return error
        for field_name in ("ref_id", "evidence_type", "uri"):
            error = _validate_non_empty_str(evidence, field_name, "MachineOperatorEvidenceRef")
            if error:
                return error
        for field_name in ("description", "media_type", "digest"):
            error = _validate_str(evidence, field_name, "MachineOperatorEvidenceRef")
            if error:
                return error
    return ""


def _validate_consumed_budget(consumed_budget: Any, *, contract_name: str) -> str:
    if not isinstance(consumed_budget, dict):
        return f"{contract_name} field 'consumed_budget' must be a dict"
    error = _validate_exact_fields(
        consumed_budget,
        field_names=_MACHINE_OPERATOR_BUDGET_USAGE_FIELDS,
        contract_name="MachineOperatorBudgetUsage",
    )
    if error:
        return error
    for field_name in ("steps", "duration_ms", "output_bytes", "side_effects"):
        error = _validate_non_negative_int(consumed_budget, field_name, "MachineOperatorBudgetUsage")
        if error:
            return error
    return ""


def _validate_side_effects(side_effects: Any, *, contract_name: str) -> str:
    if not isinstance(side_effects, list):
        return f"{contract_name} field 'side_effects_declared' must be a list"
    for side_effect in side_effects:
        if not isinstance(side_effect, dict):
            return "MachineOperatorSideEffectDeclaration entries must be dicts"
        error = _validate_exact_fields(
            side_effect,
            field_names=_MACHINE_OPERATOR_SIDE_EFFECT_FIELDS,
            contract_name="MachineOperatorSideEffectDeclaration",
        )
        if error:
            return error
        for field_name in ("effect_type", "target_domain", "description"):
            error = _validate_non_empty_str(side_effect, field_name, "MachineOperatorSideEffectDeclaration")
            if error:
                return error
        error = _validate_str(side_effect, "target_ref", "MachineOperatorSideEffectDeclaration")
        if error:
            return error
    return ""


def machine_operator_request_kind(payload: Any) -> MachineOperatorRequestKind:
    request, _ = _as_contract_dict(payload, contract_name="MachineOperatorIntentRequest")
    if isinstance(request, dict) and "workflow_steps" in request:
        return "workflow"
    return "single_step"


def normalize_machine_operator_request(payload: Any) -> tuple[dict[str, Any] | None, str]:
    request, error = _as_contract_dict(payload, contract_name="MachineOperatorIntentRequest")
    if request is None:
        return None, error

    approval, error = normalize_machine_operator_approval(request.get("approval"))
    if error:
        return None, error

    if "workflow_steps" in request:
        normalized_request = dict(request)
        normalized_request["approval"] = approval
        return normalized_request, ""

    legacy_error = _validate_exact_fields(
        request,
        field_names=_MACHINE_OPERATOR_LEGACY_REQUEST_FIELDS,
        contract_name="MachineOperatorIntentRequest",
    )
    if legacy_error:
        return None, legacy_error

    arguments = request.get("arguments")
    if not isinstance(arguments, dict):
        return None, "MachineOperatorIntentRequest field 'arguments' must be a dict[str, MachineOperatorValue]"

    policy_context = request.get("policy_context")
    if not isinstance(policy_context, dict):
        return None, "MachineOperatorIntentRequest field 'policy_context' must be a dict"

    budget = request.get("budget")
    if not isinstance(budget, dict):
        return None, "MachineOperatorIntentRequest field 'budget' must be a dict"

    requested_side_effects = request.get("requested_side_effects")
    if not isinstance(requested_side_effects, list):
        return None, "MachineOperatorIntentRequest field 'requested_side_effects' must be a list[str]"

    return (
        {
            "intent_id": request["intent_id"],
            "correlation_id": request["correlation_id"],
            "workflow_steps": [
                {
                    "capability_name": request["capability_name"],
                    "capability_tier": request["capability_tier"],
                    "arguments": dict(arguments),
                }
            ],
            "policy_context": dict(policy_context),
            "budget": dict(budget),
            "requested_side_effects": list(requested_side_effects),
            "approval": approval,
        },
        "",
    )


def machine_operator_request_capabilities(payload: Any) -> list[str]:
    request, error = normalize_machine_operator_request(payload)
    if request is None:
        raise ValueError(error)
    return [str(step["capability_name"]) for step in request["workflow_steps"]]


def machine_operator_request_step_count(payload: Any) -> int:
    return len(machine_operator_request_capabilities(payload))


def machine_operator_request_capability_name(payload: Any) -> str:
    capabilities = machine_operator_request_capabilities(payload)
    if machine_operator_request_kind(payload) == "single_step":
        return capabilities[0]
    if len(capabilities) == 1:
        return capabilities[0]
    return "workflow:" + "->".join(capabilities)


def machine_operator_request_capability_tier(payload: Any) -> MachineOperatorCapabilityTier:
    request, error = normalize_machine_operator_request(payload)
    if request is None:
        raise ValueError(error)
    tiers = {str(step["capability_tier"]) for step in request["workflow_steps"]}
    if "mutating" in tiers:
        return "mutating"
    if "interactive" in tiers:
        return "interactive"
    return "read_only"


def _validate_single_step_request(request: dict[str, Any]) -> tuple[bool, str]:
    error = _validate_exact_fields(
        request,
        field_names=_MACHINE_OPERATOR_LEGACY_REQUEST_FIELDS,
        contract_name="MachineOperatorIntentRequest",
    )
    if error:
        return False, error

    for field_name in ("intent_id", "correlation_id", "capability_name"):
        error = _validate_non_empty_str(request, field_name, "MachineOperatorIntentRequest")
        if error:
            return False, error

    capability_tier = request.get("capability_tier")
    if capability_tier not in _MACHINE_OPERATOR_CAPABILITY_TIER_VALUES:
        return False, (
            "MachineOperatorIntentRequest field 'capability_tier' must be one of "
            f"{sorted(_MACHINE_OPERATOR_CAPABILITY_TIER_VALUES)}"
        )

    error = _validate_json_object(
        request.get("arguments"),
        field_name="arguments",
        contract_name="MachineOperatorIntentRequest",
    )
    if error:
        return False, error

    error = _validate_policy_context_dict(request.get("policy_context"), contract_name="MachineOperatorIntentRequest")
    if error:
        return False, error

    error = _validate_optional_approval(
        request.get("approval"),
        contract_name="MachineOperatorIntentRequest",
    )
    if error:
        return False, error

    error = _validate_string_list(
        request.get("requested_side_effects"),
        field_name="requested_side_effects",
        contract_name="MachineOperatorIntentRequest",
    )
    if error:
        return False, error

    error = _validate_budget_dict(request.get("budget"), contract_name="MachineOperatorIntentRequest")
    if error:
        return False, error

    if len(request["requested_side_effects"]) > request["budget"]["max_side_effects"]:
        return False, (
            "MachineOperatorIntentRequest requested_side_effects cannot exceed "
            "MachineOperatorBudget.max_side_effects"
        )
    return True, ""


def _validate_workflow_step(
    workflow_step: Any,
    *,
    step_index: int,
) -> tuple[bool, str]:
    if not isinstance(workflow_step, dict):
        return False, f"MachineOperatorWorkflowStep at index {step_index} must be a dict"

    error = _validate_exact_fields(
        workflow_step,
        field_names=_MACHINE_OPERATOR_WORKFLOW_STEP_FIELDS,
        contract_name="MachineOperatorWorkflowStep",
    )
    if error:
        return False, error

    error = _validate_non_empty_str(workflow_step, "capability_name", "MachineOperatorWorkflowStep")
    if error:
        return False, error

    if workflow_step["capability_name"] not in MACHINE_OPERATOR_ALLOWED_CAPABILITIES:
        return False, (
            "MachineOperatorWorkflowStep field 'capability_name' must be one of "
            f"{sorted(MACHINE_OPERATOR_ALLOWED_CAPABILITIES)}"
        )

    capability_tier = workflow_step.get("capability_tier")
    if capability_tier not in _MACHINE_OPERATOR_CAPABILITY_TIER_VALUES:
        return False, (
            "MachineOperatorWorkflowStep field 'capability_tier' must be one of "
            f"{sorted(_MACHINE_OPERATOR_CAPABILITY_TIER_VALUES)}"
        )

    error = _validate_json_object(
        workflow_step.get("arguments"),
        field_name="arguments",
        contract_name="MachineOperatorWorkflowStep",
    )
    if error:
        return False, error
    return True, ""


def _validate_workflow_request(request: dict[str, Any]) -> tuple[bool, str]:
    error = _validate_exact_fields(
        request,
        field_names=_MACHINE_OPERATOR_WORKFLOW_REQUEST_FIELDS,
        contract_name="MachineOperatorWorkflowRequest",
    )
    if error:
        return False, error

    for field_name in ("intent_id", "correlation_id"):
        error = _validate_non_empty_str(request, field_name, "MachineOperatorWorkflowRequest")
        if error:
            return False, error

    workflow_steps = request.get("workflow_steps")
    if not isinstance(workflow_steps, list) or not workflow_steps:
        return False, "MachineOperatorWorkflowRequest field 'workflow_steps' must be a non-empty list"
    if len(workflow_steps) > MACHINE_OPERATOR_MAX_WORKFLOW_STEPS:
        return False, (
            "MachineOperatorWorkflowRequest field 'workflow_steps' exceeds the explicit workflow limit "
            f"of {MACHINE_OPERATOR_MAX_WORKFLOW_STEPS}"
        )
    for step_index, workflow_step in enumerate(workflow_steps):
        ok, error = _validate_workflow_step(workflow_step, step_index=step_index)
        if not ok:
            return False, error

    error = _validate_policy_context_dict(
        request.get("policy_context"),
        contract_name="MachineOperatorWorkflowRequest",
    )
    if error:
        return False, error

    error = _validate_optional_approval(
        request.get("approval"),
        contract_name="MachineOperatorWorkflowRequest",
    )
    if error:
        return False, error

    error = _validate_string_list(
        request.get("requested_side_effects"),
        field_name="requested_side_effects",
        contract_name="MachineOperatorWorkflowRequest",
    )
    if error:
        return False, error

    error = _validate_budget_dict(request.get("budget"), contract_name="MachineOperatorWorkflowRequest")
    if error:
        return False, error

    if len(workflow_steps) > request["budget"]["max_steps"]:
        return False, (
            "MachineOperatorWorkflowRequest workflow_steps cannot exceed "
            "MachineOperatorBudget.max_steps"
        )
    if len(request["requested_side_effects"]) > request["budget"]["max_side_effects"]:
        return False, (
            "MachineOperatorWorkflowRequest requested_side_effects cannot exceed "
            "MachineOperatorBudget.max_side_effects"
        )
    return True, ""


def validate_machine_operator_request(payload: Any) -> tuple[bool, str]:
    """Validate single-step or workflow MACHINE_OPERATOR requests."""

    request, error = _as_contract_dict(payload, contract_name="MachineOperatorIntentRequest")
    if request is None:
        return False, error
    if "workflow_steps" in request:
        return _validate_workflow_request(request)
    return _validate_single_step_request(request)


def _validate_response_common(
    response: dict[str, Any],
    *,
    contract_name: str,
    field_names: set[str],
) -> tuple[bool, str]:
    error = _validate_exact_fields(
        response,
        field_names=field_names,
        contract_name=contract_name,
    )
    if error:
        return False, error

    for field_name in ("intent_id", "correlation_id"):
        error = _validate_non_empty_str(response, field_name, contract_name)
        if error:
            return False, error

    status = response.get("status")
    if status not in _MACHINE_OPERATOR_STATUS_VALUES:
        return False, (
            f"{contract_name} field 'status' must be one of "
            f"{sorted(_MACHINE_OPERATOR_STATUS_VALUES)}"
        )

    error = _validate_observation_dict(response.get("observation"), contract_name=contract_name)
    if error:
        return False, error

    error = _validate_evidence_refs(response.get("evidence_refs"), contract_name=contract_name)
    if error:
        return False, error

    error = _validate_consumed_budget(response.get("consumed_budget"), contract_name=contract_name)
    if error:
        return False, error

    error = _validate_side_effects(response.get("side_effects_declared"), contract_name=contract_name)
    if error:
        return False, error

    error = _validate_string_list(
        response.get("audit_event_ids"),
        field_name="audit_event_ids",
        contract_name=contract_name,
    )
    if error:
        return False, error

    consumed_budget = response["consumed_budget"]
    side_effects = response["side_effects_declared"]
    if consumed_budget["side_effects"] < len(side_effects):
        return False, (
            "MachineOperatorBudgetUsage field 'side_effects' cannot be less than the number "
            "of declared side effects"
        )
    return True, ""


def _validate_workflow_step_result(step_result: Any, *, expected_index: int) -> tuple[bool, str]:
    if not isinstance(step_result, dict):
        return False, "MachineOperatorWorkflowStepResult entries must be dicts"

    error = _validate_exact_fields(
        step_result,
        field_names=_MACHINE_OPERATOR_WORKFLOW_STEP_RESULT_FIELDS,
        contract_name="MachineOperatorWorkflowStepResult",
    )
    if error:
        return False, error

    error = _validate_non_negative_int(step_result, "step_index", "MachineOperatorWorkflowStepResult")
    if error:
        return False, error
    if step_result["step_index"] != expected_index:
        return False, "MachineOperatorWorkflowStepResult step_index values must be contiguous from zero"

    error = _validate_non_empty_str(step_result, "capability_name", "MachineOperatorWorkflowStepResult")
    if error:
        return False, error
    if step_result["capability_name"] not in MACHINE_OPERATOR_ALLOWED_CAPABILITIES:
        return False, (
            "MachineOperatorWorkflowStepResult field 'capability_name' must be one of "
            f"{sorted(MACHINE_OPERATOR_ALLOWED_CAPABILITIES)}"
        )

    capability_tier = step_result.get("capability_tier")
    if capability_tier not in _MACHINE_OPERATOR_CAPABILITY_TIER_VALUES:
        return False, (
            "MachineOperatorWorkflowStepResult field 'capability_tier' must be one of "
            f"{sorted(_MACHINE_OPERATOR_CAPABILITY_TIER_VALUES)}"
        )

    status = step_result.get("status")
    if status not in _MACHINE_OPERATOR_STATUS_VALUES:
        return False, (
            "MachineOperatorWorkflowStepResult field 'status' must be one of "
            f"{sorted(_MACHINE_OPERATOR_STATUS_VALUES)}"
        )

    if not is_machine_operator_lane_outcome(str(step_result.get("lane_outcome", ""))):
        return False, "MachineOperatorWorkflowStepResult field 'lane_outcome' must be canonical"

    error = _validate_non_empty_str(step_result, "backend_status", "MachineOperatorWorkflowStepResult")
    if error:
        return False, error

    for field_name in (
        "backend_execution_attempted",
        "backend_execution_performed",
        "machine_action_performed",
    ):
        error = _validate_bool(step_result, field_name, "MachineOperatorWorkflowStepResult")
        if error:
            return False, error

    error = _validate_observation_dict(
        step_result.get("observation"),
        contract_name="MachineOperatorWorkflowStepResult",
    )
    if error:
        return False, error

    error = _validate_evidence_refs(
        step_result.get("evidence_refs"),
        contract_name="MachineOperatorWorkflowStepResult",
    )
    if error:
        return False, error

    error = _validate_consumed_budget(
        step_result.get("consumed_budget"),
        contract_name="MachineOperatorWorkflowStepResult",
    )
    if error:
        return False, error

    error = _validate_side_effects(
        step_result.get("side_effects_declared"),
        contract_name="MachineOperatorWorkflowStepResult",
    )
    if error:
        return False, error

    error = _validate_string_list(
        step_result.get("audit_event_ids"),
        field_name="audit_event_ids",
        contract_name="MachineOperatorWorkflowStepResult",
    )
    if error:
        return False, error
    return True, ""


def validate_machine_operator_response(payload: Any) -> tuple[bool, str]:
    """Validate single-step or workflow MACHINE_OPERATOR responses."""

    response, error = _as_contract_dict(payload, contract_name="MachineOperatorIntentResponse")
    if response is None:
        return False, error

    if "step_results" not in response:
        return _validate_response_common(
            response,
            contract_name="MachineOperatorIntentResponse",
            field_names=_MACHINE_OPERATOR_RESPONSE_FIELDS,
        )

    ok, error = _validate_response_common(
        response,
        contract_name="MachineOperatorWorkflowResponse",
        field_names=_MACHINE_OPERATOR_WORKFLOW_RESPONSE_FIELDS,
    )
    if not ok:
        return False, error

    step_results = response.get("step_results")
    if not isinstance(step_results, list):
        return False, "MachineOperatorWorkflowResponse field 'step_results' must be a list"
    if len(step_results) > MACHINE_OPERATOR_MAX_WORKFLOW_STEPS:
        return False, (
            "MachineOperatorWorkflowResponse field 'step_results' exceeds the explicit workflow limit "
            f"of {MACHINE_OPERATOR_MAX_WORKFLOW_STEPS}"
        )

    for expected_index, step_result in enumerate(step_results):
        ok, error = _validate_workflow_step_result(step_result, expected_index=expected_index)
        if not ok:
            return False, error
    return True, ""


@dataclass(slots=True)
class WorkerExecutionLimits:
    """Explicit execution limits applied to a bounded worker task."""

    timeout_ms: int
    max_operations: int
    max_input_refs: int
    max_artifact_count: int
    max_artifact_bytes: int
    single_flight: bool = True


@dataclass(slots=True)
class WorkerScopeValidationResult:
    """Inspectable outcome of worker scope/input validation."""

    allowed: bool
    reason_code: str
    detail: str
    normalized_refs: list[str] = field(default_factory=list)
    rejected_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkerSecurityEvent:
    """Structured security-relevant worker event."""

    event_id: str
    task_id: str
    trace_id: str
    worker_id: str
    event_type: WorkerSecurityEventType
    lifecycle_state: WorkerLifecycleState
    detail: str
    created_at: str
    severity: AnomalySeverity = "low"
    process_id: int = 0
    scope_ref: str = ""
    limit_name: str = ""
    count_within_window: int = 1
    response_triggered: bool = False


@dataclass(slots=True)
class SecurityResponseRecord:
    """Threshold-based security response emitted by MSO hardening."""

    response_id: str
    source: str
    event_type: WorkerSecurityEventType
    action: str
    detail: str
    created_at: str
    count_within_window: int
    window_seconds: int
    target_domain: str = "COGNITIVE"
    target_action: str = ""
    expires_at: str = ""
    restriction_id: str = ""


@dataclass(slots=True)
class ActiveRestriction:
    """Explicit active or historical restriction record."""

    restriction_id: str
    type: RestrictionType
    target: str
    scope: dict[str, Any]
    source_events: list[str]
    created_at: str
    expires_at: str
    status: RestrictionStatus
    reason: str
    trace_id: str
    response_id: str = ""
    enforcement_kind: str = ""
    enforcement_ref: str = ""
    last_transition_at: str = ""
    last_transition_reason: str = ""
    review_state: RestrictionReviewState = "unreviewed"
    reviewed_at: str = ""
    reviewed_by: str = ""
    actioned_at: str = ""
    actioned_by: str = ""
    allow_override: bool = True


@dataclass(slots=True)
class OperatorIdentity:
    """Minimal operator identity used for governed admin access."""

    operator_id: str
    role: OperatorRole
    is_active: bool
    created_at: str
    last_used_at: str = ""


@dataclass(slots=True)
class OperatorAuthToken:
    """Opaque operator auth token metadata persisted by the control plane."""

    token_id: str
    operator_id: str
    issued_at: str
    expires_at: str
    is_active: bool
    token_hash: str = ""
    last_used_at: str = ""
    revoked_at: str = ""
    revoked_by: str = ""
    rotated_from: str = ""
    rotation_reason: str = ""
    issued_reason: str = ""


@dataclass(slots=True)
class OperatorContext:
    """Per-request authenticated operator context for admin operations."""

    operator_id: str
    role: OperatorRole
    token_id: str
    request_id: str
    authenticated_at: str


@dataclass(slots=True)
class ControlPlaneRequest:
    """Structured request handed from the control plane to governed admin services."""

    request_id: str
    operator_context: OperatorContext
    action: str
    payload: dict[str, Any]
    created_at: str


@dataclass(slots=True)
class ControlPlaneBootstrapRecord:
    """Traceable bootstrap record for initial operator/control-plane setup."""

    bootstrap_id: str
    operator_id: str
    role: OperatorRole
    token_id: str
    created_at: str
    expires_at: str
    reason: str
    request_id: str


@dataclass(slots=True)
class MaintenanceActionRecord:
    """Traceable control-plane maintenance action or run."""

    action_id: str
    action_type: str
    trigger: str
    created_at: str
    status: str
    trace_id: str = ""
    operator_id: str = ""
    request_id: str = ""
    detail: str = ""
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OperationalSignal:
    """Structured operational signal for control-plane maintenance issues."""

    signal_id: str
    source: str
    severity: OperationalSignalSeverity
    code: str
    detail: str
    created_at: str
    related_action_id: str = ""
    trace_id: str = ""
    status: str = "OPEN"


@dataclass(slots=True)
class OperatorActionRecord:
    """Traceable operator action over a restriction lifecycle."""

    action_id: str
    operator_id: str
    operator_role: OperatorRole
    action_type: OperatorActionType
    target_restriction_id: str
    reason: str
    timestamp: str
    trace_id: str
    token_id: str = ""
    request_id: str = ""
    result_status: str = ""
    notes: str = ""


@dataclass(slots=True)
class EscalationRequest:
    """Worker request for additional authority. Never self-approved."""

    escalation_id: str
    task_id: str
    worker_id: str
    requested_capability: str
    requested_scope: dict[str, Any]
    reason: str
    current_limit_hit: str
    trace_id: str
    timestamp: str


@dataclass(slots=True)
class TranslatorRejection:
    """Typed record for deterministic translator rejection."""

    rejection_id: str
    intent_id: str
    session_id: str
    trace_id: str
    reason_code: str
    message: str
    original_text: str
    created_at: str


@dataclass(slots=True)
class SovereignCycleRecord:
    """Bookkeeping record for one sovereign runtime cycle."""

    cycle_id: str
    session_id: str
    intent_id: str
    user_request_ref: str
    decision_type: RuntimeDecisionType
    created_at: str
    interpreted_goal: str
    translator_status: str
    canonical_context_id: str = ""
    canonical_action: str = ""
    canonical_domain: str = ""
    plan_id: str = ""
    trace_id: str = ""
    delegation_task_id: str = ""
    translator_rejection_ref: str = ""
    persistence_recommendation: str = ""
    notes: str = ""
    persistence_refs: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class GovernanceReason:
    """Inspectable reason used by MSO governance."""

    code: str
    detail: str


@dataclass(slots=True)
class GovernanceConstraint:
    """Constraint or degradation note imposed by governance."""

    kind: str
    value: str


@dataclass(slots=True)
class GovernanceIntervention:
    """Explicit adaptive intervention applied by MSO governance."""

    kind: str
    value: str
    reason: str = ""


@dataclass(slots=True)
class CapabilityScope:
    """Optional scope boundary for a capability override."""

    domain: str
    action: str = "*"
    scope_id: str = ""
    notes: str = ""


@dataclass(slots=True)
class CapabilityRecord:
    """Initial capability authority record."""

    action: str
    domain: str
    mode: CapabilityMode
    allowed: bool = True
    notes: str = ""


@dataclass(slots=True)
class CapabilityGrant:
    """Temporary capability grant layered over static capability policy."""

    grant_id: str
    action: str
    domain: str
    mode: CapabilityMode
    created_at: str
    reason: str
    expires_at: str = ""
    scope: CapabilityScope | None = None
    granted_by: str = "mso"


@dataclass(slots=True)
class CapabilityRevocation:
    """Explicit capability revocation layered over static capability policy."""

    revocation_id: str
    action: str
    domain: str
    created_at: str
    reason: str
    scope: CapabilityScope | None = None
    revoked_by: str = "mso"
    expires_at: str = ""


@dataclass(slots=True)
class CapabilityCheckResult:
    """Outcome of a capability authority lookup."""

    action: str
    domain: str
    allowed: bool
    mode: CapabilityMode
    requires_confirmation: bool
    deny_reason: str = ""
    notes: str = ""
    source: str = "static"
    is_temporary: bool = False
    is_revoked: bool = False
    scope: CapabilityScope | None = None
    expires_at: str = ""


@dataclass(slots=True)
class AnomalySignal:
    """Deterministic anomaly signal derived from observable system state."""

    signal_id: str
    code: str
    severity: AnomalySeverity
    detail: str
    created_at: str
    domain: str = ""
    target_action: str = ""
    recommended_mode: OperationalMode = "NORMAL"
    recommended_intervention: str = ""


@dataclass(slots=True)
class RiskEvaluation:
    """Rule-driven MSO risk evaluation."""

    level: RiskLevel
    reasons: list[GovernanceReason]
    base_risk: str
    recent_failure_count: int = 0
    anomaly_detected: bool = False
    operational_mode: OperationalMode = "NORMAL"
    anomaly_signals: list[AnomalySignal] = field(default_factory=list)


@dataclass(slots=True)
class TaskRecord:
    """Internal MSO task registry record."""

    task_id: str
    context_id: str
    trace_id: str
    plan_id: str
    domain: str
    status: TaskStatus
    created_at: str
    updated_at: str
    last_known_action: str
    request_text: str = ""
    execution_mode: str = ""
    started_at: str = ""
    completed_at: str = ""
    execution_id: str = ""
    result_type: str = ""
    advisory_trace_ref: str = ""
    decision_trace_ref: str = ""
    governance_trace_ref: str = ""
    error_type: str = ""
    error_message: str = ""


@dataclass(slots=True)
class GovernanceDecision:
    """Final governance outcome applied over the base deterministic policy."""

    governance_ref: str
    action: GovernanceAction
    target_domain: str
    target_action: str
    effective_execution_mode: str
    risk_level: RiskLevel
    justification: str
    reasons: list[GovernanceReason]
    constraints: list[GovernanceConstraint]
    interventions: list[GovernanceIntervention]
    capability_mode: CapabilityMode
    base_execution_mode: str
    operational_mode: OperationalMode
    created_at: str
    capability_source: str = "static"
    anomaly_signals: list[AnomalySignal] = field(default_factory=list)
    dynamic_factors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaskTransition:
    """Status transition event for a tracked task."""

    transition_id: str
    task_id: str
    at: str
    to_status: TaskStatus
    from_status: str = ""
    domain: str = ""
    action: str = ""
    reason: str = ""
    trace_id: str = ""
    plan_id: str = ""


@dataclass(slots=True)
class TraceChain:
    """Unified request -> advisory -> decision -> execution -> result chain."""

    chain_id: str
    task_id: str
    context_id: str
    trace_id: str
    plan_id: str
    request_text: str
    operation: str
    domain: str
    action: str
    execution_mode: str
    created_at: str
    advisory_trace_ref: str = ""
    decision_trace_ref: str = ""
    governance_trace_ref: str = ""
    sovereign_cycle_ref: str = ""
    sovereign_intent_ref: str = ""
    delegation_task_ref: str = ""
    execution_capability_ref: str = ""
    execution_report_ref: str = ""
    escalation_request_ref: str = ""
    worker_security_event_refs: list[str] = field(default_factory=list)
    advisory_trace: dict[str, Any] = field(default_factory=dict)
    decision_trace: dict[str, Any] = field(default_factory=dict)
    governance_trace: dict[str, Any] = field(default_factory=dict)
    sovereign_cycle: dict[str, Any] = field(default_factory=dict)
    sovereign_intent: dict[str, Any] = field(default_factory=dict)
    delegation_task: dict[str, Any] = field(default_factory=dict)
    execution_capability: dict[str, Any] = field(default_factory=dict)
    execution_report: dict[str, Any] = field(default_factory=dict)
    escalation_request: dict[str, Any] = field(default_factory=dict)
    worker_security_events: list[dict[str, Any]] = field(default_factory=list)
    persistence_refs: dict[str, str] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DomainStatusSummary:
    """Aggregated per-domain task status counts."""

    domain: str
    active: int = 0
    pending: int = 0
    completed: int = 0
    failed: int = 0
    blocked: int = 0


@dataclass(slots=True)
class DomainOperationalState:
    """Derived domain-level operational posture."""

    domain: str
    mode: OperationalMode
    hardened: bool = False
    active_anomaly_count: int = 0
    notes: str = ""


@dataclass(slots=True)
class AgentStatusSummary:
    """Minimal, extensible component status model."""

    agent_name: str
    status: str
    active_tasks: int
    notes: str = ""


@dataclass(slots=True)
class SystemStateSnapshot:
    """Structured current-state snapshot for internal MSO governance."""

    generated_at: str
    operational_mode: OperationalMode
    operational_mode_reason: str
    operational_mode_source: str
    active_tasks: list[TaskRecord]
    pending_tasks: list[TaskRecord]
    blocked_tasks: list[TaskRecord]
    recent_task_transitions: list[TaskTransition]
    recent_decisions: list[DeterministicDecisionTrace]
    recent_governance_decisions: list[GovernanceDecision]
    recent_anomaly_signals: list[AnomalySignal]
    recent_worker_security_events: list[WorkerSecurityEvent]
    active_capability_grants: list[CapabilityGrant]
    active_capability_revocations: list[CapabilityRevocation]
    running_executions: list[str]
    domain_status_summary: list[DomainStatusSummary]
    domain_operational_states: list[DomainOperationalState]
    agent_status_summary: list[AgentStatusSummary]
    trace_chain_refs: list[str]


@dataclass(slots=True)
class GovernanceSummary:
    """Minimal MSO-facing read model."""

    generated_at: str
    active_count: int
    pending_count: int
    blocked_count: int
    failed_recent_count: int
    active_task_ids: list[str]
    pending_task_ids: list[str]
    recent_failure_task_ids: list[str]
    current_state: str
    operational_mode: OperationalMode = "NORMAL"
    active_revocation_count: int = 0
    active_grant_count: int = 0
    recent_anomaly_count: int = 0
    hardened_domains: list[str] = field(default_factory=list)
