from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from assistant_os.agents.registry import get_agent
from assistant_os.mso.delegated_seat import (
    DelegatedMSOSeat,
    MSOSeatScope,
    MSOSeatStatus,
    MSOSeatType,
)
from assistant_os.mso.delegated_seat_registry import (
    get_mso_seat_registry,
    reset_mso_seat_registry,
)
from assistant_os.police.authorized_plan_registry import register_authorized_plan_ref
from assistant_os.police.enforcement import (
    _reset_delegated_seat_validator_for_testing,
    check,
    configure_delegated_seat_validator,
)
from assistant_os.police.gate_models import PoliceGateRequest, PoliceOutcome, PoliceReason
from assistant_os.police.token_registry import _STATUS_SPENT, _lookup, register_token


@pytest.fixture(autouse=True)
def _seat_registry_isolation():
    reset_mso_seat_registry()
    _reset_delegated_seat_validator_for_testing()
    yield
    _reset_delegated_seat_validator_for_testing()
    reset_mso_seat_registry()


@pytest.fixture
def now():
    return datetime.now(timezone.utc)


def _seat(
    *,
    seat_id: str = "seat-active",
    issued_at: datetime,
    expires_at: datetime | None = None,
    status: MSOSeatStatus = MSOSeatStatus.ACTIVE,
    revoked_at: datetime | None = None,
) -> DelegatedMSOSeat:
    return DelegatedMSOSeat(
        seat_id=seat_id,
        seat_type=MSOSeatType.CLAUDE_ANALYTICAL,
        holder="claude-sonnet",
        issued_by="kernel",
        issued_at=issued_at,
        expires_at=expires_at,
        revoked_at=revoked_at,
        scope=(
            MSOSeatScope.PLAN,
            MSOSeatScope.AUDIT,
            MSOSeatScope.CLASSIFY,
            MSOSeatScope.RECOMMEND,
            MSOSeatScope.PREPARE_EXECUTION_REQUEST,
        ),
        forbidden_actions=("direct_execution", "invoke_machine_operator"),
        requires_policy=True,
        requires_police=True,
        status=status,
        audit_ref=f"audit-{seat_id}",
    )


def _install_mso_registry_validator():
    registry = get_mso_seat_registry()

    def validate(seat_ref: str, action: str | None) -> tuple[bool, str]:
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

    configure_delegated_seat_validator(validate)


def _register_authority_chain(
    *,
    token_ref: str = "seat-token",
    binding_ref: str = "seat-binding",
    plan_ref: str = "seat-plan",
    execution_id: str = "seat-exec",
    capability_scope: tuple[str, ...] = ("code.execute",),
    delegated_seat_ref: str | None = None,
) -> None:
    register_token(token_ref, binding_ref=binding_ref)
    register_authorized_plan_ref(
        plan_ref,
        execution_id=execution_id,
        token_ref=token_ref,
        binding_ref=binding_ref,
        capability_scope=capability_scope,
        delegated_seat_ref=delegated_seat_ref,
    )


def _request(**overrides) -> PoliceGateRequest:
    values = {
        "execution_id": "seat-exec",
        "operation_key": "op.code.execute",
        "token_ref": "seat-token",
        "binding_ref": "seat-binding",
        "authorized_plan_ref": "seat-plan",
        "capability_name": "code.execute",
        "governance_ref": "governance-ref",
        "policy_decision_ref": "policy-ref",
        "trace_id": "trace-ref",
    }
    values.update(overrides)
    return PoliceGateRequest(**values)


def test_active_delegated_seat_can_be_referenced_in_police_gate_request(now):
    registry = get_mso_seat_registry()
    registry.register_seat(_seat(issued_at=now, expires_at=now + timedelta(hours=1)))
    _install_mso_registry_validator()
    _register_authority_chain(delegated_seat_ref="seat-active")

    decision = check(
        _request(
            delegated_seat_ref="seat-active",
            delegated_seat_action=MSOSeatScope.PREPARE_EXECUTION_REQUEST.value,
        )
    )

    assert decision.outcome is PoliceOutcome.PERMITTED
    assert decision.reason is PoliceReason.ALLOWED


def test_missing_delegated_seat_ref_does_not_break_legacy_requests():
    _register_authority_chain()

    decision = check(_request())

    assert decision.outcome is PoliceOutcome.PERMITTED
    assert decision.reason is PoliceReason.ALLOWED


def test_missing_delegated_seat_ref_denies_when_context_requires_it():
    _register_authority_chain()

    decision = check(_request(delegated_seat_required=True))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.DELEGATED_SEAT_INVALID


def test_unknown_delegated_seat_ref_denies_when_provided():
    _install_mso_registry_validator()
    _register_authority_chain(delegated_seat_ref="unknown-seat")

    decision = check(
        _request(
            delegated_seat_ref="unknown-seat",
            delegated_seat_action=MSOSeatScope.PLAN.value,
        )
    )

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.DELEGATED_SEAT_INVALID


def test_revoked_delegated_seat_ref_denies(now):
    registry = get_mso_seat_registry()
    registry.register_seat(
        _seat(
            seat_id="seat-revoked",
            issued_at=now - timedelta(hours=1),
            revoked_at=now,
            status=MSOSeatStatus.REVOKED,
        )
    )
    _install_mso_registry_validator()
    _register_authority_chain(delegated_seat_ref="seat-revoked")

    decision = check(
        _request(
            delegated_seat_ref="seat-revoked",
            delegated_seat_action=MSOSeatScope.PLAN.value,
        )
    )

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.DELEGATED_SEAT_INVALID


