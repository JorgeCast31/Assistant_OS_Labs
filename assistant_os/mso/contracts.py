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
class CapabilityRecord:
    """Initial capability authority record."""

    action: str
    domain: str
    mode: CapabilityMode
    allowed: bool = True
    notes: str = ""


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


@dataclass(slots=True)
class RiskEvaluation:
    """Rule-driven MSO risk evaluation."""

    level: RiskLevel
    reasons: list[GovernanceReason]
    base_risk: str
    recent_failure_count: int = 0
    anomaly_detected: bool = False


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
    effective_execution_mode: str
    risk_level: RiskLevel
    justification: str
    reasons: list[GovernanceReason]
    constraints: list[GovernanceConstraint]
    capability_mode: CapabilityMode
    base_execution_mode: str
    created_at: str


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
    advisory_trace: dict[str, Any] = field(default_factory=dict)
    decision_trace: dict[str, Any] = field(default_factory=dict)
    governance_trace: dict[str, Any] = field(default_factory=dict)
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
    active_tasks: list[TaskRecord]
    pending_tasks: list[TaskRecord]
    blocked_tasks: list[TaskRecord]
    recent_task_transitions: list[TaskTransition]
    recent_decisions: list[DeterministicDecisionTrace]
    recent_governance_decisions: list[GovernanceDecision]
    running_executions: list[str]
    domain_status_summary: list[DomainStatusSummary]
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
