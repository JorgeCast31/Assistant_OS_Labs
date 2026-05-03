"""Read-only authority posture summary over capability registry state.

S-AUTH-SURFACE-01A

This module is a passive producer. It does not evaluate execution requests,
does not call policy/governance engines, and does not mutate capability state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TypedDict

from .capability_registry import (
    list_active_revocations,
    list_registered_capabilities,
    list_temporary_grants,
)


class AuthorityCapabilityRow(TypedDict):
    domain: str
    action: str
    mode: str
    allowed: bool
    notes: str
    active_grant: bool
    active_revocation: bool
    effective_posture: str


class AuthorityStatusCounts(TypedDict):
    total: int
    allow: int
    confirm_only: int
    deny: int
    blocked: int
    active_grants: int
    active_revocations: int


class AuthorityStatusSummary(TypedDict, total=False):
    source: str
    feature_enabled: bool
    last_health_check: str
    note: str
    capabilities: list[AuthorityCapabilityRow]
    counts: AuthorityStatusCounts
    error: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _matches_scope(entry_action: str, entry_domain: str, action: str, domain: str) -> bool:
    return (entry_action in {"*", action}) and (entry_domain in {"*", domain})


def _empty_counts() -> AuthorityStatusCounts:
    return {
        "total": 0,
        "allow": 0,
        "confirm_only": 0,
        "deny": 0,
        "blocked": 0,
        "active_grants": 0,
        "active_revocations": 0,
    }


def _effective_posture(*, mode: str, allowed: bool, active_grant: bool, active_revocation: bool) -> str:
    if active_revocation:
        return "revoked"
    if active_grant:
        return "temporarily_granted"
    if mode == "confirm_only":
        return "requires_confirmation"
    if mode == "allow" and allowed:
        return "allowed_by_registry"
    if mode in {"deny", "blocked"} or not allowed:
        return "blocked_by_registry"
    return "unknown"


def list_authority_matrix() -> list[AuthorityCapabilityRow]:
    capabilities = list_registered_capabilities()
    revocations = list_active_revocations()
    grants = list_temporary_grants()

    rows: list[AuthorityCapabilityRow] = []
    for capability in capabilities:
        action = str(getattr(capability, "action", ""))
        domain = str(getattr(capability, "domain", ""))
        mode = str(getattr(capability, "mode", ""))
        allowed = bool(getattr(capability, "allowed", False))
        notes = str(getattr(capability, "notes", "") or "")

        active_revocation = any(
            _matches_scope(str(getattr(rev, "action", "")), str(getattr(rev, "domain", "")), action, domain)
            for rev in revocations
        )
        active_grant = any(
            _matches_scope(str(getattr(grant, "action", "")), str(getattr(grant, "domain", "")), action, domain)
            for grant in grants
        )

        rows.append(
            {
                "domain": domain,
                "action": action,
                "mode": mode,
                "allowed": allowed,
                "notes": notes,
                "active_grant": active_grant,
                "active_revocation": active_revocation,
                "effective_posture": _effective_posture(
                    mode=mode,
                    allowed=allowed,
                    active_grant=active_grant,
                    active_revocation=active_revocation,
                ),
            }
        )

    rows.sort(key=lambda row: (row["domain"], row["action"]))
    return rows


def get_authority_status() -> AuthorityStatusSummary:
    base: AuthorityStatusSummary = {
        "source": "authority_status",
        "feature_enabled": True,
        "last_health_check": _now_iso(),
        "note": "Authority status is read-only posture, not execution permission.",
        "capabilities": [],
        "counts": _empty_counts(),
    }

    try:
        rows = list_authority_matrix()
        counts = _empty_counts()
        counts["total"] = len(rows)
        counts["allow"] = sum(1 for row in rows if row["mode"] == "allow")
        counts["confirm_only"] = sum(1 for row in rows if row["mode"] == "confirm_only")
        counts["deny"] = sum(1 for row in rows if row["mode"] == "deny")
        counts["blocked"] = sum(
            1
            for row in rows
            if row["mode"] == "blocked"
            or row["effective_posture"] in {"revoked", "blocked_by_registry"}
        )
        counts["active_grants"] = sum(1 for row in rows if row["active_grant"])
        counts["active_revocations"] = sum(1 for row in rows if row["active_revocation"])

        base["capabilities"] = rows
        base["counts"] = counts
        return base
    except Exception as exc:  # noqa: BLE001
        base["note"] = "Authority status unavailable; this does not grant execution permission."
        base["error"] = f"{type(exc).__name__}: {exc}"
        return base
