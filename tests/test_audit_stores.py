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


def _police_event() -> PoliceAuditEvent:
    return PoliceAuditEvent(
        request_id="request-1",
        evaluation_id="evaluation-1",
        event_type="police.allow",
        message="allowed for audit test",
        actor="police",
    )


def _candidate_record() -> CandidateAuditRecord:
    return CandidateAuditRecord(
        event_type=CandidateAuditEventType.CANDIDATE_CREATED,
        candidate_id="candidate-1",
        mission_id="mission-1",
        activity_id="activity-1",
        workstream_id="workstream-1",
        agent_id="agent-1",
        agent_profile_id="profile-1",
        request_id="request-1",
        police_evaluation_id="evaluation-1",
        police_evaluation_outcome="ALLOW",
        operation_key="operation-1",
    )


@pytest.mark.parametrize(
    ("store_type", "record_factory", "path_name"),
    [
        (PoliceAuditEventStore, _police_event, "police.jsonl"),
        (CandidateAuditRecordStore, _candidate_record, "candidate.jsonl"),
    ],
)
def test_store_emits_reads_and_survives_restart(
    tmp_path: Path,
    store_type: type,
    record_factory: object,
    path_name: str,
) -> None:
    path = tmp_path / path_name
    store = store_type(path)
    store.emit(record_factory())

    records = store.read_all()
    restarted = store_type(path)

    assert isinstance(records, list)
    assert len(records) == 1
    assert path.exists()
    assert str(path).startswith(str(tmp_path))
    assert restarted.read_all() == records


@pytest.mark.parametrize(
    "store",
    [
        PoliceAuditEventStore,
        CandidateAuditRecordStore,
    ],
)
def test_store_has_no_mutation_helpers(tmp_path: Path, store: type) -> None:
    instance = store(tmp_path / "audit.jsonl")

    for method_name in ("clear", "delete", "update"):
        assert not hasattr(instance, method_name)


def test_wrong_record_type_raises_type_error(tmp_path: Path) -> None:
    store = PoliceAuditEventStore(tmp_path / "police.jsonl")

    with pytest.raises(TypeError):
        store.emit(_candidate_record())


def test_seq_is_monotonic_when_present(tmp_path: Path) -> None:
    store = PoliceAuditEventStore(tmp_path / "police.jsonl")
    store.emit(_police_event())
    store.emit(_police_event())

    records = store.read_all()
    seqs = [record["_seq"] for record in records if "_seq" in record]

    assert seqs == sorted(seqs)
    assert seqs == [1, 2]


def test_police_event_does_not_affect_candidate_store(tmp_path: Path) -> None:
    police_store = PoliceAuditEventStore(tmp_path / "police.jsonl")
    candidate_store = CandidateAuditRecordStore(tmp_path / "candidate.jsonl")

    police_store.emit(_police_event())

    assert len(police_store.read_all()) == 1
    assert candidate_store.read_all() == []


def test_candidate_paths_are_injectable_and_under_tmp_path(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "candidate.jsonl"
    store = CandidateAuditRecordStore(path)

    store.emit(_candidate_record())

    assert path.exists()
    assert "docs" not in path.parts
    assert "atlas" not in path.parts
