from pathlib import Path
from typing import cast

from assistant_os.audit.jsonl_store import JsonlAuditStore
from assistant_os.audit.sink import AuditSink
from assistant_os.audit.stores import (
    CandidateAuditRecordStore,
    PoliceAuditEventStore,
)


class EmitOnlySink:
    def __init__(self) -> None:
        self.records: list[object] = []

    def emit(self, record: object) -> None:
        self.records.append(record)


class SimpleRecord:
    event_type = "simple.record"

    def to_dict(self) -> dict[str, object]:
        return {"event_type": self.event_type, "value": "ok"}


def test_audit_sink_protocol_accepts_emit_only_objects() -> None:
    sink = cast(AuditSink, EmitOnlySink())

    sink.emit({"event_type": "example"})


def test_jsonl_audit_store_satisfies_audit_sink(tmp_path: Path) -> None:
    sink = cast(AuditSink, JsonlAuditStore(tmp_path / "audit.jsonl"))

    sink.emit(SimpleRecord())


def test_store_classes_expose_emit() -> None:
    assert hasattr(PoliceAuditEventStore, "emit")
    assert hasattr(CandidateAuditRecordStore, "emit")


def test_protocol_does_not_require_read_or_write() -> None:
    assert not hasattr(AuditSink, "read")
    assert not hasattr(AuditSink, "read_all")
    assert not hasattr(AuditSink, "write")


def test_audit_sink_has_no_authority_methods() -> None:
    for method_name in ("allow", "deny", "permitted", "authorize"):
        assert not hasattr(AuditSink, method_name)
        assert not hasattr(PoliceAuditEventStore, method_name)
        assert not hasattr(CandidateAuditRecordStore, method_name)
