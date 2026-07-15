"""Mission Inbox / Preview Index v0 — read-only index of preview bundles.

PR: Mission Inbox / Preview Index v0.

Scans a folder of preview *bundles* (``*.preview-bundle.json``, #269) and builds an
auditable index of the dry-run previews (#268) — for human review.

    python -m assistant_os.mso.mission_inbox_index docs/mission/inbox

WHAT THIS IS NOT
----------------
It does NOT run missions, dispatch, execute, call models/APIs, run a Runner, use a
real queue/scheduler, mint tokens, grant authority, WRITE/move/rename/delete files,
or mark work as processed. It is read-only + index only. ``can_execute`` and
``can_dispatch`` are always ``False``.

> inbox ≠ real queue · index ≠ execution · preview ≠ dispatch · valid bundle ≠ authorization ·
> stdout JSON is review/simulation evidence, not execution proof.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .orchestration_preview_io import (
    OrchestrationBundleError, load_bundle_from_path, build_preview_from_bundle,
)


class MissionInboxError(ValueError):
    """Raised when the inbox path itself cannot be scanned (fail-closed)."""


class InboxRecordStatus(str, Enum):
    VALID_PREVIEW = "VALID_PREVIEW"
    INVALID_BUNDLE = "INVALID_BUNDLE"
    NO_ELIGIBLE_WORKER = "NO_ELIGIBLE_WORKER"
    BLOCKED = "BLOCKED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    SKIPPED_UNSUPPORTED_FILE = "SKIPPED_UNSUPPORTED_FILE"
    ERROR = "ERROR"


_BUNDLE_SUFFIX = ".preview-bundle.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _map_preview_status(ps: str) -> InboxRecordStatus:
    return {
        "READY_FOR_REVIEW": InboxRecordStatus.VALID_PREVIEW,
        "NEEDS_HUMAN_REVIEW": InboxRecordStatus.NEEDS_HUMAN_REVIEW,
        "NO_ELIGIBLE_WORKER": InboxRecordStatus.NO_ELIGIBLE_WORKER,
        "BLOCKED": InboxRecordStatus.BLOCKED,
        "EXPIRED": InboxRecordStatus.BLOCKED,
        "INVALID_INPUT": InboxRecordStatus.INVALID_BUNDLE,
    }.get(ps, InboxRecordStatus.BLOCKED)


@dataclass(slots=True)
class InboxPreviewRecord:
    source_path: str
    status: InboxRecordStatus
    bundle_id: str = ""
    preview_status: str = ""
    recommended_worker_id: str = ""
    requires_human_review: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    audit_notes: str = ""

    @property
    def can_execute(self) -> bool:
        return False

    @property
    def can_dispatch(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["can_execute"] = False
        d["can_dispatch"] = False
        return d


@dataclass(slots=True)
class MissionInboxIndex:
    inbox_path: str
    created_at: str
    total_files: int
    valid_bundles: int
    invalid_bundles: int
    records: list[InboxPreviewRecord] = field(default_factory=list)
    audit_notes: str = ""

    @property
    def can_execute(self) -> bool:
        return False

    @property
    def can_dispatch(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "inbox_path": self.inbox_path,
            "created_at": self.created_at,
            "total_files": self.total_files,
            "valid_bundles": self.valid_bundles,
            "invalid_bundles": self.invalid_bundles,
            "records": [r.to_dict() for r in self.records],
            "can_execute": False,
            "can_dispatch": False,
            "audit_notes": self.audit_notes,
        }


def scan_bundle_file(path: str, *, strict_unknown: bool = True) -> InboxPreviewRecord:
    """Read-only: build one record for a single bundle file. Never raises for content."""
    name = os.path.basename(path)
    if not name.endswith(_BUNDLE_SUFFIX):
        return InboxPreviewRecord(source_path=path, status=InboxRecordStatus.SKIPPED_UNSUPPORTED_FILE,
                                  audit_notes=f"unsupported file (expected *{_BUNDLE_SUFFIX})")
    try:
        bundle = load_bundle_from_path(path, strict_unknown=strict_unknown)
    except OrchestrationBundleError as exc:
        return InboxPreviewRecord(source_path=path, status=InboxRecordStatus.INVALID_BUNDLE,
                                  errors=[str(exc)])
    try:
        preview = build_preview_from_bundle(bundle)
        pd = preview.to_dict()
    except Exception as exc:  # noqa: BLE001 — per-file fail-soft; never breaks the index
        return InboxPreviewRecord(source_path=path, status=InboxRecordStatus.ERROR,
                                  bundle_id=getattr(bundle, "bundle_id", ""),
                                  errors=[f"preview build failed: {type(exc).__name__}"])
    ps = str(pd.get("preview_status", ""))
    return InboxPreviewRecord(
        source_path=path, status=_map_preview_status(ps), bundle_id=bundle.bundle_id,
        preview_status=ps, recommended_worker_id=str(pd.get("selected_worker_id", "")),
        requires_human_review=bool(pd.get("requires_human_review", True)),
        warnings=list(pd.get("warnings", [])),
    )


def scan_inbox(path: str | os.PathLike[str], *, strict_unknown: bool = True) -> MissionInboxIndex:
    """Read-only scan of a directory. Fail-closed on a bad path. No writes/moves."""
    p = os.fspath(path)
    if not os.path.isdir(p):
        raise MissionInboxError(f"inbox path is not a directory: {p}")
    try:
        names = sorted(os.listdir(p))  # deterministic lexicographic order
    except OSError as exc:
        raise MissionInboxError(f"could not read inbox {p}: {exc.strerror}") from None

    records: list[InboxPreviewRecord] = []
    for name in names:
        fp = os.path.join(p, name)
        if not os.path.isfile(fp):
            continue
        records.append(scan_bundle_file(fp, strict_unknown=strict_unknown))

    considered = [r for r in records if r.status != InboxRecordStatus.SKIPPED_UNSUPPORTED_FILE]
    invalid = sum(1 for r in considered if r.status in (InboxRecordStatus.INVALID_BUNDLE, InboxRecordStatus.ERROR))
    valid = len(considered) - invalid
    return MissionInboxIndex(
        inbox_path=p, created_at=_now_iso(), total_files=len(records),
        valid_bundles=valid, invalid_bundles=invalid, records=records,
        audit_notes="Read-only preview index. No execution, dispatch, writes, or file moves.",
    )


def index_to_dict(index: MissionInboxIndex) -> dict[str, Any]:
    return index.to_dict()


def normalize_index_to_json(index: MissionInboxIndex, *, indent: int | None = 2) -> str:
    return json.dumps(index.to_dict(), sort_keys=True, indent=indent, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    """Read-only CLI. Prints the index JSON (exit 0) or an error JSON (exit 1). Never writes."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="mission_inbox_index",
        description="Index preview bundles in a folder (read-only; dispatches nothing).")
    parser.add_argument("path", help="path to an inbox directory")
    parser.add_argument("--allow-unknown", action="store_true",
                        help="treat unknown bundle fields as warnings instead of errors")
    args = parser.parse_args(argv)
    try:
        index = scan_inbox(args.path, strict_unknown=not args.allow_unknown)
    except MissionInboxError as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)],
                          "can_execute": False, "can_dispatch": False},
                         sort_keys=True, indent=2, ensure_ascii=False))
        return 1
    print(normalize_index_to_json(index))
    return 0


__all__ = [
    "MissionInboxError", "InboxRecordStatus", "InboxPreviewRecord", "MissionInboxIndex",
    "scan_inbox", "scan_bundle_file", "index_to_dict", "normalize_index_to_json", "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
