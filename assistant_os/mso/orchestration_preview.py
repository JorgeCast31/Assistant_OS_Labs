"""Orchestration Preview / Dry-Run v0 — a reviewable handoff PREVIEW (no execution).

PR: Orchestration Preview / Dry-Run v0.

Chains a ``DelegationWorkPacket`` (#264), a list of ``WorkerProfile`` (#265), the
``RoutingRecommendation`` (#266) and a ``HandoffEnvelope`` (#267) into a single
reviewable preview: which worker would be recommended, why, whether a handoff
envelope could be built, blockers/warnings, whether human review is required,
and pending evidence refs.

WHAT THIS IS NOT
----------------
A dry-run/preview — NOT execution. It does NOT dispatch, execute, call models,
contact external APIs, run a Runner, use a queue, mint a token, grant authority,
perform automatic handoff, mutate its inputs, or produce side effects.
``can_dispatch`` and ``can_execute`` are hard-wired ``False``.

> preview ≠ dispatch · dry-run ≠ execution · recommendation ≠ authorization ·
> handoff envelope ≠ real handoff · evidence_refs ≠ proof of execution.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .delegation_packet import DelegationWorkPacket
from .worker_registry import WorkerProfile
from .routing_policy import recommend_worker, RoutingStatus, RoutingRecommendation
from .handoff_envelope import HandoffEnvelope, HandoffStatus


class OrchestrationPreviewError(ValueError):
    """Raised when a preview fails validation (fail-closed)."""


class PreviewStatus(str, Enum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    NO_ELIGIBLE_WORKER = "NO_ELIGIBLE_WORKER"
    BLOCKED = "BLOCKED"
    INVALID_INPUT = "INVALID_INPUT"
    EXPIRED = "EXPIRED"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return _now_utc().isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


_DERIVED_IGNORED = frozenset({"can_dispatch", "can_execute"})


@dataclass(slots=True)
class OrchestrationPreview:
    """A reviewable dry-run preview. Dispatches nothing; grants nothing."""

    preview_id: str
    mission_id: str
    packet_id: str
    routing_decision_id: str
    preview_status: PreviewStatus
    handoff_id: str = ""
    selected_worker_id: str = ""
    selected_worker_type: str = ""
    steps: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    requires_human_review: bool = True
    created_at: str = ""
    expires_at: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    audit_notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.preview_status, PreviewStatus):
            try:
                object.__setattr__(self, "preview_status", PreviewStatus(self.preview_status))
            except (ValueError, KeyError):
                raise OrchestrationPreviewError(f"invalid preview_status: {self.preview_status!r}")

    @property
    def can_dispatch(self) -> bool:
        return False

    @property
    def can_execute(self) -> bool:
        return False

    def is_expired(self, *, now: datetime | None = None) -> bool:
        dt = _parse_iso(self.expires_at)
        return False if dt is None else dt <= (now or _now_utc())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["preview_status"] = self.preview_status.value
        d["can_dispatch"] = False
        d["can_execute"] = False
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrchestrationPreview":
        allowed = set(cls.__dataclass_fields__) - _DERIVED_IGNORED  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in allowed})


def validate_preview(preview: OrchestrationPreview) -> OrchestrationPreview:
    """Fail-closed structural validation of a preview."""
    if not isinstance(preview, OrchestrationPreview):
        raise OrchestrationPreviewError("not an OrchestrationPreview")
    if not preview.preview_id or not preview.packet_id or not preview.mission_id:
        raise OrchestrationPreviewError("preview missing required ids")
    if preview.can_dispatch or preview.can_execute:
        raise OrchestrationPreviewError("preview must never be dispatchable/executable")
    return preview


def _routing_to_preview_status(rs: RoutingStatus) -> PreviewStatus:
    if rs == RoutingStatus.INVALID_INPUT:
        return PreviewStatus.INVALID_INPUT
    if rs == RoutingStatus.NO_ELIGIBLE_WORKER:
        return PreviewStatus.NO_ELIGIBLE_WORKER
    if rs in (RoutingStatus.BLOCKED_BY_RISK, RoutingStatus.BLOCKED_BY_PRIVACY,
              RoutingStatus.BLOCKED_BY_COST, RoutingStatus.BLOCKED_BY_STATUS):
        return PreviewStatus.BLOCKED
    if rs == RoutingStatus.NEEDS_HUMAN_REVIEW:
        return PreviewStatus.NEEDS_HUMAN_REVIEW
    return PreviewStatus.READY_FOR_REVIEW  # RECOMMENDED


def preview_handoff(packet: Any, workers: Any, *, created_by: str = "mso"
                    ) -> tuple[RoutingRecommendation, HandoffEnvelope | None, OrchestrationPreview]:
    """Pure dry-run: returns (recommendation, envelope|None, preview). No side effects."""
    rec = recommend_worker(packet, workers)
    p_status = _routing_to_preview_status(rec.routing_status)

    envelope: HandoffEnvelope | None = None
    handoff_id = ""
    reasons = list(rec.reasons)
    warnings = list(rec.warnings)
    blockers = list(rec.blockers)

    mission_id = getattr(packet, "mission_id", "") if isinstance(packet, DelegationWorkPacket) else ""
    packet_id = getattr(packet, "packet_id", "") if isinstance(packet, DelegationWorkPacket) else ""

    if p_status in (PreviewStatus.READY_FOR_REVIEW, PreviewStatus.NEEDS_HUMAN_REVIEW) and rec.recommended_worker_id:
        handoff_id = "handoff-" + _hash(mission_id, packet_id, rec.decision_id)[:12]
        try:
            envelope = HandoffEnvelope(
                handoff_id=handoff_id, mission_id=mission_id, packet_id=packet_id,
                routing_decision_id=rec.decision_id,
                target_worker_id=rec.recommended_worker_id,
                target_worker_type=rec.recommended_worker_type,
                created_at=now_iso(), created_by=created_by, objective=packet.objective,
                handoff_status=HandoffStatus.DRAFT,
                input_refs=list(packet.allowed_inputs),
                forbidden_input_refs=list(packet.forbidden_inputs),
                allowed_operations=list(packet.allowed_operations),
                forbidden_operations=list(packet.forbidden_operations),
                constraints=[f"risk_level:{packet.risk_level.value}", f"cost_tier:{packet.cost_tier.value}"],
                expected_outputs=list(packet.expected_outputs),
                verification_plan=list(packet.verification_plan),
                acceptance_criteria=list(packet.acceptance_criteria),
                evidence_refs=list(packet.linked_evidence),
                requires_human_review=True,
            ).validate()
        except Exception as exc:  # noqa: BLE001 — envelope build failure => blocked (fail-closed)
            envelope = None
            handoff_id = ""
            p_status = PreviewStatus.BLOCKED
            blockers = blockers + [f"handoff envelope could not be built: {type(exc).__name__}"]

    steps = [
        f"routing: {rec.routing_status.value}",
        f"eligible worker: {rec.recommended_worker_id or 'none'}",
        f"handoff envelope: {'built (DRAFT)' if envelope is not None else 'not built'}",
        f"human review: {'required' if rec.requires_human_review or p_status == PreviewStatus.NEEDS_HUMAN_REVIEW else 'recommended'}",
        "dispatch: NOT enabled (can_dispatch=false)",
        "execution: NOT enabled (can_execute=false)",
    ]
    evidence_refs = (list(packet.linked_evidence)
                     if isinstance(packet, DelegationWorkPacket) and packet.linked_evidence
                     else ["pending: none captured (dry-run)"])

    preview = OrchestrationPreview(
        preview_id="preview-" + _hash(mission_id, packet_id, rec.decision_id, p_status.value)[:12],
        mission_id=mission_id, packet_id=packet_id, routing_decision_id=rec.decision_id,
        preview_status=p_status, handoff_id=handoff_id,
        selected_worker_id=rec.recommended_worker_id, selected_worker_type=rec.recommended_worker_type,
        steps=steps, reasons=reasons, warnings=warnings, blockers=blockers,
        requires_human_review=bool(rec.requires_human_review or p_status == PreviewStatus.NEEDS_HUMAN_REVIEW
                                   or p_status not in (PreviewStatus.READY_FOR_REVIEW,)),
        created_at=now_iso(), evidence_refs=evidence_refs,
        audit_notes="Dry-run preview only. Dispatches nothing; grants nothing.",
    )
    return rec, envelope, preview


def build_orchestration_preview(packet: Any, workers: Any, *, created_by: str = "mso") -> OrchestrationPreview:
    """Convenience wrapper returning only the preview."""
    _rec, _env, preview = preview_handoff(packet, workers, created_by=created_by)
    return preview


__all__ = [
    "OrchestrationPreviewError", "PreviewStatus", "OrchestrationPreview",
    "build_orchestration_preview", "preview_handoff", "validate_preview", "now_iso",
]
