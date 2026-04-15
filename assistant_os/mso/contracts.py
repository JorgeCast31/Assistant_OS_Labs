"""Typed contracts for the local LLM/MSO seam."""

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, TypedDict


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
