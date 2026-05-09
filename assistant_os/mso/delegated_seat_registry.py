"""
Delegated MSO Seat Registry — Process-Local Authority Lookup.

In-memory, process-local registry for delegated MSO seats.
No persistence, no distributed state, no caching.

Design
------
The registry is the single source of truth for seat state at runtime.
Every action that checks a seat queries the registry for fresh state.

Operations
----------
- register_seat(seat): Add a new seat
- is_seat_active(seat_id): Check if seat exists and is active
- get_seat(seat_id): Retrieve seat by ID
- get_scope(seat_id): Get allowed operations for a seat
- can_request_action(seat_id, action): Check if action is allowed
- revoke_seat(seat_id, reason, audit_ref): Revoke a seat immediately
- list_active_seats(): Get all active seats
- get_seat_by_holder(holder): Find seat by holder identity

Registry Lifecycle
------------------
- Created fresh on process startup (no persistence)
- Seats are added via register_seat() (typically by kernel/orchestrator)
- Seats are removed by revoke_seat() or expiration
- No background tasks (expiration is lazy, checked at lookup time)
- All timestamps are UTC-aware

Fail-Closed Behavior
--------------------
- Missing seat → return None or False
- Expired seat → treated as inactive
- Revoked seat → treated as inactive
- Invalid action → return False
- No exceptions on lookup (only on registration)
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Optional
from uuid import uuid4

from .delegated_seat import (
    DelegatedMSOSeat,
    MSOSeatScope,
    MSOSeatStatus,
    validate_delegated_mso_seat,
)


class MSOSeatRegistry:
    """
    Process-local registry for delegated MSO seats.

    Thread-safe via Lock. All operations are atomic (no partial updates).
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._seats: dict[str, DelegatedMSOSeat] = {}
        self._lock = Lock()

    def register_seat(self, seat: DelegatedMSOSeat) -> None:
        """
        Register a new seat in the registry.

        Parameters
        ----------
        seat : DelegatedMSOSeat
            Seat to register. Must be validated before this call.

        Raises
        ------
        ValueError
            If seat_id already exists.
            If seat fails validation.
        """
        validate_delegated_mso_seat(seat)

        with self._lock:
            if seat.seat_id in self._seats:
                raise ValueError(
                    f"Seat {seat.seat_id} already registered. Use revoke_seat() to remove it first."
                )

            self._seats[seat.seat_id] = seat

    def is_seat_active(self, seat_id: str) -> bool:
        """
        Check if a seat exists and is currently active.

        Returns False if seat does not exist, is expired, is revoked, or is suspended.

        Parameters
        ----------
        seat_id : str
            Seat identifier.

        Returns
        -------
        bool
            True if seat is active, False otherwise.
        """
        seat = self.get_seat(seat_id)
        if not seat:
            return False

        if seat.status != MSOSeatStatus.ACTIVE:
            return False

        if seat.is_expired():
            return False

        return True

    def get_seat(self, seat_id: str) -> Optional[DelegatedMSOSeat]:
        """
        Retrieve a seat by ID.

        Returns the seat object or None if not found.
        Does not check if seat is active (use is_seat_active() for that).

        Parameters
        ----------
        seat_id : str
            Seat identifier.

        Returns
        -------
        Optional[DelegatedMSOSeat]
            The seat object, or None if not found.
        """
        with self._lock:
            return self._seats.get(seat_id)

    def get_scope(self, seat_id: str) -> Optional[tuple[MSOSeatScope, ...]]:
        """
        Get the allowed scope (operations) for a seat.

        Returns None if seat does not exist.

        Parameters
        ----------
        seat_id : str
            Seat identifier.

        Returns
        -------
        Optional[tuple[MSOSeatScope, ...]]
            Tuple of allowed operations, or None if seat not found.
        """
        seat = self.get_seat(seat_id)
        if not seat:
            return None
        return seat.scope

    def can_request_action(self, seat_id: str, action: str) -> bool:
        """
        Check if a seat can request a specific action.

        Combines multiple checks:
        1. Seat must exist
        2. Seat must be active
        3. Action must be in scope
        4. Action must not be forbidden

        Parameters
        ----------
        seat_id : str
            Seat identifier.
        action : str
            Action to check (e.g., "plan", "audit").

        Returns
        -------
        bool
            True if action is allowed, False otherwise.
        """
        if not self.is_seat_active(seat_id):
            return False

        seat = self.get_seat(seat_id)
        if not seat:
            return False

        return seat.can_perform_action(action)

    def revoke_seat(
        self, seat_id: str, reason: str, audit_ref: Optional[str] = None
    ) -> None:
        """
        Revoke a seat immediately and irrevocably.

        Parameters
        ----------
        seat_id : str
            Seat identifier.
        reason : str
            Reason for revocation (e.g., "Security incident").
        audit_ref : Optional[str]
            Reference to audit log entry. If not provided, a new UUID is generated.

        Raises
        ------
        ValueError
            If seat does not exist.
        """
        with self._lock:
            seat = self._seats.get(seat_id)
            if not seat:
                raise ValueError(f"Seat {seat_id} not found in registry")

            # Create revoked copy (dataclass is frozen, so we need to create new)
            revoked_seat = DelegatedMSOSeat(
                seat_id=seat.seat_id,
                seat_type=seat.seat_type,
                holder=seat.holder,
                issued_by=seat.issued_by,
                issued_at=seat.issued_at,
                expires_at=seat.expires_at,
                revoked_at=datetime.now(timezone.utc),
                scope=seat.scope,
                forbidden_actions=seat.forbidden_actions,
                requires_policy=seat.requires_policy,
                requires_police=seat.requires_police,
                requires_human_approval=seat.requires_human_approval,
                status=MSOSeatStatus.REVOKED,
                audit_ref=seat.audit_ref,
                revocation_reason=reason,
            )

            self._seats[seat_id] = revoked_seat

    def list_active_seats(self) -> list[DelegatedMSOSeat]:
        """
        Get all currently active seats.

        Active means: status == ACTIVE, not expired, not revoked.

        Returns
        -------
        list[DelegatedMSOSeat]
            List of active seats. Empty list if no active seats.
        """
        with self._lock:
            return [
                seat for seat in self._seats.values() if self._is_active_unsafe(seat)
            ]

    def get_seat_by_holder(self, holder: str) -> Optional[DelegatedMSOSeat]:
        """
        Find an active seat by holder identity.

        Returns the first active seat with matching holder.
        If multiple seats with same holder exist, returns arbitrary one.

        Parameters
        ----------
        holder : str
            Holder identity (e.g., "gpt-4", "claude-opus").

        Returns
        -------
        Optional[DelegatedMSOSeat]
            Active seat with matching holder, or None if not found.
        """
        with self._lock:
            for seat in self._seats.values():
                if seat.holder == holder and self._is_active_unsafe(seat):
                    return seat
            return None

    def count_active_seats(self) -> int:
        """
        Count the number of currently active seats.

        Returns
        -------
        int
            Number of active seats.
        """
        return len(self.list_active_seats())

    def _is_active_unsafe(self, seat: DelegatedMSOSeat) -> bool:
        """
        Internal helper to check if seat is active (assumes lock is held).

        Used within methods that already hold the lock.
        """
        if seat.status != MSOSeatStatus.ACTIVE:
            return False
        if seat.is_expired():
            return False
        return True


# Global registry instance
_global_registry: Optional[MSOSeatRegistry] = None


def get_mso_seat_registry() -> MSOSeatRegistry:
    """
    Get or create the global MSO Seat Registry.

    Lazy initialization pattern. Registry is created on first access.

    Returns
    -------
    MSOSeatRegistry
        The global registry instance.
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = MSOSeatRegistry()
    return _global_registry


def reset_mso_seat_registry() -> None:
    """
    Reset the global registry to a new empty instance.

    Used primarily for testing. In production, should only be called during
    process restart.
    """
    global _global_registry
    _global_registry = MSOSeatRegistry()
