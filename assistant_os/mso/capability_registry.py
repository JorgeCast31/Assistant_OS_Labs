"""Dynamic MSO capability authority registry."""

from __future__ import annotations

from threading import RLock
import uuid
from datetime import datetime, timezone

from ..contracts import now_iso
from .contracts import (
    CapabilityCheckResult,
    CapabilityGrant,
    CapabilityMode,
    CapabilityRecord,
    CapabilityRevocation,
    CapabilityScope,
)
from ..contracts import (
    ACTION_CLASSIFY,
    ACTION_BASIC_COGNITIVE_EXECUTION,
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
    # HOST domain
    ACTION_HOST_OPEN_APP,
    ACTION_HOST_CLOSE_PID,
    ACTION_HOST_OPEN_DIRECTORY,
    ACTION_HOST_OPEN_URL,
    ACTION_HOST_LIST_DIRECTORY,
    ACTION_HOST_OPEN_FILE,
    ACTION_HOST_READ_TEXT_FILE,
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
    ACTION_BASIC_COGNITIVE_EXECUTION: CapabilityRecord(ACTION_BASIC_COGNITIVE_EXECUTION, "COGNITIVE", "allow"),
    ACTION_COMMAND: CapabilityRecord(ACTION_COMMAND, "UNKNOWN", "deny", allowed=False, notes="Generic command execution is not governed for autonomous execution."),
    ACTION_CLASSIFY: CapabilityRecord(ACTION_CLASSIFY, "UNKNOWN", "deny", allowed=False, notes="Classification-only actions are not executable capabilities."),
    ACTION_UNKNOWN: CapabilityRecord(ACTION_UNKNOWN, "UNKNOWN", "deny", allowed=False, notes="Unknown actions are denied by capability policy."),
    # HOST domain — read-only actions (auto-execute, no confirmation required)
    ACTION_HOST_LIST_DIRECTORY: CapabilityRecord(ACTION_HOST_LIST_DIRECTORY, "HOST", "allow"),
    ACTION_HOST_READ_TEXT_FILE: CapabilityRecord(ACTION_HOST_READ_TEXT_FILE, "HOST", "allow"),
    # HOST domain — externally effectful / launch actions (confirmation required)
    ACTION_HOST_OPEN_APP:       CapabilityRecord(ACTION_HOST_OPEN_APP,       "HOST", "confirm_only"),
    ACTION_HOST_OPEN_URL:       CapabilityRecord(ACTION_HOST_OPEN_URL,       "HOST", "confirm_only"),
    ACTION_HOST_OPEN_DIRECTORY: CapabilityRecord(ACTION_HOST_OPEN_DIRECTORY, "HOST", "confirm_only"),
    ACTION_HOST_OPEN_FILE:      CapabilityRecord(ACTION_HOST_OPEN_FILE,      "HOST", "confirm_only"),
    ACTION_HOST_CLOSE_PID:      CapabilityRecord(ACTION_HOST_CLOSE_PID,      "HOST", "confirm_only"),
}

_lock = RLock()
_temporary_grants: dict[str, CapabilityGrant] = {}
_revocations: dict[str, CapabilityRevocation] = {}


def _is_active(expires_at: str) -> bool:
    if not expires_at:
        return True
    try:
        return datetime.fromisoformat(expires_at.replace("Z", "+00:00")) > datetime.now(timezone.utc)
    except ValueError:
        return True


def _matches_scope(record_action: str, record_domain: str, action: str, domain: str) -> bool:
    return (record_action == "*" or record_action == action) and (record_domain == "*" or record_domain == domain)


def get_capability_for_action(action: str, domain: str) -> CapabilityRecord:
    """Return the registered static capability or a safe deny fallback."""
    record = _CAPABILITIES.get(action)
    if record is not None:
        return record
    return CapabilityRecord(action=action, domain=domain, mode="deny", allowed=False, notes="Unregistered action denied by default.")


def list_registered_capabilities(*, domain: str = "") -> list[CapabilityRecord]:
    """Return static capability records without exposing the live registry dict."""
    records = [
        CapabilityRecord(
            action=record.action,
            domain=record.domain,
            mode=record.mode,
            allowed=record.allowed,
            notes=record.notes,
        )
        for record in _CAPABILITIES.values()
    ]
    if domain:
        records = [record for record in records if record.domain == domain]
    return sorted(records, key=lambda record: (record.domain, record.action))


