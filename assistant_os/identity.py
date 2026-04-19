"""
AssistantOS — Canonical Identity Model (F1)

Introduces explicit runtime types for:
  - Principal   : who is acting (Human | AgentInstance | System)
  - SubjectState: lifecycle state of a subject within a session
  - RequestIdentity: per-request identity envelope with delegation skeleton

Design notes
------------
- All types are backward-compatible: nothing in this module changes
  existing contracts; it only ADDS new optional fields/parameters.
- Principal is frozen (immutable once created).
- RequestIdentity carries a delegation skeleton (spawned_by, root_principal)
  for forward compatibility with F2/F3 agent delegation; these fields are
  not enforced or evaluated in this sprint.
- Factory helpers (anonymous_human, human_principal, ...) are the intended
  construction path — direct dataclass instantiation is allowed but not
  the primary API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import uuid


# ---------------------------------------------------------------------------
# PrincipalKind
# ---------------------------------------------------------------------------

class PrincipalKind(str, Enum):
    """
    Canonical classification of an acting party.

    Variants:
        Human          — A human user interacting through the chat UI or API.
        AgentInstance  — A spawned agent acting under a delegation chain.
        System         — An internal system actor (scheduled task, watchdog, etc.).
    """
    Human = "human"
    AgentInstance = "agent_instance"
    System = "system"


# ---------------------------------------------------------------------------
# SubjectState
# ---------------------------------------------------------------------------

class SubjectState(str, Enum):
    """
    Lifecycle state of a subject (the combination of principal × session).

    States:
        Active      — Normal operation. All permitted requests proceed.
        Suspended   — Temporarily blocked. Requests are held or rejected.
        Quarantined — Isolated due to detected anomaly.
                      Read-only / restricted operations only.
        Terminated  — Session has ended. No further operations are permitted.

    Transition rules (enforced in F2+):
        Active → Suspended      : operator action or policy trigger
        Active → Quarantined    : anomaly engine detection
        Active → Terminated     : explicit logout or session expiry
        Suspended → Active      : operator release
        Quarantined → Suspended : operator review
        Any → Terminated        : operator or TTL expiry
    """
    Active = "active"
    Suspended = "suspended"
    Quarantined = "quarantined"
    Terminated = "terminated"

    def is_operational(self) -> bool:
        """True when the subject can initiate normal (write) operations."""
        return self == SubjectState.Active

    def allows_read_only(self) -> bool:
        """True when read-only operations are still permitted."""
        return self in (SubjectState.Active, SubjectState.Quarantined)

    def blocks_all(self) -> bool:
        """True when ALL operations are blocked."""
        return self == SubjectState.Terminated


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Principal:
    """
    Canonical, immutable identity of an acting party.

    Fields:
        kind       — PrincipalKind variant
        id         — Stable identifier string.
                     For humans:  "human:<short-uuid>" or a real user id.
                     For agents:  the agent_id from the delegation registry.
                     For system:  the literal string "system".
        label      — Human-readable name for logging and UI display.
        metadata   — Optional extensible bag (not compared, not hashed).
    """
    kind: PrincipalKind
    id: str
    label: str
    metadata: dict = field(default_factory=dict, compare=False, hash=False)

    # ── Convenience predicates ─────────────────────────────────────────────

    def is_human(self) -> bool:
        return self.kind == PrincipalKind.Human

    def is_agent(self) -> bool:
        return self.kind == PrincipalKind.AgentInstance

    def is_system(self) -> bool:
        return self.kind == PrincipalKind.System

    # ── Serialization ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict (excludes metadata for compactness)."""
        return {
            "kind": self.kind.value,
            "id": self.id,
            "label": self.label,
        }


# ---------------------------------------------------------------------------
# RequestIdentity
# ---------------------------------------------------------------------------

