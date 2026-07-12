"""Tests for Model / Worker Routing Policy v0. Recommendation only; no execution."""
import json, os
from assistant_os.mso.delegation_packet import (
    DelegationWorkPacket, CostTier, RiskLevel, TaskType, now_iso)
from assistant_os.mso.worker_registry import (
    WorkerProfile, WorkerType, WorkerStatus, PrivacyClass)
from assistant_os.mso.routing_policy import (
    recommend_worker, eligible_workers, explain_worker_mismatch,
    RoutingRecommendation, RoutingStatus)

SECRET = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

def pkt(**o):
    d = dict(packet_id="P1", mission_id="M1", created_at=now_iso(), created_by="jorge",
             objective="summarize", task_type=TaskType.SUMMARIZATION,
             cost_tier=CostTier.LOCAL_PREFERRED, risk_level=RiskLevel.READ_ONLY,
             allowed_operations=["read"], allowed_inputs=["repo:docs"])
    d.update(o); return DelegationWorkPacket(**d)

def wkr(**o):
    d = dict(worker_id="W1", display_name="Local", worker_type=WorkerType.LOCAL_MODEL,
             status=WorkerStatus.AVAILABLE,
             supported_cost_tiers=[CostTier.LOCAL_PREFERRED.value, CostTier.LOW.value],
             default_cost_tier=CostTier.LOCAL_PREFERRED, max_risk_level=RiskLevel.PATCH_ALLOWED,
             preferred_task_types=[TaskType.SUMMARIZATION.value], privacy_class=PrivacyClass.LOCAL_ONLY)
    d.update(o); return WorkerProfile(**d)

def test_recommends_for_simple_read_only():
    r = recommend_worker(pkt(), [wkr()])
    assert r.routing_status == RoutingStatus.RECOMMENDED
    assert r.recommended_worker_id == "W1"
    assert r.can_execute is False

def test_does_not_recommend_non_available_workers():
    for st in (WorkerStatus.DRAFT, WorkerStatus.DISABLED, WorkerStatus.BLOCKED, WorkerStatus.DEPRECATED):
        r = recommend_worker(pkt(), [wkr(status=st)])
        assert r.recommended_worker_id == ""
        assert r.routing_status == RoutingStatus.BLOCKED_BY_STATUS

def test_can_execute_always_false():
    assert recommend_worker(pkt(), [wkr()]).can_execute is False
    assert recommend_worker(pkt(risk_level=RiskLevel.BLOCKED), [wkr()]).can_execute is False
    assert recommend_worker("bad", "bad").can_execute is False

def test_recommendation_is_not_authorization():
    r = recommend_worker(pkt(), [wkr()])
    d = r.to_dict()
    assert d["can_execute"] is False
    for a in ("issue_token", "grant", "execute", "handoff"):
        assert not hasattr(r, a)

def test_no_eligible_worker():
    r = recommend_worker(pkt(), [])
    assert r.routing_status == RoutingStatus.NO_ELIGIBLE_WORKER
    assert r.recommended_worker_id == ""

def test_forbidden_task_beats_preferred():
    w = wkr(preferred_task_types=[TaskType.SUMMARIZATION.value],
            forbidden_task_types=[TaskType.SUMMARIZATION.value])
    assert any("task" in m for m in explain_worker_mismatch(pkt(), w))
    r = recommend_worker(pkt(), [w])
    assert r.recommended_worker_id == ""

def test_cost_tier_not_supported_blocks():
    r = recommend_worker(pkt(cost_tier=CostTier.HIGH), [wkr(supported_cost_tiers=[CostTier.LOW.value], default_cost_tier=CostTier.LOW)])
    assert r.routing_status == RoutingStatus.BLOCKED_BY_COST

def test_premium_requires_human_review():
    p = pkt(cost_tier=CostTier.PREMIUM_REQUIRED, audit_notes="justified premium")
    w = wkr(supported_cost_tiers=[CostTier.PREMIUM_REQUIRED.value], default_cost_tier=CostTier.PREMIUM_REQUIRED,
            audit_notes="justified")
    r = recommend_worker(p, [w])
    assert r.routing_status == RoutingStatus.NEEDS_HUMAN_REVIEW
    assert r.requires_human_review is True

def test_risk_blocked_blocks():
    r = recommend_worker(pkt(risk_level=RiskLevel.BLOCKED), [wkr()])
    assert r.routing_status == RoutingStatus.BLOCKED_BY_RISK

def test_external_write_confirmation_needs_human_review():
    p = pkt(risk_level=RiskLevel.EXTERNAL_WRITE_REQUIRES_CONFIRMATION)
    w = wkr(max_risk_level=RiskLevel.EXTERNAL_WRITE_REQUIRES_CONFIRMATION)
    r = recommend_worker(p, [w])
    assert r.routing_status == RoutingStatus.NEEDS_HUMAN_REVIEW

def test_local_preferred_favors_local():
    local = wkr(worker_id="LOCAL", worker_type=WorkerType.LOCAL_MODEL)
    cloud = wkr(worker_id="CLOUD", worker_type=WorkerType.CODEX, privacy_class=PrivacyClass.INTERNAL_ONLY)
    r = recommend_worker(pkt(cost_tier=CostTier.LOCAL_PREFERRED), [cloud, local])
    assert r.recommended_worker_type == WorkerType.LOCAL_MODEL.value

def test_local_only_blocks_non_local():
    p = pkt(forbidden_inputs=["cloud"])
    w = wkr(worker_type=WorkerType.CODEX, privacy_class=PrivacyClass.INTERNAL_ONLY)
    r = recommend_worker(p, [w])
    assert r.routing_status == RoutingStatus.BLOCKED_BY_PRIVACY

def test_secret_privacy_incompatible_blocks():
    p = pkt(allowed_inputs=["secrets", "repo:docs"])
    w = wkr(can_access_secrets=False, privacy_class=PrivacyClass.SECRET_PROHIBITED)
    r = recommend_worker(p, [w])
    assert r.routing_status == RoutingStatus.BLOCKED_BY_PRIVACY

def test_deterministic_ordering():
    a = wkr(worker_id="A"); b = wkr(worker_id="B")
    assert [w.worker_id for w in eligible_workers(pkt(), [b, a])] == \
           [w.worker_id for w in eligible_workers(pkt(), [b, a])]

def test_json_roundtrip_stable():
    r = recommend_worker(pkt(), [wkr()])
    d = r.to_dict(); json.loads(json.dumps(d, sort_keys=True))
    assert RoutingRecommendation.from_dict(d).to_dict() == d

def test_no_secret_leakage():
    # invalid worker (secret in notes) -> not assignable -> blocked; secret must not appear
    w = wkr(audit_notes="api_key=" + SECRET)
    r = recommend_worker(pkt(), [w])
    assert SECRET not in json.dumps(r.to_dict())

def test_shipped_example_is_valid():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ex = os.path.join(here, "docs", "mission", "examples", "routing-decision.example.json")
    with open(ex, encoding="utf-8") as fh: data = json.load(fh)
    r = RoutingRecommendation.from_dict(data)
    assert r.can_execute is False
    assert r.to_dict()["can_execute"] is False