def grant_temporary_capability(
    *,
    action: str,
    domain: str,
    mode: CapabilityMode = "allow",
    reason: str,
    expires_at: str = "",
    scope: CapabilityScope | None = None,
    granted_by: str = "mso",
) -> CapabilityGrant:
    """Register a temporary capability grant."""
    grant = CapabilityGrant(
        grant_id=str(uuid.uuid4()),
        action=action,
        domain=domain,
        mode=mode,
        created_at=now_iso(),
        reason=reason,
        expires_at=expires_at,
        scope=scope,
        granted_by=granted_by,
    )
    with _lock:
        _temporary_grants[grant.grant_id] = grant
    return grant


def revoke_capability(
    *,
    action: str,
    domain: str,
    reason: str,
    scope: CapabilityScope | None = None,
    revoked_by: str = "mso",
    expires_at: str = "",
) -> CapabilityRevocation:
    """Register an explicit capability revocation."""
    revocation = CapabilityRevocation(
        revocation_id=str(uuid.uuid4()),
        action=action,
        domain=domain,
        created_at=now_iso(),
        reason=reason,
        scope=scope,
        revoked_by=revoked_by,
        expires_at=expires_at,
    )
    with _lock:
        _revocations[revocation.revocation_id] = revocation
    return revocation


def clear_revocation(revocation_id: str) -> None:
    with _lock:
        _revocations.pop(revocation_id, None)


def clear_grant(grant_id: str) -> None:
    with _lock:
        _temporary_grants.pop(grant_id, None)


def list_active_revocations(*, domain: str = "", action: str = "") -> list[CapabilityRevocation]:
    with _lock:
        items = [item for item in _revocations.values() if _is_active(item.expires_at)]
    filtered = [item for item in items if _matches_scope(item.action, item.domain, action or item.action, domain or item.domain)]
    if domain:
        filtered = [item for item in filtered if item.domain in {domain, "*"}]
    if action:
        filtered = [item for item in filtered if item.action in {action, "*"}]
    return sorted(filtered, key=lambda item: item.created_at, reverse=True)


def list_temporary_grants(*, domain: str = "", action: str = "") -> list[CapabilityGrant]:
    with _lock:
        items = [item for item in _temporary_grants.values() if _is_active(item.expires_at)]
    filtered = [item for item in items if _matches_scope(item.action, item.domain, action or item.action, domain or item.domain)]
    if domain:
        filtered = [item for item in filtered if item.domain in {domain, "*"}]
    if action:
        filtered = [item for item in filtered if item.action in {action, "*"}]
    return sorted(filtered, key=lambda item: item.created_at, reverse=True)


def check_capability(action: str, domain: str) -> CapabilityCheckResult:
    """Check whether the requested action is currently allowed by capability policy."""
    revocations = list_active_revocations(domain=domain, action=action)
    if revocations:
        revocation = revocations[0]
        return CapabilityCheckResult(
            action=action,
            domain=domain,
            allowed=False,
            mode="deny",
            requires_confirmation=False,
            deny_reason=revocation.reason,
            notes="Capability revoked by dynamic governance policy.",
            source="revocation",
            is_revoked=True,
            scope=revocation.scope,
            expires_at=revocation.expires_at,
        )

    grants = list_temporary_grants(domain=domain, action=action)
    if grants:
        grant = grants[0]
        return CapabilityCheckResult(
            action=action,
            domain=domain,
            allowed=grant.mode != "deny",
            mode=grant.mode,
            requires_confirmation=grant.mode == "confirm_only",
            deny_reason="" if grant.mode != "deny" else grant.reason,
            notes=grant.reason,
            source="temporary_grant",
            is_temporary=True,
            scope=grant.scope,
            expires_at=grant.expires_at,
        )

    record = get_capability_for_action(action, domain)
    return CapabilityCheckResult(
        action=action,
        domain=domain,
        allowed=record.allowed,
        mode=record.mode,
        requires_confirmation=record.mode == "confirm_only",
        deny_reason="" if record.allowed else (record.notes or "Capability denied by registry."),
        notes=record.notes,
        source="static",
    )


def reset_dynamic_capabilities() -> None:
    with _lock:
        _temporary_grants.clear()
        _revocations.clear()
