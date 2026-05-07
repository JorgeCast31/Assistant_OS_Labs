"""Stdlib-only Mission Core domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class MissionStatus(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    ACTIVE = "active"
    WAITING_FOR_CONTEXT = "waiting_for_context"
    AWAITING_INPUT = "awaiting_input"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass
class MissionActivity:
    title: str
    description: str
    workstream_id: str = ""
    status: MissionStatus = MissionStatus.DRAFT
    dependencies: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    activity_id: str = field(default_factory=lambda: new_id("activity"))


@dataclass
class Workstream:
    mission_id: str
    name: str
    objective: str
    domain: str
    assigned_role: str | None = None
    status: MissionStatus = MissionStatus.DRAFT
    activities: list[MissionActivity] = field(default_factory=list)
    workstream_id: str = field(default_factory=lambda: new_id("workstream"))

    def __post_init__(self) -> None:
        for activity in self.activities:
            if not activity.workstream_id:
                activity.workstream_id = self.workstream_id


@dataclass
class MissionBlueprint:
    mission_id: str
    summary: str
    workstreams: list[Workstream] = field(default_factory=list)
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    status: MissionStatus = MissionStatus.DRAFT
    blueprint_id: str = field(default_factory=lambda: new_id("blueprint"))


@dataclass
class Mission:
    title: str
    macro_goal: str
    created_by: str
    source_surface: str
    status: MissionStatus = MissionStatus.DRAFT
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    blueprint_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    mission_id: str = field(default_factory=lambda: new_id("mission"))


@dataclass(frozen=True)
class MissionEvent:
    mission_id: str
    event_type: str
    message: str
    actor: str
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: new_id("event"))
