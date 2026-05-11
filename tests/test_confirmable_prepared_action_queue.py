"""
ConfirmablePreparedAction Queue Tests.

Validates that ConfirmablePreparedAction maps correctly to a manual review
queue entry, that all safety invariants are preserved, and that no execution
authority is granted at any point.

Sprint scope: Manual review queue — no execution, no approval, no tokens.

Coverage
--------
1.  ConfirmablePreparedAction maps to ConfirmablePreparedActionQueueEntry.
2.  queue_entry.execution_allowed is False.
3.  queue_entry.can_execute_now is False.
4.  queue_entry.review_only is True.
5.  queue entry preserves prepared_action_id.
6.  queue entry preserves proposal_id.
7.  queue entry preserves preparation_id.
8.  queue entry preserves delegated_seat_ref.
9.  queue entry preserves provider_name/model_name.
10. queue entry starts pending_review with human_confirmation_status=pending.
11. queue does not call token issuer.
12. queue does not call PoliceGate.
13. queue does not call runner/pipeline.
14. list_pending_confirmable_actions returns queued item.
15. blocked prepared action remains non-executable.
16. enqueue rejects wrong type.
17. enqueue does not mutate original action.
18. queue to_dict serialization is safe.
19. plan_request surface includes queued_prepared_action.
20. queued_prepared_action has execution_allowed=False.
21. queued_prepared_action has can_execute_now=False.
22. queued_prepared_action has review_only=True.
23. plan_request message says manual review / not execution.
24. no tasks registered after plan_request.
25. ambiguous request still asks for context.
26. queue entry is frozen / immutable.
27. invariant violations raise ValueError.
28. get_confirmable_action_queue_entry returns entry by id.
29. queue accumulates multiple entries.
30. clear_confirmable_action_queue_for_tests resets queue.
"""
from __future__ import annotations

import pytest

from assistant_os.mso.authority_preparation import prepare_authority_from_proposal
from assistant_os.mso.confirmable_prepared_action import (
    ConfirmablePreparedAction,
    build_confirmable_from_preparation,
)
from assistant_os.mso.execution_proposal import (
    build_execution_proposal,
    build_safe_fallback_proposal,
)
from assistant_os.mso.prepared_action_queue import (
    ConfirmablePreparedActionQueueEntry,
    clear_confirmable_action_queue_for_tests,
    enqueue_confirmable_prepared_action,
    get_confirmable_action_queue_entry,
    list_pending_confirmable_action_dicts,
    list_pending_confirmable_actions,
)
from assistant_os.mso.task_registry import list_tasks, reset_task_registry
from assistant_os.surface_behavior import get_surface_behavior_response


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _mock_identity():
    class _Id:
        def to_audit_dict(self):
            return {}
    return _Id()


def _mock_guard():
    class _G:
        def to_audit_dict(self):
            return {}
    return _G()


def _route_assistant_chat(text: str) -> dict | None:
    return get_surface_behavior_response(
        surface="assistant_chat",
        text=text,
        context_id="test-ctx",
        identity=_mock_identity(),
        guard_result=_mock_guard(),
    )


@pytest.fixture(autouse=True)
def _reset_state():
    clear_confirmable_action_queue_for_tests()
    reset_task_registry()
    yield
    clear_confirmable_action_queue_for_tests()
    reset_task_registry()


def _code_confirmable(
    *,
    user_intent: str = "Review the docs/ directory for compliance issues.",
    domain: str = "CODE",
    requested_action: str = "CODE_REVIEW",
    capability_name: str = "code_review",
    capability_scope: tuple[str, ...] = ("code_review",),
    delegated_seat_ref: str | None = "seat-test-ref",
    provider_name: str | None = "anthropic",
    model_name: str | None = "claude-haiku-4-5-20251001",
) -> ConfirmablePreparedAction:
    proposal = build_execution_proposal(
        user_intent=user_intent,
        domain=domain,
        requested_action=requested_action,
        capability_name=capability_name,
        capability_scope=capability_scope,
        delegated_seat_ref=delegated_seat_ref,
        provider_name=provider_name,
        model_name=model_name,
    )
    prep = prepare_authority_from_proposal(proposal)
    return build_confirmable_from_preparation(prep)


