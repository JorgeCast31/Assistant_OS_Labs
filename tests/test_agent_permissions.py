from dataclasses import FrozenInstanceError

import pytest

from assistant_os.agents import permissions
from assistant_os.agents.permissions import (
    AgentOperationalStatus,
    AgentPermissionProfile,
    AgentPoliceRequest,
    build_agent_permission_profile,
    evaluate_agent_permissions,
    profile_to_agent_permission,
)
from assistant_os.agents.registry import AGENT_REGISTRY
from assistant_os.police.models import AgentPermission, PoliceEvaluation, PoliceEvaluationType


def _profile(**overrides):
    values = {
        "agent_id": "agent-1",
        "display_name": "Agent One",
        "role": "support",
        "declared_capabilities": frozenset({"read"}),
        "permitted_tools": frozenset({"search"}),
        "permitted_environments": frozenset({"local"}),
    }
    values.update(overrides)
    return AgentPermissionProfile(**values)


def _request(**overrides):
    values = {
        "request_id": "req-1",
        "agent_id": "agent-1",
        "requested_by": "operator",
        "requested_tool": "search",
        "requested_environment": "local",
        "requested_capabilities": ("read",),
    }
    values.update(overrides)
    return AgentPoliceRequest(**values)


def test_profile_defaults_are_auditable():
    profile = _profile()

    assert profile.profile_id
    assert profile.requires_review is False
    assert profile.status is AgentOperationalStatus.ACTIVE
    assert profile.derived_at.tzinfo is not None
    assert profile.derived_at.utcoffset() is not None


def test_profile_is_frozen():
    profile = _profile()

    with pytest.raises(FrozenInstanceError):
        profile.agent_id = "changed"


def test_status_enum_values():
    assert AgentOperationalStatus.ACTIVE.value == "ACTIVE"
    assert AgentOperationalStatus.INACTIVE.value == "INACTIVE"
    assert AgentOperationalStatus.DEGRADED.value == "DEGRADED"
    assert AgentOperationalStatus.DISABLED.value == "DISABLED"


def test_permission_sets_are_preserved_as_frozensets():
    profile = _profile(
        declared_capabilities=frozenset({"read", "summarize"}),
        permitted_tools=frozenset({"search", "summarize"}),
        permitted_environments=frozenset({"local", "browser"}),
    )

    assert profile.declared_capabilities == frozenset({"read", "summarize"})
    assert profile.permitted_tools == frozenset({"search", "summarize"})
    assert profile.permitted_environments == frozenset({"local", "browser"})


def test_profile_to_agent_permission_returns_police_permission():
    permission = profile_to_agent_permission(_profile())

    assert isinstance(permission, AgentPermission)
    assert not isinstance(permission, AgentPermissionProfile)


def test_profile_to_agent_permission_maps_fields():
    permission = profile_to_agent_permission(_profile(requires_review=True))

    assert permission.agent_id == "agent-1"
    assert permission.allowed_tools == ["search"]
    assert permission.allowed_environments == ["local"]
    assert permission.capability_scope == ["read"]
    assert permission.requires_review is True


def test_permitted_tools_and_environments_do_not_come_from_declared_capabilities():
    profile = _profile(
        declared_capabilities=frozenset({"search", "local"}),
        permitted_tools=frozenset(),
        permitted_environments=frozenset(),
    )

    permission = profile_to_agent_permission(profile)

    assert permission.capability_scope == ["local", "search"]
    assert permission.allowed_tools == []
    assert permission.allowed_environments == []


def test_build_agent_permission_profile_uses_police_owned_config():
    profile = build_agent_permission_profile("code_executor")

    assert profile.agent_id == "code_executor"
    assert profile.declared_capabilities == frozenset({"code_execute"})
    assert profile.permitted_tools == frozenset({"code.review"})
    assert profile.permitted_environments == frozenset({"local"})


def test_build_agent_permission_profile_does_not_access_entrypoint(monkeypatch):
    class GuardedDefinition(dict):
        def __getitem__(self, key):
            if key == "entrypoint":
                raise AssertionError("must not read callable boundary")
            return super().__getitem__(key)

        def get(self, key, default=None):
            if key == "entrypoint":
                raise AssertionError("must not read callable boundary")
            return super().get(key, default)

    guarded = GuardedDefinition(
        {
            "name": "guarded_agent",
            "domain": "TEST",
            "version": "1.0.0",
            "description": "Guarded",
            "input_contract": "In",
            "output_contract": "Out",
            "requires_review": False,
            "capability_scope": ["read"],
            "entrypoint": lambda request: request,
        }
    )
    monkeypatch.setattr(permissions, "get_agent", lambda agent_name: guarded)
    monkeypatch.setitem(
        permissions.AGENT_POLICE_PERMISSION_CONFIG,
        "guarded_agent",
        {
            "permitted_tools": ("inspect",),
            "permitted_environments": ("local",),
        },
    )

    profile = build_agent_permission_profile("guarded_agent")

    assert profile.agent_id == "guarded_agent"
    assert profile.declared_capabilities == frozenset({"read"})


def test_build_agent_permission_profile_works_for_all_registered_agents():
    for agent_name in AGENT_REGISTRY:
        profile = build_agent_permission_profile(agent_name)
        assert profile.agent_id == agent_name
        assert profile.profile_id


def test_unknown_agent_raises_clear_exception():
    with pytest.raises(KeyError, match="Unknown agent permission profile"):
        build_agent_permission_profile("missing-agent")


def test_missing_police_config_raises_clear_exception(monkeypatch):
    monkeypatch.setattr(
        permissions,
        "get_agent",
        lambda agent_name: {
            "name": agent_name,
            "domain": "TEST",
            "version": "1.0.0",
            "requires_review": False,
            "capability_scope": ["read"],
        },
    )

    with pytest.raises(ValueError, match="Missing Police permission config"):
        build_agent_permission_profile("unconfigured_agent")


def test_disabled_agent_denies_without_police_allow():
    evaluation = evaluate_agent_permissions(
        _profile(status=AgentOperationalStatus.DISABLED),
        _request(),
    )

    assert isinstance(evaluation, PoliceEvaluation)
    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert evaluation.why_blocked == "Agent status is DISABLED."


def test_inactive_agent_denies_without_police_allow():
    evaluation = evaluate_agent_permissions(
        _profile(status=AgentOperationalStatus.INACTIVE),
        _request(),
    )

    assert isinstance(evaluation, PoliceEvaluation)
    assert evaluation.outcome is PoliceEvaluationType.DENY
    assert evaluation.why_blocked == "Agent status is INACTIVE."


def test_evaluate_agent_permissions_returns_police_evaluation_not_later_gate_type():
    evaluation = evaluate_agent_permissions(_profile(), _request())

    assert isinstance(evaluation, PoliceEvaluation)
    assert type(evaluation).__name__ == "PoliceEvaluation"
    assert type(evaluation).__name__ != "PoliceDecision"
