"""
Backend-agnostic adapter boundary for the MACHINE_OPERATOR lane.

Sprint 5 introduces the first real execution path behind this boundary for the
approved Tier A browser capabilities only. Backend transport remains sealed
inside this module; the pipeline and sovereign contracts stay implementation-
independent.
"""

from __future__ import annotations

import json
import posixpath
import re
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Protocol
from urllib.parse import unquote, urlparse, urlunparse

try:
    import requests
except ImportError:  # pragma: no cover - dependency guard
    requests = None  # type: ignore[assignment]

from .. import config
from .contracts import (
    MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE,
    MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED,
    MACHINE_OPERATOR_OUTCOME_EXECUTION_FAILED,
    MACHINE_OPERATOR_OUTCOME_EXECUTION_PARTIAL,
    MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST,
    MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION,
    MACHINE_OPERATOR_OUTCOME_SUCCESS,
    MACHINE_OPERATOR_STATE_REQUESTED,
    MachineOperatorBudgetUsage,
    MachineOperatorEvidenceRef,
    MachineOperatorObservation,
    MachineOperatorSideEffectDeclaration,
    is_machine_operator_transition_allowed,
)
from .machine_operator_audit import (
    MachineOperatorAuditEventType,
    emit_machine_operator_event,
)
from .machine_operator_policy import (
    CAPABILITY_BROWSER_NAVIGATE,
    CAPABILITY_BROWSER_READ_VISIBLE_TEXT,
    CAPABILITY_BROWSER_SCREENSHOT,
    CAPABILITY_BROWSER_SNAPSHOT,
    enforce_machine_operator_request,
)

_SUPPORTED_REAL_CAPABILITIES = frozenset(
    {
        CAPABILITY_BROWSER_NAVIGATE,
        CAPABILITY_BROWSER_SNAPSHOT,
        CAPABILITY_BROWSER_SCREENSHOT,
        CAPABILITY_BROWSER_READ_VISIBLE_TEXT,
    }
)
_SUPPORTED_URL_SCHEMES = frozenset({"http", "https"})
_FORBIDDEN_ESCAPES = ("%2f", "%5c", "%00")
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9a-fA-F]{2}")
_BACKEND_STATE_HEALTHY = "HEALTHY"
_BACKEND_STATE_DEGRADED = "DEGRADED"
_BACKEND_STATE_UNAVAILABLE = "UNAVAILABLE"
_BACKEND_UNAVAILABLE_FAILURE_THRESHOLD = 2
_BACKEND_UNAVAILABLE_COOLDOWN_SECONDS = 30.0


@dataclass(slots=True)
class MachineOperatorAdapterContext:
    """Execution context passed from the canonical pipeline into the adapter."""

    plan_id: str
    execution_id: str
    trace_id: str
    policy_decision_ref: str
    capability_name: str
    capability_tier: str
    policy_reason_code: str
    policy_message: str


@dataclass(slots=True)
class MachineOperatorAdapterResult:
    """Structured adapter result returned to the canonical pipeline."""

    status: str
    observation: MachineOperatorObservation
    evidence_refs: list[MachineOperatorEvidenceRef]
    consumed_budget: MachineOperatorBudgetUsage = field(default_factory=MachineOperatorBudgetUsage)
    side_effects_declared: list[MachineOperatorSideEffectDeclaration] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    audit_event_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _CanonicalUrl:
    scheme: str
    hostname: str
    port: int
    path: str
    query: str = ""

    @property
    def origin(self) -> str:
        default_port = _default_port_for_scheme(self.scheme)
        if self.port == default_port:
            return f"{self.scheme}://{self.hostname}"
        return f"{self.scheme}://{self.hostname}:{self.port}"

    @property
    def normalized_url(self) -> str:
        return urlunparse((self.scheme, self._netloc(), self.path, "", self.query, ""))

    def _netloc(self) -> str:
        default_port = _default_port_for_scheme(self.scheme)
        if self.port == default_port:
            return self.hostname
        return f"{self.hostname}:{self.port}"


@dataclass(frozen=True, slots=True)
class _AllowlistRule:
    schemes: frozenset[str]
    hostname: str
    ports: frozenset[int]
    path_prefix: str


@dataclass(slots=True)
class _BackendHealthState:
    state: str = _BACKEND_STATE_HEALTHY
    consecutive_failures: int = 0
    last_success_timestamp: float = 0.0
    last_failure_timestamp: float = 0.0


class MachineOperatorAdapter(Protocol):
    """Backend-agnostic execution boundary for the MACHINE_OPERATOR lane."""

    def execute(
        self,
        request: Any,
        context: MachineOperatorAdapterContext,
    ) -> MachineOperatorAdapterResult: ...


class StubMachineOperatorAdapter:
    """
    Non-executing fallback adapter implementation.

    This remains available for tests and explicit fallback use, but Sprint 5
    binds the live-capable adapter by default.
    """

    def execute(
        self,
        request: Any,
        context: MachineOperatorAdapterContext,
    ) -> MachineOperatorAdapterResult:
        request_dict = _coerce_request_dict(request)
        audit_event_ids = _emit_base_audit_events(request_dict, context)
        audit_event_ids.extend(
            [
                emit_machine_operator_event(
                    event_type=MachineOperatorAuditEventType.MO_BACKEND_UNAVAILABLE,
                    plan_id=context.plan_id,
                    execution_id=context.execution_id,
                    trace_id=context.trace_id,
                    intent_id=request_dict["intent_id"],
                    correlation_id=request_dict["correlation_id"],
                    capability_name=request_dict["capability_name"],
                    status="backend_unavailable",
                    detail="No MACHINE_OPERATOR backend is configured.",
                ),
                emit_machine_operator_event(
                    event_type=MachineOperatorAuditEventType.MO_EXECUTION_SKIPPED,
                    plan_id=context.plan_id,
                    execution_id=context.execution_id,
                    trace_id=context.trace_id,
                    intent_id=request_dict["intent_id"],
                    correlation_id=request_dict["correlation_id"],
                    capability_name=request_dict["capability_name"],
                    status="skipped",
                    detail="Execution was intentionally skipped; no machine action occurred.",
                ),
                emit_machine_operator_event(
                    event_type=MachineOperatorAuditEventType.MO_ABORTED,
                    plan_id=context.plan_id,
                    execution_id=context.execution_id,
                    trace_id=context.trace_id,
                    intent_id=request_dict["intent_id"],
                    correlation_id=request_dict["correlation_id"],
                    capability_name=request_dict["capability_name"],
                    status="aborted",
                    detail="Request aborted because no backend execution path exists.",
                ),
            ]
        )
        return _finalize_terminal_result(
            result=_build_nonexecuted_result(
                status="aborted",
                summary="MACHINE_OPERATOR adapter reached; backend unavailable.",
                detail="No real machine or browser action was performed.",
                metadata={
                    "lane_outcome": MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE,
                    "backend_status": "unavailable",
                    "backend_execution_attempted": False,
                    "backend_execution_performed": False,
                    "machine_action_performed": False,
                    "adapter_status": "backend_unavailable",
                },
                audit_event_ids=audit_event_ids,
            ),
            request_dict=request_dict,
            context=context,
            audit_event_ids=audit_event_ids,
        )


