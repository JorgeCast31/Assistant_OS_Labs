"""
S-MISSION-CONTROL-TRUTH-CONTRACTS-ALPHA-01 / Task 2

Truth-contract tests for the three read-model aggregation functions in
assistant_os/mso/mission_control_status.py.

Invariants verified for every function:
  - execution_allowed         = False   (never True)
  - used_execution            = False   (never True)
  - runner_reachable_from_ui  = False   (never True)
  - source                    = "backend_read_model"

None of these tests invoke an LLM, mock internal functions, or start a server.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Autouse fixture — reset MSO state around every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_mso_state():
    from assistant_os.mso.task_registry import reset_task_registry
    from assistant_os.mso.capability_registry import reset_dynamic_capabilities
    reset_dynamic_capabilities()
    reset_task_registry()
    try:
        from assistant_os.context_store import clear_store
        clear_store()
    except Exception:
        pass
    try:
        from assistant_os.mso.prepared_action_queue import clear_confirmable_action_queue_for_tests
        clear_confirmable_action_queue_for_tests()
    except Exception:
        pass
    yield
    reset_dynamic_capabilities()
    reset_task_registry()


# ---------------------------------------------------------------------------
# Helper imports — deferred so fixture runs first
# ---------------------------------------------------------------------------


def _status():
    from assistant_os.mso.mission_control_status import build_mission_control_status
    return build_mission_control_status()


def _readiness():
    from assistant_os.mso.mission_control_status import build_mission_control_readiness
    return build_mission_control_readiness()


def _snapshot():
    from assistant_os.mso.mission_control_status import build_orchestration_snapshot
    return build_orchestration_snapshot()


# ===========================================================================
# build_mission_control_status
# ===========================================================================


class TestBuildMissionControlStatus:

    def test_returns_dict(self):
        result = _status()
        assert isinstance(result, dict)

    def test_execution_allowed_is_false(self):
        result = _status()
        assert result["execution_allowed"] is False

    def test_used_execution_is_false(self):
        result = _status()
        assert result["used_execution"] is False

    def test_runner_reachable_from_ui_is_false(self):
        result = _status()
        assert result["runner_reachable_from_ui"] is False

    def test_source_is_backend_read_model(self):
        result = _status()
        assert result["source"] == "backend_read_model"

    def test_mission_control_section_present(self):
        result = _status()
        assert "mission_control" in result

    def test_mission_control_mode_is_read_model(self):
        result = _status()
        assert result["mission_control"]["mode"] == "read_model"

    def test_mission_control_execution_allowed_is_false(self):
        result = _status()
        assert result["mission_control"]["execution_allowed"] is False

    def test_mso_section_present(self):
        result = _status()
        assert "mso" in result

    def test_mso_boundary_is_sovereign(self):
        result = _status()
        assert result["mso"]["boundary"] == "sovereign"

    def test_queues_section_present(self):
        result = _status()
        assert "queues" in result

    def test_queues_has_prepared_actions_count_key(self):
        result = _status()
        assert "prepared_actions_count" in result["queues"]

    def test_queues_has_confirm_pending_count_key(self):
        result = _status()
        assert "confirm_pending_count" in result["queues"]

    def test_queues_prepared_actions_count_is_int(self):
        result = _status()
        assert isinstance(result["queues"]["prepared_actions_count"], int)

    def test_outcome_section_present(self):
        result = _status()
        assert "outcome" in result

    def test_authority_status_is_valid_state_word(self):
        from assistant_os.mso.mission_control_status import build_mission_control_status
        result = build_mission_control_status()
        assert result["authority"]["status"] in ("available", "unavailable", "degraded")

    def test_does_not_raise(self):
        # Should complete without exception even if internals fail
        try:
            _status()
        except Exception as exc:
            pytest.fail(f"build_mission_control_status() raised unexpectedly: {exc}")

    def test_mission_control_state_is_valid_value(self):
        result = _status()
        assert result["mission_control"]["state"] in ("available", "partial", "unavailable")

    def test_mso_entity_status_is_valid_value(self):
        result = _status()
        assert result["mso"]["entity_status"] in ("available", "unavailable")

    def test_mso_seat_status_is_valid_value(self):
        result = _status()
        assert result["mso"]["seat_status"] in ("available", "unavailable")

    def test_authority_section_present(self):
        result = _status()
        assert "authority" in result

    def test_authority_counts_is_dict(self):
        result = _status()
        assert isinstance(result["authority"]["counts"], dict)


# ===========================================================================
# build_mission_control_readiness
# ===========================================================================


class TestBuildMissionControlReadiness:

    def test_returns_dict(self):
        result = _readiness()
        assert isinstance(result, dict)

    def test_execution_allowed_is_false(self):
        result = _readiness()
        assert result["execution_allowed"] is False

    def test_used_execution_is_false(self):
        result = _readiness()
        assert result["used_execution"] is False

    def test_runner_reachable_from_ui_is_false(self):
        result = _readiness()
        assert result["runner_reachable_from_ui"] is False

    def test_arms_is_list(self):
        result = _readiness()
        assert isinstance(result["arms"], list)

    def test_all_arms_can_execute_without_mso_is_false(self):
        result = _readiness()
        for arm in result["arms"]:
            assert arm["can_execute_without_mso"] is False, (
                f"Arm {arm.get('id')!r} has can_execute_without_mso != False"
            )

    def test_all_arms_requires_authority_is_true(self):
        result = _readiness()
        for arm in result["arms"]:
            assert arm["requires_authority"] is True, (
                f"Arm {arm.get('id')!r} has requires_authority != True"
            )

    def test_all_arms_execution_status_is_unavailable(self):
        """No live arm status — execution_status must always be 'unavailable'."""
        result = _readiness()
        for arm in result["arms"]:
            assert arm["execution_status"] == "unavailable", (
                f"Arm {arm.get('id')!r} fabricated execution_status="
                f"{arm.get('execution_status')!r}"
            )

    def test_system_section_present(self):
        result = _readiness()
        assert "system" in result

    def test_system_overall_is_valid_value(self):
        result = _readiness()
        assert result["system"]["overall"] in ("available", "partial", "unavailable")

    def test_does_not_raise(self):
        try:
            _readiness()
        except Exception as exc:
            pytest.fail(f"build_mission_control_readiness() raised unexpectedly: {exc}")

    def test_source_is_backend_read_model(self):
        result = _readiness()
        assert result["source"] == "backend_read_model"

    def test_arms_have_id_and_label(self):
        result = _readiness()
        for arm in result["arms"]:
            assert "id" in arm
            assert "label" in arm

    def test_arms_have_readiness_source(self):
        result = _readiness()
        for arm in result["arms"]:
            assert arm.get("readiness_source") == "agent_registry"


# ===========================================================================
# build_orchestration_snapshot
# ===========================================================================


class TestBuildOrchestrationSnapshot:

    def test_returns_dict(self):
        result = _snapshot()
        assert isinstance(result, dict)

    def test_execution_allowed_is_false(self):
        result = _snapshot()
        assert result["execution_allowed"] is False

    def test_live_execution_is_false(self):
        result = _snapshot()
        assert result["live_execution"] is False

    def test_event_stream_connected_is_false(self):
        result = _snapshot()
        assert result["event_stream_connected"] is False

    def test_runs_is_empty_list(self):
        """No live runs — runs must always be []."""
        result = _snapshot()
        assert result["runs"] == []

    def test_threads_is_empty_list(self):
        result = _snapshot()
        assert result["threads"] == []

    def test_prepared_actions_is_list(self):
        result = _snapshot()
        assert isinstance(result["prepared_actions"], list)

    def test_no_run_has_status_running(self):
        """Invariant: no fabricated running runs."""
        result = _snapshot()
        for run in result["runs"]:
            assert run.get("status") != "running", (
                "A run with status='running' was fabricated — this violates the "
                "truth contract. runs must always be empty when nothing is running."
            )

    def test_does_not_raise(self):
        try:
            _snapshot()
        except Exception as exc:
            pytest.fail(f"build_orchestration_snapshot() raised unexpectedly: {exc}")

    def test_source_is_backend_read_model(self):
        result = _snapshot()
        assert result["source"] == "backend_read_model"

    def test_runner_reachable_from_ui_is_false(self):
        result = _snapshot()
        assert result["runner_reachable_from_ui"] is False

    def test_used_execution_is_false(self):
        result = _snapshot()
        assert result["used_execution"] is False

    def test_confirm_pending_is_list(self):
        result = _snapshot()
        assert isinstance(result["confirm_pending"], list)

    def test_prepared_actions_from_queue_have_expected_keys(self):
        """Entries derived from the queue must have id, status, domain, intent."""
        result = _snapshot()
        for action in result["prepared_actions"]:
            assert "id" in action
            assert "status" in action
            assert "domain" in action
            assert "intent" in action

    def test_prepared_actions_status_is_prepared(self):
        """All prepared_actions must carry status='prepared'."""
        result = _snapshot()
        for action in result["prepared_actions"]:
            assert action["status"] == "prepared", (
                f"Action {action.get('id')!r} has unexpected status={action.get('status')!r}"
            )

    def test_prepared_actions_intent_max_60_chars(self):
        """intent must be truncated to 60 chars or None."""
        result = _snapshot()
        for action in result["prepared_actions"]:
            intent = action.get("intent")
            if intent is not None:
                assert len(intent) <= 60, (
                    f"intent for action {action.get('id')!r} exceeds 60 chars"
                )


class TestMissionControlRouteHandlers:
    """Verify the four new webhook_server handler methods exist and are callable.

    These tests confirm:
    - Each handler method exists on the server class
    - Handler can be called without raising (fail-soft)
    - Responses include read-only invariants
    - Runner is never called
    """

    def _make_mock_handler(self):
        """Build a minimal WebhookHandler with mocked transport."""
        from assistant_os.webhook_server import WebhookHandler
        import unittest.mock as mock

        handler = object.__new__(WebhookHandler)
        handler._responses = []

        def fake_send(status_code, body):
            handler._responses.append((status_code, body))

        handler._send_json_response = fake_send
        handler._check_auth = lambda: None  # auth passes
        return handler

    def test_mission_control_status_handler_exists(self):
        from assistant_os.webhook_server import WebhookHandler
        assert hasattr(WebhookHandler, "_handle_mso_mission_control_status_get")

    def test_mission_control_readiness_handler_exists(self):
        from assistant_os.webhook_server import WebhookHandler
        assert hasattr(WebhookHandler, "_handle_mso_mission_control_readiness_get")

    def test_orchestration_snapshot_handler_exists(self):
        from assistant_os.webhook_server import WebhookHandler
        assert hasattr(WebhookHandler, "_handle_mso_orchestration_snapshot_get")

    def test_authority_trace_snapshot_handler_exists(self):
        from assistant_os.webhook_server import WebhookHandler
        assert hasattr(WebhookHandler, "_handle_mso_authority_trace_snapshot_get")

    def test_status_handler_returns_read_only_invariants(self):
        handler = self._make_mock_handler()
        handler._handle_mso_mission_control_status_get()
        assert len(handler._responses) == 1
        status_code, body = handler._responses[0]
        assert status_code == 200
        assert body.get("execution_allowed") is False
        assert body.get("used_execution") is False
        assert body.get("runner_reachable_from_ui") is False

    def test_readiness_handler_returns_read_only_invariants(self):
        handler = self._make_mock_handler()
        handler._handle_mso_mission_control_readiness_get()
        assert len(handler._responses) == 1
        status_code, body = handler._responses[0]
        assert status_code == 200
        assert body.get("execution_allowed") is False
        assert body.get("used_execution") is False
        assert body.get("runner_reachable_from_ui") is False

    def test_orchestration_handler_returns_read_only_invariants(self):
        handler = self._make_mock_handler()
        handler._handle_mso_orchestration_snapshot_get()
        assert len(handler._responses) == 1
        status_code, body = handler._responses[0]
        assert status_code == 200
        assert body.get("execution_allowed") is False
        assert body.get("used_execution") is False
        assert body.get("live_execution") is False

    def test_authority_trace_handler_returns_read_only_invariants(self):
        handler = self._make_mock_handler()
        handler._handle_mso_authority_trace_snapshot_get()
        assert len(handler._responses) == 1
        status_code, body = handler._responses[0]
        assert status_code == 200
        assert body.get("execution_allowed") is False
        assert body.get("used_execution") is False
        assert body.get("runner_reachable_from_ui") is False

    def test_authority_trace_handler_returns_stages_list(self):
        handler = self._make_mock_handler()
        handler._handle_mso_authority_trace_snapshot_get()
        status_code, body = handler._responses[0]
        assert isinstance(body.get("stages"), list)
        assert len(body["stages"]) == 9  # all 9 authority chain stages

    def test_authority_trace_runner_stage_not_reachable(self):
        handler = self._make_mock_handler()
        handler._handle_mso_authority_trace_snapshot_get()
        status_code, body = handler._responses[0]
        stages = {s["id"]: s for s in body.get("stages", [])}
        runner = stages.get("runner")
        assert runner is not None
        # Runner is architecturally closed — state must NOT be "available"
        assert runner["state"] in ("blocked", "architectural", "unavailable")
        assert runner["state"] != "available"

    def test_orchestration_handler_runs_always_empty(self):
        handler = self._make_mock_handler()
        handler._handle_mso_orchestration_snapshot_get()
        status_code, body = handler._responses[0]
        assert body.get("runs") == []
        assert body.get("threads") == []
        assert body.get("live_execution") is False