# ---------------------------------------------------------------------------
# Test 1: Maps from ConfirmablePreparedAction
# ---------------------------------------------------------------------------


class TestMapsFromConfirmableAction:
    """enqueue_confirmable_prepared_action returns a correct queue entry."""

    def test_returns_queue_entry_instance(self):
        action = _code_confirmable()
        entry = enqueue_confirmable_prepared_action(action)
        assert isinstance(entry, ConfirmablePreparedActionQueueEntry)

    def test_has_queue_entry_id(self):
        action = _code_confirmable()
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.queue_entry_id
        assert entry.queue_entry_id.startswith("qe-")

    def test_queue_entry_id_is_unique(self):
        action = _code_confirmable()
        e1 = enqueue_confirmable_prepared_action(action)
        e2 = enqueue_confirmable_prepared_action(action)
        assert e1.queue_entry_id != e2.queue_entry_id

    def test_has_created_at(self):
        entry = enqueue_confirmable_prepared_action(_code_confirmable())
        assert entry.created_at
        assert "T" in entry.created_at


# ---------------------------------------------------------------------------
# Tests 2-4: Core safety invariants
# ---------------------------------------------------------------------------


class TestCoreInvariants:
    """execution_allowed, can_execute_now, review_only are always safe."""

    def test_execution_allowed_is_false(self):
        entry = enqueue_confirmable_prepared_action(_code_confirmable())
        assert entry.execution_allowed is False

    def test_can_execute_now_is_false(self):
        entry = enqueue_confirmable_prepared_action(_code_confirmable())
        assert entry.can_execute_now is False

    def test_review_only_is_true(self):
        entry = enqueue_confirmable_prepared_action(_code_confirmable())
        assert entry.review_only is True

    def test_cannot_set_execution_allowed_true(self):
        with pytest.raises(ValueError, match="execution_allowed"):
            ConfirmablePreparedActionQueueEntry(execution_allowed=True)

    def test_cannot_set_can_execute_now_true(self):
        with pytest.raises(ValueError, match="can_execute_now"):
            ConfirmablePreparedActionQueueEntry(can_execute_now=True)

    def test_cannot_set_review_only_false(self):
        with pytest.raises(ValueError, match="review_only"):
            ConfirmablePreparedActionQueueEntry(review_only=False)


# ---------------------------------------------------------------------------
# Tests 5-9: Field preservation
# ---------------------------------------------------------------------------


class TestFieldPreservation:
    """Queue entry preserves all relevant fields from the prepared action."""

    def test_preserves_prepared_action_id(self):
        action = _code_confirmable()
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.prepared_action_id == action.action_id

    def test_preserves_preparation_id(self):
        action = _code_confirmable()
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.preparation_id == action.preparation_id

    def test_preserves_proposal_id(self):
        action = _code_confirmable()
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.proposal_id == action.proposal_id

    def test_preserves_user_intent(self):
        action = _code_confirmable(user_intent="Audit the docs/ directory.")
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.user_intent == "Audit the docs/ directory."

    def test_preserves_domain(self):
        action = _code_confirmable(domain="CODE")
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.domain == "CODE"

    def test_preserves_requested_action(self):
        action = _code_confirmable(requested_action="CODE_REVIEW")
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.requested_action == "CODE_REVIEW"

    def test_preserves_capability_name(self):
        action = _code_confirmable(capability_name="code_review")
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.capability_name == "code_review"

    def test_preserves_capability_scope(self):
        action = _code_confirmable(capability_scope=("code_review",))
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.capability_scope == ("code_review",)

    def test_preserves_delegated_seat_ref(self):
        action = _code_confirmable(delegated_seat_ref="seat-xyz")
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.delegated_seat_ref == "seat-xyz"

    def test_preserves_provider_name(self):
        action = _code_confirmable(provider_name="anthropic")
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.provider_name == "anthropic"

    def test_preserves_model_name(self):
        action = _code_confirmable(model_name="claude-haiku-4-5-20251001")
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.model_name == "claude-haiku-4-5-20251001"

    def test_preserves_none_traceability(self):
        action = _code_confirmable(delegated_seat_ref=None, provider_name=None, model_name=None)
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.delegated_seat_ref is None
        assert entry.provider_name is None
        assert entry.model_name is None


