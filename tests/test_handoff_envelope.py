"""Tests for Handoff Envelope v0. No dispatch, no execution, no authority."""
import json, os
from datetime import datetime, timedelta, timezone
import pytest
from assistant_os.mso.handoff_envelope import (
    HandoffEnvelope, HandoffEnvelopeError, HandoffStatus, now_iso)

SECRET = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

def env(**o):
    d = dict(handoff_id="H1", mission_id="M1", packet_id="P1", routing_decision_id="R1",
             target_worker_id="W1", created_at=now_iso(), created_by="jorge",
             objective="summarize docs", target_worker_type="LOCAL_MODEL",
             allowed_operations=["read"], forbidden_operations=["deploy"],
             input_refs=["repo:docs"], forbidden_input_refs=["env:SECRETS"])
    d.update(o); return HandoffEnvelope(**d)

def test_valid_envelope_passes():
    e = env(); assert e.is_valid(); e.validate()

def test_missing_mission_id_fails():
    with pytest.raises(HandoffEnvelopeError): env(mission_id="").validate()

def test_missing_packet_id_fails():
    with pytest.raises(HandoffEnvelopeError): env(packet_id="  ").validate()

def test_missing_routing_decision_id_fails():
    with pytest.raises(HandoffEnvelopeError): env(routing_decision_id="").validate()

def test_missing_target_worker_id_fails():
    with pytest.raises(HandoffEnvelopeError): env(target_worker_id="").validate()

def test_missing_objective_fails():
    with pytest.raises(HandoffEnvelopeError): env(objective="").validate()

def test_can_dispatch_always_false():
    assert env().can_dispatch is False
    assert env(handoff_status=HandoffStatus.APPROVED_FOR_HANDOFF).can_dispatch is False
    assert env().to_dict()["can_dispatch"] is False

def test_can_execute_always_false():
    assert env().can_execute is False
    assert env().to_dict()["can_execute"] is False

def test_approved_for_handoff_does_not_dispatch():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    e = env(handoff_status=HandoffStatus.APPROVED_FOR_HANDOFF, expires_at=future)
    assert e.is_active() is True
    assert e.is_dispatchable() is False
    assert e.can_dispatch is False and e.can_execute is False

def test_human_approval_ref_does_not_authorize():
    e = env(handoff_status=HandoffStatus.APPROVED_FOR_HANDOFF,
            human_approval_ref="coordination/decisions/DEC-1.md")
    assert e.can_execute is False and e.can_dispatch is False

def test_forbidden_operation_wins():
    e = env(allowed_operations=["read", "deploy"], forbidden_operations=["deploy"])
    assert e.is_operation_allowed("deploy") is False
    assert not e.is_valid()  # contradiction invalid

def test_forbidden_input_wins():
    e = env(input_refs=["a", "b"], forbidden_input_refs=["b"])
    assert e.is_input_allowed("b") is False
    assert not e.is_valid()

def test_expired_is_not_active():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    e = env(handoff_status=HandoffStatus.APPROVED_FOR_HANDOFF, expires_at=past)
    assert e.is_expired() and e.is_active() is False

def test_requires_human_review_default_true():
    assert env().requires_human_review is True

def test_secret_like_content_fails_without_leaking_value():
    e = env(audit_notes="api_key=" + SECRET)
    assert not e.is_valid()
    errs = e.validation_errors()
    assert SECRET not in json.dumps(errs)
    with pytest.raises(HandoffEnvelopeError) as ei:
        e.validate()
    assert SECRET not in str(ei.value)

def test_raw_large_content_rejected():
    assert not env(objective="x" * 5000).is_valid()

def test_invalid_enum_fails():
    with pytest.raises(HandoffEnvelopeError): env(handoff_status="RUNNING")

def test_json_roundtrip_stable():
    e = env()
    d = e.to_dict(); json.loads(json.dumps(d, sort_keys=True))
    e2 = HandoffEnvelope.from_dict(d)  # ignores derived can_dispatch/can_execute
    assert e2.to_dict() == d

def test_determinism():
    a = env(created_at="2026-07-09T00:00:00+00:00").to_dict()
    b = env(created_at="2026-07-09T00:00:00+00:00").to_dict()
    assert a == b

def test_no_token_or_capability_minting():
    e = env()
    for a in ("issue_token", "mint", "grant", "dispatch", "execute", "run"):
        assert not hasattr(e, a)
    assert e.to_dict()["can_dispatch"] is False and e.to_dict()["can_execute"] is False

def test_shipped_example_is_valid():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ex = os.path.join(here, "docs", "mission", "examples", "handoff-envelope.example.json")
    with open(ex, encoding="utf-8") as fh: data = json.load(fh)
    e = HandoffEnvelope.from_dict(data)
    assert e.is_valid()
    assert e.can_dispatch is False and e.can_execute is False