@dataclass
class RequestIdentity:
    """
    Identity envelope for a single request.

    Carries who is acting (principal), under what lifecycle state (subject_state),
    within which session (session_id).

    Delegation skeleton fields are present for forward compatibility:
        spawned_by      — The principal that delegated to this one (F2+).
        root_principal  — The root of the delegation chain (F3+).
        session_lineage — Ordered list of session_ids tracing the delegation
                          chain from root to current (F3+).  An empty list
                          means this is a direct (non-delegated) session.
                          Example: ["root-sess-id", "mid-sess-id", "this-sess"]

    Fields:
        principal       — The acting party for this request.
        subject_state   — Current lifecycle state of this principal×session.
        session_id      — Matches the chat_db session_id when available.
        spawned_by      — The principal that delegated to this one (F2+).
        root_principal  — The root of the delegation chain (F3+).
        session_lineage — Chain of session IDs from root to current (F3+).
    """
    principal: Principal
    subject_state: SubjectState
    session_id: Optional[str] = None
    spawned_by: Optional[Principal] = None        # delegation skeleton — F2+
    root_principal: Optional[Principal] = None    # delegation chain root — F3+
    session_lineage: list = field(default_factory=list)  # [str] session chain — F3+

    # ── Convenience predicates ─────────────────────────────────────────────

    def is_active(self) -> bool:
        """True when the subject is in Active state."""
        return self.subject_state.is_operational()

    def is_delegated(self) -> bool:
        """True when this identity was created by delegation (F2+)."""
        return self.spawned_by is not None

    # ── Serialization ──────────────────────────────────────────────────────

    def to_audit_dict(self) -> dict:
        """
        Serialize for inclusion in audit / response metadata.

        Produces a compact, JSON-safe dict. Delegation fields are omitted
        when absent to keep payloads lean.
        """
        d: dict = {
            "principal": self.principal.to_dict(),
            "subject_state": self.subject_state.value,
        }
        if self.session_id:
            d["session_id"] = self.session_id
        if self.spawned_by is not None:
            d["spawned_by"] = self.spawned_by.to_dict()
        if self.root_principal is not None:
            d["root_principal"] = self.root_principal.to_dict()
        if self.session_lineage:
            d["session_lineage"] = list(self.session_lineage)
        return d


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def human_principal(
    *,
    user_id: Optional[str] = None,
    label: str = "user",
    metadata: Optional[dict] = None,
) -> Principal:
    """
    Create a Human principal.

    Args:
        user_id:  Stable external user identifier. Auto-generated if absent.
        label:    Display name / tag (default "user").
        metadata: Optional extra metadata (not propagated to audit).
    """
    return Principal(
        kind=PrincipalKind.Human,
        id=user_id or f"human:{uuid.uuid4().hex[:8]}",
        label=label,
        metadata=metadata or {},
    )


def agent_principal(
    *,
    agent_id: str,
    label: str,
    metadata: Optional[dict] = None,
) -> Principal:
    """
    Create an AgentInstance principal.

    Args:
        agent_id: Identifier from the delegation registry.
        label:    Human-readable agent name.
        metadata: Optional extra metadata.
    """
    return Principal(
        kind=PrincipalKind.AgentInstance,
        id=agent_id,
        label=label,
        metadata=metadata or {},
    )


def system_principal(*, label: str = "system") -> Principal:
    """
    Create a System principal for internal actors.

    The id is always the literal "system" — there is only one system actor.
    """
    return Principal(
        kind=PrincipalKind.System,
        id="system",
        label=label,
        metadata={},
    )


def anonymous_human(session_id: Optional[str] = None) -> RequestIdentity:
    """
    Create a RequestIdentity for an anonymous human user in Active state.

    This is the default identity constructed at the /chat/process entrypoint
    when no explicit user authentication context is present.

    The principal id is scoped to the session when a session_id is available,
    so repeat requests within the same session share a stable id within that
    session's lifetime.

    Args:
        session_id: chat_db session_id, used to anchor the principal id.
    """
    # Derive a stable-within-session principal id
    if session_id:
        principal_id = f"human:{session_id[:8]}"
    else:
        principal_id = f"human:{uuid.uuid4().hex[:8]}"

    return RequestIdentity(
        principal=Principal(
            kind=PrincipalKind.Human,
            id=principal_id,
            label="user",
        ),
        subject_state=SubjectState.Active,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Enums
    "PrincipalKind",
    "SubjectState",
    # Dataclasses
    "Principal",
    "RequestIdentity",
    # Factories
    "human_principal",
    "agent_principal",
    "system_principal",
    "anonymous_human",
]
