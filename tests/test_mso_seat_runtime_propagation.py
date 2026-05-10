from datetime import datetime, timedelta, timezone

import pytest

from assistant_os.core.orchestrator import _attach_authority_context
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
from assistant_os.mso.police_delegated_seat_validator import (
    install_mso_delegated_seat_validator,
)
from assistant_os.pipelines.code_pipeline import _extract_authority_context
from assistant_os.police.authorized_plan_registry import (
    _reset_for_testing as _reset_authorized_plans,
    register_authorized_plan_ref,
)
from assistant_os.police.enforcement import (
    _reset_delegated_seat_validator_for_testing,
    check,
)
from assistant_os.police.gate_models import PoliceGateRequest, PoliceOutcome, PoliceReason
from assistant_os.police.token_registry import (
    _STATUS_ACTIVE,
    _STATUS_SPENT,
    _lookup,
    _reset_for_testing as _reset_tokens,
    register_token,
)


@pytest.fixture(autouse=True)
def _runtime_isolation():
    reset_mso_seat_registry()
    _reset_delegated_seat_validator_for_testing()
    _reset_tokens()
    _reset_authorized_plans()
    yield
    _reset_authorized_plans()
    _reset_tokens()
    _reset_delegated_seat_validator_for_testing()
    reset_mso_seat_registry()


@pytest.fixture
def now() -> datetime:
    return datetime.now(timezone.utc)


def _seat(
    *,
    seat_id: str = "seat-runtime-active",
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
        scope=(MSOSeatScope.PLAN, MSOSeatScope.PREPARE_EXECUTION_REQUEST),
        forbidden_actions=("direct_execution", "invoke_machine_operator"),
        requires_policy=True,
        requires_police=True,
        status=status,
        audit_ref=f"audit-{seat_id}",
    )


def _register_chain(
    *,
    token_ref: str = "token-runtime",
    binding_ref: str = "binding-runtime",
    plan_ref: str = "plan-runtime",
    execution_id: str = "exec-runtime",
    capability_scope: tuple[str, ...] = ("code.execute",),
    delegated_seat_ref: str | None = "seat-runtime-active",
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
        "execution_id": "exec-runtime",
        "operation_key": "op.code.execute",
        "token_ref": "token-runtime",
        "binding_ref": "binding-runtime",
        "authorized_plan_ref": "plan-runtime",
        "capability_name": "code.execute",
        "governance_ref": "governance-runtime",
        "policy_decision_ref": "policy-runtime",
        "trace_id": "trace-runtime",
        "delegated_seat_ref": "seat-runtime-active",
        "delegated_seat_action": MSOSeatScope.PREPARE_EXECUTION_REQUEST.value,
    }
    values.update(overrides)
    return PoliceGateRequest(**values)


def _register_active_seat(now: datetime, seat_id: str = "seat-runtime-active") -> None:
    get_mso_seat_registry().register_seat(
        _seat(seat_id=seat_id, issued_at=now, expires_at=now + timedelta(hours=1))
    )


def test_registered_active_seat_validates_successfully_through_police_gate(now):
    _register_active_seat(now)
    install_mso_delegated_seat_validator()
    _register_chain()

    decision = check(_request())

    assert decision.outcome is PoliceOutcome.PERMITTED
    assert decision.reason is PoliceReason.ALLOWED
    assert _lookup("token-runtime")["status"] == _STATUS_SPENT


