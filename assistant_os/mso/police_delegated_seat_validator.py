"""MSO-owned delegated-seat validator bridge for the Police Gate.

Police owns the enforcement seam, but does not import MSO. This module lives
on the MSO side of that boundary and installs a registry-backed validator into
Police when a production caller opts into delegated-seat validation.
"""

from __future__ import annotations

from .delegated_seat_registry import get_mso_seat_registry


def validate_delegated_seat_ref(
    seat_ref: str,
    action: str | None,
) -> tuple[bool, str]:
    """Validate a delegated seat reference against the live MSO registry."""
    registry = get_mso_seat_registry()
    seat = registry.get_seat(seat_ref)
    if seat is None:
        return False, "Delegated seat reference is not recognized."

    if seat.is_revoked():
        return False, "Delegated seat has been revoked."

    if seat.is_expired():
        return False, "Delegated seat has expired."

    if not registry.is_seat_active(seat_ref):
        return False, "Delegated seat is not active."

    if action and not registry.can_request_action(seat_ref, action):
        return False, "Delegated seat action is outside scope or forbidden."

    return True, "Delegated seat is active and scope-compatible."


def install_mso_delegated_seat_validator() -> None:
    """Install the MSO registry-backed validator into the Police seam."""
    from ..police.enforcement import configure_delegated_seat_validator

    configure_delegated_seat_validator(validate_delegated_seat_ref)
