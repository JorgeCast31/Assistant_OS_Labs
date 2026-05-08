from __future__ import annotations

from pathlib import Path

from assistant_os.audit.paths import candidate_audit_path, police_audit_path
from assistant_os.audit.stores import (
    CandidateAuditRecordStore,
    PoliceAuditEventStore,
)
from assistant_os.missions.candidate_audit import CandidateAuditRecord
from assistant_os.mso.candidate_orchestration import (
    CandidateOrchestrationOutcome,
    MSOCandidateOrchestrationResult,
)
from assistant_os.police.models import PoliceAuditEvent


class OrchestrationAuditRouter:
    def __init__(
        self,
        *,
        police_store: PoliceAuditEventStore,
        candidate_store: CandidateAuditRecordStore,
    ) -> None:
        self._police_store = police_store
        self._candidate_store = candidate_store

    def emit(self, record: object) -> None:
        if isinstance(record, PoliceAuditEvent):
            self._police_store.emit(record)
        elif isinstance(record, CandidateAuditRecord):
            self._candidate_store.emit(record)


def make_default_orchestration_sink(
    base_dir: Path | str | None = None,
) -> OrchestrationAuditRouter:
    resolved_base_dir = None if base_dir is None else Path(base_dir)
    police_path = (
        police_audit_path()
        if resolved_base_dir is None
        else police_audit_path(resolved_base_dir)
    )
    candidate_path = (
        candidate_audit_path()
        if resolved_base_dir is None
        else candidate_audit_path(resolved_base_dir)
    )
    return OrchestrationAuditRouter(
        police_store=PoliceAuditEventStore(police_path),
        candidate_store=CandidateAuditRecordStore(candidate_path),
    )


def persist_orchestration_result(
    result: MSOCandidateOrchestrationResult,
    *,
    police_store: PoliceAuditEventStore,
    candidate_store: CandidateAuditRecordStore,
) -> None:
    router = OrchestrationAuditRouter(
        police_store=police_store,
        candidate_store=candidate_store,
    )

    if result.outcome is CandidateOrchestrationOutcome.AGENT_NOT_FOUND:
        return

    if result.police_audit_event is not None:
        router.emit(result.police_audit_event)

    if (
        result.outcome is CandidateOrchestrationOutcome.CANDIDATE_CREATED
        and result.candidate_audit_record is not None
    ):
        router.emit(result.candidate_audit_record)
