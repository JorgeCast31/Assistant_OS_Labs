from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from assistant_os.audit.stores import (
    CandidateAuditRecordStore,
    PoliceAuditEventStore,
)


_OBSERVATIONAL_ONLY = (
    "Query results are observational. "
    "They do not represent authority to execute and must not be consulted as a gate."
)


@dataclass(frozen=True)
class PoliceAuditEventReadModel:
    event_id: str
    request_id: str
    evaluation_id: str
    event_type: str
    message: str
    actor: str
    created_at: str
    metadata: Mapping[str, object]
    raw_seq: int | None


@dataclass(frozen=True)
class CandidateAuditRecordReadModel:
    audit_id: str
    event_type: str
    candidate_id: str
    mission_id: str
    activity_id: str | None
    agent_id: str
    police_evaluation_id: str
    police_evaluation_outcome: str
    operation_key: str
    created_at: str
    raw_seq: int | None


@dataclass(frozen=True)
class OrchestrationAuditEntry:
    police_event: PoliceAuditEventReadModel
    candidate_record: CandidateAuditRecordReadModel | None


def list_police_audit_events(
    store: PoliceAuditEventStore,
) -> list[PoliceAuditEventReadModel]:
    return [
        parsed
        for raw in store.read_all()
        if (parsed := _parse_police_audit_event(raw)) is not None
    ]


def list_candidate_audit_records(
    store: CandidateAuditRecordStore,
) -> list[CandidateAuditRecordReadModel]:
    return [
        parsed
        for raw in store.read_all()
        if (parsed := _parse_candidate_audit_record(raw)) is not None
    ]


def build_orchestration_audit_timeline(
    police_store: PoliceAuditEventStore,
    candidate_store: CandidateAuditRecordStore,
) -> list[OrchestrationAuditEntry]:
    candidate_by_evaluation = {
        record.police_evaluation_id: record
        for record in list_candidate_audit_records(candidate_store)
    }

    return [
        OrchestrationAuditEntry(
            police_event=event,
            candidate_record=candidate_by_evaluation.get(event.evaluation_id),
        )
        for event in list_police_audit_events(police_store)
    ]


def _parse_police_audit_event(
    raw: Mapping[str, object],
) -> PoliceAuditEventReadModel | None:
    event_id = _required_str(raw, "event_id")
    request_id = _required_str(raw, "request_id")
    evaluation_id = _required_str(raw, "evaluation_id")
    event_type = _required_str(raw, "event_type")
    message = _required_str(raw, "message")
    actor = _required_str(raw, "actor")
    created_at = _required_str(raw, "created_at")
    metadata = raw.get("metadata")

    if (
        event_id is None
        or request_id is None
        or evaluation_id is None
        or event_type is None
        or message is None
        or actor is None
        or created_at is None
    ):
        return None
    metadata_dict = dict(metadata) if isinstance(metadata, Mapping) else {}

    return PoliceAuditEventReadModel(
        event_id=event_id,
        request_id=request_id,
        evaluation_id=evaluation_id,
        event_type=event_type,
        message=message,
        actor=actor,
        created_at=created_at,
        metadata=MappingProxyType(metadata_dict),
        raw_seq=_optional_int(raw, "_seq"),
    )


def _parse_candidate_audit_record(
    raw: Mapping[str, object],
) -> CandidateAuditRecordReadModel | None:
    audit_id = _required_str(raw, "audit_id")
    event_type = _required_str(raw, "event_type")
    candidate_id = _required_str(raw, "candidate_id")
    mission_id = _required_str(raw, "mission_id")
    activity_id = _optional_str(raw, "activity_id")
    agent_id = _required_str(raw, "agent_id")
    police_evaluation_id = _required_str(raw, "police_evaluation_id")
    police_evaluation_outcome = _required_str(raw, "police_evaluation_outcome")
    operation_key = _required_str(raw, "operation_key")
    created_at = _required_str(raw, "created_at")

    if (
        audit_id is None
        or event_type is None
        or candidate_id is None
        or mission_id is None
        or agent_id is None
        or police_evaluation_id is None
        or police_evaluation_outcome is None
        or operation_key is None
        or created_at is None
    ):
        return None

    return CandidateAuditRecordReadModel(
        audit_id=audit_id,
        event_type=event_type,
        candidate_id=candidate_id,
        mission_id=mission_id,
        activity_id=activity_id,
        agent_id=agent_id,
        police_evaluation_id=police_evaluation_id,
        police_evaluation_outcome=police_evaluation_outcome,
        operation_key=operation_key,
        created_at=created_at,
        raw_seq=_optional_int(raw, "_seq"),
    )


def _required_str(raw: Mapping[str, object], key: str) -> str | None:
    value = raw.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _optional_str(raw: Mapping[str, object], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return None


def _optional_int(raw: Mapping[str, object], key: str) -> int | None:
    value = raw.get(key)
    if isinstance(value, int):
        return value
    return None
