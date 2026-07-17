"""Tests for Orchestration Preview / Dry-Run v0. No execution, no dispatch."""
import json, os, copy
from assistant_os.mso.delegation_packet import (
    DelegationWorkPacket, CostTier, RiskLevel, TaskType, TargetWorker, now_iso)
from assistant_os.mso.worker_registry import (
    WorkerProfile, WorkerType, WorkerStatus, PrivacyClass)
from assistant_os.mso.handoff_envelope import HandoffEnvelope
from assistant_os.mso.orchestration_preview import (
    build_orchestration_preview, preview_handoff, validate_preview,
    OrchestrationPreview, PreviewStatus)

SECRET = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

def pkt(**o):
    d = dict(packet_id="P1", mission_id="M1", created_at=now_iso(), created_by="jorge",
             objective="summarize docs", task_type=TaskType.SUMMARIZATION,
             cost_tier=CostTier.LOCAL_PREFERRED, risk_level=RiskLevel.READ_ONLY,
             allowed_operations=["read"], allowed_inputs=["repo:docs"],
             expected_outputs=["summary"], verification_plan=["human review"],
             acceptance_criteria=["accurate"], linked_evidence=["PR#268"])
    d.update(o); return DelegationWorkPacket(**d)

def wkr(**o):
    d = dict(worker_id="W1", display_name="Local", worker_type=WorkerType.LOCAL_MODEL,
             status=WorkerStatus.AVAILABLE,
             supported_cost_tiers=[CostTier.LOCAL_PREFERRED.value],
             default_cost_tier=CostTier.LOCAL_PREFERRED, max_risk_level=RiskLevel.PATCH_ALLOWED,
             preferred_task_types=[TaskType.SUMMARIZATION.value], privacy_class=PrivacyClass.LOCAL_ONLY)
    d.update(o); return WorkerProfile(**d)

def test_valid_preview_ready_for_review():
    p = build_orchestration_preview(pkt(), [wkr()])
    assert p.preview_status == PreviewStatus.READY_FOR_REVIEW
    assert p.selected_worker_id == "W1" and p.handoff_id != ""
    validate_preview(p)

def test_can_dispatch_always_false():
    assert build_orchestration_preview(pkt(), [wkr()]).can_dispatch is False
    assert build_orchestration_preview(pkt(risk_level=RiskLevel.BLOCKED), [wkr()]).can_dispatch is False

def test_can_execute_always_false():
    p = build_orchestration_preview(pkt(), [wkr()])
    assert p.can_execute is False and p.to_dict()["can_execute"] is False and p.to_dict()["can_dispatch"] is False

def test_preview_does_not_authorize():
    p = build_orchestration_preview(pkt(), [wkr()])
    for a in ("dispatch", "execute", "issue_token", "grant", "run"):
        assert not hasattr(p, a)

def test_no_eligible_worker():
    p = build_orchestration_preview(pkt(), [])
    assert p.preview_status == PreviewStatus.NO_ELIGIBLE_WORKER
    assert p.handoff_id == "" and p.selected_worker_id == ""

def test_non_assignable_worker_blocks():
    p = build_orchestration_preview(pkt(), [wkr(status=WorkerStatus.DISABLED)])
    assert p.preview_status == PreviewStatus.BLOCKED
    assert p.handoff_id == ""

def test_needs_human_review_reflected():
    p = build_orchestration_preview(
        pkt(cost_tier=CostTier.PREMIUM_REQUIRED, audit_notes="justified"),
        [wkr(supported_cost_tiers=[CostTier.PREMIUM_REQUIRED.value], default_cost_tier=CostTier.PREMIUM_REQUIRED, audit_notes="ok")])
    assert p.preview_status == PreviewStatus.NEEDS_HUMAN_REVIEW
    assert p.requires_human_review is True

def test_risk_blocked_reflected():
    p = build_orchestration_preview(pkt(risk_level=RiskLevel.BLOCKED), [wkr()])
    assert p.preview_status == PreviewStatus.BLOCKED

def test_invalid_packet_gives_invalid_input():
    p = build_orchestration_preview("not a packet", [wkr()])
    assert p.preview_status == PreviewStatus.INVALID_INPUT
    assert p.handoff_id == ""

def test_handoff_built_keeps_flags_false():
    rec, env, p = preview_handoff(pkt(), [wkr()])
    assert isinstance(env, HandoffEnvelope)
    assert env.can_dispatch is False and env.can_execute is False
    assert p.handoff_id == env.handoff_id

def test_explicit_target_propagates_to_preview_and_handoff_without_fallback():
    codex = wkr(worker_id="A-CODEX", worker_type=WorkerType.CODEX)
    claude = wkr(worker_id="Z-CLAUDE", worker_type=WorkerType.CLAUDE_CODE)
    rec, env, preview = preview_handoff(
        pkt(target_worker=TargetWorker.CLAUDE_CODE), [codex, claude])
    assert rec.recommended_worker_id == "Z-CLAUDE"
    assert preview.selected_worker_id == "Z-CLAUDE"
    assert env is not None and env.target_worker_id == "Z-CLAUDE"
    assert env.can_dispatch is False and env.can_execute is False

    rec, env, preview = preview_handoff(
        pkt(target_worker=TargetWorker.CLAUDE_CODE), [codex])
    assert preview.preview_status == PreviewStatus.NO_ELIGIBLE_WORKER
    assert env is None and preview.selected_worker_id == ""

def test_no_handoff_if_no_eligible_worker():
    rec, env, p = preview_handoff(pkt(), [wkr(status=WorkerStatus.BLOCKED)])
    assert env is None and p.handoff_id == ""

def test_does_not_mutate_inputs():
    p = pkt(); ws = [wkr()]
    before_p = p.to_dict(); before_w = [w.to_dict() for w in ws]
    build_orchestration_preview(p, ws)
    assert p.to_dict() == before_p
    assert [w.to_dict() for w in ws] == before_w

def test_determinism():
    a = build_orchestration_preview(pkt(created_at="2026-07-09T00:00:00+00:00"), [wkr()]).to_dict()
    b = build_orchestration_preview(pkt(created_at="2026-07-09T00:00:00+00:00"), [wkr()]).to_dict()
    a.pop("created_at"); b.pop("created_at")
    assert a == b

def test_json_roundtrip_stable():
    p = build_orchestration_preview(pkt(), [wkr()])
    d = p.to_dict(); json.loads(json.dumps(d, sort_keys=True))
    assert OrchestrationPreview.from_dict(d).to_dict() == d

def test_secret_like_content_blocks_without_leak():
    # secret in packet -> invalid packet -> INVALID_INPUT; secret must not leak
    p = build_orchestration_preview(pkt(audit_notes="api_key=" + SECRET), [wkr()])
    assert p.preview_status == PreviewStatus.INVALID_INPUT
    assert SECRET not in json.dumps(p.to_dict())

def test_no_token_or_capability_minting():
    import assistant_os.mso.orchestration_preview as m
    for name in dir(m):
        assert "token" not in name.lower() and "mint" not in name.lower()

def test_shipped_example_is_valid():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ex = os.path.join(here, "docs", "mission", "examples", "orchestration-preview.example.json")
    with open(ex, encoding="utf-8") as fh: data = json.load(fh)
    p = OrchestrationPreview.from_dict(data)
    assert p.can_dispatch is False and p.can_execute is False
    validate_preview(p)