class OpenClawGatewayMachineOperatorAdapter:
    """
    Live-capable Tier A adapter for the MACHINE_OPERATOR lane.

    The adapter seals all OpenClaw transport details behind a narrow boundary.
    It executes one ephemeral request at a time, with strict timeout handling
    and fail-closed validation around URL allowlisting and no-side-effect rules.
    No reusable session handle or persistent browser profile is retained across
    requests; Sprint 7 makes that lifecycle explicit in terminal metadata/audit.
    """

    def __init__(self) -> None:
        self._backend_health = _BackendHealthState()

    def reset_backend_health(self) -> None:
        self._backend_health = _BackendHealthState()

    def execute(
        self,
        request: Any,
        context: MachineOperatorAdapterContext,
    ) -> MachineOperatorAdapterResult:
        request_dict = _coerce_request_dict(request)
        audit_event_ids = _emit_base_audit_events(request_dict, context)
        consistency_result = _validate_context_consistency(
            request_dict=request_dict,
            context=context,
            audit_event_ids=audit_event_ids,
        )
        if consistency_result is not None:
            return consistency_result

        governance_result = _validate_execution_governance(
            request_dict=request_dict,
            context=context,
            audit_event_ids=audit_event_ids,
        )
        if governance_result is not None:
            return governance_result

        if _abort_requested(request_dict):
            audit_event_ids.extend(
                _emit_terminal_events(
                    request_dict,
                    context,
                    status=MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED,
                    detail="MACHINE_OPERATOR execution was aborted before backend dispatch.",
                    include_skipped=True,
                    include_aborted=True,
                )
            )
            return _finalize_terminal_result(
                result=_build_nonexecuted_result(
                    status="aborted",
                    summary="MACHINE_OPERATOR execution aborted before backend dispatch.",
                    detail="Abort was requested locally for the MACHINE_OPERATOR lane.",
                    metadata={
                        "lane_outcome": MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED,
                        "backend_status": "aborted",
                        "backend_execution_attempted": False,
                        "backend_execution_performed": False,
                        "machine_action_performed": False,
                        "adapter_status": "aborted",
                    },
                    audit_event_ids=audit_event_ids,
                ),
                request_dict=request_dict,
                context=context,
                audit_event_ids=audit_event_ids,
            )
        return _execute_request(
            request_dict=request_dict,
            context=context,
            audit_event_ids=audit_event_ids,
            health_state=self._backend_health,
        )


DEFAULT_MACHINE_OPERATOR_ADAPTER: MachineOperatorAdapter = OpenClawGatewayMachineOperatorAdapter()


def execute_machine_operator(
    request: Any,
    context: MachineOperatorAdapterContext,
) -> MachineOperatorAdapterResult:
    """Execute the default MACHINE_OPERATOR adapter boundary."""
    return DEFAULT_MACHINE_OPERATOR_ADAPTER.execute(request, context)


def reset_machine_operator_backend_health() -> None:
    if isinstance(DEFAULT_MACHINE_OPERATOR_ADAPTER, OpenClawGatewayMachineOperatorAdapter):
        DEFAULT_MACHINE_OPERATOR_ADAPTER.reset_backend_health()


def _execute_request(
    *,
    request_dict: dict[str, Any],
    context: MachineOperatorAdapterContext,
    audit_event_ids: list[str],
    health_state: _BackendHealthState,
) -> MachineOperatorAdapterResult:
    return _execute_step_request(
        request_dict=request_dict,
        context=context,
        audit_event_ids=audit_event_ids,
        health_state=health_state,
    )