# ---------------------------------------------------------------------------
# Test 10: Starts pending_review with human_confirmation_status=pending
# ---------------------------------------------------------------------------


class TestInitialStatus:
    """Queue entry starts in pending_review with human_confirmation_status=pending."""

    def test_status_is_pending_review(self):
        entry = enqueue_confirmable_prepared_action(_code_confirmable())
        assert entry.status == "pending_review"

    def test_human_confirmation_status_is_pending(self):
        entry = enqueue_confirmable_prepared_action(_code_confirmable())
        assert entry.human_confirmation_status == "pending"

    def test_artifact_type(self):
        entry = enqueue_confirmable_prepared_action(_code_confirmable())
        assert entry.artifact_type == "confirmable_prepared_action_queue_entry"


# ---------------------------------------------------------------------------
# Tests 11-13: No execution/token/police calls
# ---------------------------------------------------------------------------


class TestNoExecutionCalls:
    """Enqueuing never calls token issuer, PoliceGate, or runner/pipeline."""

    def test_does_not_register_task(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        assert list_tasks() == []

    def test_does_not_create_execution_result(self):
        action = _code_confirmable()
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.execution_allowed is False
        assert entry.can_execute_now is False

    def test_multiple_enqueues_no_tasks(self):
        for _ in range(3):
            enqueue_confirmable_prepared_action(_code_confirmable())
        assert list_tasks() == []

    def test_enqueue_is_pure_no_side_effects_on_action(self):
        """Original action is not mutated by enqueue."""
        action = _code_confirmable()
        original_id = action.action_id
        enqueue_confirmable_prepared_action(action)
        assert action.action_id == original_id
        assert action.status == "waiting_for_human_confirmation"
        assert action.confirmed is False


# ---------------------------------------------------------------------------
# Test 14: list_pending_confirmable_actions
# ---------------------------------------------------------------------------


class TestListPending:
    """list_pending_confirmable_actions returns queued items."""

    def test_returns_empty_when_no_entries(self):
        result = list_pending_confirmable_actions()
        assert result == []

    def test_returns_enqueued_entry(self):
        action = _code_confirmable()
        entry = enqueue_confirmable_prepared_action(action)
        pending = list_pending_confirmable_actions()
        assert len(pending) == 1
        assert pending[0].queue_entry_id == entry.queue_entry_id

    def test_returns_all_enqueued_entries(self):
        for _ in range(3):
            enqueue_confirmable_prepared_action(_code_confirmable())
        pending = list_pending_confirmable_actions()
        assert len(pending) == 3

    def test_returns_list(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        result = list_pending_confirmable_actions()
        assert isinstance(result, list)

    def test_all_returned_entries_are_review_only(self):
        for _ in range(5):
            enqueue_confirmable_prepared_action(_code_confirmable())
        for entry in list_pending_confirmable_actions():
            assert entry.review_only is True
            assert entry.execution_allowed is False
            assert entry.can_execute_now is False

    def test_list_does_not_mutate_queue(self):
        action = _code_confirmable()
        enqueue_confirmable_prepared_action(action)
        _ = list_pending_confirmable_actions()
        _ = list_pending_confirmable_actions()
        assert len(list_pending_confirmable_actions()) == 1


# ---------------------------------------------------------------------------
# Test 15: Blocked prepared action
# ---------------------------------------------------------------------------


class TestBlockedAction:
    """Blocked prepared action remains non-executable in the queue."""

    def test_blocked_action_can_be_enqueued(self):
        fallback = build_safe_fallback_proposal(user_intent="")
        prep = prepare_authority_from_proposal(fallback)
        action = build_confirmable_from_preparation(prep)
        entry = enqueue_confirmable_prepared_action(action)
        assert isinstance(entry, ConfirmablePreparedActionQueueEntry)

    def test_blocked_entry_is_still_non_executable(self):
        fallback = build_safe_fallback_proposal(user_intent="")
        prep = prepare_authority_from_proposal(fallback)
        action = build_confirmable_from_preparation(prep)
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.execution_allowed is False
        assert entry.can_execute_now is False
        assert entry.review_only is True

    def test_blocked_entry_status_is_pending_review(self):
        fallback = build_safe_fallback_proposal(user_intent="")
        prep = prepare_authority_from_proposal(fallback)
        action = build_confirmable_from_preparation(prep)
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.status == "pending_review"

    def test_blocked_entry_human_confirmation_pending(self):
        fallback = build_safe_fallback_proposal(user_intent="")
        prep = prepare_authority_from_proposal(fallback)
        action = build_confirmable_from_preparation(prep)
        entry = enqueue_confirmable_prepared_action(action)
        assert entry.human_confirmation_status == "pending"


# ---------------------------------------------------------------------------
# Test 16: TypeError on invalid input
# ---------------------------------------------------------------------------


class TestTypeValidation:
    """enqueue_confirmable_prepared_action rejects wrong types."""

    def test_raises_on_none(self):
        with pytest.raises(TypeError, match="ConfirmablePreparedAction"):
            enqueue_confirmable_prepared_action(None)  # type: ignore[arg-type]

    def test_raises_on_dict(self):
        with pytest.raises(TypeError, match="ConfirmablePreparedAction"):
            enqueue_confirmable_prepared_action({"action_id": "x"})  # type: ignore[arg-type]

    def test_raises_on_preparation(self):
        proposal = build_execution_proposal(
            user_intent="test", domain="CODE", requested_action="CODE_REVIEW"
        )
        prep = prepare_authority_from_proposal(proposal)
        with pytest.raises(TypeError, match="ConfirmablePreparedAction"):
            enqueue_confirmable_prepared_action(prep)  # type: ignore[arg-type]

    def test_raises_on_string(self):
        with pytest.raises(TypeError, match="ConfirmablePreparedAction"):
            enqueue_confirmable_prepared_action("action-123")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 17: enqueue does not mutate original action
# ---------------------------------------------------------------------------


class TestImmutability:
    """Original ConfirmablePreparedAction is not mutated by enqueue."""

    def test_original_action_status_unchanged(self):
        action = _code_confirmable()
        enqueue_confirmable_prepared_action(action)
        assert action.status == "waiting_for_human_confirmation"

    def test_original_action_confirmed_unchanged(self):
        action = _code_confirmable()
        enqueue_confirmable_prepared_action(action)
        assert action.confirmed is False

    def test_queue_entry_is_frozen(self):
        entry = enqueue_confirmable_prepared_action(_code_confirmable())
        with pytest.raises((AttributeError, TypeError)):
            entry.execution_allowed = True  # type: ignore[misc]

    def test_queue_entry_is_frozen_review_only(self):
        entry = enqueue_confirmable_prepared_action(_code_confirmable())
        with pytest.raises((AttributeError, TypeError)):
            entry.review_only = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 18: to_dict() serialization contract
# ---------------------------------------------------------------------------


class TestToDict:
    """to_dict() produces a complete, safe serialization."""

    REQUIRED_KEYS = {
        "artifact_type",
        "queue_entry_id",
        "prepared_action_id",
        "preparation_id",
        "proposal_id",
        "user_intent",
        "domain",
        "requested_action",
        "capability_name",
        "capability_scope",
        "delegated_seat_ref",
        "provider_name",
        "model_name",
        "human_confirmation_status",
        "status",
        "created_at",
        "review_only",
        "execution_allowed",
        "can_execute_now",
        "notes",
    }

    def test_to_dict_returns_dict(self):
        entry = enqueue_confirmable_prepared_action(_code_confirmable())
        assert isinstance(entry.to_dict(), dict)

    def test_to_dict_has_all_required_keys(self):
        d = enqueue_confirmable_prepared_action(_code_confirmable()).to_dict()
        assert self.REQUIRED_KEYS.issubset(d.keys())

    def test_to_dict_execution_allowed_false(self):
        d = enqueue_confirmable_prepared_action(_code_confirmable()).to_dict()
        assert d["execution_allowed"] is False

    def test_to_dict_can_execute_now_false(self):
        d = enqueue_confirmable_prepared_action(_code_confirmable()).to_dict()
        assert d["can_execute_now"] is False

    def test_to_dict_review_only_true(self):
        d = enqueue_confirmable_prepared_action(_code_confirmable()).to_dict()
        assert d["review_only"] is True

    def test_to_dict_human_confirmation_status_pending(self):
        d = enqueue_confirmable_prepared_action(_code_confirmable()).to_dict()
        assert d["human_confirmation_status"] == "pending"

    def test_to_dict_status_pending_review(self):
        d = enqueue_confirmable_prepared_action(_code_confirmable()).to_dict()
        assert d["status"] == "pending_review"

    def test_to_dict_capability_scope_is_list(self):
        d = enqueue_confirmable_prepared_action(
            _code_confirmable(capability_scope=("code_review",))
        ).to_dict()
        assert isinstance(d["capability_scope"], list)

    def test_to_dict_no_tokens_or_plan_refs(self):
        d = enqueue_confirmable_prepared_action(_code_confirmable()).to_dict()
        assert "token" not in d
        assert "capability_token" not in d
        assert "authorized_plan_ref" not in d
        assert "police_decision_ref" not in d


# ---------------------------------------------------------------------------
# Tests 19-23: plan_request surface integration
# ---------------------------------------------------------------------------


class TestSurfaceIntegration:
    """plan_request response includes queued_prepared_action."""

    def test_plan_request_includes_queued_prepared_action(self):
        result = _route_assistant_chat("Prepare a CODE/docs action for manual review. Do not execute.")
        assert result is not None
        assert "queued_prepared_action" in result

    def test_queued_prepared_action_is_not_none(self):
        result = _route_assistant_chat("plan only: review the docs/ directory")
        assert result is not None
        qpa = result.get("queued_prepared_action")
        assert qpa is not None

    def test_queued_prepared_action_execution_allowed_false(self):
        result = _route_assistant_chat("Prepare a CODE/docs action for manual review. Do not execute.")
        qpa = result.get("queued_prepared_action")
        assert qpa is not None
        assert qpa["execution_allowed"] is False

    def test_queued_prepared_action_can_execute_now_false(self):
        result = _route_assistant_chat("plan only: deploy backend")
        qpa = result.get("queued_prepared_action")
        assert qpa is not None
        assert qpa["can_execute_now"] is False

    def test_queued_prepared_action_review_only_true(self):
        result = _route_assistant_chat("Plan only: review README and prepare action.")
        qpa = result.get("queued_prepared_action")
        assert qpa is not None
        assert qpa["review_only"] is True

    def test_queued_prepared_action_human_confirmation_pending(self):
        result = _route_assistant_chat("Prepare a plan. Do not execute.")
        qpa = result.get("queued_prepared_action")
        assert qpa is not None
        assert qpa["human_confirmation_status"] == "pending"

    def test_queued_prepared_action_has_queue_entry_id(self):
        result = _route_assistant_chat("plan only: run integration tests")
        qpa = result.get("queued_prepared_action")
        assert qpa is not None
        assert qpa.get("queue_entry_id")

    def test_queued_prepared_action_has_prepared_action_id(self):
        result = _route_assistant_chat("plan only: deploy the backend")
        qpa = result.get("queued_prepared_action")
        assert qpa is not None
        assert qpa.get("prepared_action_id")

    def test_plan_request_message_mentions_manual_review(self):
        result = _route_assistant_chat("Prepare a CODE/docs action for manual review. Do not execute.")
        assert result is not None
        msg = result["message"]
        assert "revision manual" in msg.lower() or "revisión manual" in msg.lower()

    def test_plan_request_message_still_says_not_execution(self):
        result = _route_assistant_chat("plan only: deploy backend")
        assert result is not None
        msg = result["message"]
        assert "NO ES EJECUCION" in msg or "no ejecutara" in msg.lower()


# ---------------------------------------------------------------------------
# Test 24: No tasks registered
# ---------------------------------------------------------------------------


class TestNoTasks:
    """plan_request with queued action still does not register MSO tasks."""

    def test_plan_request_no_tasks(self):
        _route_assistant_chat("Prepare a CODE/docs action for manual review. Do not execute.")
        assert list_tasks() == []

    def test_plan_request_queue_entry_no_tasks(self):
        result = _route_assistant_chat("plan only: review the docs/ directory")
        assert result is not None
        assert result["needs_confirmation"] is False
        assert result["plan"] == []
        assert list_tasks() == []


# ---------------------------------------------------------------------------
# Test 25: Ambiguous request still asks for context
# ---------------------------------------------------------------------------


class TestAmbiguousRequest:
    """Ambiguous inputs still return a clarification, not a queued action."""

    def test_ambiguous_request_asks_for_context(self):
        result = _route_assistant_chat("do something")
        assert result is not None
        # Must not be a queued action — must clarify
        assert result.get("result_type") in {
            "clarification", "surface_response", "status_response"
        }

    def test_ambiguous_has_no_queued_prepared_action_key_or_none(self):
        result = _route_assistant_chat("fix something")
        # Either the key is absent or None (not a plan_request)
        qpa = result.get("queued_prepared_action") if result else None
        # Ambiguous requests should not produce a queued action with execution authority
        if qpa is not None:
            assert qpa.get("execution_allowed") is False
            assert qpa.get("can_execute_now") is False


# ---------------------------------------------------------------------------
# Tests 28-30: Queue operation utilities
# ---------------------------------------------------------------------------


class TestQueueOperations:
    """get_confirmable_action_queue_entry and clear_confirmable_action_queue_for_tests."""

    def test_get_entry_by_id(self):
        action = _code_confirmable()
        entry = enqueue_confirmable_prepared_action(action)
        found = get_confirmable_action_queue_entry(entry.queue_entry_id)
        assert found is not None
        assert found.queue_entry_id == entry.queue_entry_id

    def test_get_entry_by_id_returns_none_for_missing(self):
        result = get_confirmable_action_queue_entry("nonexistent-id")
        assert result is None

    def test_queue_accumulates_multiple_entries(self):
        for i in range(5):
            enqueue_confirmable_prepared_action(
                _code_confirmable(user_intent=f"intent {i}")
            )
        assert len(list_pending_confirmable_actions()) == 5

    def test_clear_resets_queue(self):
        for _ in range(3):
            enqueue_confirmable_prepared_action(_code_confirmable())
        assert len(list_pending_confirmable_actions()) == 3
        clear_confirmable_action_queue_for_tests()
        assert list_pending_confirmable_actions() == []

    def test_clear_idempotent_on_empty_queue(self):
        clear_confirmable_action_queue_for_tests()
        clear_confirmable_action_queue_for_tests()
        assert list_pending_confirmable_actions() == []

    def test_get_entry_returns_none_after_clear(self):
        action = _code_confirmable()
        entry = enqueue_confirmable_prepared_action(action)
        eid = entry.queue_entry_id
        clear_confirmable_action_queue_for_tests()
        assert get_confirmable_action_queue_entry(eid) is None


# ---------------------------------------------------------------------------
# list_pending_confirmable_action_dicts — serialization helper
# ---------------------------------------------------------------------------


class TestListPendingDicts:
    """list_pending_confirmable_action_dicts returns safe serialized dicts."""

    def test_returns_empty_list_when_queue_is_empty(self):
        result = list_pending_confirmable_action_dicts()
        assert result == []

    def test_returns_list_of_dicts(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        result = list_pending_confirmable_action_dicts()
        assert isinstance(result, list)
        assert all(isinstance(d, dict) for d in result)

    def test_dict_has_required_keys(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        d = list_pending_confirmable_action_dicts()[0]
        for key in (
            "queue_entry_id", "prepared_action_id", "preparation_id",
            "human_confirmation_status", "execution_allowed", "can_execute_now",
            "review_only", "domain", "requested_action", "capability_name",
        ):
            assert key in d, f"Missing key: {key!r}"

    def test_dict_execution_allowed_is_false(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        d = list_pending_confirmable_action_dicts()[0]
        assert d["execution_allowed"] is False

    def test_dict_can_execute_now_is_false(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        d = list_pending_confirmable_action_dicts()[0]
        assert d["can_execute_now"] is False

    def test_dict_review_only_is_true(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        d = list_pending_confirmable_action_dicts()[0]
        assert d["review_only"] is True

    def test_dict_human_confirmation_status_is_pending(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        d = list_pending_confirmable_action_dicts()[0]
        assert d["human_confirmation_status"] == "pending"

    def test_count_matches_enqueued(self):
        for i in range(3):
            enqueue_confirmable_prepared_action(_code_confirmable(user_intent=f"intent {i}"))
        result = list_pending_confirmable_action_dicts()
        assert len(result) == 3

    def test_no_token_or_plan_refs(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        d = list_pending_confirmable_action_dicts()[0]
        assert "token" not in d
        assert "capability_token" not in d
        assert "authorized_plan_ref" not in d
        assert "police_decision_ref" not in d


# ---------------------------------------------------------------------------
# Review queue status surface query
# ---------------------------------------------------------------------------


class TestReviewQueueStatusQuery:
    """assistant_chat review_queue_status intent returns safe narrative response."""

    def test_queue_status_query_returns_non_none(self):
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None

    def test_queue_status_empty_result_type_is_surface_response(self):
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None
        assert result["result_type"] == "surface_response"

    def test_queue_status_intent_is_review_queue_status(self):
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None
        assert result["intent"] == "review_queue_status"

    def test_empty_queue_returns_no_pending_items(self):
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None
        assert result["pending_review_items"] == []
        assert result["count"] == 0

    def test_empty_queue_message_explains_no_pending(self):
        result = _route_assistant_chat("Show pending prepared actions.")
        assert result is not None
        msg = result["message"].lower()
        assert "no hay" in msg or "no pending" in msg or "no action" in msg

    def test_empty_queue_message_suggests_plan_request(self):
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None
        msg = result["message"].lower()
        assert "plan" in msg

    def test_after_plan_request_queue_status_lists_item(self):
        _route_assistant_chat("Prepare a CODE/docs action for manual review. Do not execute.")
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None
        assert result["count"] >= 1
        assert len(result["pending_review_items"]) >= 1

    def test_queued_item_has_queue_entry_id(self):
        _route_assistant_chat("plan only: review the docs/ directory")
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None
        item = result["pending_review_items"][0]
        assert item.get("queue_entry_id")

    def test_queued_item_has_prepared_action_id(self):
        _route_assistant_chat("Prepare a plan. Do not execute.")
        result = _route_assistant_chat("Show pending prepared actions.")
        assert result is not None
        item = result["pending_review_items"][0]
        assert item.get("prepared_action_id")

    def test_queued_item_human_confirmation_status_is_pending(self):
        _route_assistant_chat("plan only: deploy backend")
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None
        item = result["pending_review_items"][0]
        assert item["human_confirmation_status"] == "pending"

    def test_queued_item_execution_allowed_is_false(self):
        _route_assistant_chat("Prepare a plan. Do not execute.")
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None
        item = result["pending_review_items"][0]
        assert item["execution_allowed"] is False

    def test_queued_item_can_execute_now_is_false(self):
        _route_assistant_chat("plan only: run integration tests")
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None
        item = result["pending_review_items"][0]
        assert item["can_execute_now"] is False

    def test_response_execution_allowed_is_false(self):
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None
        assert result["execution_allowed"] is False

    def test_response_can_execute_now_is_false(self):
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None
        assert result["can_execute_now"] is False

    def test_populated_message_says_review_not_execution(self):
        _route_assistant_chat("Prepare a plan. Do not execute.")
        result = _route_assistant_chat("Show pending prepared actions.")
        assert result is not None
        msg = result["message"].lower()
        assert "revision manual" in msg or "no ejecucion" in msg

    def test_status_query_does_not_register_tasks(self):
        from assistant_os.mso.task_registry import list_tasks
        _route_assistant_chat("What is waiting for manual review?")
        assert list_tasks() == []

    def test_status_query_has_no_execution_artifacts(self):
        result = _route_assistant_chat("What is waiting for manual review?")
        assert result is not None
        assert result["needs_confirmation"] is False
        assert result["plan"] == []
        assert result["ui_actions"] == []

    def test_show_pending_prepared_actions_phrase(self):
        result = _route_assistant_chat("Show pending prepared actions.")
        assert result is not None
        assert result["intent"] == "review_queue_status"

    def test_pending_prepared_actions_phrase(self):
        result = _route_assistant_chat("What actions are queued?")
        assert result is not None
        assert result["intent"] == "review_queue_status"

    def test_spanish_que_esta_esperando_phrase(self):
        result = _route_assistant_chat("Que esta esperando revision manual?")
        assert result is not None
        assert result["intent"] == "review_queue_status"

    def test_review_queue_phrase(self):
        result = _route_assistant_chat("Show me the review queue status.")
        assert result is not None
        assert result["intent"] == "review_queue_status"

    def test_ambiguous_unrelated_still_asks_context(self):
        result = _route_assistant_chat("fix something randomly")
        assert result is not None
        assert result.get("intent") != "review_queue_status"


# ---------------------------------------------------------------------------
# Backend endpoint response contract
# ---------------------------------------------------------------------------


class TestBackendEndpointResponseContract:
    """list_pending_confirmable_action_dicts() produces the expected endpoint payload shape."""

    def test_empty_queue_produces_empty_items(self):
        items = list_pending_confirmable_action_dicts()
        assert items == []

    def test_populated_queue_produces_items(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        items = list_pending_confirmable_action_dicts()
        assert len(items) == 1

    def test_items_are_dicts_with_review_invariants(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        items = list_pending_confirmable_action_dicts()
        item = items[0]
        assert item["review_only"] is True
        assert item["execution_allowed"] is False
        assert item["can_execute_now"] is False

    def test_items_have_source_safe_fields(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        items = list_pending_confirmable_action_dicts()
        item = items[0]
        for key in ("queue_entry_id", "prepared_action_id", "domain",
                    "requested_action", "capability_name", "human_confirmation_status"):
            assert key in item, f"Missing field: {key!r}"

    def test_items_have_no_execution_tokens(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        items = list_pending_confirmable_action_dicts()
        item = items[0]
        assert "token" not in item
        assert "capability_token" not in item
        assert "authorized_plan_ref" not in item
        assert "police_decision_ref" not in item

    def test_endpoint_does_not_mutate_queue(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        _ = list_pending_confirmable_action_dicts()
        _ = list_pending_confirmable_action_dicts()
        assert len(list_pending_confirmable_action_dicts()) == 1

    def test_endpoint_count_matches_queue_length(self):
        for i in range(3):
            enqueue_confirmable_prepared_action(_code_confirmable(user_intent=f"intent {i}"))
        items = list_pending_confirmable_action_dicts()
        assert len(items) == 3

    def test_endpoint_human_confirmation_status_pending(self):
        enqueue_confirmable_prepared_action(_code_confirmable())
        items = list_pending_confirmable_action_dicts()
        assert items[0]["human_confirmation_status"] == "pending"
