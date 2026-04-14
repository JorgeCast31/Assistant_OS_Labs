"""Initial MSO capability authority registry."""

from __future__ import annotations

from .contracts import CapabilityCheckResult, CapabilityRecord
from ..contracts import (
    ACTION_CLASSIFY,
    ACTION_CODE_CREATE,
    ACTION_CODE_EXPLAIN,
    ACTION_CODE_FIX,
    ACTION_CODE_REVIEW,
    ACTION_COMMAND,
    ACTION_FIN_BATCH,
    ACTION_FIN_CHAPERON,
    ACTION_FIN_COMMIT,
    ACTION_FIN_CONFIRM,
    ACTION_FIN_EXPENSE,
    ACTION_FIN_PLAN,
    ACTION_UNKNOWN,
    ACTION_WORK_CREATE,
    ACTION_WORK_CREATE_TEST,
    ACTION_WORK_DELETE,
    ACTION_WORK_DELETE_TEST,
    ACTION_WORK_QUERY,
    ACTION_WORK_TEST_RESET,
    ACTION_WORK_UPDATE,
    ACTION_WORK_UPDATE_BULK,
)

_CAPABILITIES: dict[str, CapabilityRecord] = {
    ACTION_WORK_QUERY: CapabilityRecord(ACTION_WORK_QUERY, "WORK", "allow"),
    ACTION_WORK_CREATE: CapabilityRecord(ACTION_WORK_CREATE, "WORK", "confirm_only"),
    ACTION_WORK_CREATE_TEST: CapabilityRecord(ACTION_WORK_CREATE_TEST, "WORK", "confirm_only"),
    ACTION_WORK_UPDATE: CapabilityRecord(ACTION_WORK_UPDATE, "WORK", "confirm_only"),
    ACTION_WORK_UPDATE_BULK: CapabilityRecord(ACTION_WORK_UPDATE_BULK, "WORK", "confirm_only"),
    ACTION_WORK_DELETE: CapabilityRecord(ACTION_WORK_DELETE, "WORK", "confirm_only"),
    ACTION_WORK_DELETE_TEST: CapabilityRecord(ACTION_WORK_DELETE_TEST, "WORK", "confirm_only"),
    ACTION_WORK_TEST_RESET: CapabilityRecord(ACTION_WORK_TEST_RESET, "WORK", "deny", allowed=False, notes="Reset actions require future explicit governance handling."),
    ACTION_FIN_EXPENSE: CapabilityRecord(ACTION_FIN_EXPENSE, "FIN", "allow"),
    ACTION_FIN_BATCH: CapabilityRecord(ACTION_FIN_BATCH, "FIN", "confirm_only"),
    ACTION_FIN_PLAN: CapabilityRecord(ACTION_FIN_PLAN, "FIN", "allow"),
    ACTION_FIN_COMMIT: CapabilityRecord(ACTION_FIN_COMMIT, "FIN", "confirm_only"),
    ACTION_FIN_CONFIRM: CapabilityRecord(ACTION_FIN_CONFIRM, "FIN", "confirm_only"),
    ACTION_FIN_CHAPERON: CapabilityRecord(ACTION_FIN_CHAPERON, "FIN", "allow"),
    ACTION_CODE_EXPLAIN: CapabilityRecord(ACTION_CODE_EXPLAIN, "CODE", "allow"),
    ACTION_CODE_REVIEW: CapabilityRecord(ACTION_CODE_REVIEW, "CODE", "allow"),
    ACTION_CODE_FIX: CapabilityRecord(ACTION_CODE_FIX, "CODE", "confirm_only"),
    ACTION_CODE_CREATE: CapabilityRecord(ACTION_CODE_CREATE, "CODE", "confirm_only"),
    ACTION_COMMAND: CapabilityRecord(ACTION_COMMAND, "UNKNOWN", "deny", allowed=False, notes="Generic command execution is not governed for autonomous execution."),
    ACTION_CLASSIFY: CapabilityRecord(ACTION_CLASSIFY, "UNKNOWN", "deny", allowed=False, notes="Classification-only actions are not executable capabilities."),
    ACTION_UNKNOWN: CapabilityRecord(ACTION_UNKNOWN, "UNKNOWN", "deny", allowed=False, notes="Unknown actions are denied by capability policy."),
}


def get_capability_for_action(action: str, domain: str) -> CapabilityRecord:
    """Return the registered capability or a safe deny fallback."""
    record = _CAPABILITIES.get(action)
    if record is not None:
        return record
    return CapabilityRecord(action=action, domain=domain, mode="deny", allowed=False, notes="Unregistered action denied by default.")


def check_capability(action: str, domain: str) -> CapabilityCheckResult:
    """Check whether the requested action is allowed by capability policy."""
    record = get_capability_for_action(action, domain)
    return CapabilityCheckResult(
        action=action,
        domain=domain,
        allowed=record.allowed,
        mode=record.mode,
        requires_confirmation=record.mode == "confirm_only",
        deny_reason="" if record.allowed else (record.notes or "Capability denied by registry."),
        notes=record.notes,
    )
