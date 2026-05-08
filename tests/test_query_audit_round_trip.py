from pathlib import Path

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
    build_orchestration_audit_timeline,
    list_candidate_audit_records,
    list_police_audit_events,
)


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
) -> tuple[PoliceAuditEventStore, CandidateAuditRecordStore, Path, Path]:
    police_path = tmp_path / "police.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    return (
        PoliceAuditEventStore(police_path),
        CandidateAuditRecordStore(candidate_path),
        police_path,
        candidate_path,
    )


def test_police_store_emit_then_query_reads_back_event(tmp_path: Path) -> None:
    police_store, _candidate_store, _police_path, _candidate_path = _stores(tmp_path)
    police_store.emit(_police_event())

    records = list_police_audit_events(police_store)

    assert len(records) == 1
    assert records[0].evaluation_id == "evaluation-1"
    assert records[0].raw_seq == 1


def test_candidate_store_emit_then_query_reads_back_candidate(tmp_path: Path) -> None:
    _police_store, candidate_store, _police_path, _candidate_path = _stores(tmp_path)
    candidate_store.emit(_candidate_record())

    records = list_candidate_audit_records(candidate_store)

    assert len(records) == 1
    assert records[0].candidate_id == "candidate-1"
    assert records[0].raw_seq == 1


def test_linked_records_build_one_joined_timeline_entry(tmp_path: Path) -> None:
    police_store, candidate_store, _police_path, _candidate_path = _stores(tmp_path)
    police_store.emit(_police_event("evaluation-linked"))
    candidate_store.emit(_candidate_record("evaluation-linked"))

    timeline = build_orchestration_audit_timeline(police_store, candidate_store)

    assert len(timeline) == 1
    assert timeline[0].police_event.evaluation_id == "evaluation-linked"
    assert timeline[0].candidate_record is not None
    assert timeline[0].candidate_record.police_evaluation_id == "evaluation-linked"


def test_corrupted_jsonl_line_is_skipped_with_no_exception(tmp_path: Path) -> None:
    police_store, _candidate_store, police_path, _candidate_path = _stores(tmp_path)
    police_store.emit(_police_event())
    with police_path.open("a", encoding="utf-8") as handle:
        handle.write("{not-json}\n")

    records = list_police_audit_events(police_store)

    assert len(records) == 1
    assert records[0].event_type == "police.allow"


def test_query_functions_do_not_write_to_files(tmp_path: Path) -> None:
    police_store, candidate_store, police_path, candidate_path = _stores(tmp_path)
    police_store.emit(_police_event())
    candidate_store.emit(_candidate_record())
    before = {
        police_path: police_path.read_text(encoding="utf-8"),
        candidate_path: candidate_path.read_text(encoding="utf-8"),
    }

    list_police_audit_events(police_store)
    list_candidate_audit_records(candidate_store)
    build_orchestration_audit_timeline(police_store, candidate_store)

    assert police_path.read_text(encoding="utf-8") == before[police_path]
    assert candidate_path.read_text(encoding="utf-8") == before[candidate_path]


def test_query_functions_do_not_mutate_store_contents(tmp_path: Path) -> None:
    police_store, candidate_store, _police_path, _candidate_path = _stores(tmp_path)
    police_store.emit(_police_event())
    candidate_store.emit(_candidate_record())
    before_police = police_store.read_all()
    before_candidate = candidate_store.read_all()

    list_police_audit_events(police_store)
    list_candidate_audit_records(candidate_store)
    build_orchestration_audit_timeline(police_store, candidate_store)

    assert police_store.read_all() == before_police
    assert candidate_store.read_all() == before_candidate
