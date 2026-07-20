"""Passive observations of local external-worker command presence.

This module deliberately performs no subprocess, model, SDK, network, auth, or
file-content read/write. It only asks an injected executable lookup whether the
allow-listed Claude Code and Codex command names are present on PATH. The default
lookup consults PATH/PATHEXT and local filesystem metadata, but returns no path.

Presence is ``INSTALLED_UNVERIFIED`` evidence, never readiness, assignment,
authority, dispatch, or execution permission.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from .worker_registry import WorkerType


class WorkerProbeState(str, Enum):
    INSTALLED_UNVERIFIED = "INSTALLED_UNVERIFIED"
    NOT_FOUND = "NOT_FOUND"
    ERROR = "ERROR"


class EvidenceLevel(str, Enum):
    PATH_ONLY = "PATH_ONLY"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class _ProbeSpec:
    worker_type: WorkerType
    command_name: str


_SPECS = (
    _ProbeSpec(WorkerType.CLAUDE_CODE, "claude"),
    _ProbeSpec(WorkerType.CODEX, "codex"),
)
_COMMAND_BY_WORKER = {spec.worker_type: spec.command_name for spec in _SPECS}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ExternalWorkerObservation:
    worker_type: WorkerType
    command_name: str
    state: WorkerProbeState
    evidence_level: EvidenceLevel
    observed_at: str
    executable_present: bool = False
    auth_status: str = "NOT_CHECKED"
    round_trip_status: str = "NOT_RUN"
    reason_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def can_dispatch(self) -> bool:
        return False

    @property
    def can_execute(self) -> bool:
        return False

    @property
    def authority_granted(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["worker_type"] = self.worker_type.value
        data["state"] = self.state.value
        data["evidence_level"] = self.evidence_level.value
        data["can_dispatch"] = False
        data["can_execute"] = False
        data["authority_granted"] = False
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExternalWorkerObservation":
        """Deserialize as untrusted data, never as local capability evidence."""
        worker_type = WorkerType(data["worker_type"])
        return cls(
            worker_type=worker_type,
            command_name=_COMMAND_BY_WORKER[worker_type],
            state=WorkerProbeState.ERROR,
            evidence_level=EvidenceLevel.NONE,
            observed_at="",
            executable_present=False,
            auth_status="NOT_CHECKED",
            round_trip_status="NOT_RUN",
            reason_codes=["deserialized_unverified"],
            warnings=["Deserialized observation is not local capability evidence."],
        )


@dataclass(slots=True)
class ExternalWorkerCapabilitySnapshot:
    observed_at: str
    observations: list[ExternalWorkerObservation] = field(default_factory=list)

    @property
    def can_dispatch(self) -> bool:
        return False

    @property
    def can_execute(self) -> bool:
        return False

    @property
    def authority_granted(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at,
            "observations": [item.to_dict() for item in self.observations],
            "can_dispatch": False,
            "can_execute": False,
            "authority_granted": False,
            "model_call_performed": False,
            "process_spawned": False,
            "network_used": False,
            "workspace_mutated": False,
        }


def _observe(
    spec: _ProbeSpec,
    *,
    observed_at: str,
    executable_lookup: Callable[[str], str | None],
) -> ExternalWorkerObservation:
    try:
        present = bool(executable_lookup(spec.command_name))
    except Exception:
        return ExternalWorkerObservation(
            worker_type=spec.worker_type,
            command_name=spec.command_name,
            state=WorkerProbeState.ERROR,
            evidence_level=EvidenceLevel.NONE,
            observed_at=observed_at,
            reason_codes=["lookup_error"],
            warnings=["Executable lookup failed; raw error suppressed."],
        )

    if not present:
        return ExternalWorkerObservation(
            worker_type=spec.worker_type,
            command_name=spec.command_name,
            state=WorkerProbeState.NOT_FOUND,
            evidence_level=EvidenceLevel.NONE,
            observed_at=observed_at,
            reason_codes=["command_not_found"],
        )

    return ExternalWorkerObservation(
        worker_type=spec.worker_type,
        command_name=spec.command_name,
        state=WorkerProbeState.INSTALLED_UNVERIFIED,
        evidence_level=EvidenceLevel.PATH_ONLY,
        observed_at=observed_at,
        executable_present=True,
        reason_codes=["path_entry_found"],
        warnings=["Presence does not prove authentication, model reachability, or permission."],
    )


def get_external_worker_capability_snapshot(
    *,
    executable_lookup: Callable[[str], str | None] = shutil.which,
    observed_at: str | None = None,
) -> ExternalWorkerCapabilitySnapshot:
    """Return passive, allow-listed PATH observations in deterministic order."""
    timestamp = observed_at or _now_iso()
    observations = [
        _observe(spec, observed_at=timestamp, executable_lookup=executable_lookup)
        for spec in _SPECS
    ]
    return ExternalWorkerCapabilitySnapshot(
        observed_at=timestamp,
        observations=observations,
    )


def normalize_snapshot_to_json(
    snapshot: ExternalWorkerCapabilitySnapshot,
    *,
    indent: int | None = 2,
) -> str:
    return json.dumps(snapshot.to_dict(), sort_keys=True, indent=indent)


def main() -> int:
    print(normalize_snapshot_to_json(get_external_worker_capability_snapshot()))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "WorkerProbeState",
    "EvidenceLevel",
    "ExternalWorkerObservation",
    "ExternalWorkerCapabilitySnapshot",
    "get_external_worker_capability_snapshot",
    "normalize_snapshot_to_json",
]
