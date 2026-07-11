"""Tests for Worker / Subagent Registry v0. No execution; no authority."""
import json, os
import pytest
from assistant_os.mso.worker_registry import (
    WorkerProfile, WorkerProfileError, WorkerType, WorkerStatus,
    PrivacyClass, ContextWindowClass,
)
from assistant_os.mso.delegation_packet import CostTier, RiskLevel

SECRET = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

def _valid(**over):
    d = dict(
        worker_id="W-1", display_name="Local Model",
        worker_type=WorkerType.LOCAL_MODEL, status=WorkerStatus.AVAILABLE,
        supported_cost_tiers=[CostTier.LOCAL_PREFERRED.value, CostTier.LOW.value],
        default_cost_tier=CostTier.LOCAL_PREFERRED,
        preferred_task_types=["SUMMARIZATION"], forbidden_task_types=["CODE_PATCH"],
    )
    d.update(over); return WorkerProfile(**d)

def test_valid_profile_passes():
    p = _valid(); assert p.is_valid(); p.validate()

def test_missing_worker_id_fails():
    with pytest.raises(WorkerProfileError): _valid(worker_id="").validate()

def test_missing_display_name_fails():
    with pytest.raises(WorkerProfileError): _valid(display_name="  ").validate()

def test_secret_like_content_fails():
    assert not _valid(audit_notes=SECRET).is_valid()
    assert not _valid(capabilities=["ok", "api_key=" + SECRET]).is_valid()

def test_defaults_are_safe():
    p = WorkerProfile(worker_id="W", display_name="D")
    assert p.can_execute is False
    assert p.can_access_secrets is False
    assert p.can_write_external is False
    assert p.requires_human_supervision is True
    assert p.privacy_class == PrivacyClass.SECRET_PROHIBITED

def test_available_is_not_executable():
    p = _valid(status=WorkerStatus.AVAILABLE)
    assert p.is_assignable() is True
    assert p.can_execute is False  # available != executable

def test_local_does_not_imply_secret_access():
    p = _valid(worker_type=WorkerType.LOCAL_MODEL, privacy_class=PrivacyClass.LOCAL_ONLY)
    assert p.can_access_secrets is False
    # SECRET_PROHIBITED contradicts claiming secret access
    assert not _valid(privacy_class=PrivacyClass.SECRET_PROHIBITED, can_access_secrets=True).is_valid()

def test_preferred_forbidden_contradiction_fails():
    assert not _valid(preferred_task_types=["REVIEW"], forbidden_task_types=["REVIEW"]).is_valid()

def test_default_cost_outside_supported_fails():
    assert not _valid(supported_cost_tiers=[CostTier.LOW.value],
                      default_cost_tier=CostTier.HIGH).is_valid()

def test_disabled_blocked_deprecated_not_assignable():
    for st in (WorkerStatus.DRAFT, WorkerStatus.DISABLED, WorkerStatus.BLOCKED, WorkerStatus.DEPRECATED):
        assert _valid(status=st).is_assignable() is False

def test_capabilities_do_not_grant_permission():
    p = _valid(capabilities=["can_do_everything", "execute", "write_external"])
    assert p.can_execute is False and p.can_write_external is False and p.can_access_secrets is False

def test_premium_without_justification_fails():
    assert not _valid(supported_cost_tiers=[CostTier.PREMIUM_REQUIRED.value],
                      default_cost_tier=CostTier.PREMIUM_REQUIRED, audit_notes="").is_valid()
    assert _valid(supported_cost_tiers=[CostTier.PREMIUM_REQUIRED.value],
                  default_cost_tier=CostTier.PREMIUM_REQUIRED,
                  audit_notes="Justified: deep reasoning needed.").is_valid()

def test_invalid_enum_fails():
    for bad in (dict(worker_type="ROBOT"), dict(status="RUNNING"),
                dict(privacy_class="OPEN"), dict(context_window_class="TINY"),
                dict(max_risk_level="YOLO")):
        with pytest.raises(WorkerProfileError): _valid(**bad)

def test_json_roundtrip_stable():
    p = _valid()
    d = p.to_dict(); json.loads(json.dumps(d, sort_keys=True))
    assert WorkerProfile.from_dict(d).to_dict() == d

def test_determinism():
    assert _valid().to_dict() == _valid().to_dict()

def test_no_token_or_capability_minting():
    p = _valid()
    for attr in ("issue_token", "mint", "grant", "execute", "run", "route"):
        assert not hasattr(p, attr)

def test_shipped_example_is_valid():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ex = os.path.join(here, "docs", "mission", "examples", "worker-profile.example.json")
    with open(ex, encoding="utf-8") as fh: data = json.load(fh)
    p = WorkerProfile.from_dict(data)
    assert p.is_valid()
    assert p.can_execute is False and p.can_access_secrets is False
    assert p.status == WorkerStatus.DRAFT
