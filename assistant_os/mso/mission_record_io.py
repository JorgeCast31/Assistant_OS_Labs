"""Mission Record File / Validator v0 — load, validate and normalize records.

PR: Mission Record File / Validator v0 (TASK-0001 F1 groundwork).

WHAT THIS IS
------------
A small, stdlib-only IO + validation layer over the ``MissionAuthorizationRecord``
contract (PR #262). It lets a sovereign authorization live as a versioned,
reviewable **file** and be validated by humans, reviewers or CI — so authority
stops travelling by chat (human-cable).

WHAT THIS IS NOT
----------------
- It executes NOTHING and grants NO authority.
- ``validator != runner``. Loading/validating a record never runs anything.
- It never mints a capability token, never infers authority, never writes
  runtime records from the backend, and never prints secret values.
- A valid file is still ``can_execute == False``. Record-exists != can-execute.

FAIL-CLOSED
-----------
Every loader raises ``MissionRecordIOError`` on: malformed JSON, missing file,
unknown fields (strict), invalid enum, or contract validation failure. Error
messages name fields/keys — never echo field *values* (secret-safe).
"""

from __future__ import annotations

import json
import os
from typing import Any

from .mission_record import (
    MissionAuthorizationRecord,
    MissionRecordError,
)


class MissionRecordIOError(MissionRecordError):
    """Raised when a record file/source cannot be safely loaded or validated."""


# Keys that ``to_dict()`` emits but that are DERIVED (not constructor fields).
# Tolerated on load so normalize -> load roundtrips cleanly; never trusted.
_DERIVED_IGNORED_KEYS = frozenset({"can_execute"})


def _field_names() -> frozenset[str]:
    return frozenset(MissionAuthorizationRecord.__dataclass_fields__)  # type: ignore[attr-defined]


def _unknown_keys(data: dict[str, Any]) -> list[str]:
    return sorted(set(data) - _field_names() - _DERIVED_IGNORED_KEYS)


# ---------------------------------------------------------------------------
# Loaders (fail-closed)
# ---------------------------------------------------------------------------

def load_record_from_dict(
    data: Any, *, strict_unknown: bool = True
) -> MissionAuthorizationRecord:
    """Build + validate a record from a mapping. Fail-closed.

    Unknown keys raise by default (``strict_unknown``). Never echoes values.
    """
    if not isinstance(data, dict):
        raise MissionRecordIOError(
            f"record source must be a JSON object/dict, got {type(data).__name__}"
        )
    unknown = _unknown_keys(data)
    if unknown and strict_unknown:
        raise MissionRecordIOError(f"unknown field(s) not permitted: {unknown}")

    payload = {k: v for k, v in data.items() if k in _field_names()}
    try:
        record = MissionAuthorizationRecord(**payload)  # enum coercion may raise
        record.validate()  # contract-level fail-closed (secrets, empties, contradictions)
    except MissionRecordIOError:
        raise
    except MissionRecordError as exc:
        # Normalize all contract errors to a fail-closed IO error. Message names
        # fields only (never echoes values).
        raise MissionRecordIOError(str(exc)) from None
    except TypeError as exc:
        # Missing required constructor fields, etc. Message names fields only.
        raise MissionRecordIOError(f"could not construct record: {exc}") from None
    return record


def load_record_from_json(
    text: str, *, strict_unknown: bool = True
) -> MissionAuthorizationRecord:
    """Parse a JSON string then load+validate. JSON errors fail closed and never
    echo the document (which could contain a secret)."""
    if not isinstance(text, str):
        raise MissionRecordIOError("json source must be a string")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # Do NOT include the raw document; only structural position + reason.
        raise MissionRecordIOError(
            f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from None
    return load_record_from_dict(data, strict_unknown=strict_unknown)


def load_record_from_path(
    path: str | os.PathLike[str], *, strict_unknown: bool = True
) -> MissionAuthorizationRecord:
    """Read a file then load+validate. Missing path fails closed."""
    p = os.fspath(path)
    if not os.path.isfile(p):
        raise MissionRecordIOError(f"mission record file not found: {p}")
    try:
        with open(p, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise MissionRecordIOError(f"could not read file {p}: {exc.strerror}") from None
    return load_record_from_json(text, strict_unknown=strict_unknown)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_to_json(record: MissionAuthorizationRecord, *, indent: int | None = 2) -> str:
    """Deterministic JSON for a record. Includes derived ``can_execute=false``.

    Stable across runs (sorted keys). Never a grant.
    """
    if not isinstance(record, MissionAuthorizationRecord):
        raise MissionRecordIOError("normalize_to_json requires a MissionAuthorizationRecord")
    return json.dumps(record.to_dict(), sort_keys=True, indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Structured validation (never raises) — for tooling / CI
# ---------------------------------------------------------------------------

def validate_source(source: Any, *, strict_unknown: bool = True) -> dict[str, Any]:
    """Validate a dict / JSON string / path. Never raises. Secret-safe.

    Returns ``{ok, errors, warnings, record_id, normalized}``. ``errors`` and
    ``warnings`` contain field/key names and reasons only — never values.
    """
    errors: list[str] = []
    warnings: list[str] = []
    record: MissionAuthorizationRecord | None = None

    try:
        if isinstance(source, MissionAuthorizationRecord):
            record = source.validate()
        elif isinstance(source, dict):
            # Surface unknowns as explicit warnings even in non-strict mode.
            unknown = _unknown_keys(source)
            if unknown:
                warnings.append(f"unknown field(s): {unknown}")
            record = load_record_from_dict(source, strict_unknown=strict_unknown)
        elif isinstance(source, (str, os.PathLike)) and os.path.isfile(os.fspath(source)):
            record = load_record_from_path(source, strict_unknown=strict_unknown)
        elif isinstance(source, str):
            record = load_record_from_json(source, strict_unknown=strict_unknown)
        else:
            errors.append(f"unsupported source type: {type(source).__name__}")
    except MissionRecordError as exc:
        errors.append(str(exc))

    ok = record is not None and not errors
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "record_id": (record.mission_id if record else None),
        # Derived, safe truths — never a grant.
        "can_execute": False,
        "is_active": (record.is_active() if record else False),
        "normalized": (normalize_to_json(record) if record else None),
    }


# ---------------------------------------------------------------------------
# Read-only CLI: `python -m assistant_os.mso.mission_record_io <path>`
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Validate a record file. Read-only. Exit 0 (valid) / 1 (invalid).

    Never writes files, never executes, never prints secret values.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="mission_record_io",
        description="Validate a Mission/Authorization Record file (read-only; grants nothing).",
    )
    parser.add_argument("path", help="path to a mission record JSON file")
    parser.add_argument("--allow-unknown", action="store_true",
                        help="treat unknown fields as warnings instead of errors")
    args = parser.parse_args(argv)

    result = validate_source(args.path, strict_unknown=not args.allow_unknown)
    if result["ok"]:
        print(f"VALID: mission_record '{result['record_id']}' "
              f"(is_active={result['is_active']}, can_execute=False)")
        for w in result["warnings"]:
            print(f"  warning: {w}")
        return 0
    print("INVALID:")
    for e in result["errors"]:
        print(f"  error: {e}")
    for w in result["warnings"]:
        print(f"  warning: {w}")
    return 1


__all__ = [
    "MissionRecordIOError",
    "load_record_from_dict",
    "load_record_from_json",
    "load_record_from_path",
    "normalize_to_json",
    "validate_source",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