def test_unknown_delegated_seat_ref_denies(now):
    _register_active_seat(now)
    install_mso_delegated_seat_validator()
    _register_chain(delegated_seat_ref="seat-missing")

    decision = check(_request(delegated_seat_ref="seat-missing"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.DELEGATED_SEAT_INVALID


def test_revoked_delegated_seat_ref_denies(now):
    get_mso_seat_registry().register_seat(
        _seat(
            seat_id="seat-revoked",
            issued_at=now - timedelta(hours=1),
            revoked_at=now,
            status=MSOSeatStatus.REVOKED,
        )
    )
    install_mso_delegated_seat_validator()
    _register_chain(delegated_seat_ref="seat-revoked")

    decision = check(_request(delegated_seat_ref="seat-revoked"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.DELEGATED_SEAT_INVALID


def test_expired_delegated_seat_ref_denies(now):
    get_mso_seat_registry().register_seat(
        _seat(
            seat_id="seat-expired",
            issued_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
    )
    install_mso_delegated_seat_validator()
    _register_chain(delegated_seat_ref="seat-expired")

    decision = check(_request(delegated_seat_ref="seat-expired"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.DELEGATED_SEAT_INVALID


def test_forbidden_action_denies(now):
    _register_active_seat(now)
    install_mso_delegated_seat_validator()
    _register_chain()

    decision = check(_request(delegated_seat_action="direct_execution"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.DELEGATED_SEAT_INVALID


def test_seat_valid_but_token_invalid_still_denies(now):
    _register_active_seat(now)
    install_mso_delegated_seat_validator()
    _register_chain()

    decision = check(_request(token_ref="token-missing"))

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.TOKEN_INVALID


def test_seat_valid_but_authorized_plan_mismatch_still_denies(now):
    _register_active_seat(now)
    install_mso_delegated_seat_validator()
    _register_chain(delegated_seat_ref="other-seat")

    decision = check(_request())

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.PLAN_BINDING_FAILURE


def test_seat_valid_but_capability_out_of_scope_still_denies(now):
    _register_active_seat(now)
    install_mso_delegated_seat_validator()
    _register_chain(capability_scope=("code.read",))

    decision = check(_request())

    assert decision.outcome is PoliceOutcome.DENIED
    assert decision.reason is PoliceReason.CAPABILITY_OUT_OF_SCOPE


def test_seat_denied_does_not_spend_token(now):
    _register_active_seat(now)
    install_mso_delegated_seat_validator()
    _register_chain()

    decision = check(_request(delegated_seat_action="direct_execution"))

    assert decision.reason is PoliceReason.DELEGATED_SEAT_INVALID
    assert _lookup("token-runtime")["status"] == _STATUS_ACTIVE


def test_registry_backed_validator_is_installed_for_police_gate(now):
    _register_active_seat(now)
    install_mso_delegated_seat_validator()
    _register_chain()

    decision = check(_request())

    assert decision.reason is PoliceReason.ALLOWED


def test_authority_context_propagates_delegated_seat_ref_from_request_metadata():
    plan = {"plan_id": "plan-runtime", "domain_payload": {}}
    request = {
        "metadata": {
            "delegated_seat_ref": "seat-runtime-active",
            "delegated_seat_action": MSOSeatScope.PREPARE_EXECUTION_REQUEST.value,
        }
    }

    plan_with_context = _attach_authority_context(
        request,
        plan,
        policy_execution_mode="confirm",
        governance_trace={"governance_ref": "governance-runtime"},
    )

    authority_context = plan_with_context["_authority_context"]
    assert authority_context["delegated_seat_ref"] == "seat-runtime-active"
    assert (
        authority_context["delegated_seat_action"]
        == MSOSeatScope.PREPARE_EXECUTION_REQUEST.value
    )


def test_code_pipeline_preserves_delegated_seat_ref_in_authority_context():
    extracted = _extract_authority_context(
        {
            "_authority_context": {
                "approval_id": "approval-runtime",
                "policy_decision_ref": "policy-runtime",
                "governance_ref": "governance-runtime",
                "execution_mode": "confirm",
                "delegated_seat_ref": "seat-runtime-active",
                "delegated_seat_action": MSOSeatScope.PREPARE_EXECUTION_REQUEST.value,
            },
            "domain_payload": {},
        }
    )

    assert extracted is not None
    assert extracted["delegated_seat_ref"] == "seat-runtime-active"
    assert (
        extracted["delegated_seat_action"]
        == MSOSeatScope.PREPARE_EXECUTION_REQUEST.value
    )
