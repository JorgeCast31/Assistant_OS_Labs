"""Orchestration Preview Bundle / CLI v0 — build a preview from a JSON bundle (read-only).

PR: Orchestration Preview Bundle / CLI v0.

Loads a JSON *bundle* (a delegation packet + candidate worker profiles) and builds an
``OrchestrationPreview`` (#268) from it, deterministically and read-only.

    python -m assistant_os.mso.orchestration_preview_io <bundle.json>

WHAT THIS IS NOT
----------------
It does NOT run a mission, dispatch, execute, call models, contact external APIs, run a
Runner, use a queue, mint a token, grant authority, or WRITE any file. Output goes only to
stdout/stderr. ``can_dispatch``/``can_execute`` are always False.

> bundle ≠ authorization · CLI preview ≠ execution · preview ≠ dispatch ·
> generated handoff envelope ≠ real handoff · stdout JSON is simulation evidence, not execution proof.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any

from .delegation_packet import DelegationWorkPacket
from .worker_registry import WorkerProfile
from .orchestration_preview import OrchestrationPreview, build_orchestration_preview


class OrchestrationBundleError(ValueError):
    """Raised when a bundle/source cannot be safely loaded (fail-closed)."""


_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),
    re.compile(r"(?i)(password|passwd|api[_-]?key|secret|token|bearer)\s*[:=]\s*\S"),
    re.compile(r"(?i)authorization:\s*\S"),
    re.compile(r"(?i)-----begin"),
)
_MAX_ITEM_LEN = 4096


def _looks_like_secret(text: str) -> bool:
    return isinstance(text, str) and any(p.search(text) for p in _SECRET_PATTERNS)


def _scan_raw(value: Any, path: str = "$") -> list[str]:
    """Walk a decoded JSON value; flag secret-like or oversized strings by PATH (never value)."""
    errs: list[str] = []
    if isinstance(value, str):
        if _looks_like_secret(value):
            errs.append(f"secret-like content at {path}")
        if len(value) > _MAX_ITEM_LEN:
            errs.append(f"oversized content (use refs) at {path}")
    elif isinstance(value, dict):
        for k, v in value.items():
            errs.extend(_scan_raw(v, f"{path}.{k}"))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            errs.extend(_scan_raw(v, f"{path}[{i}]"))
    return errs


@dataclass(slots=True)
class OrchestrationPreviewBundle:
    bundle_id: str
    delegation_packet: dict[str, Any]
    workers: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    created_by: str = "mso"
    requested_preview_id: str = ""
    audit_notes: str = ""


def _fields() -> frozenset[str]:
    return frozenset(OrchestrationPreviewBundle.__dataclass_fields__)  # type: ignore[attr-defined]


def load_bundle_from_dict(data: Any, *, strict_unknown: bool = True) -> OrchestrationPreviewBundle:
    if not isinstance(data, dict):
        raise OrchestrationBundleError(f"bundle must be a JSON object, got {type(data).__name__}")
    unknown = sorted(set(data) - _fields())
    if unknown and strict_unknown:
        raise OrchestrationBundleError(f"unknown field(s) not permitted: {unknown}")
    scan = _scan_raw(data)
    if scan:
        raise OrchestrationBundleError("; ".join(scan))
    payload = {k: v for k, v in data.items() if k in _fields()}
    if not isinstance(payload.get("bundle_id"), str) or not payload.get("bundle_id", "").strip():
        raise OrchestrationBundleError("critical field empty: bundle_id")
    if not isinstance(payload.get("delegation_packet"), dict):
        raise OrchestrationBundleError("delegation_packet must be an object")
    if "workers" in payload and not isinstance(payload["workers"], list):
        raise OrchestrationBundleError("workers must be a list")
    try:
        return OrchestrationPreviewBundle(**payload)
    except TypeError as exc:
        raise OrchestrationBundleError(f"could not construct bundle: {exc}") from None


def load_bundle_from_json(text: str, *, strict_unknown: bool = True) -> OrchestrationPreviewBundle:
    if not isinstance(text, str):
        raise OrchestrationBundleError("json source must be a string")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OrchestrationBundleError(
            f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}") from None
    return load_bundle_from_dict(data, strict_unknown=strict_unknown)


def load_bundle_from_path(path: str | os.PathLike[str], *, strict_unknown: bool = True) -> OrchestrationPreviewBundle:
    p = os.fspath(path)
    if not os.path.isfile(p):
        raise OrchestrationBundleError(f"bundle file not found: {p}")
    try:
        with open(p, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise OrchestrationBundleError(f"could not read file {p}: {exc.strerror}") from None
    return load_bundle_from_json(text, strict_unknown=strict_unknown)


def build_preview_from_bundle(bundle: OrchestrationPreviewBundle) -> OrchestrationPreview:
    """Build the preview. Invalid packet ⇒ INVALID_INPUT; invalid workers ⇒ not eligible.

    Pure: never writes, never mutates the bundle, never calls network/models.
    """
    if not isinstance(bundle, OrchestrationPreviewBundle):
        raise OrchestrationBundleError("not an OrchestrationPreviewBundle")
    try:
        packet: Any = DelegationWorkPacket.from_dict(dict(bundle.delegation_packet))
    except Exception:  # noqa: BLE001 — bad packet ⇒ INVALID_INPUT downstream
        packet = None
    workers: list[WorkerProfile] = []
    for wd in bundle.workers:
        if not isinstance(wd, dict):
            continue
        try:
            workers.append(WorkerProfile.from_dict(dict(wd)))  # invalid ⇒ excluded by routing
        except Exception:  # noqa: BLE001 — unconstructable worker can never be eligible
            continue
    return build_orchestration_preview(packet, workers, created_by=(bundle.created_by or "mso"))


def normalize_preview_to_json(preview: OrchestrationPreview, *, indent: int | None = 2) -> str:
    return json.dumps(preview.to_dict(), sort_keys=True, indent=indent, ensure_ascii=False)


def validate_bundle_source(source: Any, *, strict_unknown: bool = True) -> dict[str, Any]:
    """Never raises. Returns {ok, errors, warnings, preview}. Secret-safe."""
    errors: list[str] = []
    warnings: list[str] = []
    preview: OrchestrationPreview | None = None
    try:
        if isinstance(source, OrchestrationPreviewBundle):
            bundle = source
        elif isinstance(source, dict):
            unknown = sorted(set(source) - _fields())
            if unknown and not strict_unknown:
                warnings.append(f"unknown field(s): {unknown}")
            bundle = load_bundle_from_dict(source, strict_unknown=strict_unknown)
        elif isinstance(source, (str, os.PathLike)) and os.path.isfile(os.fspath(source)):
            bundle = load_bundle_from_path(source, strict_unknown=strict_unknown)
        elif isinstance(source, str):
            bundle = load_bundle_from_json(source, strict_unknown=strict_unknown)
        else:
            return {"ok": False, "errors": [f"unsupported source type: {type(source).__name__}"],
                    "warnings": warnings, "preview": None, "can_dispatch": False, "can_execute": False}
        preview = build_preview_from_bundle(bundle)
    except OrchestrationBundleError as exc:
        errors.append(str(exc))
    return {
        "ok": preview is not None and not errors,
        "errors": errors, "warnings": warnings,
        "preview": (preview.to_dict() if preview else None),
        "can_dispatch": False, "can_execute": False,
    }


def main(argv: list[str] | None = None) -> int:
    """Read-only CLI. Prints normalized preview JSON (exit 0) or error JSON (exit 1). Never writes."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="orchestration_preview_io",
        description="Build an Orchestration Preview from a JSON bundle (read-only; dispatches nothing).")
    parser.add_argument("path", help="path to a JSON bundle file")
    parser.add_argument("--allow-unknown", action="store_true",
                        help="treat unknown bundle fields as warnings instead of errors")
    args = parser.parse_args(argv)

    res = validate_bundle_source(args.path, strict_unknown=not args.allow_unknown)
    if res["ok"] and res["preview"] is not None:
        # Re-serialize the preview deterministically.
        print(json.dumps(res["preview"], sort_keys=True, indent=2, ensure_ascii=False))
        return 0
    print(json.dumps({"ok": False, "errors": res["errors"], "warnings": res["warnings"],
                      "can_execute": False, "can_dispatch": False},
                     sort_keys=True, indent=2, ensure_ascii=False))
    return 1


__all__ = [
    "OrchestrationBundleError", "OrchestrationPreviewBundle",
    "load_bundle_from_dict", "load_bundle_from_json", "load_bundle_from_path",
    "build_preview_from_bundle", "validate_bundle_source", "normalize_preview_to_json", "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
