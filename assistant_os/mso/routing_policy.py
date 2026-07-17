"""Model / Worker Routing Policy v0 — recommend a worker (NOT operational routing).

PR: Model / Worker Routing Policy v0.

Evaluates a ``DelegationWorkPacket`` (#264) against ``list[WorkerProfile]`` (#265)
and produces a ``RoutingRecommendation``. This is a **recommendation, not a router**.

It does NOT execute, call models, contact external APIs, run a Runner, use a queue,
mint a capability token, grant authority, or perform automatic handoff. ``can_execute``
is hard-wired ``False``. A recommendation is not an authorization; a recommended worker
is not an automatic handoff.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .delegation_packet import DelegationWorkPacket, CostTier, RiskLevel, TargetWorker
from .worker_registry import WorkerProfile, WorkerType, PrivacyClass


class RoutingStatus(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    NO_ELIGIBLE_WORKER = "NO_ELIGIBLE_WORKER"
    BLOCKED_BY_RISK = "BLOCKED_BY_RISK"
    BLOCKED_BY_PRIVACY = "BLOCKED_BY_PRIVACY"
    BLOCKED_BY_COST = "BLOCKED_BY_COST"
    BLOCKED_BY_STATUS = "BLOCKED_BY_STATUS"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    INVALID_INPUT = "INVALID_INPUT"


_RISK_RANK = {
    RiskLevel.READ_ONLY: 0,
    RiskLevel.DOCS_ONLY: 1,
    RiskLevel.PATCH_ALLOWED: 2,
    RiskLevel.EXTERNAL_WRITE_REQUIRES_CONFIRMATION: 3,
    RiskLevel.EXTERNAL_WRITE_PROHIBITED: 4,
    RiskLevel.BLOCKED: 99,
}

# Mismatch reason -> RoutingStatus category (for single-cause aggregation).
_STATUS = "status"; _COST = "cost"; _RISK = "risk"; _PRIVACY = "privacy"; _TASK = "task"; _TARGET = "target"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _requires_local(packet: DelegationWorkPacket) -> bool:
    low = {str(x).lower() for x in packet.forbidden_inputs}
    return "cloud" in low or "external" in low


def _requires_secret_access(packet: DelegationWorkPacket) -> bool:
    return any(str(x).lower() == "secrets" for x in packet.allowed_inputs)


@dataclass(slots=True)
class RoutingRecommendation:
    decision_id: str
    packet_id: str
    mission_id: str
    routing_status: RoutingStatus
    recommended_worker_id: str = ""
    recommended_worker_type: str = ""
    recommended_model_preference: str = ""
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    cost_tier: str = ""
    risk_level: str = ""
    requires_human_review: bool = True
    can_execute: bool = False
    created_at: str = ""
    audit_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["routing_status"] = self.routing_status.value
        d["can_execute"] = False  # derived, never a grant
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoutingRecommendation":
        allowed = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        kw = {k: v for k, v in data.items() if k in allowed}
        if "routing_status" in kw and not isinstance(kw["routing_status"], RoutingStatus):
            kw["routing_status"] = RoutingStatus(kw["routing_status"])
        return cls(**kw)


def explain_worker_mismatch(packet: DelegationWorkPacket, worker: WorkerProfile) -> list[str]:
    """Return reasons the worker is NOT eligible for the packet. Empty == eligible.

    Never raises; never leaks secrets (reasons name fields/enums only).
    """
    reasons: list[str] = []
    if not worker.is_assignable():
        reasons.append(f"{_STATUS}: worker not assignable (status {worker.status.value})")
    if (packet.target_worker != TargetWorker.UNASSIGNED
            and worker.worker_type.value != packet.target_worker.value):
        reasons.append(
            f"{_TARGET}: packet targets {packet.target_worker.value}; "
            f"worker type is {worker.worker_type.value}"
        )
    if packet.task_type.value in worker.forbidden_task_types:
        reasons.append(f"{_TASK}: task_type {packet.task_type.value} is forbidden by worker")
    if packet.cost_tier.value not in worker.supported_cost_tiers:
        reasons.append(f"{_COST}: cost_tier {packet.cost_tier.value} not supported by worker")
    if _RISK_RANK.get(packet.risk_level, 0) > _RISK_RANK.get(worker.max_risk_level, 0):
        reasons.append(f"{_RISK}: packet risk {packet.risk_level.value} exceeds worker max {worker.max_risk_level.value}")
    if _requires_local(packet) and worker.worker_type != WorkerType.LOCAL_MODEL:
        reasons.append(f"{_PRIVACY}: packet requires a local worker; worker is {worker.worker_type.value}")
    if _requires_secret_access(packet) and (not worker.can_access_secrets or worker.privacy_class == PrivacyClass.SECRET_PROHIBITED):
        reasons.append(f"{_PRIVACY}: packet needs secret-context handling; worker cannot (privacy {worker.privacy_class.value})")
    return reasons


def eligible_workers(packet: DelegationWorkPacket, workers: list[WorkerProfile]) -> list[WorkerProfile]:
    """Deterministically ordered eligible workers. LOCAL_MODEL preferred when the
    packet requires/prefers local. No unsafe fallback: ineligible workers excluded."""
    prefer_local = _requires_local(packet) or packet.cost_tier == CostTier.LOCAL_PREFERRED
    elig = [w for w in workers if isinstance(w, WorkerProfile) and not explain_worker_mismatch(packet, w)]

    def _key(w: WorkerProfile):
        local_rank = 0 if (prefer_local and w.worker_type == WorkerType.LOCAL_MODEL) else 1
        return (local_rank, w.worker_id)

    return sorted(elig, key=_key)


def _decision_id(packet_id: str, worker_id: str, status: RoutingStatus) -> str:
    raw = f"{packet_id}|{worker_id}|{status.value}".encode("utf-8")
    return "routing-" + hashlib.sha256(raw).hexdigest()[:16]


def recommend_worker(packet: Any, workers: Any) -> RoutingRecommendation:
    """Recommend a worker for a packet. Fail-closed; recommendation != authorization."""
    # --- input validation (fail-closed) ---
    if not isinstance(packet, DelegationWorkPacket) or not isinstance(workers, list):
        return RoutingRecommendation(
            decision_id=_decision_id("?", "", RoutingStatus.INVALID_INPUT),
            packet_id="", mission_id="", routing_status=RoutingStatus.INVALID_INPUT,
            blockers=["invalid input: packet/workers types"], created_at=_now_iso())
    if not packet.is_valid():
        return RoutingRecommendation(
            decision_id=_decision_id(packet.packet_id, "", RoutingStatus.INVALID_INPUT),
            packet_id=packet.packet_id, mission_id=packet.mission_id,
            routing_status=RoutingStatus.INVALID_INPUT,
            blockers=packet.validation_errors(), created_at=_now_iso())

    base = dict(packet_id=packet.packet_id, mission_id=packet.mission_id,
                cost_tier=packet.cost_tier.value, risk_level=packet.risk_level.value,
                created_at=_now_iso())

    # --- global risk block ---
    if packet.risk_level == RiskLevel.BLOCKED:
        return RoutingRecommendation(
            decision_id=_decision_id(packet.packet_id, "", RoutingStatus.BLOCKED_BY_RISK),
            routing_status=RoutingStatus.BLOCKED_BY_RISK,
            blockers=["packet risk_level is BLOCKED"], **base)

    elig = eligible_workers(packet, workers)

    if not elig:
        # Aggregate mismatch categories; if a single category explains all, use it.
        cats: set[str] = set()
        all_reasons: list[str] = []
        for w in workers:
            if not isinstance(w, WorkerProfile):
                continue
            rs = explain_worker_mismatch(packet, w)
            all_reasons.extend(rs)
            cats.update(r.split(":", 1)[0] for r in rs)
        status = RoutingStatus.NO_ELIGIBLE_WORKER
        if cats == {_COST}:
            status = RoutingStatus.BLOCKED_BY_COST
        elif cats == {_PRIVACY}:
            status = RoutingStatus.BLOCKED_BY_PRIVACY
        elif cats == {_STATUS}:
            status = RoutingStatus.BLOCKED_BY_STATUS
        elif cats == {_RISK}:
            status = RoutingStatus.BLOCKED_BY_RISK
        return RoutingRecommendation(
            decision_id=_decision_id(packet.packet_id, "", status),
            routing_status=status,
            blockers=sorted(set(all_reasons)) or ["no workers provided"],
            reasons=["no eligible worker; no unsafe fallback chosen"], **base)

    chosen = elig[0]
    hard_review = (packet.cost_tier == CostTier.PREMIUM_REQUIRED
                   or packet.risk_level == RiskLevel.EXTERNAL_WRITE_REQUIRES_CONFIRMATION)
    requires_review = bool(packet.human_review_required or chosen.requires_human_supervision or hard_review)
    status = RoutingStatus.NEEDS_HUMAN_REVIEW if hard_review else RoutingStatus.RECOMMENDED

    warnings: list[str] = []
    if chosen.preferred_task_types and packet.task_type.value not in chosen.preferred_task_types:
        warnings.append(f"task_type {packet.task_type.value} is not among worker preferred types")
    if len(elig) > 1:
        warnings.append(f"{len(elig)} eligible workers; chose deterministically")

    return RoutingRecommendation(
        decision_id=_decision_id(packet.packet_id, chosen.worker_id, status),
        routing_status=status,
        recommended_worker_id=chosen.worker_id,
        recommended_worker_type=chosen.worker_type.value,
        recommended_model_preference=(chosen.model_name or chosen.model_family or ""),
        reasons=[f"worker {chosen.worker_id} eligible for {packet.task_type.value}"],
        warnings=warnings,
        requires_human_review=requires_review,
        **base)


__all__ = [
    "RoutingStatus", "RoutingRecommendation",
    "recommend_worker", "eligible_workers", "explain_worker_mismatch",
]
