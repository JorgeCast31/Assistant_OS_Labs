"""Exhaustive unit tests for MSOSovereignStateStore.

Covers:
- allowed path (all fields valid, no active signals/restrictions)
- blocked: approval_missing (empty approval_id)
- blocked: approval_missing (empty capability fields)
- blocked: governance_missing (empty policy_decision_ref)
- blocked: governance_missing (empty governance_ref)
- blocked: approval_expired (expires_at in the past)
- blocked: approval_expired (expires_at is invalid string)
- blocked: kill_switch_active (active signal with kill_switch token)
- blocked: kill_switch_active (active signal with paused token)
- blocked: kill_switch_active (active signal with quarantine token)
- blocked: kill_switch is NOT active when signal has empty status (hardening fix)
- blocked: restriction_active (domain-scoped restriction)
- blocked: restriction_active (wildcard action restriction)
- blocked: restriction_active (domain-wide restriction with no trace when trace-specific exists)
- blocked: state_unavailable on store read exception
- blocked: state_unavailable on malformed payload (no dict)
- get_kill_switch_state: returns inactive when no signals
- get_kill_switch_state: returns active when matching signal present
- get_kill_switch_state: returns active=True/unknown on store exception (fail-closed)
- get_reason: approval_missing
- get_reason: governance_missing
- get_reason: kill_switch_active
- get_reason: restriction_active
- get_reason: allowed (clean state)
- get_reason: state_unavailable on exception
- get_governance_snapshot: coherent shape in clean state
- get_governance_snapshot: kill_switch_state is populated
- get_governance_snapshot: approval_id echoed back
- get_governance_snapshot: state_unavailable fallback on exception
- restriction inactive by status (EXPIRED is not active)
- restriction inactive by expiry (expires_at in the past)
- restriction for different domain does not block
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from assistant_os.mso.mso_sovereign_state_store import MSOSovereignStateStore
from assistant_os.mso.sovereign_state_store import (
    SovereignExecutionDecision,
    SovereignExecutionQuery,
    SovereignGovernanceSnapshot,
    SovereignKillSwitchSnapshot,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FUTURE = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
_PAST = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
_MOCK_PATH = "assistant_os.mso.mso_sovereign_state_store.query_records"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_query(**overrides) -> SovereignExecutionQuery:
    defaults = dict(
        approval_id="appr-001",
        capability_name="shell_exec",
        capability_scope="MACHINE_OPERATOR",
        expires_at=_FUTURE,
        policy_decision_ref="pdr-001",
        governance_ref="gov-001",
        trace_id="trace-001",
        target_domain="MACHINE_OPERATOR",
        target_action="shell_exec",
    )
    defaults.update(overrides)
    return SovereignExecutionQuery(**defaults)


def _make_signal(
    signal_id: str = "sig-001",
    code: str = "kill_switch",
    detail: str = "",
    source: str = "test",
    status: str = "OPEN",
    trace_id: str = "",
) -> dict:
    return {
        "_meta": {"trace_id": trace_id},
        "payload": {
            "signal_id": signal_id,
            "code": code,
            "detail": detail,
            "source": source,
            "status": status,
            "trace_id": trace_id,
        },
    }


def _make_restriction(
    restriction_id: str = "res-001",
    status: str = "ACTIVE",
    expires_at: str = "",
    scope_domain: str = "MACHINE_OPERATOR",
    scope_action: str = "",
    target: str = "",
    trace_id: str = "",
) -> dict:
    return {
        "_meta": {"trace_id": trace_id},
        "payload": {
            "restriction_id": restriction_id,
            "status": status,
            "expires_at": expires_at,
            "scope": {"domain": scope_domain, "action": scope_action},
            "target": target,
            "trace_id": trace_id,
        },
    }


def _store_factory(
    signals: list | None = None,
    restrictions: list | None = None,
):
    """Return a side_effect callable that dispatches query_records by kind."""
    signals = signals or []
    restrictions = restrictions or []

    def _side_effect(*, kind: str, limit: int = 20, trace_id: str = "", since: str = ""):
        if kind == "control_plane_signals":
            return list(signals)
        if kind == "restrictions":
            return list(restrictions)
        return []

    return _side_effect


# ---------------------------------------------------------------------------
# is_execution_allowed — allowed path
# ---------------------------------------------------------------------------


class TestIsExecutionAllowedAllowed:
    def test_allowed_when_all_valid_clean_state(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            decision = store.is_execution_allowed(_make_query())

        assert isinstance(decision, SovereignExecutionDecision)
        assert decision.allowed is True
        assert decision.state == "allowed"
        assert decision.reason.code == "allowed"
        assert decision.kill_switch_state == "inactive"
        assert decision.approval_id == "appr-001"
        assert decision.governance_ref == "gov-001"
        assert decision.policy_decision_ref == "pdr-001"

    def test_allowed_populates_checked_at(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            decision = store.is_execution_allowed(_make_query())
        assert decision.checked_at != ""


# ---------------------------------------------------------------------------
# is_execution_allowed — approval_missing
# ---------------------------------------------------------------------------


class TestIsExecutionAllowedApprovalMissing:
    def test_blocked_empty_approval_id(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            decision = store.is_execution_allowed(_make_query(approval_id=""))
        assert decision.allowed is False
        assert decision.reason.code == "approval_missing"

    def test_blocked_whitespace_approval_id(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            decision = store.is_execution_allowed(_make_query(approval_id="   "))
        assert decision.allowed is False
        assert decision.reason.code == "approval_missing"

    def test_blocked_empty_capability_name(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            decision = store.is_execution_allowed(_make_query(capability_name=""))
        assert decision.allowed is False
        assert decision.reason.code == "approval_missing"

    def test_blocked_empty_capability_scope(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            decision = store.is_execution_allowed(_make_query(capability_scope=""))
        assert decision.allowed is False
        assert decision.reason.code == "approval_missing"

    def test_blocked_empty_expires_at(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            decision = store.is_execution_allowed(_make_query(expires_at=""))
        assert decision.allowed is False
        assert decision.reason.code == "approval_missing"


# ---------------------------------------------------------------------------
# is_execution_allowed — governance_missing
# ---------------------------------------------------------------------------


class TestIsExecutionAllowedGovernanceMissing:
    def test_blocked_empty_policy_decision_ref(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            decision = store.is_execution_allowed(_make_query(policy_decision_ref=""))
        assert decision.allowed is False
        assert decision.reason.code == "governance_missing"

    def test_blocked_empty_governance_ref(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            decision = store.is_execution_allowed(_make_query(governance_ref=""))
        assert decision.allowed is False
        assert decision.reason.code == "governance_missing"


# ---------------------------------------------------------------------------
# is_execution_allowed — approval_expired
# ---------------------------------------------------------------------------


class TestIsExecutionAllowedExpiry:
    def test_blocked_expires_at_in_the_past(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            decision = store.is_execution_allowed(_make_query(expires_at=_PAST))
        assert decision.allowed is False
        assert decision.reason.code == "approval_expired"

    def test_blocked_expires_at_invalid_string(self):
        """Malformed expires_at raises internally → fail-closed as state_unavailable."""
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            decision = store.is_execution_allowed(_make_query(expires_at="not-a-date"))
        assert decision.allowed is False
        assert decision.reason.code == "state_unavailable"

    def test_blocked_expires_at_no_timezone(self):
        """ISO string without timezone info → _parse_iso returns None → ValueError."""
        store = MSOSovereignStateStore()
        naive = datetime.now().isoformat()  # no timezone
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            decision = store.is_execution_allowed(_make_query(expires_at=naive))
        assert decision.allowed is False
        assert decision.reason.code == "state_unavailable"


# ---------------------------------------------------------------------------
# is_execution_allowed — kill_switch_active
# ---------------------------------------------------------------------------


class TestIsExecutionAllowedKillSwitch:
    def test_blocked_kill_switch_token_in_code(self):
        signal = _make_signal(code="kill_switch", status="OPEN")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is False
        assert decision.reason.code == "kill_switch_active"
        assert decision.kill_switch_state == "active"

    def test_blocked_paused_token_in_code(self):
        signal = _make_signal(code="paused", status="ACTIVE")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is False
        assert decision.reason.code == "kill_switch_active"

    def test_blocked_quarantine_token_in_detail(self):
        signal = _make_signal(code="system_event", detail="quarantine triggered", status="OPEN")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is False
        assert decision.reason.code == "kill_switch_active"

    def test_blocked_killswitch_variant_token(self):
        signal = _make_signal(code="killswitch", status="OPEN")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is False
        assert decision.reason.code == "kill_switch_active"

    def test_kill_switch_signal_ids_propagated(self):
        signal = _make_signal(signal_id="sig-xyz", code="kill_switch", status="OPEN")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            decision = store.is_execution_allowed(_make_query())
        assert "sig-xyz" in decision.reason.signal_ids

    def test_not_blocked_by_kill_switch_token_with_empty_status(self):
        """Hardening fix: empty status must NOT activate the kill switch."""
        signal = _make_signal(code="kill_switch", status="")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            decision = store.is_execution_allowed(_make_query())
        # No active restrictions either → should be allowed
        assert decision.allowed is True

    def test_not_blocked_by_closed_signal(self):
        signal = _make_signal(code="kill_switch", status="CLOSED")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is True

    def test_not_blocked_by_signal_without_matching_token(self):
        signal = _make_signal(code="heartbeat", detail="system nominal", status="OPEN")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# is_execution_allowed — restriction_active
# ---------------------------------------------------------------------------


class TestIsExecutionAllowedRestriction:
    def test_blocked_by_domain_restriction(self):
        restriction = _make_restriction(scope_domain="MACHINE_OPERATOR")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(restrictions=[restriction])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is False
        assert decision.reason.code == "restriction_active"
        assert "res-001" in decision.reason.restriction_ids

    def test_blocked_by_wildcard_action_restriction(self):
        restriction = _make_restriction(scope_domain="MACHINE_OPERATOR", scope_action="*")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(restrictions=[restriction])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is False
        assert decision.reason.code == "restriction_active"

    def test_blocked_by_domain_wide_restriction_even_when_trace_specific_exists(self):
        """
        Hardening fix: domain-wide restrictions (no trace_id) must block
        even when trace-specific restrictions also exist for a different action.
        This was a bug in the old double-read logic.
        """
        # trace-specific restriction for a DIFFERENT action (no match)
        trace_restriction = _make_restriction(
            restriction_id="res-trace",
            scope_domain="MACHINE_OPERATOR",
            scope_action="file_write",
            trace_id="trace-001",
        )
        # domain-wide restriction with no action filter (matches everything)
        domain_restriction = _make_restriction(
            restriction_id="res-domain",
            scope_domain="MACHINE_OPERATOR",
            scope_action="",
            trace_id="",
        )
        store = MSOSovereignStateStore()
        with patch(
            _MOCK_PATH,
            side_effect=_store_factory(restrictions=[trace_restriction, domain_restriction]),
        ):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is False
        assert decision.reason.code == "restriction_active"
        assert "res-domain" in decision.reason.restriction_ids

    def test_not_blocked_by_restriction_for_different_domain(self):
        restriction = _make_restriction(scope_domain="HOST")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(restrictions=[restriction])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is True

    def test_not_blocked_by_restriction_for_different_action(self):
        restriction = _make_restriction(scope_domain="MACHINE_OPERATOR", scope_action="file_write")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(restrictions=[restriction])):
            # query is for shell_exec, restriction is for file_write
            decision = store.is_execution_allowed(_make_query(target_action="shell_exec"))
        assert decision.allowed is True

    def test_not_blocked_by_expired_restriction(self):
        restriction = _make_restriction(
            scope_domain="MACHINE_OPERATOR",
            expires_at=_PAST,
        )
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(restrictions=[restriction])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is True

    def test_not_blocked_by_restriction_with_status_expired(self):
        restriction = _make_restriction(scope_domain="MACHINE_OPERATOR", status="EXPIRED")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(restrictions=[restriction])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is True

    def test_not_blocked_by_restriction_with_status_cleared(self):
        restriction = _make_restriction(scope_domain="MACHINE_OPERATOR", status="CLEARED")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(restrictions=[restriction])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is True

    def test_blocked_by_restriction_with_status_extended(self):
        restriction = _make_restriction(scope_domain="MACHINE_OPERATOR", status="EXTENDED")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(restrictions=[restriction])):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is False
        assert decision.reason.code == "restriction_active"


# ---------------------------------------------------------------------------
# is_execution_allowed — fail-closed on store error
# ---------------------------------------------------------------------------


class TestIsExecutionAllowedFailClosed:
    def test_blocked_on_store_read_exception(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=RuntimeError("disk failure")):
            decision = store.is_execution_allowed(_make_query())
        assert decision.allowed is False
        assert decision.reason.code == "state_unavailable"

    def test_blocked_on_malformed_payload(self):
        """If a record has a non-dict payload, downstream .get() raises → fail-closed."""
        bad_record = {"_meta": {}, "payload": "corrupted string not a dict"}
        store = MSOSovereignStateStore()
        with patch(
            _MOCK_PATH,
            side_effect=_store_factory(restrictions=[bad_record]),
        ):
            # Malformed restriction payload — _restriction_is_active calls .get on str
            decision = store.is_execution_allowed(_make_query())
        # Either allowed (if error is silently skipped) or blocked — must never be
        # allowed due to bad data; verify no exception escapes
        assert isinstance(decision, SovereignExecutionDecision)
        assert decision.allowed is False  # fail-closed: bad data → state_unavailable

    def test_blocked_state_is_blocked_not_allowed(self):
        """Ensure decision.state == 'blocked' and not 'allowed' on error."""
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=Exception("unknown")):
            decision = store.is_execution_allowed(_make_query())
        assert decision.state == "blocked"


# ---------------------------------------------------------------------------
# get_kill_switch_state
# ---------------------------------------------------------------------------


class TestGetKillSwitchState:
    def test_inactive_when_no_signals(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            snap = store.get_kill_switch_state(target_domain="MACHINE_OPERATOR")
        assert isinstance(snap, SovereignKillSwitchSnapshot)
        assert snap.active is False
        assert snap.state == "inactive"
        assert snap.reason.code == "allowed"

    def test_active_when_matching_signal_present(self):
        signal = _make_signal(code="kill_switch", status="OPEN")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            snap = store.get_kill_switch_state(target_domain="MACHINE_OPERATOR")
        assert snap.active is True
        assert snap.state == "active"
        assert snap.reason.code == "kill_switch_active"

    def test_fail_closed_on_store_exception(self):
        """kill-switch state must be active=True when store is unreadable."""
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=IOError("network")):
            snap = store.get_kill_switch_state(target_domain="MACHINE_OPERATOR")
        assert snap.active is True
        assert snap.state == "unknown"
        assert snap.reason.code == "state_unavailable"

    def test_checked_at_always_populated(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            snap = store.get_kill_switch_state(target_domain="MACHINE_OPERATOR")
        assert snap.checked_at != ""

    def test_empty_status_signal_does_not_activate_kill_switch(self):
        """Hardening: empty status must not be treated as active."""
        signal = _make_signal(code="kill_switch", status="")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            snap = store.get_kill_switch_state(target_domain="MACHINE_OPERATOR")
        assert snap.active is False


# ---------------------------------------------------------------------------
# get_reason
# ---------------------------------------------------------------------------


class TestGetReason:
    def test_approval_missing_when_no_approval_id(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            reason = store.get_reason(
                governance_ref="gov-001",
                policy_decision_ref="pdr-001",
                approval_id="",
            )
        assert reason.code == "approval_missing"

    def test_governance_missing_when_no_policy_ref(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            reason = store.get_reason(approval_id="appr-001", policy_decision_ref="")
        assert reason.code == "governance_missing"

    def test_governance_missing_when_no_governance_ref(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            reason = store.get_reason(
                approval_id="appr-001",
                policy_decision_ref="pdr-001",
                governance_ref="",
            )
        assert reason.code == "governance_missing"

    def test_kill_switch_active_reason(self):
        signal = _make_signal(code="kill_switch", status="OPEN")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            reason = store.get_reason(
                approval_id="appr-001",
                policy_decision_ref="pdr-001",
                governance_ref="gov-001",
            )
        assert reason.code == "kill_switch_active"

    def test_restriction_active_reason(self):
        restriction = _make_restriction(
            restriction_id="res-001",
            scope_domain="MACHINE_OPERATOR",
            trace_id="trace-001",
        )
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(restrictions=[restriction])):
            reason = store.get_reason(
                approval_id="appr-001",
                policy_decision_ref="pdr-001",
                governance_ref="gov-001",
                trace_id="trace-001",
            )
        assert reason.code == "restriction_active"
        assert "res-001" in reason.restriction_ids

    def test_allowed_reason_clean_state(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            reason = store.get_reason(
                approval_id="appr-001",
                policy_decision_ref="pdr-001",
                governance_ref="gov-001",
            )
        assert reason.code == "allowed"

    def test_state_unavailable_on_exception(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=RuntimeError("broken")):
            reason = store.get_reason(
                approval_id="appr-001",
                policy_decision_ref="pdr-001",
                governance_ref="gov-001",
            )
        assert reason.code == "state_unavailable"


# ---------------------------------------------------------------------------
# get_governance_snapshot
# ---------------------------------------------------------------------------


class TestGetGovernanceSnapshot:
    def test_coherent_shape_clean_state(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            snap = store.get_governance_snapshot(
                governance_ref="gov-001",
                policy_decision_ref="pdr-001",
                trace_id="trace-001",
                approval_id="appr-001",
            )
        assert isinstance(snap, SovereignGovernanceSnapshot)
        assert snap.governance_ref == "gov-001"
        assert snap.policy_decision_ref == "pdr-001"
        assert snap.trace_id == "trace-001"
        assert snap.approval_id == "appr-001"
        assert snap.kill_switch_state == "inactive"
        assert snap.active_restriction_ids == ()
        assert snap.active_signal_ids == ()

    def test_kill_switch_state_populated_on_active_signal(self):
        signal = _make_signal(code="kill_switch", status="OPEN", signal_id="sig-ks")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            snap = store.get_governance_snapshot(governance_ref="gov-001")
        assert snap.kill_switch_state == "active"
        assert "sig-ks" in snap.active_signal_ids

    def test_approval_id_echoed_in_snapshot(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            snap = store.get_governance_snapshot(
                governance_ref="gov-001",
                approval_id="appr-xyz",
            )
        assert snap.approval_id == "appr-xyz"

    def test_active_restriction_ids_in_snapshot(self):
        restriction = _make_restriction(restriction_id="res-snap", scope_domain="MACHINE_OPERATOR")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(restrictions=[restriction])):
            snap = store.get_governance_snapshot(governance_ref="gov-001")
        assert "res-snap" in snap.active_restriction_ids

    def test_state_unavailable_fallback_on_exception(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=RuntimeError("disk")):
            snap = store.get_governance_snapshot(
                governance_ref="gov-001",
                approval_id="appr-001",
            )
        assert isinstance(snap, SovereignGovernanceSnapshot)
        assert snap.kill_switch_state == "unknown"
        assert snap.active_restriction_ids == ()
        assert len(snap.active_reasons) > 0
        assert snap.active_reasons[0].code == "state_unavailable"
        # governance_ref and approval_id must still be echoed even in fallback
        assert snap.governance_ref == "gov-001"
        assert snap.approval_id == "appr-001"

    def test_backing_record_kinds_non_empty(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            snap = store.get_governance_snapshot(governance_ref="gov-001")
        # Even with empty store, fallback ensures kinds are present
        assert len(snap.backing_record_kinds) > 0


# ---------------------------------------------------------------------------
# reason.code coverage audit
# ---------------------------------------------------------------------------


class TestReasonCodeCoverage:
    """Ensure every SovereignReasonCode is reachable and returns the right code."""

    _EXPECTED_CODES = {
        "allowed",
        "kill_switch_active",
        "restriction_active",
        "approval_missing",
        "approval_expired",
        "governance_missing",
        "governance_unresolved",
        "state_unavailable",
    }

    def test_all_expected_codes_are_literals(self):
        from assistant_os.mso.sovereign_state_store import SovereignReasonCode
        import typing

        args = typing.get_args(SovereignReasonCode)
        assert set(args) == self._EXPECTED_CODES

    def test_allowed_code_reachable(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            d = store.is_execution_allowed(_make_query())
        assert d.reason.code == "allowed"

    def test_kill_switch_active_code_reachable(self):
        signal = _make_signal(code="kill_switch", status="OPEN")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(signals=[signal])):
            d = store.is_execution_allowed(_make_query())
        assert d.reason.code == "kill_switch_active"

    def test_restriction_active_code_reachable(self):
        r = _make_restriction(scope_domain="MACHINE_OPERATOR")
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory(restrictions=[r])):
            d = store.is_execution_allowed(_make_query())
        assert d.reason.code == "restriction_active"

    def test_approval_missing_code_reachable(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            d = store.is_execution_allowed(_make_query(approval_id=""))
        assert d.reason.code == "approval_missing"

    def test_approval_expired_code_reachable(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            d = store.is_execution_allowed(_make_query(expires_at=_PAST))
        assert d.reason.code == "approval_expired"

    def test_governance_missing_code_reachable(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=_store_factory()):
            d = store.is_execution_allowed(_make_query(governance_ref=""))
        assert d.reason.code == "governance_missing"

    def test_state_unavailable_code_reachable(self):
        store = MSOSovereignStateStore()
        with patch(_MOCK_PATH, side_effect=RuntimeError("bang")):
            d = store.is_execution_allowed(_make_query())
        assert d.reason.code == "state_unavailable"
