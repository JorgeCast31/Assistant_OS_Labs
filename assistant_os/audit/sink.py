from __future__ import annotations

from typing import Protocol


class AuditSink(Protocol):
    def emit(self, record: object) -> None: ...
