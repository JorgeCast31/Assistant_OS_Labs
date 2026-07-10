"""Tests for Mission Record File / Validator v0 (IO layer). No execution."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from assistant_os.mso.mission_record import (
    MissionAuthorizationRecord, MissionStatus, MissionAuthorityLevel,
    MissionExecutionPolicy, now_iso,
)
from assistant_os.mso.mission_record_io import (
    MissionRecordIOError,
    load_record_from_dict, load_record_from_json, load_record_from_path,
    normalize_to_json, validate_source, main,
)

SECRET = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _valid_dict(**over):
    d = dict(
        mission_id="M-IO-1", created_at=now_iso(), created_by="jorge",
        objective="Validate record file", scope="repo:docs read-only",
        authority_level="READ_ONLY", status="DRAFT", execution_policy="NO_EXECUTION",
        allowed_operations=["read"], forbidden_operations=["deploy"],
        required_human_confirmations=[], linked_evidence=["PR#263"],
    )
    d.update(over)
    return d


# 1
def test_load_valid_from_dict():
    r = load_record_from_dict(_valid_dict())
    assert r.is_valid() and r.mission_id == "M-IO-1"


# 2
def test_load_valid_from_json_string():
    r = load_record_from_json(json.dumps(_valid_dict()))
    assert r.is_valid()


# 3
def test_load_valid_from_file(tmp_path):
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(_valid_dict()), encoding="utf-8")
    r = load_record_from_path(str(p))
    assert r.is_valid()


# 4
def test_invalid_json_fails_closed():
    with pytest.raises(MissionRecordIOError):
        load_record_from_json("{not valid json")


# 5
def test_missing_critical_field_fails():
    d = _valid_dict(); d.pop("mission_id")
    with pytest.raises(MissionRecordIOError):
        load_record_from_dict(d)
    with pytest.raises(MissionRecordIOError):
        load_record_from_dict(_valid_dict(objective="  "))


# 6
def test_unknown_field_fails_strict_and_warns_when_allowed():
    d = _valid_dict(surprise_field="x")
    with pytest.raises(MissionRecordIOError):
        load_record_from_dict(d)  # strict default
    res = validate_source(d, strict_unknown=False)
    assert any("unknown field" in w for w in res["warnings"])
    assert res["ok"] is True  # tolerated as warning


# 7
def test_secret_in_file_is_rejected(tmp_path):
    p = tmp_path / "sec.json"
    p.write_text(json.dumps(_valid_dict(audit_notes=SECRET)), encoding="utf-8")
    with pytest.raises(MissionRecordIOError):
        load_record_from_path(str(p))


# 8
def test_expired_loads_but_is_not_active():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = load_record_from_dict(_valid_dict(
        status="HUMAN_APPROVED", required_human_confirmations=["jorge_in_repo"],
        expires_at=past))
    assert r.is_expired() and r.is_active() is False


# 9
def test_approved_loads_but_cannot_execute():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    r = load_record_from_dict(_valid_dict(
        status="HUMAN_APPROVED", required_human_confirmations=["jorge_in_repo"],
        expires_at=future))
    assert r.is_approved() and r.can_execute is False


# 10
def test_no_execution_stays_non_executable():
    r = load_record_from_dict(_valid_dict(execution_policy="NO_EXECUTION"))
    assert r.can_execute is False
    assert r.to_dict()["can_execute"] is False


# 11
def test_normalization_is_deterministic():
    d = _valid_dict(created_at="2026-07-09T00:00:00+00:00")
    a = normalize_to_json(load_record_from_dict(d))
    b = normalize_to_json(load_record_from_dict(d))
    assert a == b


# 12
def test_forbidden_wins_over_allowed():
    r = load_record_from_dict(_valid_dict(allowed_operations=["read"], forbidden_operations=["deploy"]))
    assert r.is_operation_allowed("deploy") is False
    assert r.is_operation_allowed("read") is True


# 13
def test_errors_never_include_secret_values():
    res = validate_source(_valid_dict(audit_notes=SECRET))
    assert res["ok"] is False
    blob = json.dumps(res)
    assert SECRET not in blob  # no secret value leaks into errors/output


# 14
def test_nonexistent_path_fails_closed():
    with pytest.raises(MissionRecordIOError):
        load_record_from_path("this/does/not/exist-xyz.json")


# 15
def test_roundtrip_is_stable(tmp_path):
    r = load_record_from_dict(_valid_dict(created_at="2026-07-09T00:00:00+00:00"))
    n1 = normalize_to_json(r)
    p = tmp_path / "rt.json"; p.write_text(n1, encoding="utf-8")
    r2 = load_record_from_path(str(p))  # normalized output (incl. can_execute) reloads
    n2 = normalize_to_json(r2)
    assert n1 == n2


# shipped example validates + CLI returns 0
def test_shipped_example_is_valid():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    example = os.path.join(here, "docs", "mission", "examples", "mission-record.draft.example.json")
    res = validate_source(example)
    assert res["ok"] is True
    assert res["can_execute"] is False
    assert main([example]) == 0


def test_cli_returns_1_on_invalid(tmp_path, capsys):
    p = tmp_path / "bad.json"; p.write_text("{oops", encoding="utf-8")
    assert main([str(p)]) == 1
    out = capsys.readouterr().out
    assert "INVALID" in out
