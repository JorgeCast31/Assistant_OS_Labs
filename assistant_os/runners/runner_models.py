"""
Data models for Runner execution — Slice 4 / M1B.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ..sandbox.authorized_plan import AuthorizedPlan


class RunnerExecutionStatus(str, Enum):
    # Intermediate statuses (set during execution, before validation)
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WORKSPACE_READY = "WORKSPACE_READY"
    CHANGES_APPLIED = "CHANGES_APPLIED"
    TESTS_PASSED = "TESTS_PASSED"
    TESTS_FAILED = "TESTS_FAILED"
    # Terminal statuses (set by ValidationEngine, also used standalone for hard failures)
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass
class RunnerExecutionRequest:
    """Minimal execution request handed to the Runner."""

    execution_id: str
    repo_path: str
    base_commit: Optional[str] = None
    changes: Optional[List[Any]] = None
    test_spec: Optional[Any] = None
    validation_spec: Optional[Any] = None
    workspace_spec: Optional[Any] = None
    metadata: Optional[Dict[str, Any]] = field(default=None)
    # M1B governance fields — optional for backward compatibility.
    # When authorized_plan is set, RunnerService delegates execution to RunnerAPI (Docker).
    # When code is set alongside authorized_plan, the sandbox execution is triggered.
    authorized_plan: Optional["AuthorizedPlan"] = field(default=None, repr=False)
    code: Optional[str] = field(default=None, repr=False)
    # Policy enforcement — governs apply and promote in RunnerService.
    # Required: "DRY_RUN" | "SAFE_EXECUTE" | "FULL_EXECUTE"
    # Absent (None) → RunnerService raises a contract violation error.
    execution_mode: Optional[str] = None


@dataclass
class TestExecutionResult:
    """Result of a single test phase execution."""

    # "passed" | "failed" | "timed_out" | "not_run"
    status: str
    command: List[str]
    exit_code: Optional[int] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    duration_ms: Optional[int] = None


@dataclass
class ValidationResult:
    """Output of ValidationEngine — the authoritative final decision."""

    # "success" | "failed" | "needs_review"
    final_status: str
    reasons: List[str]
    validation_summary: str


@dataclass
class ReportArtifacts:
    """Paths of the report files produced by ReportBuilder."""

    json_path: str
    md_path: str


@dataclass
class NotificationResult:
    """Record of the notification emitted by NotificationEngine."""

    notification_path: str


@dataclass
class RunnerExecutionResult:
    """Structured result returned by the Runner."""

    execution_id: str
    # Intermediate status reflecting the phase that last ran successfully.
    # After validation, see final_status for the authoritative outcome.
    status: RunnerExecutionStatus
    started_at: datetime
    finished_at: datetime
    workspace_path: Optional[str] = None
    artifacts_path: Optional[str] = None
    error: Optional[str] = None
    summary: str = ""
    modified_files: List[str] = field(default_factory=list)
    test_result: Optional[TestExecutionResult] = None
    # Slice 4 fields — filled by ValidationEngine / ReportBuilder / NotificationEngine
    validation_result: Optional[ValidationResult] = None
    final_status: Optional[str] = None           # "success" | "failed" | "needs_review"
    report_json_path: Optional[str] = None
    report_md_path: Optional[str] = None
    notification_path: Optional[str] = None
    # M1B governance fields — populated when RunnerAPI (Docker) was invoked.
    authorized_plan_info: Optional[Dict[str, Any]] = field(default=None, repr=False)
    sandbox_metadata: Optional[Dict[str, Any]] = field(default=None, repr=False)
    # M2D audit — per-file change detail (path, operation, before_hash, after_hash, diff).
    changes_detail: Optional[List[Dict[str, Any]]] = field(default=None, repr=False)
    # Policy promotion tracking — populated by RunnerService after execution_mode enforcement.
    promoted_files: List[str] = field(default_factory=list)
    promotion_status: Optional[str] = None
    # Rollback — populated when backup ran before promote (FULL_EXECUTE only).
    backup_path: Optional[str] = None
    backup_manifest: Optional[Dict[str, str]] = field(default=None, repr=False)
