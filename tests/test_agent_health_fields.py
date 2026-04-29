from assistant_os.contracts import ACTION_CODE_FIX
from assistant_os.mso.capability_registry import reset_dynamic_capabilities, revoke_capability
from assistant_os.mso.contracts import TaskRecord
from assistant_os.mso.task_registry import register_task, reset_task_registry
from assistant_os.operability import build_agents_registry_response


def setup_function():
    reset_task_registry()
    reset_dynamic_capabilities()


def teardown_function():
    reset_task_registry()
    reset_dynamic_capabilities()


def _agent(response: dict, agent_id: str) -> dict:
    return next(agent for agent in response["agents"] if agent["id"] == agent_id)


def test_agents_registry_exposes_health_fields_without_task_history():
    response = build_agents_registry_response()
    code_agent = _agent(response, "code_executor")

    assert "last_execution_at" in code_agent
    assert "last_result" in code_agent
    assert "policy_restricted" in code_agent
    assert code_agent["last_execution_at"] is None
    assert code_agent["last_result"] is None
    assert code_agent["policy_restricted"] is False


def test_agents_registry_derives_last_result_from_task_registry():
    register_task(
        TaskRecord(
            task_id="task-code-1",
            context_id="ctx-1",
            trace_id="trace-1",
            plan_id="plan-1",
            domain="CODE",
            status="completed",
            created_at="2026-04-27T10:00:00+00:00",
            updated_at="2026-04-27T10:05:00+00:00",
            completed_at="2026-04-27T10:05:00+00:00",
            last_known_action=ACTION_CODE_FIX,
            result_type="code_fix",
        )
    )

    response = build_agents_registry_response()
    code_agent = _agent(response, "code_executor")

    assert code_agent["last_execution_at"] == "2026-04-27T10:05:00+00:00"
    assert code_agent["last_result"] == {
        "task_id": "task-code-1",
        "status": "completed",
        "result_type": "code_fix",
        "error_type": None,
        "error_message": None,
    }


def test_agents_registry_marks_policy_restricted_from_active_revocations():
    revoke_capability(
        action="*",
        domain="CODE",
        reason="incident response",
    )

    response = build_agents_registry_response()

    assert _agent(response, "code_executor")["policy_restricted"] is True
    assert _agent(response, "host_launcher")["policy_restricted"] is False
