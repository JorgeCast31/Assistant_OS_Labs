"""Tests for Delegation / Work Packet v0. No execution; no authority."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from assistant_os.mso.delegation_packet import (
    DelegationWorkPacket, DelegationPacketError, DelegationStatus,
    TargetWorker, TaskType, CostTier, RiskLevel, now_iso,
)

SECRET = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _valid(**over):
    d = dict(
        packet_id="P-1", mission_id="M-1", created_at=now_iso(), created_by="jorge",
        objective="Inspect coordination folder", task_title="Inspect",
        task_type=TaskType.REPO_INSPECTION, target_worker=TargetWorker.CLAUDE_CODE,
        cost_tier=CostTier.LOCAL_PREFERRED, risk_level=RiskLevel.READ_ONLY,
        status=DelegationStatus.DRAFT,
        allowed_operations=["read"], forbidden_operations=["deploy"],
        allowed_inputs=["repo:docs"], forbidden_inputs=["env:SECRETS"],
    )
    d.update(over)
    return DelegationWorkPacket(**d)


def test_valid_packet_passes():
    p = _valid()
    assert p.is_valid(); p.validate()


def test_missing_packet_id_fails():
    with pytest.raises(DelegationPacketError):
        _valid(packet_id="").validate()


def test_missing_mission_id_fails():
    with pytest.raises(DelegationPacketError):
        _valid(mission_id="  ").validate()


def test_missing_objective_fails():
    with pytest.raises(DelegationPacketError):
        _valid(objective="").validate()


def test_secret_is_rejected():
    p = _valid(audit_notes=SECRET)
    assert not p.is_valid()
    with pytest.raises(DelegationPacketError):
        p.validate()
    assert not _valid(allowed_inputs=["ok", SECRET]).is_valid()


def test_forbidden_wins_over_allowed():
    p = _valid(allowed_operations=["read", "deploy"], forbidden_operations=["deploy"])
    assert p.is_operation_allowed("deploy") is False
    assert not p.is_valid()  # contradiction invalidates
    q = _valid(allowed_inputs=["a"], forbidden_inputs=["a"])
    assert q.is_input_allowed("a") is False
    assert not q.is_valid()


def test_human_review_required_default_true():
    assert _valid().human_review_required is True


def test_model_preference_does_not_authorize():
    p = _valid(model_preference="premium-model-xyz",
               status=DelegationStatus.APPROVED_FOR_HANDOFF)
    assert p.can_execute is False


def test_approved_for_handoff_does_not_execute():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    p = _valid(status=DelegationStatus.APPROVED_FOR_HANDOFF, expires_at=future)
    assert p.is_active() is True
    assert p.can_execute is False
    assert p.is_auto_executable() is False


def test_expired_is_not_active():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    p = _valid(status=DelegationStatus.APPROVED_FOR_HANDOFF, expires_at=past)
    assert p.is_expired() and p.is_active() is False


def test_invalid_enum_fails_closed():
    for bad in (dict(status="RUNNING"), dict(target_worker="ROBOT"),
                dict(task_type="MINING"), dict(cost_tier="FREE"), dict(risk_level="YOLO")):
        with pytest.raises(DelegationPacketError):
            _valid(**bad)


def test_premium_without_justification_fails():
    p = _valid(cost_tier=CostTier.PREMIUM_REQUIRED, audit_notes="")
    assert not p.is_valid()
    with pytest.raises(DelegationPacketError):
        p.validate()
    # with justification it passes
    assert _valid(cost_tier=CostTier.PREMIUM_REQUIRED,
                  audit_notes="Needed for deep reasoning; approved rationale.").is_valid()


def test_json_roundtrip_stable():
    p = _valid(created_at="2026-07-09T00:00:00+00:00")
    d = p.to_dict()
    json.loads(json.dumps(d, sort_keys=True))
    p2 = DelegationWorkPacket.from_dict(d)
    assert p2.to_dict() == d
    assert p2.to_dict()["can_execute"] is False


def test_determinism():
    a = _valid(created_at="2026-07-09T00:00:00+00:00").to_dict()
    b = _valid(created_at="2026-07-09T00:00:00+00:00").to_dict()
    assert a == b


def test_no_token_or_capability_minting():
    # Contract exposes no token/capability/execute surface.
    p = _valid()
    for attr in ("issue_token", "mint", "capability", "execute", "run", "grant"):
        assert not hasattr(p, attr)
    assert p.to_dict()["can_execute"] is False


def test_shipped_example_is_valid():
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ex = os.path.join(here, "docs", "mission", "examples", "delegation-work-packet.example.json")
    with open(ex, encoding="utf-8") as fh:
        data = json.load(fh)
    p = DelegationWorkPacket.from_dict(data)
    assert p.is_valid()
    assert p.can_execute is False
    assert p.status == DelegationStatus.DRAFT