def test_expired_delegated_seat_ref_denies(now):
    registry = get_mso_seat_registry()
    registry.register_seat(
        _seat(
            seat_id="seat-expired",
            issued_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
    )
    _install_mso_registry_validator()
    _register_authority_chain(delegated_seat_ref="seat-expired")

    decision = check(
        _request(
            delegated_seat_ref="seat-expired",
            delegated_seat_action=MSOSeatScope.PLAN.value,
        )
    )

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.DELEGATED_SEAT_INVALID


def test_delegated_seat_cannot_authorize_direct_execution_by_itself(now):
    registry = get_mso_seat_registry()
    registry.register_seat(_seat(issued_at=now, expires_at=now + timedelta(hours=1)))
    _install_mso_registry_validator()

    decision = check(
        _request(
            token_ref=None,
            binding_ref=None,
            authorized_plan_ref=None,
            governance_ref=None,
            policy_decision_ref=None,
            delegated_seat_ref="seat-active",
            delegated_seat_action=MSOSeatScope.PREPARE_EXECUTION_REQUEST.value,
        )
    )

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.TOKEN_MISSING


def test_delegated_seat_cannot_request_forbidden_execution_action(now):
    registry = get_mso_seat_registry()
    registry.register_seat(_seat(issued_at=now, expires_at=now + timedelta(hours=1)))
    _install_mso_registry_validator()
    _register_authority_chain(delegated_seat_ref="seat-active")

    decision = check(
        _request(
            delegated_seat_ref="seat-active",
            delegated_seat_action="direct_execution",
        )
    )

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.DELEGATED_SEAT_INVALID


def test_delegated_seat_cannot_invoke_host_or_machine_operator(now):
    registry = get_mso_seat_registry()
    registry.register_seat(_seat(issued_at=now, expires_at=now + timedelta(hours=1)))
    _install_mso_registry_validator()
    _register_authority_chain(delegated_seat_ref="seat-active")

    host_decision = check(
        _request(
            delegated_seat_ref="seat-active",
            delegated_seat_action="host.execute",
        )
    )
    machine_decision = check(
        _request(
            delegated_seat_ref="seat-active",
            delegated_seat_action="invoke_machine_operator",
        )
    )

    assert host_decision.reason is PoliceReason.DELEGATED_SEAT_INVALID
    assert machine_decision.reason is PoliceReason.DELEGATED_SEAT_INVALID


def test_delegated_seat_cannot_bypass_token_binding_plan_or_capability_checks(now):
    registry = get_mso_seat_registry()
    registry.register_seat(_seat(issued_at=now, expires_at=now + timedelta(hours=1)))
    _install_mso_registry_validator()
    _register_authority_chain(delegated_seat_ref="seat-active")

    token_decision = check(
        _request(
            token_ref="missing-token",
            delegated_seat_ref="seat-active",
            delegated_seat_action=MSOSeatScope.PLAN.value,
        )
    )
    binding_decision = check(
        _request(
            binding_ref="wrong-binding",
            delegated_seat_ref="seat-active",
            delegated_seat_action=MSOSeatScope.PLAN.value,
        )
    )
    plan_decision = check(
        _request(
            authorized_plan_ref="missing-plan",
            delegated_seat_ref="seat-active",
            delegated_seat_action=MSOSeatScope.PLAN.value,
        )
    )
    capability_decision = check(
        _request(
            capability_name="admin.execute",
            delegated_seat_ref="seat-active",
            delegated_seat_action=MSOSeatScope.PLAN.value,
        )
    )

    assert token_decision.reason is PoliceReason.TOKEN_INVALID
    assert binding_decision.reason is PoliceReason.BINDING_MISMATCH
    assert plan_decision.reason is PoliceReason.PLAN_BINDING_FAILURE
    assert capability_decision.reason is PoliceReason.CAPABILITY_OUT_OF_SCOPE


def test_valid_seat_and_valid_authority_chain_permits(now):
    registry = get_mso_seat_registry()
    registry.register_seat(_seat(issued_at=now, expires_at=now + timedelta(hours=1)))
    _install_mso_registry_validator()
    _register_authority_chain(delegated_seat_ref="seat-active")

    decision = check(
        _request(
            delegated_seat_ref="seat-active",
            delegated_seat_action=MSOSeatScope.PLAN.value,
        )
    )

    assert decision.outcome is PoliceOutcome.PERMITTED
    assert decision.reason is PoliceReason.ALLOWED
    assert _lookup("seat-token")["status"] == _STATUS_SPENT


def test_seat_denied_case_does_not_spend_token(now):
    registry = get_mso_seat_registry()
    registry.register_seat(_seat(issued_at=now, expires_at=now + timedelta(hours=1)))
    _install_mso_registry_validator()
    _register_authority_chain(delegated_seat_ref="seat-active")

    first_decision = check(
        _request(
            delegated_seat_ref="seat-active",
            delegated_seat_action="direct_execution",
        )
    )
    second_decision = check(
        _request(
            delegated_seat_ref="seat-active",
            delegated_seat_action=MSOSeatScope.PLAN.value,
        )
    )

    assert first_decision.reason is PoliceReason.DELEGATED_SEAT_INVALID
    assert second_decision.reason is PoliceReason.ALLOWED


def test_direct_agent_registry_calls_remain_police_denied():
    host_request = SimpleNamespace(execution_id="host-direct", action="notepad")
    host_result = get_agent("host_launcher")["entrypoint"](host_request)
    machine_result = get_agent("machine_operator")["entrypoint"](
        {
            "execution_id": "machine-direct",
            "capability_name": "browser.snapshot",
        }
    )

    assert host_result.ok is False
    assert "token_missing" in host_result.error
    assert machine_result["ok"] is False
    assert machine_result["error"]["type"] == "police_gate_denied"
