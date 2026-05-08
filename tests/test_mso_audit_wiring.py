from pathlib import Path
from typing import cast

from assistant_os.audit.paths import candidate_audit_path, police_audit_path
from assistant_os.audit.sink import AuditSink
from assistant_os.audit.stores import (
    CandidateAuditRecordStore,
    PoliceAuditEventStore,
)
from assistant_os.missions.candidate_audit import (
    CandidateAuditEventType,
    CandidateAuditRecord,
)
from assistant_os.mso.audit_wiring import (
    OrchestrationAuditRouter,
    make_default_orchestration_sink,
    persist_orchestration_result,
)
from assistant_os.mso.candidate_orchestration import (
    CandidateOrchestrationOutcome,
    MSOCandidateOrchestrationResult,
)
from assistant_os.police.models import PoliceAuditEvent


class SpoofedRecord:
    event_type = "police.allow"


def _police_event() -> PoliceAuditEvent:
    return PoliceAuditEvent(
        request_id="request-1",
        evaluation_id="evaluation-1",
        event_type="police.allow",
        message="allowed",
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


def _stores(
    tmp_path: Path,
) -> tuple[PoliceAuditEventStore, CandidateAuditRecordStore]:
    return (
        PoliceAuditEventStore(police_audit_path(tmp_path)),
        CandidateAuditRecordStore(candidate_audit_path(tmp_path)),
    )


def _router(tmp_path: Path) -> OrchestrationAuditRouter:
    police_store, candidate_store = _stores(tmp_path)
    return OrchestrationAuditRouter(
        police_store=police_store,
        candidate_store=candidate_store,
    )


def _result(
    outcome: CandidateOrchestrationOutcome,
    *,
    police_audit_event: PoliceAuditEvent | None = None,
    candidate_audit_record: CandidateAuditRecord | None = None,
) -> MSOCandidateOrchestrationResult:
    return MSOCandidateOrchestrationResult(
        outcome=outcome,
        request_id="request-1",
        police_evaluation=None,
        police_audit_event=police_audit_event,
        candidate=None,
        candidate_audit_record=candidate_audit_record,
        detail="audit wiring test",
    )


def test_router_satisfies_audit_sink_shape(tmp_path: Path) -> None:
    sink = cast(AuditSink, _router(tmp_path))

    sink.emit(_police_event())


def test_router_exposes_emit_only(tmp_path: Path) -> None:
    router = _router(tmp_path)

    assert hasattr(router, "emit")
    for method_name in ("read_all", "read", "write", "clear", "delete", "update"):
        assert not hasattr(router, method_name)


def test_police_event_routes_only_to_police_store(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)
    router = OrchestrationAuditRouter(
        police_store=police_store,
        candidate_store=candidate_store,
    )

    router.emit(_police_event())

    assert len(police_store.read_all()) == 1
    assert candidate_store.read_all() == []


def test_candidate_record_routes_only_to_candidate_store(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)
    router = OrchestrationAuditRouter(
        police_store=police_store,
        candidate_store=candidate_store,
    )

    router.emit(_candidate_record())

    assert police_store.read_all() == []
    assert len(candidate_store.read_all()) == 1


def test_mixed_emits_persist_to_separate_jsonl_files(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)
    router = OrchestrationAuditRouter(
        police_store=police_store,
        candidate_store=candidate_store,
    )

    router.emit(_police_event())
    router.emit(_candidate_record())

    assert police_audit_path(tmp_path).exists()
    assert candidate_audit_path(tmp_path).exists()
    assert len(police_store.read_all()) == 1
    assert len(candidate_store.read_all()) == 1


def test_unsupported_object_is_ignored(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)
    router = OrchestrationAuditRouter(
        police_store=police_store,
        candidate_store=candidate_store,
    )

    router.emit(object())

    assert police_store.read_all() == []
    assert candidate_store.read_all() == []


def test_routing_is_not_based_on_spoofed_event_type(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)
    router = OrchestrationAuditRouter(
        police_store=police_store,
        candidate_store=candidate_store,
    )

    router.emit(SpoofedRecord())

    assert police_store.read_all() == []
    assert candidate_store.read_all() == []


def test_make_default_orchestration_sink_uses_tmp_path(tmp_path: Path) -> None:
    router = make_default_orchestration_sink(tmp_path)

    router.emit(_police_event())
    router.emit(_candidate_record())

    assert police_audit_path(tmp_path).exists()
    assert candidate_audit_path(tmp_path).exists()
    for path in (police_audit_path(tmp_path), candidate_audit_path(tmp_path)):
        assert str(path).startswith(str(tmp_path))


def test_persist_candidate_created_writes_both_stores(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)

    persist_orchestration_result(
        _result(
            CandidateOrchestrationOutcome.CANDIDATE_CREATED,
            police_audit_event=_police_event(),
            candidate_audit_record=_candidate_record(),
        ),
        police_store=police_store,
        candidate_store=candidate_store,
    )

    assert len(police_store.read_all()) == 1
    assert len(candidate_store.read_all()) == 1


def test_persist_denied_writes_police_only(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)

    persist_orchestration_result(
        _result(
            CandidateOrchestrationOutcome.DENIED,
            police_audit_event=_police_event(),
            candidate_audit_record=_candidate_record(),
        ),
        police_store=police_store,
        candidate_store=candidate_store,
    )

    assert len(police_store.read_all()) == 1
    assert candidate_store.read_all() == []


def test_persist_requires_confirmation_writes_police_only(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)

    persist_orchestration_result(
        _result(
            CandidateOrchestrationOutcome.REQUIRES_CONFIRMATION,
            police_audit_event=_police_event(),
            candidate_audit_record=_candidate_record(),
        ),
        police_store=police_store,
        candidate_store=candidate_store,
    )

    assert len(police_store.read_all()) == 1
    assert candidate_store.read_all() == []


def test_persist_agent_not_found_writes_nothing(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)

    persist_orchestration_result(
        _result(
            CandidateOrchestrationOutcome.AGENT_NOT_FOUND,
            police_audit_event=_police_event(),
            candidate_audit_record=_candidate_record(),
        ),
        police_store=police_store,
        candidate_store=candidate_store,
    )

    assert police_store.read_all() == []
    assert candidate_store.read_all() == []


def test_result_persistence_tolerates_none_fields(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)

    persist_orchestration_result(
        _result(CandidateOrchestrationOutcome.DENIED),
        police_store=police_store,
        candidate_store=candidate_store,
    )

    assert police_store.read_all() == []
    assert candidate_store.read_all() == []


def test_round_trip_records_preserve_expected_fields(tmp_path: Path) -> None:
    police_store, candidate_store = _stores(tmp_path)
    router = OrchestrationAuditRouter(
        police_store=police_store,
        candidate_store=candidate_store,
    )

    router.emit(_police_event())
    router.emit(_candidate_record())

    police_records = police_store.read_all()
    candidate_records = candidate_store.read_all()
    assert police_records[0]["event_type"] == "police.allow"
    assert police_records[0]["request_id"] == "request-1"
    assert candidate_records[0]["event_type"] == "candidate_created"
    assert candidate_records[0]["candidate_id"] == "candidate-1"
