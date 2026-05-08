from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from assistant_os.audit.stores import (
    CandidateAuditRecordStore,
    PoliceAuditEventStore,
)
from assistant_os.missions.candidate_audit import (
    CandidateAuditEventType,
    CandidateAuditRecord,
)
from assistant_os.police.models import PoliceAuditEvent
from assistant_os.query.audit_records import (
    CandidateAuditRecordReadModel,
    OrchestrationAuditEntry,
    PoliceAuditEventReadModel,
    _parse_candidate_audit_record,
    _parse_police_audit_event,
    build_orchestration_audit_timeline,
    list_candidate_audit_records,
    list_police_audit_events,
)


def _police_raw(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "_seq": 1,
        "event_id": "event-1",
        "request_id": "request-1",
        "evaluation_id": "evaluation-1",
        "event_type": "police.allow",
        "message": "recorded",
        "actor": "police",
        "created_at": "2026-05-08T00:00:00+00:00",
        "metadata": {"source": "test"},
    }
    raw.update(overrides)
    return raw


def _candidate_raw(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "_seq": 1,
        "audit_id": "audit-1",
        "event_type": "candidate_created",
        "candidate_id": "candidate-1",
        "mission_id": "mission-1",
        "activity_id": "activity-1",
        "agent_id": "agent-1",
        "police_evaluation_id": "evaluation-1",
        "police_evaluation_outcome": "ALLOW",
        "operation_key": "operation-1",
        "created_at": "2026-05-08T00:00:01+00:00",
    }
    raw.update(overrides)
    return raw


def _police_event(evaluation_id: str = "evaluation-1") -> PoliceAuditEvent:
    return PoliceAuditEvent(
        request_id="request-1",
        evaluation_id=evaluation_id,
        event_type="police.allow",
        message="recorded",
        actor="police",
    )


def _candidate_record(evaluation_id: str = "evaluation-1") -> CandidateAuditRecord:
    return CandidateAuditRecord(
        event_type=CandidateAuditEventType.CANDIDATE_CREATED,
        candidate_id="candidate-1",
        mission_id="mission-1",
        activity_id="activity-1",
        workstream_id="workstream-1",
        agent_id="agent-1",
        agent_profile_id="profile-1",
        request_id="request-1",
        police_evaluation_id=evaluation_id,
        police_evaluation_outcome="ALLOW",
        operation_key="operation-1",
    )


def _stores(
    tmp_path: Path,
) -> tuple[PoliceAuditEventStore, CandidateAuditRecordStore]:
    return (
        PoliceAuditEventStore(tmp_path / "police.jsonl"),
        CandidateAuditRecordStore(tmp_path / "candidate.jsonl"),
    )


def test_valid_police_raw_dict_parses_into_read_model() -> None:
    parsed = _parse_police_audit_event(_police_raw())

    assert parsed == PoliceAuditEventReadModel(
        event_id="event-1",
        request_id="request-1",
        evaluation_id="evaluation-1",
        event_type="police.allow",
        message="recorded",
        actor="police",
        created_at="2026-05-08T00:00:00+00:00",
        metadata={"source": "test"},
        raw_seq=1,
    )


def test_police_raw_dict_missing_required_field_returns_none() -> None:
    raw = _police_raw()
    raw.pop("event_id")

    assert _parse_police_audit_event(raw) is None


def test_police_raw_dict_missing_metadata_defaults_to_empty_mapping() -> None:
    raw = _police_raw()
    raw.pop("metadata")

    parsed = _parse_police_audit_event(raw)

    assert parsed is not None
    assert parsed.metadata == {}


def test_valid_candidate_raw_dict_parses_into_read_model() -> None:
    parsed = _parse_candidate_audit_record(_candidate_raw())

    assert parsed == CandidateAuditRecordReadModel(
        audit_id="audit-1",
        event_type="candidate_created",
        candidate_id="candidate-1",
        mission_id="mission-1",
        activity_id="activity-1",
        agent_id="agent-1",
        police_evaluation_id="evaluation-1",
        police_evaluation_outcome="ALLOW",
        operation_key="operation-1",
        created_at="2026-05-08T00:00:01+00:00",
        raw_seq=1,
    )


def test_candidate_raw_dict_missing_required_field_returns_none() -> None:
    raw = _candidate_raw()
    raw.pop("candidate_id")

    assert _parse_candidate_audit_record(raw) is None


def test_empty_police_store_returns_empty_list(tmp_path: Path) -> None:
    police_store, _candidate_store = _stores(tmp_path)

    assert list_police_audit_events(police_store) == []


def test_empty_candidate_store_returns_empty_list(tmp_path: Path) -> None:
    _police_store, candidate_store = _stores(tmp_path)

    assert list_candidate_audit_records(candidate_store) == []


def test_police_store_record_returns_typed_model(tmp_path: Path) -> None:
    police_store, _candidate_store = _stores(tmp_path)
    police_store.emit(_police_event())

    records = list_police_audit_events(police_store)

    assert len(records) == 1
    assert isinstance(records[0], PoliceAuditEventReadModel)


def test_candidate_store_record_returns_typed_model(tmp_path: Path) -> None:
    _police_store, candidate_store = _stores(tmp_path)
    candidate_store.emit(_candidate_record())

    records = list_candidate_audit_records(candidate_store)

    assert len(records) == 1
    assert isinstance(records[0], CandidateAuditRecordReadModel)


def test_timeline_joins_linked_records(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)
    police_store.emit(_police_event("evaluation-linked"))
    candidate_store.emit(_candidate_record("evaluation-linked"))

    timeline = build_orchestration_audit_timeline(police_store, candidate_store)

    assert timeline == [
        OrchestrationAuditEntry(
            police_event=list_police_audit_events(police_store)[0],
            candidate_record=list_candidate_audit_records(candidate_store)[0],
        )
    ]


def test_timeline_includes_police_only_record_with_none_candidate(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)
    police_store.emit(_police_event())

    timeline = build_orchestration_audit_timeline(police_store, candidate_store)

    assert len(timeline) == 1
    assert timeline[0].candidate_record is None


def test_orphan_candidate_record_is_excluded_from_timeline(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)
    candidate_store.emit(_candidate_record())

    assert build_orchestration_audit_timeline(police_store, candidate_store) == []


def test_read_models_are_frozen() -> None:
    parsed = _parse_police_audit_event(_police_raw())
    assert parsed is not None

    with pytest.raises(FrozenInstanceError):
        parsed.event_id = "changed"