def _execute_step_request(
    *,
    request_dict: dict[str, Any],
    context: MachineOperatorAdapterContext,
    audit_event_ids: list[str],
    health_state: _BackendHealthState,
) -> MachineOperatorAdapterResult:
    capability_name = request_dict["capability_name"]
    if capability_name not in _SUPPORTED_REAL_CAPABILITIES:
        audit_event_ids.extend(
            _emit_terminal_events(
                request_dict,
                context,
                status=MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED,
                detail=f"MACHINE_OPERATOR capability is not implemented for live execution: {capability_name}",
                include_skipped=True,
                include_aborted=True,
            )
        )
        return _finalize_terminal_result(
            result=_build_nonexecuted_result(
                status="aborted",
                summary="MACHINE_OPERATOR capability is not implemented for live execution.",
                detail=f"Capability remains non-executing in Sprint 5: {capability_name}",
                metadata={
                    "lane_outcome": MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED,
                    "backend_status": "unsupported_capability",
                    "backend_execution_attempted": False,
                    "backend_execution_performed": False,
                    "machine_action_performed": False,
                    "adapter_status": "unsupported_capability",
                },
                audit_event_ids=audit_event_ids,
            ),
            request_dict=request_dict,
            context=context,
            audit_event_ids=audit_event_ids,
        )

    probe_allowed = False
    if health_state.state == _BACKEND_STATE_UNAVAILABLE:
        if _cooldown_elapsed(health_state):
            probe_allowed = True
        else:
            detail = "MACHINE_OPERATOR backend circuit is open; execution was blocked before gateway dispatch."
            audit_event_ids.append(
                emit_machine_operator_event(
                    event_type=MachineOperatorAuditEventType.MO_BACKEND_UNAVAILABLE,
                    plan_id=context.plan_id,
                    execution_id=context.execution_id,
                    trace_id=context.trace_id,
                    intent_id=request_dict["intent_id"],
                    correlation_id=request_dict["correlation_id"],
                    capability_name=capability_name,
                    status=MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE,
                    detail=detail,
                    backend_state=health_state.state,
                )
            )
            return _finalize_terminal_result(
                result=_build_nonexecuted_result(
                    status="aborted",
                    summary="MACHINE_OPERATOR backend circuit is open.",
                    detail=detail,
                    metadata={
                        "lane_outcome": MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE,
                        "backend_status": "unavailable",
                        "backend_execution_attempted": False,
                        "backend_execution_performed": False,
                        "machine_action_performed": False,
                        "adapter_status": "circuit_open",
                        **_backend_observability_metadata(
                            health_state=health_state,
                            backend_latency_ms=0,
                        ),
                    },
                    audit_event_ids=audit_event_ids,
                ),
                request_dict=request_dict,
                context=context,
                audit_event_ids=audit_event_ids,
            )

    try:
        requested_url = _extract_request_url(request_dict)
    except ValueError as exc:
        audit_event_ids.extend(
            _emit_terminal_events(
                request_dict,
                context,
                status=MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST,
                detail=str(exc),
                include_skipped=True,
            )
        )
        return _finalize_terminal_result(
            result=_build_nonexecuted_result(
                status="failed",
                summary="MACHINE_OPERATOR request is missing a safe browser target.",
                detail=str(exc),
                metadata={
                    "lane_outcome": MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST,
                    "backend_status": "invalid_arguments",
                    "backend_execution_attempted": False,
                    "backend_execution_performed": False,
                    "machine_action_performed": False,
                    "adapter_status": "invalid_arguments",
                },
                audit_event_ids=audit_event_ids,
            ),
            request_dict=request_dict,
            context=context,
            audit_event_ids=audit_event_ids,
        )

    if not _is_allowlisted_url(requested_url, request_dict["policy_context"]["allowlist_refs"]):
        detail = f"MACHINE_OPERATOR runtime allowlist blocked URL: {requested_url.normalized_url}"
        audit_event_ids.extend(
            _emit_terminal_events(
                request_dict,
                context,
                status=MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION,
                detail=detail,
                include_skipped=True,
            )
        )
        return _finalize_terminal_result(
            result=_build_nonexecuted_result(
                status="denied",
                summary="MACHINE_OPERATOR request blocked by runtime allowlist.",
                detail=detail,
                metadata={
                    "lane_outcome": MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION,
                    "backend_status": "allowlist_blocked",
                    "backend_execution_attempted": False,
                    "backend_execution_performed": False,
                    "machine_action_performed": False,
                    "adapter_status": "allowlist_blocked",
                },
                audit_event_ids=audit_event_ids,
            ),
            request_dict=request_dict,
            context=context,
            audit_event_ids=audit_event_ids,
        )

    timeout_seconds = _compute_timeout_seconds(request_dict)
    audit_event_ids.append(
        emit_machine_operator_event(
            event_type=MachineOperatorAuditEventType.MO_STEP_STARTED,
            plan_id=context.plan_id,
            execution_id=context.execution_id,
            trace_id=context.trace_id,
            intent_id=request_dict["intent_id"],
            correlation_id=request_dict["correlation_id"],
            capability_name=capability_name,
            status="started",
            detail=(
                f"MACHINE_OPERATOR backend request started with timeout {timeout_seconds:.3f}s."
                if not probe_allowed
                else f"MACHINE_OPERATOR recovery probe started with timeout {timeout_seconds:.3f}s."
            ),
            backend_state=health_state.state,
        )
    )

    started = time.perf_counter()
    try:
        gateway_response = _post_openclaw_request(
            request_dict=request_dict,
            context=context,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        _record_backend_failure(health_state, preserve_unavailable=probe_allowed)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        result = _build_gateway_exception_result(
            exc=exc,
            request_dict=request_dict,
            elapsed_ms=elapsed_ms,
            health_state=health_state,
        )
        _emit_execution_terminal_event(
            request_dict=request_dict,
            context=context,
            result=result,
            audit_event_ids=audit_event_ids,
        )
        return _finalize_terminal_result(
            result=result,
            request_dict=request_dict,
            context=context,
            audit_event_ids=audit_event_ids,
        )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    try:
        result = _translate_gateway_response(
            request_dict=request_dict,
            capability_name=capability_name,
            timeout_seconds=timeout_seconds,
            elapsed_ms=elapsed_ms,
            body=gateway_response,
        )
        _record_backend_success(health_state)
        result.metadata.update(
            _backend_observability_metadata(
                health_state=health_state,
                backend_latency_ms=elapsed_ms,
            )
        )
    except ValueError as exc:
        _record_backend_failure(health_state, preserve_unavailable=probe_allowed)
        result = _build_nonexecuted_result(
            status="failed",
            summary="MACHINE_OPERATOR backend returned an invalid execution envelope.",
            detail=str(exc),
            metadata={
                "lane_outcome": MACHINE_OPERATOR_OUTCOME_EXECUTION_FAILED,
                "backend_status": "invalid_backend_response",
                "backend_execution_attempted": True,
                "backend_execution_performed": False,
                "machine_action_performed": False,
                "adapter_status": "invalid_backend_response",
                "timeout_seconds": timeout_seconds,
                **_backend_observability_metadata(
                    health_state=health_state,
                    backend_latency_ms=elapsed_ms,
                    backend_error_type=type(exc).__name__,
                ),
            },
            audit_event_ids=audit_event_ids,
        )
    _emit_execution_terminal_event(
        request_dict=request_dict,
        context=context,
        result=result,
        audit_event_ids=audit_event_ids,
    )
    return _finalize_terminal_result(
        result=result,
        request_dict=request_dict,
        context=context,
        audit_event_ids=audit_event_ids,
    )


def _build_gateway_exception_result(
    *,
    exc: Exception,
    request_dict: dict[str, Any],
    elapsed_ms: int,
    health_state: _BackendHealthState,
) -> MachineOperatorAdapterResult:
    timeout_seconds = _compute_timeout_seconds(request_dict)
    backend_error_type = type(exc).__name__
    if requests is None:
        detail = "Python requests dependency is unavailable for MACHINE_OPERATOR execution."
        return _build_nonexecuted_result(
            status="aborted",
            summary="MACHINE_OPERATOR backend is unavailable.",
            detail=detail,
            metadata={
                "lane_outcome": MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE,
                "backend_status": "unavailable",
                "backend_execution_attempted": False,
                "backend_execution_performed": False,
                "machine_action_performed": False,
                "adapter_status": "backend_unavailable",
                "timeout_seconds": timeout_seconds,
                **_backend_observability_metadata(
                    health_state=health_state,
                    backend_latency_ms=elapsed_ms,
                    backend_error_type=backend_error_type,
                ),
            },
            consumed_budget=MachineOperatorBudgetUsage(
                steps=0,
                duration_ms=max(elapsed_ms, 0),
                output_bytes=0,
                side_effects=0,
            ),
            audit_event_ids=[],
        )
    if isinstance(exc, requests.Timeout):
        detail = f"MACHINE_OPERATOR execution timed out after {timeout_seconds:.3f}s."
        return _build_nonexecuted_result(
            status="aborted",
            summary="MACHINE_OPERATOR execution timed out.",
            detail=detail,
            metadata={
                "lane_outcome": MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED,
                "backend_status": "timeout",
                "backend_execution_attempted": True,
                "backend_execution_performed": False,
                "machine_action_performed": False,
                "adapter_status": "timeout",
                "timeout_seconds": timeout_seconds,
                **_backend_observability_metadata(
                    health_state=health_state,
                    backend_latency_ms=elapsed_ms,
                    backend_error_type=backend_error_type,
                ),
            },
            consumed_budget=MachineOperatorBudgetUsage(
                steps=0,
                duration_ms=max(elapsed_ms, 0),
                output_bytes=0,
                side_effects=0,
            ),
            audit_event_ids=[],
        )
    detail = f"MACHINE_OPERATOR backend request failed: {exc}"
    return _build_nonexecuted_result(
        status="aborted",
        summary="MACHINE_OPERATOR backend is unavailable.",
        detail=detail,
        metadata={
            "lane_outcome": MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE,
            "backend_status": "unavailable",
            "backend_execution_attempted": True,
            "backend_execution_performed": False,
            "machine_action_performed": False,
            "adapter_status": "backend_unavailable",
            "timeout_seconds": timeout_seconds,
            **_backend_observability_metadata(
                health_state=health_state,
                backend_latency_ms=elapsed_ms,
                backend_error_type=backend_error_type,
            ),
        },
        consumed_budget=MachineOperatorBudgetUsage(
            steps=0,
            duration_ms=max(elapsed_ms, 0),
            output_bytes=0,
            side_effects=0,
        ),
        audit_event_ids=[],
    )


def _emit_execution_terminal_event(
    *,
    request_dict: dict[str, Any],
    context: MachineOperatorAdapterContext,
    result: MachineOperatorAdapterResult,
    audit_event_ids: list[str],
) -> None:
    lane_outcome = str(result.metadata.get("lane_outcome", ""))
    backend_error_type = str(result.metadata.get("backend_error_type", ""))
    adapter_status = str(result.metadata.get("adapter_status", ""))
    if adapter_status == "circuit_open":
        event_type = MachineOperatorAuditEventType.MO_BACKEND_UNAVAILABLE
        status = MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE
    elif lane_outcome == MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE:
        event_type = MachineOperatorAuditEventType.MO_BACKEND_UNAVAILABLE
        status = MACHINE_OPERATOR_OUTCOME_BACKEND_UNAVAILABLE
    elif result.status == "ok":
        event_type = MachineOperatorAuditEventType.MO_STEP_COMPLETED
        status = MACHINE_OPERATOR_OUTCOME_SUCCESS
    elif result.status == "partial":
        event_type = MachineOperatorAuditEventType.MO_STEP_PARTIAL
        status = MACHINE_OPERATOR_OUTCOME_EXECUTION_PARTIAL
    elif result.status == "failed":
        event_type = MachineOperatorAuditEventType.MO_EXECUTION_FAILED
        status = MACHINE_OPERATOR_OUTCOME_EXECUTION_FAILED
    elif result.status == "denied":
        event_type = MachineOperatorAuditEventType.MO_EXECUTION_SKIPPED
        status = MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION
    else:
        event_type = MachineOperatorAuditEventType.MO_ABORTED
        status = MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED
    audit_event_ids.append(
        emit_machine_operator_event(
            event_type=event_type,
            plan_id=context.plan_id,
            execution_id=context.execution_id,
            trace_id=context.trace_id,
            intent_id=request_dict["intent_id"],
            correlation_id=request_dict["correlation_id"],
            capability_name=request_dict["capability_name"],
            status=status,
            detail=(
                result.observation.summary
                + (f" (error_type={backend_error_type})" if backend_error_type else "")
            ),
            backend_state=str(result.metadata.get("backend_state", "")),
        )
    )


def _emit_base_audit_events(
    request_dict: dict[str, Any],
    context: MachineOperatorAdapterContext,
) -> list[str]:
    return [
        emit_machine_operator_event(
            event_type=MachineOperatorAuditEventType.MO_INTENT_RECEIVED,
            plan_id=context.plan_id,
            execution_id=context.execution_id,
            trace_id=context.trace_id,
            intent_id=request_dict["intent_id"],
            correlation_id=request_dict["correlation_id"],
            capability_name=request_dict["capability_name"],
            status="received",
            detail="MACHINE_OPERATOR intent reached the adapter boundary.",
        ),
        emit_machine_operator_event(
            event_type=MachineOperatorAuditEventType.MO_POLICY_EVALUATED,
            plan_id=context.plan_id,
            execution_id=context.execution_id,
            trace_id=context.trace_id,
            intent_id=request_dict["intent_id"],
            correlation_id=request_dict["correlation_id"],
            capability_name=request_dict["capability_name"],
            status=context.policy_reason_code,
            detail=context.policy_message,
        ),
    ]


def _emit_terminal_events(
    request_dict: dict[str, Any],
    context: MachineOperatorAdapterContext,
    *,
    status: str,
    detail: str,
    include_skipped: bool = False,
    include_execution_failed: bool = False,
    include_backend_unavailable: bool = False,
    include_aborted: bool = False,
) -> list[str]:
    event_ids: list[str] = []
    if include_backend_unavailable:
        event_ids.append(
            emit_machine_operator_event(
                event_type=MachineOperatorAuditEventType.MO_BACKEND_UNAVAILABLE,
                plan_id=context.plan_id,
                execution_id=context.execution_id,
                trace_id=context.trace_id,
                intent_id=request_dict["intent_id"],
                correlation_id=request_dict["correlation_id"],
                capability_name=request_dict["capability_name"],
                status=status,
                detail=detail,
            )
        )
    if include_skipped:
        event_ids.append(
            emit_machine_operator_event(
                event_type=MachineOperatorAuditEventType.MO_EXECUTION_SKIPPED,
                plan_id=context.plan_id,
                execution_id=context.execution_id,
                trace_id=context.trace_id,
                intent_id=request_dict["intent_id"],
                correlation_id=request_dict["correlation_id"],
                capability_name=request_dict["capability_name"],
                status=status,
                detail=detail,
            )
        )
    if include_execution_failed:
        event_ids.append(
            emit_machine_operator_event(
                event_type=MachineOperatorAuditEventType.MO_EXECUTION_FAILED,
                plan_id=context.plan_id,
                execution_id=context.execution_id,
                trace_id=context.trace_id,
                intent_id=request_dict["intent_id"],
                correlation_id=request_dict["correlation_id"],
                capability_name=request_dict["capability_name"],
                status=status,
                detail=detail,
            )
        )
    if include_aborted:
        event_ids.append(
            emit_machine_operator_event(
                event_type=MachineOperatorAuditEventType.MO_ABORTED,
                plan_id=context.plan_id,
                execution_id=context.execution_id,
                trace_id=context.trace_id,
                intent_id=request_dict["intent_id"],
                correlation_id=request_dict["correlation_id"],
                capability_name=request_dict["capability_name"],
                status=status,
                detail=detail,
            )
        )
    return event_ids


def _finalize_terminal_result(
    *,
    result: MachineOperatorAdapterResult,
    request_dict: dict[str, Any],
    context: MachineOperatorAdapterContext,
    audit_event_ids: list[str],
) -> MachineOperatorAdapterResult:
    lane_outcome = str(result.metadata.get("lane_outcome", ""))
    if not is_machine_operator_transition_allowed(MACHINE_OPERATOR_STATE_REQUESTED, lane_outcome):
        raise ValueError(f"Unsupported MACHINE_OPERATOR lane_outcome: {lane_outcome}")

    result.metadata.update(_ephemeral_session_metadata())
    result.metadata.setdefault("backend_latency_ms", max(result.consumed_budget.duration_ms, 0))
    result.metadata.setdefault("backend_state", "")
    result.metadata.setdefault("backend_error_type", "")
    result.metadata.setdefault("circuit_state", "closed")
    structured_data = dict(result.observation.structured_data)
    structured_data.update(_ephemeral_session_structured_data())
    structured_data.update(
        {
            "evidence_available": bool(result.evidence_refs),
            "evidence_count": len(result.evidence_refs),
            "backend_latency_ms": result.metadata["backend_latency_ms"],
            "backend_state": result.metadata["backend_state"],
            "backend_error_type": result.metadata["backend_error_type"],
            "circuit_state": result.metadata["circuit_state"],
        }
    )
    result.observation = MachineOperatorObservation(
        summary=result.observation.summary,
        detail=result.observation.detail,
        structured_data=structured_data,
    )

    finalized_audit_ids = list(audit_event_ids)
    finalized_audit_ids.append(
        emit_machine_operator_event(
            event_type=MachineOperatorAuditEventType.MO_EPHEMERAL_SCOPE_CLOSED,
            plan_id=context.plan_id,
            execution_id=context.execution_id,
            trace_id=context.trace_id,
            intent_id=request_dict["intent_id"],
            correlation_id=request_dict["correlation_id"],
            capability_name=request_dict["capability_name"],
            status=lane_outcome,
            detail="MACHINE_OPERATOR retained no reusable session state after terminal outcome.",
            backend_state=str(result.metadata.get("backend_state", "")),
        )
    )
    result.audit_event_ids = finalized_audit_ids
    return result


def _ephemeral_session_metadata() -> dict[str, Any]:
    return {
        "session_mode": "ephemeral",
        "session_reused": False,
        "session_persisted": False,
        "session_retained_after_terminal": False,
        "cleanup_semantics": "no_reusable_session_retained",
    }


def _ephemeral_session_structured_data() -> dict[str, Any]:
    return {
        "session_mode": "ephemeral",
        "session_reused": False,
        "session_persisted": False,
        "session_retained_after_terminal": False,
        "cleanup_semantics": "no_reusable_session_retained",
    }


def _validate_context_consistency(
    *,
    request_dict: dict[str, Any],
    context: MachineOperatorAdapterContext,
    audit_event_ids: list[str],
) -> MachineOperatorAdapterResult | None:
    if request_dict["capability_name"] == context.capability_name and request_dict["capability_tier"] == context.capability_tier:
        return None
    detail = (
        "MACHINE_OPERATOR adapter context must match the request capability and tier. "
        f"request={request_dict['capability_name']}:{request_dict['capability_tier']} "
        f"context={context.capability_name}:{context.capability_tier}"
    )
    audit_event_ids.extend(
        _emit_terminal_events(
            request_dict,
            context,
            status=MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST,
            detail=detail,
            include_skipped=True,
        )
    )
    return _finalize_terminal_result(
        result=_build_nonexecuted_result(
            status="failed",
            summary="MACHINE_OPERATOR adapter context is inconsistent with the request.",
            detail=detail,
            metadata={
                "lane_outcome": MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST,
                "backend_status": "invalid_context",
                "backend_execution_attempted": False,
                "backend_execution_performed": False,
                "machine_action_performed": False,
                "adapter_status": "invalid_context",
            },
            audit_event_ids=audit_event_ids,
        ),
        request_dict=request_dict,
        context=context,
        audit_event_ids=audit_event_ids,
    )


def _validate_execution_governance(
    *,
    request_dict: dict[str, Any],
    context: MachineOperatorAdapterContext,
    audit_event_ids: list[str],
) -> MachineOperatorAdapterResult | None:
    decision = enforce_machine_operator_request(request_dict)
    if decision.allowed and context.policy_reason_code == "allowed" and decision.policy.policy_level in {"N0", "N1"}:
        return None

    if decision.reason_code == "invalid_request":
        lane_outcome = MACHINE_OPERATOR_OUTCOME_INVALID_REQUEST
        status = "failed"
        summary = "MACHINE_OPERATOR request rejected by execution-time validation."
        adapter_status = "invalid_request"
    else:
        lane_outcome = MACHINE_OPERATOR_OUTCOME_POLICY_VIOLATION
        status = "denied"
        summary = "MACHINE_OPERATOR request rejected by execution-time policy."
        adapter_status = "rejected_by_policy"

    audit_event_ids.extend(
        _emit_terminal_events(
            request_dict,
            context,
            status=lane_outcome,
            detail=decision.message,
            include_skipped=True,
        )
    )
    return _finalize_terminal_result(
        result=_build_nonexecuted_result(
            status=status,
            summary=summary,
            detail=decision.message,
            metadata={
                "lane_outcome": lane_outcome,
                "backend_status": "not_executed",
                "backend_execution_attempted": False,
                "backend_execution_performed": False,
                "machine_action_performed": False,
                "adapter_status": adapter_status,
            },
            audit_event_ids=audit_event_ids,
        ),
        request_dict=request_dict,
        context=context,
        audit_event_ids=audit_event_ids,
    )


def _abort_requested(request_dict: dict[str, Any]) -> bool:
    arguments = request_dict.get("arguments", {})
    if isinstance(arguments, dict) and arguments.get("abort_requested") is True:
        return True
    policy_context = request_dict.get("policy_context", {})
    if isinstance(policy_context, dict):
        constraints = policy_context.get("constraints", [])
        if isinstance(constraints, list):
            return any(item in {"abort_requested", "cancel_requested"} for item in constraints)
    return False


def _translate_gateway_response(
    *,
    request_dict: dict[str, Any],
    capability_name: str,
    timeout_seconds: float,
    elapsed_ms: int,
    body: Any,
) -> MachineOperatorAdapterResult:
    if not isinstance(body, dict):
        raise ValueError("MACHINE_OPERATOR backend returned a non-dict response.")

    status = body.get("status")
    if status not in {"ok", "partial", "failed", "aborted"}:
        raise ValueError("MACHINE_OPERATOR backend returned an invalid status.")

    final_url: _CanonicalUrl | None = None
    if status in {"ok", "partial"}:
        final_url = _extract_final_url(
            body.get("final_url"),
            allowlist_refs=request_dict["policy_context"]["allowlist_refs"],
        )
    elif body.get("final_url") is not None:
        final_url = _extract_final_url(
            body.get("final_url"),
            allowlist_refs=request_dict["policy_context"]["allowlist_refs"],
        )
    observation = _build_observation(body.get("observation"))
    evidence_refs = _build_evidence_refs(body.get("evidence_refs"))
    consumed_budget = _build_consumed_budget(
        body.get("consumed_budget"),
        elapsed_ms=elapsed_ms,
        executed=status in {"ok", "partial"},
        observation=observation,
        evidence_refs=evidence_refs,
    )
    side_effects_declared = _build_side_effect_declarations(body.get("side_effects_declared"))
    if side_effects_declared or consumed_budget.side_effects != 0:
        raise ValueError("MACHINE_OPERATOR backend reported disallowed side effects.")
    if status in {"failed", "aborted"} and evidence_refs:
        raise ValueError("MACHINE_OPERATOR failed or aborted responses must not include evidence_refs.")

    _validate_budget_constraints(
        request_dict=request_dict,
        capability_name=capability_name,
        consumed_budget=consumed_budget,
        observation=observation,
        evidence_refs=evidence_refs,
        executed=status in {"ok", "partial"},
    )
    if status == "aborted":
        backend_execution_performed = False
        machine_action_performed = False
        lane_outcome = MACHINE_OPERATOR_OUTCOME_EXECUTION_ABORTED
        backend_status = "aborted"
    elif status == "failed":
        backend_execution_performed = False
        machine_action_performed = False
        lane_outcome = MACHINE_OPERATOR_OUTCOME_EXECUTION_FAILED
        backend_status = "failed"
    else:
        if final_url is None:
            raise ValueError("MACHINE_OPERATOR successful responses must include final_url.")
        backend_execution_performed = _derive_execution_truth(
            capability_name=capability_name,
            status=status,
            final_url=final_url,
            observation=observation,
            evidence_refs=evidence_refs,
            request_dict=request_dict,
        )
        machine_action_performed = backend_execution_performed
        lane_outcome = (
            MACHINE_OPERATOR_OUTCOME_SUCCESS
            if status == "ok"
            else MACHINE_OPERATOR_OUTCOME_EXECUTION_PARTIAL
        )
        backend_status = "completed" if status == "ok" else "partial"
    _validate_backend_execution_claims(
        body=body,
        backend_execution_performed=backend_execution_performed,
        machine_action_performed=machine_action_performed,
    )

    metadata_payload = body.get("metadata")
    if metadata_payload is not None and not isinstance(metadata_payload, dict):
        raise ValueError("MACHINE_OPERATOR backend metadata must be a dict when present.")

    metadata: dict[str, Any] = {
        "lane_outcome": lane_outcome,
        "backend_status": backend_status,
        "backend_execution_attempted": True,
        "backend_execution_performed": backend_execution_performed,
        "machine_action_performed": machine_action_performed,
        "adapter_status": backend_status,
        "timeout_seconds": timeout_seconds,
        "executed_capability": capability_name,
    }
    if isinstance(metadata_payload, dict):
        metadata.update(
            {
                key: value
                for key, value in metadata_payload.items()
                if key not in metadata
            }
        )

    structured_data = dict(observation.structured_data)
    structured_data.update(
        {
            "lane_outcome": lane_outcome,
            "backend_status": backend_status,
            "backend_execution_performed": backend_execution_performed,
            "machine_action_performed": machine_action_performed,
            "adapter_boundary_reached": True,
        }
    )
    if final_url is not None:
        structured_data["final_url"] = final_url.normalized_url
    observation = MachineOperatorObservation(
        summary=observation.summary,
        detail=observation.detail,
        structured_data=structured_data,
    )
    return MachineOperatorAdapterResult(
        status=status,
        observation=observation,
        evidence_refs=evidence_refs,
        consumed_budget=consumed_budget,
        side_effects_declared=side_effects_declared,
        metadata=metadata,
    )


def _post_openclaw_request(
    *,
    request_dict: dict[str, Any],
    context: MachineOperatorAdapterContext,
    timeout_seconds: float,
) -> dict[str, Any]:
    if requests is None:
        raise RuntimeError("requests dependency unavailable")

    # No retry policy by design (deterministic execution model).
    response = requests.post(
        _gateway_execute_url(),
        json=_build_gateway_payload(
            request_dict=request_dict,
            context=context,
            timeout_seconds=timeout_seconds,
        ),
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("MACHINE_OPERATOR backend returned non-JSON or non-dict content.")
    return body


def _build_gateway_payload(
    *,
    request_dict: dict[str, Any],
    context: MachineOperatorAdapterContext,
    timeout_seconds: float,
) -> dict[str, Any]:
    return {
        "intent_id": request_dict["intent_id"],
        "correlation_id": request_dict["correlation_id"],
        "capability_name": request_dict["capability_name"],
        "arguments": dict(request_dict["arguments"]),
        "budget": {
            "max_steps": request_dict["budget"]["max_steps"],
            "max_duration_ms": request_dict["budget"]["max_duration_ms"],
            "max_output_bytes": request_dict["budget"]["max_output_bytes"],
            "max_side_effects": 0,
        },
        "policy": {
            "policy_decision_ref": context.policy_decision_ref,
            "allowlist_refs": list(request_dict["policy_context"]["allowlist_refs"]),
            "constraints": list(request_dict["policy_context"]["constraints"]),
            "approval_mode": request_dict["policy_context"]["approval_mode"],
        },
        "execution": {
            "mode": "ephemeral",
            "reuse_session": False,
            "persist_profile": False,
            "allow_side_effects": False,
            "require_credentials": False,
            "timeout_seconds": timeout_seconds,
        },
    }


def _build_observation(payload: Any) -> MachineOperatorObservation:
    if not isinstance(payload, dict):
        raise ValueError("MACHINE_OPERATOR backend observation must be a dict.")
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("MACHINE_OPERATOR backend observation.summary must be a non-empty string.")
    detail = payload.get("detail", "")
    if not isinstance(detail, str):
        raise ValueError("MACHINE_OPERATOR backend observation.detail must be a string.")
    structured_data = payload.get("structured_data", {})
    if not isinstance(structured_data, dict):
        raise ValueError("MACHINE_OPERATOR backend observation.structured_data must be a dict.")
    try:
        json.dumps(structured_data)
    except TypeError as exc:
        raise ValueError(f"MACHINE_OPERATOR backend observation.structured_data is not JSON-like: {exc}") from exc
    return MachineOperatorObservation(
        summary=summary.strip(),
        detail=detail,
        structured_data=structured_data,
    )


def _build_evidence_refs(payload: Any) -> list[MachineOperatorEvidenceRef]:
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError("MACHINE_OPERATOR backend evidence_refs must be a list.")
    evidence_refs: list[MachineOperatorEvidenceRef] = []
    seen_ref_ids: set[str] = set()
    seen_uris: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("MACHINE_OPERATOR backend evidence_refs entries must be dicts.")
        ref_id = item.get("ref_id")
        evidence_type = item.get("evidence_type")
        uri = item.get("uri")
        if not isinstance(ref_id, str) or not ref_id.strip():
            raise ValueError("MACHINE_OPERATOR backend evidence_refs.ref_id must be a non-empty string.")
        if not isinstance(evidence_type, str) or not evidence_type.strip():
            raise ValueError("MACHINE_OPERATOR backend evidence_refs.evidence_type must be a non-empty string.")
        if not isinstance(uri, str) or not uri.strip():
            raise ValueError("MACHINE_OPERATOR backend evidence_refs.uri must be a non-empty string.")
        normalized_ref_id = ref_id.strip()
        normalized_uri = uri.strip()
        if normalized_ref_id in seen_ref_ids:
            raise ValueError("MACHINE_OPERATOR backend evidence_refs.ref_id values must be unique.")
        if normalized_uri in seen_uris:
            raise ValueError("MACHINE_OPERATOR backend evidence_refs.uri values must be unique.")
        seen_ref_ids.add(normalized_ref_id)
        seen_uris.add(normalized_uri)
        evidence_refs.append(
            MachineOperatorEvidenceRef(
                ref_id=normalized_ref_id,
                evidence_type=evidence_type.strip(),
                uri=normalized_uri,
                description=_optional_string_field(
                    item,
                    field_name="description",
                    contract_name="MACHINE_OPERATOR backend evidence_refs",
                ),
                media_type=_optional_string_field(
                    item,
                    field_name="media_type",
                    contract_name="MACHINE_OPERATOR backend evidence_refs",
                ),
                digest=_optional_string_field(
                    item,
                    field_name="digest",
                    contract_name="MACHINE_OPERATOR backend evidence_refs",
                ),
            )
        )
    return evidence_refs


def _build_side_effect_declarations(payload: Any) -> list[MachineOperatorSideEffectDeclaration]:
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError("MACHINE_OPERATOR backend side_effects_declared must be a list.")
    declarations: list[MachineOperatorSideEffectDeclaration] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("MACHINE_OPERATOR backend side_effects_declared entries must be dicts.")
        declarations.append(
            MachineOperatorSideEffectDeclaration(
                effect_type=str(item.get("effect_type", "")),
                target_domain=str(item.get("target_domain", "")),
                description=str(item.get("description", "")),
                target_ref=str(item.get("target_ref", "")),
            )
        )
    return declarations


def _build_consumed_budget(
    payload: Any,
    *,
    elapsed_ms: int,
    executed: bool,
    observation: MachineOperatorObservation,
    evidence_refs: list[MachineOperatorEvidenceRef],
) -> MachineOperatorBudgetUsage:
    estimated_output_bytes = _estimate_output_bytes(observation, evidence_refs)
    default_usage = MachineOperatorBudgetUsage(
        steps=1 if executed else 0,
        duration_ms=max(elapsed_ms, 0),
        output_bytes=estimated_output_bytes,
        side_effects=0,
    )
    if payload is None:
        return default_usage
    if not isinstance(payload, dict):
        raise ValueError("MACHINE_OPERATOR backend consumed_budget must be a dict.")
    try:
        steps = int(payload.get("steps", default_usage.steps))
        duration_ms = int(payload.get("duration_ms", default_usage.duration_ms))
        output_bytes = int(payload.get("output_bytes", default_usage.output_bytes))
        side_effects = int(payload.get("side_effects", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"MACHINE_OPERATOR backend consumed_budget must contain integers: {exc}") from exc
    if min(steps, duration_ms, output_bytes, side_effects) < 0:
        raise ValueError("MACHINE_OPERATOR backend consumed_budget values must be non-negative.")
    if executed:
        steps = max(steps, 1)
    duration_ms = max(duration_ms, elapsed_ms)
    output_bytes = max(output_bytes, estimated_output_bytes)
    return MachineOperatorBudgetUsage(
        steps=steps,
        duration_ms=duration_ms,
        output_bytes=output_bytes,
        side_effects=side_effects,
    )


def _validate_budget_constraints(
    *,
    request_dict: dict[str, Any],
    capability_name: str,
    consumed_budget: MachineOperatorBudgetUsage,
    observation: MachineOperatorObservation,
    evidence_refs: list[MachineOperatorEvidenceRef],
    executed: bool,
) -> None:
    budget = request_dict["budget"]
    if consumed_budget.steps > budget["max_steps"]:
        raise ValueError("MACHINE_OPERATOR backend consumed_budget.steps exceeded request budget.")
    if consumed_budget.duration_ms > budget["max_duration_ms"]:
        raise ValueError("MACHINE_OPERATOR backend consumed_budget.duration_ms exceeded request budget.")
    if consumed_budget.output_bytes > budget["max_output_bytes"]:
        raise ValueError("MACHINE_OPERATOR backend consumed_budget.output_bytes exceeded request budget.")
    if not executed:
        return
    if capability_name == CAPABILITY_BROWSER_READ_VISIBLE_TEXT:
        _validate_read_visible_text_payload(
            observation=observation,
            max_output_bytes=budget["max_output_bytes"],
        )
    elif capability_name in {CAPABILITY_BROWSER_SNAPSHOT, CAPABILITY_BROWSER_SCREENSHOT} and not evidence_refs:
        raise ValueError(
            f"MACHINE_OPERATOR capability {capability_name} requires evidence_refs for truthful execution."
        )


def _validate_read_visible_text_payload(
    *,
    observation: MachineOperatorObservation,
    max_output_bytes: int,
) -> None:
    visible_text = observation.structured_data.get("visible_text")
    if not isinstance(visible_text, str):
        raise ValueError("browser.read_visible_text must include structured_data.visible_text.")
    truncated = observation.structured_data.get("is_truncated")
    if not isinstance(truncated, bool):
        raise ValueError("browser.read_visible_text must include structured_data.is_truncated.")
    visible_text_bytes = len(visible_text.encode("utf-8"))
    if visible_text_bytes > max_output_bytes:
        raise ValueError("browser.read_visible_text visible_text exceeds requested max_output_bytes.")


def _derive_execution_truth(
    *,
    capability_name: str,
    status: str,
    final_url: _CanonicalUrl,
    observation: MachineOperatorObservation,
    evidence_refs: list[MachineOperatorEvidenceRef],
    request_dict: dict[str, Any],
) -> bool:
    if status not in {"ok", "partial"}:
        return False
    if not _is_allowlisted_url(final_url, request_dict["policy_context"]["allowlist_refs"]):
        raise ValueError("MACHINE_OPERATOR backend final_url is not allowlisted.")
    if capability_name == CAPABILITY_BROWSER_READ_VISIBLE_TEXT:
        return True
    if capability_name in {CAPABILITY_BROWSER_SNAPSHOT, CAPABILITY_BROWSER_SCREENSHOT}:
        return bool(evidence_refs)
    if capability_name == CAPABILITY_BROWSER_NAVIGATE:
        return True
    return False


def _validate_backend_execution_claims(
    *,
    body: dict[str, Any],
    backend_execution_performed: bool,
    machine_action_performed: bool,
) -> None:
    if "backend_execution_performed" in body and bool(body["backend_execution_performed"]) != backend_execution_performed:
        raise ValueError("MACHINE_OPERATOR backend_execution_performed claim is inconsistent with validated payload.")
    if "machine_action_performed" in body and bool(body["machine_action_performed"]) != machine_action_performed:
        raise ValueError("MACHINE_OPERATOR machine_action_performed claim is inconsistent with validated payload.")


def _estimate_output_bytes(
    observation: MachineOperatorObservation,
    evidence_refs: list[MachineOperatorEvidenceRef],
) -> int:
    observation_bytes = len(json.dumps(asdict(observation), sort_keys=True).encode("utf-8"))
    evidence_bytes = sum(len(evidence.uri.encode("utf-8")) for evidence in evidence_refs)
    return observation_bytes + evidence_bytes


def _optional_string_field(
    payload: dict[str, Any],
    *,
    field_name: str,
    contract_name: str,
) -> str:
    value = payload.get(field_name, "")
    if not isinstance(value, str):
        raise ValueError(f"{contract_name}.{field_name} must be a string when present.")
    return value


def _build_nonexecuted_result(
    *,
    status: str,
    summary: str,
    detail: str,
    metadata: dict[str, Any],
    audit_event_ids: list[str],
    consumed_budget: MachineOperatorBudgetUsage | None = None,
) -> MachineOperatorAdapterResult:
    lane_outcome = metadata["lane_outcome"]
    if not is_machine_operator_transition_allowed(MACHINE_OPERATOR_STATE_REQUESTED, lane_outcome):
        raise ValueError(f"Unsupported MACHINE_OPERATOR lane_outcome: {lane_outcome}")
    structured_data = {
        "lane_outcome": lane_outcome,
        "backend_status": metadata["backend_status"],
        "backend_execution_performed": metadata["backend_execution_performed"],
        "machine_action_performed": metadata["machine_action_performed"],
        "adapter_boundary_reached": True,
    }
    return MachineOperatorAdapterResult(
        status=status,
        observation=MachineOperatorObservation(
            summary=summary,
            detail=detail,
            structured_data=structured_data,
        ),
        evidence_refs=[],
        consumed_budget=consumed_budget or MachineOperatorBudgetUsage(),
        side_effects_declared=[],
        metadata=metadata,
        audit_event_ids=audit_event_ids,
    )


def _extract_request_url(request_dict: dict[str, Any]) -> _CanonicalUrl:
    arguments = request_dict.get("arguments")
    if not isinstance(arguments, dict):
        raise ValueError("Tier A browser capabilities require an 'arguments' object.")
    url = arguments.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Tier A browser capabilities require a non-empty 'url' argument.")
    return _canonicalize_url(url.strip())


def _extract_final_url(
    final_url: Any,
    *,
    allowlist_refs: Any,
) -> _CanonicalUrl:
    if not isinstance(final_url, str) or not final_url.strip():
        raise ValueError("MACHINE_OPERATOR backend response must include final_url.")
    canonical_final_url = _canonicalize_url(final_url.strip())
    if not _is_allowlisted_url(canonical_final_url, allowlist_refs):
        raise ValueError("MACHINE_OPERATOR backend final_url is not allowlisted.")
    return canonical_final_url


def _is_allowlisted_url(url: _CanonicalUrl, allowlist_refs: Any) -> bool:
    if not isinstance(allowlist_refs, list) or not allowlist_refs:
        return False
    for ref in allowlist_refs:
        rule = _parse_allowlist_rule(ref)
        if rule is None:
            continue
        if url.scheme not in rule.schemes:
            continue
        if url.hostname != rule.hostname:
            continue
        if url.port not in rule.ports:
            continue
        if _path_matches_prefix(url.path, rule.path_prefix):
            return True
    return False


def _parse_allowlist_rule(ref: Any) -> _AllowlistRule | None:
    if not isinstance(ref, str):
        return None
    ref = ref.strip()
    if not ref:
        return None
    if ref == "allowlist:web-safe":
        return _AllowlistRule(
            schemes=frozenset({"https"}),
            hostname="example.test",
            ports=frozenset({443}),
            path_prefix="/",
        )
    if ref.startswith("host:"):
        hostname = ref[5:].strip().lower()
        if not hostname or any(ch in hostname for ch in "@/"):
            return None
        return _AllowlistRule(
            schemes=frozenset(_SUPPORTED_URL_SCHEMES),
            hostname=hostname,
            ports=frozenset({80, 443}),
            path_prefix="/",
        )
    if ref.startswith("url_prefix:"):
        try:
            canonical_prefix = _canonicalize_url(ref[11:].strip())
        except ValueError:
            return None
        return _AllowlistRule(
            schemes=frozenset({canonical_prefix.scheme}),
            hostname=canonical_prefix.hostname,
            ports=frozenset({canonical_prefix.port}),
            path_prefix=canonical_prefix.path,
        )
    return None


def _path_matches_prefix(path: str, path_prefix: str) -> bool:
    normalized_prefix = path_prefix.rstrip("/") or "/"
    if normalized_prefix == "/":
        return True
    return path == normalized_prefix or path.startswith(normalized_prefix + "/")


def _canonicalize_url(url: str) -> _CanonicalUrl:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL must be a non-empty string.")
    stripped = url.strip()
    if "\\" in stripped:
        raise ValueError("URL must not contain backslashes.")

    parsed = urlparse(stripped)
    scheme = parsed.scheme.lower()
    if scheme not in _SUPPORTED_URL_SCHEMES:
        raise ValueError("URL scheme is not allowed.")
    if not parsed.netloc:
        raise ValueError("URL must include an absolute hostname.")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError("URL userinfo is not allowed.")
    if parsed.fragment:
        raise ValueError("URL fragments are not allowed.")

    try:
        port = parsed.port or _default_port_for_scheme(scheme)
    except ValueError as exc:
        raise ValueError(f"URL port is invalid: {exc}") from exc
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL hostname is invalid.")
    path = _normalize_url_path(parsed.path)
    return _CanonicalUrl(
        scheme=scheme,
        hostname=hostname,
        port=port,
        path=path,
        query=parsed.query,
    )


def _normalize_url_path(path: str) -> str:
    raw_path = path or "/"
    if not raw_path.startswith("/"):
        raw_path = "/" + raw_path
    if "\\" in raw_path:
        raise ValueError("URL path must not contain backslashes.")
    _validate_percent_encoding(raw_path)
    lowered = raw_path.lower()
    if any(token in lowered for token in _FORBIDDEN_ESCAPES):
        raise ValueError("URL path contains ambiguous encoded separators.")
    decoded_path = unquote(raw_path)
    if "\\" in decoded_path or "\x00" in decoded_path:
        raise ValueError("URL path contains forbidden characters.")
    normalized = posixpath.normpath(decoded_path)
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if decoded_path.endswith("/") and normalized != "/":
        normalized += "/"
    return normalized


def _validate_percent_encoding(value: str) -> None:
    index = 0
    while True:
        index = value.find("%", index)
        if index == -1:
            return
        chunk = value[index:index + 3]
        if not _PERCENT_ESCAPE_RE.fullmatch(chunk):
            raise ValueError("URL contains invalid percent encoding.")
        index += 3


def _default_port_for_scheme(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _compute_timeout_seconds(request_dict: dict[str, Any]) -> float:
    budget = request_dict.get("budget", {})
    max_duration_ms = budget.get("max_duration_ms", 0)
    try:
        requested_timeout = max(float(max_duration_ms) / 1000.0, 0.001)
    except (TypeError, ValueError):
        requested_timeout = max(config.OPENCLAW_TIMEOUT_SECONDS, 0.001)
    configured_timeout = max(config.OPENCLAW_TIMEOUT_SECONDS, 0.001)
    return min(requested_timeout, configured_timeout)


def _backend_observability_metadata(
    *,
    health_state: _BackendHealthState,
    backend_latency_ms: int,
    backend_error_type: str = "",
) -> dict[str, Any]:
    return {
        "backend_latency_ms": max(backend_latency_ms, 0),
        "backend_state": health_state.state,
        "backend_error_type": backend_error_type,
        "circuit_state": _circuit_state(health_state),
    }


def _circuit_state(health_state: _BackendHealthState) -> str:
    return "open" if health_state.state == _BACKEND_STATE_UNAVAILABLE else "closed"


def _record_backend_success(health_state: _BackendHealthState) -> None:
    health_state.consecutive_failures = 0
    health_state.state = _BACKEND_STATE_HEALTHY
    health_state.last_success_timestamp = time.time()


def _cooldown_elapsed(health_state: _BackendHealthState) -> bool:
    if health_state.last_failure_timestamp <= 0:
        return False
    return (time.time() - health_state.last_failure_timestamp) >= _BACKEND_UNAVAILABLE_COOLDOWN_SECONDS


def _record_backend_failure(
    health_state: _BackendHealthState,
    *,
    preserve_unavailable: bool = False,
) -> None:
    health_state.consecutive_failures += 1
    health_state.last_failure_timestamp = time.time()
    if preserve_unavailable:
        health_state.state = _BACKEND_STATE_UNAVAILABLE
        return
    if health_state.consecutive_failures >= _BACKEND_UNAVAILABLE_FAILURE_THRESHOLD:
        health_state.state = _BACKEND_STATE_UNAVAILABLE
        return
    health_state.state = _BACKEND_STATE_DEGRADED


def _gateway_execute_url() -> str:
    raw_url = config.OPENCLAW_GATEWAY_URL.strip()
    if "\\" in raw_url:
        raise ValueError("OPENCLAW_GATEWAY_URL must use URL separators, not backslashes.")
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.netloc:
        raise ValueError("OPENCLAW_GATEWAY_URL must be an absolute http(s) or ws(s) URL.")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError("OPENCLAW_GATEWAY_URL must not include params, query, or fragments.")
    scheme = parsed.scheme
    if scheme == "ws":
        scheme = "http"
    elif scheme == "wss":
        scheme = "https"
    base_path = parsed.path.rstrip("/")
    execute_path = f"{base_path}/v1/machine-operator/execute" if base_path else "/v1/machine-operator/execute"
    return urlunparse((scheme, parsed.netloc, execute_path, "", "", ""))


def _coerce_request_dict(payload: Any) -> dict[str, Any]:
    if is_dataclass(payload):
        return asdict(payload)
    if isinstance(payload, dict):
        return dict(payload)
    raise TypeError("MachineOperatorIntentRequest must be a dict or dataclass instance")
