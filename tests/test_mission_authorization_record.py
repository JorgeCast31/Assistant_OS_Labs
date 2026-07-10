"""Tests for Mission / Authorization Record v0.

Contract + validation + safety. No execution is ever performed or granted.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from assistant_os.mso.mission_record import (
    MissionAuthorizationRecord,
    MissionAuthorityLevel,
    MissionExecutionPolicy,
    MissionRecordError,
    MissionStatus,
    now_iso,
)


def _valid(**over):
    base = dict(
        mission_id="M-0001",
        created_at=now_iso(),
        created_by="jorge",
        objective="Audit coordination contract for F1 gap",
        scope="repo:coordination read-only",
        authority_level=MissionAuthorityLevel.READ_ONLY,
        status=MissionStatus.DRAFT,
        execution_policy=MissionExecutionPolicy.NO_EXECUTION,
        allowed_operations=["read"],
        forbidden_operations=["write", "deploy"],
        required_human_confirmations=[],
        linked_evidence=["PR#262"],
    )
    base.update(over)
    return MissionAuthorizationRecord(**base)


# 1
def test_valid_record_passes_validation():
    r = _valid()
    assert r.is_valid()
    r.validate()  # must not raise


# 2
def test_missing_mission_id_fails():
    r = _valid(mission_id="")
    assert not r.is_valid()
    with pytest.raises(MissionRecordError):
        r.validate()


# 3
def test_missing_objective_fails():
    r = _valid(objective="   ")
    assert not r.is_valid()
    with pytest.raises(MissionRecordError):
        r.validate()


# 4
def test_expired_record_is_not_active():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = _valid(status=MissionStatus.HUMAN_APPROVED,
               required_human_confirmations=["jorge_in_repo"],
               expires_at=past)
    assert r.is_expired()
    assert not r.is_active()
    assert not r.is_approved()


# 5
def test_draft_record_is_not_approved():
    r = _valid(status=MissionStatus.DRAFT)
    assert not r.is_approved()
    assert not r.is_active()


# 6
def test_human_approved_can_be_approved_but_never_executes():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    r = _valid(status=MissionStatus.HUMAN_APPROVED,
               required_human_confirmations=["jorge_in_repo"],
               expires_at=future)
    assert r.is_approved()
    assert r.is_active()
    assert r.can_execute is False  # approval != execution


# 3b — approved status without a recorded human confirmation is invalid
def test_human_approved_without_confirmation_is_invalid():
    r = _valid(status=MissionStatus.HUMAN_APPROVED, required_human_confirmations=[])
    assert not r.is_valid()
    assert not r.is_approved()


# 7
def test_forbidden_overrides_allowed():
    r = _valid(allowed_operations=["read", "special"],
               forbidden_operations=["deploy"])
    assert r.is_operation_allowed("read") is True
    assert r.is_operation_allowed("deploy") is False
    # An op both allowed and forbidden -> contradiction invalidates the record.
    r2 = _valid(allowed_operations=["read", "deploy"], forbidden_operations=["deploy"])
    assert not r2.is_valid()
    assert r2.is_operation_allowed("deploy") is False  # forbidden wins regardless


# 8
def test_secrets_are_detected_and_rejected():
    for bad in ("sk-ABCDEFGHIJKLMNOPQRSTUVWX",
                "password=hunter2",
                "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"):
        r = _valid(audit_notes=bad)
        assert not r.is_valid(), bad
        with pytest.raises(MissionRecordError):
            r.validate()
    # secret hidden inside a list field is also caught
    r = _valid(linked_evidence=["ok", "authorization: Bearer abcdef1234567890"])
    assert not r.is_valid()


# 9
def test_invalid_enum_fails_closed():
    with pytest.raises(MissionRecordError):
        _valid(authority_level="GOD_MODE")
    with pytest.raises(MissionRecordError):
        _valid(status="RUNNING")
    with pytest.raises(MissionRecordError):
        _valid(execution_policy="EXECUTE_NOW")


# 10
def test_no_execution_keeps_can_execute_false():
    for pol in MissionExecutionPolicy:
        r = _valid(execution_policy=pol,
                   status=MissionStatus.HUMAN_APPROVED,
                   required_human_confirmations=["jorge_in_repo"])
        assert r.can_execute is False
        assert r.to_dict()["can_execute"] is False


# 11
def test_json_serialization_is_stable_and_roundtrips():
    r = _valid()
    d = r.to_dict()
    blob = json.dumps(d, sort_keys=True)
    json.loads(blob)  # serializable
    r2 = MissionAuthorizationRecord.from_dict(d)
    assert r2.to_dict() == d  # roundtrip stable
    assert r2.status == r.status
    assert r2.authority_level == r.authority_level


# 12
def test_determinism():
    a = _valid(created_at="2026-07-09T00:00:00+00:00")
    b = _valid(created_at="2026-07-09T00:00:00+00:00")
    assert a.to_dict() == b.to_dict()


# empty critical field (scope) invalidates
def test_empty_scope_is_invalid():
    r = _valid(scope="")
    assert not r.is_valid()


# to_dict always carries can_execute=false, never a grant
def test_to_dict_never_grants_execution():
    d = _valid(status=MissionStatus.HUMAN_APPROVED,
               required_human_confirmations=["jorge_in_repo"]).to_dict()
    assert d["can_execute"] is False
    assert "execution_policy" in d and d["execution_policy"] in {p.value for p in MissionExecutionPolicy}
