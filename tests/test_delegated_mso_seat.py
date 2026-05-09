"""
Tests for Delegated MSO Seat Recognition.

Validates:
1. DelegatedMSOSeat contract and validation
2. MSOSeatRegistry operations
3. Scope and forbidden action enforcement
4. Lifecycle (active, expired, revoked, suspended)
5. Authority boundaries (cannot execute, cannot bypass policy, etc.)

Does NOT test integration with PolicyDecision, Police, or pipelines
(those are done separately in integration tests).
"""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from assistant_os.mso.delegated_seat import (
    DelegatedMSOSeat,
    MSOSeatType,
    MSOSeatScope,
    MSOSeatStatus,
    validate_delegated_mso_seat,
    coerce_delegated_mso_seat,
)
from assistant_os.mso.delegated_seat_registry import (
    MSOSeatRegistry,
    get_mso_seat_registry,
    reset_mso_seat_registry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def now():
    """Current UTC time."""
    return datetime.now(timezone.utc)


@pytest.fixture
def gpt_seat_active(now):
    """GPT conversational seat, currently active."""
    return DelegatedMSOSeat(
        seat_id="gpt-seat-001",
        seat_type=MSOSeatType.GPT_CONVERSATIONAL,
        holder="gpt-4-turbo",
        issued_by="kernel",
        issued_at=now,
        expires_at=now + timedelta(hours=24),
        scope=(MSOSeatScope.PLAN, MSOSeatScope.AUDIT, MSOSeatScope.RECOMMEND),
        forbidden_actions=("direct_execution", "invoke_machine_operator"),
        requires_policy=True,
        requires_police=True,
        requires_human_approval=False,
        status=MSOSeatStatus.ACTIVE,
        audit_ref="audit-gpt-001",
    )


@pytest.fixture
def claude_seat_with_execution(now):
    """Claude analytical seat with prepare_execution_request scope."""
    return DelegatedMSOSeat(
        seat_id="claude-seat-dev-001",
        seat_type=MSOSeatType.CLAUDE_ANALYTICAL,
        holder="claude-opus",
        issued_by="kernel",
        issued_at=now,
        expires_at=now + timedelta(days=7),
        scope=(
            MSOSeatScope.PLAN,
            MSOSeatScope.AUDIT,
            MSOSeatScope.RECOMMEND,
            MSOSeatScope.PREPARE_EXECUTION_REQUEST,
        ),
        forbidden_actions=("direct_execution", "invoke_machine_operator"),
        requires_policy=True,
        requires_police=True,
        requires_human_approval=True,
        status=MSOSeatStatus.ACTIVE,
        audit_ref="audit-claude-dev-001",
    )


@pytest.fixture
def expired_seat(now):
    """A seat that has already expired."""
    return DelegatedMSOSeat(
        seat_id="expired-seat-001",
        seat_type=MSOSeatType.GPT_CONVERSATIONAL,
        holder="gpt-3.5",
        issued_by="kernel",
        issued_at=now - timedelta(hours=48),
        expires_at=now - timedelta(hours=24),  # Expired 24 hours ago
        scope=(MSOSeatScope.PLAN,),
        forbidden_actions=(),
        status=MSOSeatStatus.ACTIVE,  # Status still says ACTIVE but TTL has passed
        audit_ref="audit-expired-001",
    )


@pytest.fixture
def revoked_seat(now):
    """A seat that has been explicitly revoked."""
    return DelegatedMSOSeat(
        seat_id="revoked-seat-001",
        seat_type=MSOSeatType.HUMAN_OPERATOR,
        holder="user@example.com",
        issued_by="kernel",
        issued_at=now - timedelta(hours=1),
        revoked_at=now,
        scope=(MSOSeatScope.PLAN, MSOSeatScope.AUDIT),
        forbidden_actions=(),
        status=MSOSeatStatus.REVOKED,
        audit_ref="audit-revoked-001",
        revocation_reason="Security incident",
    )


@pytest.fixture
def registry():
    """Fresh registry for each test."""
    reset_mso_seat_registry()
    return get_mso_seat_registry()


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestDelegatedMSOSeatContract:
    """Tests for DelegatedMSOSeat dataclass and validation."""

    def test_seat_construction_valid(self, gpt_seat_active):
        """Valid seat can be constructed."""
        assert gpt_seat_active.seat_id == "gpt-seat-001"
        assert gpt_seat_active.seat_type == MSOSeatType.GPT_CONVERSATIONAL
        assert gpt_seat_active.holder == "gpt-4-turbo"
        assert gpt_seat_active.status == MSOSeatStatus.ACTIVE

    def test_seat_construction_invalid_seat_id(self, now):
        """Empty seat_id raises ValueError."""
        with pytest.raises(ValueError, match="seat_id must be non-empty"):
            DelegatedMSOSeat(
                seat_id="",
                seat_type=MSOSeatType.GPT_CONVERSATIONAL,
                holder="gpt-4",
                issued_by="kernel",
                issued_at=now,
                scope=(MSOSeatScope.PLAN,),
                audit_ref="audit-001",
            )

    def test_seat_construction_invalid_holder(self, now):
        """Empty holder raises ValueError."""
        with pytest.raises(ValueError, match="holder must be non-empty"):
            DelegatedMSOSeat(
                seat_id="seat-001",
                seat_type=MSOSeatType.GPT_CONVERSATIONAL,
                holder="",
                issued_by="kernel",
                issued_at=now,
                scope=(MSOSeatScope.PLAN,),
                audit_ref="audit-001",
            )

    def test_seat_construction_empty_scope(self, now):
        """Empty scope raises ValueError."""
        with pytest.raises(ValueError, match="scope must be non-empty"):
            DelegatedMSOSeat(
                seat_id="seat-001",
                seat_type=MSOSeatType.GPT_CONVERSATIONAL,
                holder="gpt-4",
                issued_by="kernel",
                issued_at=now,
                scope=(),  # Empty
                audit_ref="audit-001",
            )

    def test_seat_construction_expires_before_issued(self, now):
        """expires_at before issued_at raises ValueError."""
        with pytest.raises(ValueError, match="expires_at must be after issued_at"):
            DelegatedMSOSeat(
                seat_id="seat-001",
                seat_type=MSOSeatType.GPT_CONVERSATIONAL,
                holder="gpt-4",
                issued_by="kernel",
                issued_at=now,
                expires_at=now - timedelta(hours=1),  # Before issued_at
                scope=(MSOSeatScope.PLAN,),
                audit_ref="audit-001",
            )

    def test_seat_construction_no_timezone_issued_at(self, now):
        """Naive issued_at raises ValueError."""
        naive_now = now.replace(tzinfo=None)
        with pytest.raises(ValueError, match="issued_at must be timezone-aware"):
            DelegatedMSOSeat(
                seat_id="seat-001",
                seat_type=MSOSeatType.GPT_CONVERSATIONAL,
                holder="gpt-4",
                issued_by="kernel",
                issued_at=naive_now,
                scope=(MSOSeatScope.PLAN,),
                audit_ref="audit-001",
            )

    def test_seat_revoked_without_revoked_at(self, now):
        """status=REVOKED but revoked_at=None raises ValueError."""
        with pytest.raises(
            ValueError, match="status is REVOKED but revoked_at is not set"
        ):
            DelegatedMSOSeat(
                seat_id="seat-001",
                seat_type=MSOSeatType.GPT_CONVERSATIONAL,
                holder="gpt-4",
                issued_by="kernel",
                issued_at=now,
                scope=(MSOSeatScope.PLAN,),
                status=MSOSeatStatus.REVOKED,
                audit_ref="audit-001",
            )

    def test_seat_revoked_at_set_but_status_active(self, now):
        """revoked_at set but status != REVOKED raises ValueError."""
        with pytest.raises(ValueError, match="revoked_at is set but status is not REVOKED"):
            DelegatedMSOSeat(
                seat_id="seat-001",
                seat_type=MSOSeatType.GPT_CONVERSATIONAL,
                holder="gpt-4",
                issued_by="kernel",
                issued_at=now,
                revoked_at=now,
                scope=(MSOSeatScope.PLAN,),
                status=MSOSeatStatus.ACTIVE,  # Mismatch
                audit_ref="audit-001",
            )

    def test_seat_frozen(self, gpt_seat_active):
        """Seat dataclass is frozen (immutable)."""
        with pytest.raises(Exception):  # FrozenInstanceError
            gpt_seat_active.holder = "different-holder"


class TestSeatMethods:
    """Tests for DelegatedMSOSeat methods."""

    def test_is_active_true_when_active_and_not_expired(self, gpt_seat_active):
        """is_active() returns True for active, non-expired seat."""
        assert gpt_seat_active.is_active() is True

    def test_is_active_false_when_status_revoked(self, revoked_seat):
        """is_active() returns False when status is REVOKED."""
        assert revoked_seat.is_active() is False

    def test_is_active_false_when_expired(self, expired_seat):
        """is_active() returns False when seat has expired."""
        assert expired_seat.is_active() is False

    def test_is_expired_true_for_expired_seat(self, expired_seat):
        """is_expired() returns True when expires_at < now."""
        assert expired_seat.is_expired() is True

    def test_is_expired_false_when_no_expiration(self, now):
        """is_expired() returns False when expires_at is None."""
        seat = DelegatedMSOSeat(
            seat_id="seat-001",
            seat_type=MSOSeatType.HUMAN_OPERATOR,
            holder="admin",
            issued_by="kernel",
            issued_at=now,
            expires_at=None,  # No expiration
            scope=(MSOSeatScope.PLAN,),
            audit_ref="audit-001",
        )
        assert seat.is_expired() is False

    def test_is_revoked_true_for_revoked_seat(self, revoked_seat):
        """is_revoked() returns True when revoked_at is set."""
        assert revoked_seat.is_revoked() is True

    def test_is_revoked_false_for_active_seat(self, gpt_seat_active):
        """is_revoked() returns False for active seat."""
        assert gpt_seat_active.is_revoked() is False

    def test_can_perform_action_allowed(self, gpt_seat_active):
        """can_perform_action() returns True for action in scope."""
        assert gpt_seat_active.can_perform_action("plan") is True
        assert gpt_seat_active.can_perform_action(MSOSeatScope.PLAN.value) is True

    def test_can_perform_action_forbidden(self, gpt_seat_active):
        """can_perform_action() returns False for forbidden action."""
        assert gpt_seat_active.can_perform_action("direct_execution") is False
        assert gpt_seat_active.can_perform_action("invoke_machine_operator") is False

    def test_can_perform_action_not_in_scope(self, gpt_seat_active):
        """can_perform_action() returns False for action not in scope."""
        assert gpt_seat_active.can_perform_action("execute") is False
        assert gpt_seat_active.can_perform_action("prepare_execution_request") is False

    def test_to_dict(self, gpt_seat_active):
        """to_dict() serializes seat correctly."""
        seat_dict = gpt_seat_active.to_dict()
        assert seat_dict["seat_id"] == "gpt-seat-001"
        assert seat_dict["seat_type"] == "gpt_conversational"
        assert seat_dict["holder"] == "gpt-4-turbo"
        assert seat_dict["status"] == "active"
        assert "plan" in seat_dict["scope"]
        assert "direct_execution" in seat_dict["forbidden_actions"]


class TestCoerceDelegatedMSOSeat:
    """Tests for coerce_delegated_mso_seat helper."""

    def test_coerce_from_dict(self, now):
        """Coerce raw dict to DelegatedMSOSeat."""
        raw = {
            "seat_id": "coerced-seat",
            "seat_type": "gpt_conversational",
            "holder": "gpt-4",
            "issued_by": "kernel",
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
            "scope": ["plan", "audit"],
            "forbidden_actions": ["direct_execution"],
            "status": "active",
            "audit_ref": "audit-coerced",
        }
        seat = coerce_delegated_mso_seat(raw)
        assert seat.seat_id == "coerced-seat"
        assert seat.seat_type == MSOSeatType.GPT_CONVERSATIONAL
        assert MSOSeatScope.PLAN in seat.scope

    def test_coerce_enum_coercion(self, now):
        """Coerce handles enum string conversion."""
        raw = {
            "seat_id": "enum-coerce-test",
            "seat_type": "claude_analytical",  # String, needs coercion
            "holder": "claude",
            "issued_by": "kernel",
            "issued_at": now.isoformat(),
            "scope": ["plan", "audit"],  # Strings, need coercion
            "status": "active",  # String, needs coercion
            "audit_ref": "audit-enum",
        }
        seat = coerce_delegated_mso_seat(raw)
        assert seat.seat_type == MSOSeatType.CLAUDE_ANALYTICAL
        assert seat.status == MSOSeatStatus.ACTIVE
        assert MSOSeatScope.PLAN in seat.scope


# ---------------------------------------------------------------------------
# Registry Tests
# ---------------------------------------------------------------------------


class TestMSOSeatRegistry:
    """Tests for MSOSeatRegistry operations."""

    def test_register_seat(self, registry, gpt_seat_active):
        """Register a valid seat."""
        registry.register_seat(gpt_seat_active)
        assert registry.is_seat_active(gpt_seat_active.seat_id) is True

    def test_register_duplicate_raises(self, registry, gpt_seat_active):
        """Registering duplicate seat_id raises ValueError."""
        registry.register_seat(gpt_seat_active)
        with pytest.raises(ValueError, match="already registered"):
            registry.register_seat(gpt_seat_active)

    def test_is_seat_active_true(self, registry, gpt_seat_active):
        """is_seat_active() returns True for active seat."""
        registry.register_seat(gpt_seat_active)
        assert registry.is_seat_active(gpt_seat_active.seat_id) is True

    def test_is_seat_active_false_not_found(self, registry):
        """is_seat_active() returns False for non-existent seat."""
        assert registry.is_seat_active("nonexistent-seat") is False

    def test_is_seat_active_false_expired(self, registry, expired_seat):
        """is_seat_active() returns False for expired seat."""
        registry.register_seat(expired_seat)
        assert registry.is_seat_active(expired_seat.seat_id) is False

    def test_is_seat_active_false_revoked(self, registry, revoked_seat):
        """is_seat_active() returns False for revoked seat."""
        registry.register_seat(revoked_seat)
        assert registry.is_seat_active(revoked_seat.seat_id) is False

    def test_get_seat(self, registry, gpt_seat_active):
        """get_seat() retrieves seat by ID."""
        registry.register_seat(gpt_seat_active)
        retrieved = registry.get_seat(gpt_seat_active.seat_id)
        assert retrieved is not None
        assert retrieved.holder == "gpt-4-turbo"

    def test_get_seat_not_found(self, registry):
        """get_seat() returns None for non-existent seat."""
        assert registry.get_seat("nonexistent") is None

    def test_get_scope(self, registry, gpt_seat_active):
        """get_scope() returns seat scope."""
        registry.register_seat(gpt_seat_active)
        scope = registry.get_scope(gpt_seat_active.seat_id)
        assert MSOSeatScope.PLAN in scope
        assert MSOSeatScope.AUDIT in scope
        assert MSOSeatScope.PREPARE_EXECUTION_REQUEST not in scope

    def test_get_scope_not_found(self, registry):
        """get_scope() returns None for non-existent seat."""
        assert registry.get_scope("nonexistent") is None

    def test_can_request_action_allowed(self, registry, gpt_seat_active):
        """can_request_action() returns True for allowed action."""
        registry.register_seat(gpt_seat_active)
        assert registry.can_request_action(gpt_seat_active.seat_id, "plan") is True
        assert registry.can_request_action(gpt_seat_active.seat_id, "audit") is True

    def test_can_request_action_forbidden(self, registry, gpt_seat_active):
        """can_request_action() returns False for forbidden action."""
        registry.register_seat(gpt_seat_active)
        assert (
            registry.can_request_action(gpt_seat_active.seat_id, "direct_execution")
            is False
        )

    def test_can_request_action_not_in_scope(self, registry, gpt_seat_active):
        """can_request_action() returns False for out-of-scope action."""
        registry.register_seat(gpt_seat_active)
        assert (
            registry.can_request_action(
                gpt_seat_active.seat_id, "prepare_execution_request"
            )
            is False
        )

    def test_can_request_action_inactive_seat(self, registry, expired_seat):
        """can_request_action() returns False for inactive seat."""
        registry.register_seat(expired_seat)
        assert registry.can_request_action(expired_seat.seat_id, "plan") is False

    def test_revoke_seat(self, registry, gpt_seat_active):
        """revoke_seat() marks seat as revoked."""
        registry.register_seat(gpt_seat_active)
        assert registry.is_seat_active(gpt_seat_active.seat_id) is True

        registry.revoke_seat(gpt_seat_active.seat_id, "Test revocation")
        assert registry.is_seat_active(gpt_seat_active.seat_id) is False

        revoked = registry.get_seat(gpt_seat_active.seat_id)
        assert revoked.status == MSOSeatStatus.REVOKED
        assert revoked.revocation_reason == "Test revocation"

    def test_revoke_nonexistent_seat_raises(self, registry):
        """revoke_seat() raises ValueError for non-existent seat."""
        with pytest.raises(ValueError, match="not found"):
            registry.revoke_seat("nonexistent", "Test")

    def test_list_active_seats(self, registry, gpt_seat_active, claude_seat_with_execution):
        """list_active_seats() returns all active seats."""
        registry.register_seat(gpt_seat_active)
        registry.register_seat(claude_seat_with_execution)
        active = registry.list_active_seats()
        assert len(active) == 2

    def test_list_active_seats_excludes_expired(self, registry, gpt_seat_active, expired_seat):
        """list_active_seats() excludes expired seats."""
        registry.register_seat(gpt_seat_active)
        registry.register_seat(expired_seat)
        active = registry.list_active_seats()
        assert len(active) == 1
        assert active[0].seat_id == gpt_seat_active.seat_id

    def test_list_active_seats_excludes_revoked(self, registry, gpt_seat_active, revoked_seat):
        """list_active_seats() excludes revoked seats."""
        registry.register_seat(gpt_seat_active)
        registry.register_seat(revoked_seat)
        active = registry.list_active_seats()
        assert len(active) == 1
        assert active[0].seat_id == gpt_seat_active.seat_id

    def test_get_seat_by_holder(self, registry, gpt_seat_active):
        """get_seat_by_holder() finds seat by holder."""
        registry.register_seat(gpt_seat_active)
        found = registry.get_seat_by_holder("gpt-4-turbo")
        assert found is not None
        assert found.seat_id == gpt_seat_active.seat_id

    def test_get_seat_by_holder_not_found(self, registry):
        """get_seat_by_holder() returns None for non-existent holder."""
        assert registry.get_seat_by_holder("nonexistent-model") is None

    def test_count_active_seats(self, registry, gpt_seat_active, expired_seat):
        """count_active_seats() counts only active seats."""
        registry.register_seat(gpt_seat_active)
        registry.register_seat(expired_seat)
        assert registry.count_active_seats() == 1


# ---------------------------------------------------------------------------
# Boundary Tests
# ---------------------------------------------------------------------------


class TestAuthorityBoundaries:
    """Tests verifying that delegated seats respect authority boundaries."""

    def test_gpt_seat_cannot_execute_directly(self, registry, gpt_seat_active):
        """GPT seat scope does not include execution."""
        registry.register_seat(gpt_seat_active)
        assert (
            registry.can_request_action(gpt_seat_active.seat_id, "execute") is False
        )
        assert (
            registry.can_request_action(
                gpt_seat_active.seat_id, "direct_execution"
            )
            is False
        )

    def test_gpt_seat_cannot_invoke_machine_operator(self, registry, gpt_seat_active):
        """GPT seat cannot invoke MACHINE_OPERATOR."""
        registry.register_seat(gpt_seat_active)
        assert (
            registry.can_request_action(
                gpt_seat_active.seat_id, "invoke_machine_operator"
            )
            is False
        )

    def test_gpt_seat_cannot_bypass_policy(self, registry, gpt_seat_active):
        """GPT seat cannot set requires_policy=False."""
        # Seat has requires_policy=True by contract
        registry.register_seat(gpt_seat_active)
        seat = registry.get_seat(gpt_seat_active.seat_id)
        assert seat.requires_policy is True

    def test_gpt_seat_cannot_bypass_police(self, registry, gpt_seat_active):
        """GPT seat cannot set requires_police=False."""
        # Seat has requires_police=True by contract
        registry.register_seat(gpt_seat_active)
        seat = registry.get_seat(gpt_seat_active.seat_id)
        assert seat.requires_police is True

    def test_revoked_seat_denies_all_actions(self, registry, gpt_seat_active):
        """Revoked seat cannot perform any action."""
        registry.register_seat(gpt_seat_active)
        registry.revoke_seat(gpt_seat_active.seat_id, "Test")

        assert registry.can_request_action(gpt_seat_active.seat_id, "plan") is False
        assert registry.can_request_action(gpt_seat_active.seat_id, "audit") is False

    def test_expired_seat_denies_all_actions(self, registry, expired_seat):
        """Expired seat cannot perform any action."""
        registry.register_seat(expired_seat)
        assert registry.can_request_action(expired_seat.seat_id, "plan") is False

    def test_seat_scope_is_immutable(self, gpt_seat_active):
        """Seat scope cannot be modified after construction."""
        original_scope = gpt_seat_active.scope
        with pytest.raises(Exception):  # FrozenInstanceError
            gpt_seat_active.scope = (MSOSeatScope.EXECUTE,)
        assert gpt_seat_active.scope == original_scope


# ---------------------------------------------------------------------------
# Registry Lifecycle Tests
# ---------------------------------------------------------------------------


class TestRegistryLifecycle:
    """Tests for registry lifecycle and reset."""

    def test_global_registry_singleton(self):
        """get_mso_seat_registry() returns same instance."""
        reg1 = get_mso_seat_registry()
        reg2 = get_mso_seat_registry()
        assert reg1 is reg2

    def test_reset_global_registry(self, gpt_seat_active):
        """reset_mso_seat_registry() creates fresh registry."""
        registry1 = get_mso_seat_registry()
        registry1.register_seat(gpt_seat_active)
        assert registry1.count_active_seats() == 1

        reset_mso_seat_registry()
        registry2 = get_mso_seat_registry()
        assert registry2.count_active_seats() == 0


# ---------------------------------------------------------------------------
# Scope and Forbidden Actions Tests
# ---------------------------------------------------------------------------


class TestScopeEnforcement:
    """Tests for scope and forbidden action enforcement."""

    def test_all_scope_values_present(self):
        """All expected scope enum values exist."""
        assert MSOSeatScope.PLAN.value == "plan"
        assert MSOSeatScope.AUDIT.value == "audit"
        assert MSOSeatScope.CLASSIFY.value == "classify"
        assert MSOSeatScope.RECOMMEND.value == "recommend"
        assert MSOSeatScope.PREPARE_EXECUTION_REQUEST.value == "prepare_execution_request"

    def test_clause_enforcement_only_scope(self, now):
        """Seat can only perform actions in scope."""
        seat = DelegatedMSOSeat(
            seat_id="scope-test",
            seat_type=MSOSeatType.GPT_CONVERSATIONAL,
            holder="gpt-4",
            issued_by="kernel",
            issued_at=now,
            scope=(MSOSeatScope.PLAN,),  # Only plan
            forbidden_actions=(),
            audit_ref="audit-scope-test",
        )
        assert seat.can_perform_action("plan") is True
        assert seat.can_perform_action("audit") is False
        assert seat.can_perform_action("classify") is False

    def test_forbidden_overrides_scope(self, now):
        """Forbidden actions override scope."""
        seat = DelegatedMSOSeat(
            seat_id="forbidden-test",
            seat_type=MSOSeatType.GPT_CONVERSATIONAL,
            holder="gpt-4",
            issued_by="kernel",
            issued_at=now,
            scope=(MSOSeatScope.PLAN, MSOSeatScope.AUDIT),
            forbidden_actions=("audit",),  # Explicitly forbid audit
            audit_ref="audit-forbidden-test",
        )
        assert seat.can_perform_action("plan") is True
        assert seat.can_perform_action("audit") is False

    def test_requires_flags_honored(self, now):
        """requires_policy, requires_police flags are preserved."""
        seat = DelegatedMSOSeat(
            seat_id="flags-test",
            seat_type=MSOSeatType.CLAUDE_ANALYTICAL,
            holder="claude-opus",
            issued_by="kernel",
            issued_at=now,
            scope=(MSOSeatScope.PREPARE_EXECUTION_REQUEST,),
            requires_policy=True,
            requires_police=True,
            requires_human_approval=True,
            audit_ref="audit-flags-test",
        )
        assert seat.requires_policy is True
        assert seat.requires_police is True
        assert seat.requires_human_approval is True
