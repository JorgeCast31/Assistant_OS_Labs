"""Tests for Orchestration Preview Bundle / CLI v0. Read-only; no execution/writes."""
import json, os
import pytest
from assistant_os.mso.orchestration_preview_io import (
    OrchestrationBundleError, OrchestrationPreviewBundle,
    load_bundle_from_dict, load_bundle_from_json, load_bundle_from_path,
    build_preview_from_bundle, validate_bundle_source, normalize_preview_to_json, main)
from assistant_os.mso.orchestration_preview import PreviewStatus

SECRET = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

def _packet(**o):
    d = dict(packet_id="P1", mission_id="M1", created_at="2026-07-09T00:00:00+00:00",
             created_by="jorge", objective="summarize docs", task_type="SUMMARIZATION",
             cost_tier="LOCAL_PREFERRED", risk_level="READ_ONLY",
             allowed_operations=["read"], allowed_inputs=["repo:docs"])
    d.update(o); return d

def _worker(**o):
    d = dict(worker_id="W1", display_name="Local", worker_type="LOCAL_MODEL", status="AVAILABLE",
             supported_cost_tiers=["LOCAL_PREFERRED"], default_cost_tier="LOCAL_PREFERRED",
             max_risk_level="PATCH_ALLOWED", preferred_task_types=["SUMMARIZATION"],
             privacy_class="LOCAL_ONLY")
    d.update(o); return d

def _bundle(**o):
    d = dict(bundle_id="B1", created_at="2026-07-09T00:00:00+00:00", created_by="mso",
             delegation_packet=_packet(), workers=[_worker()], requested_preview_id="", audit_notes="demo")
    d.update(o); return d

def test_valid_bundle_produces_preview():
    p = build_preview_from_bundle(load_bundle_from_dict(_bundle()))
    assert p.preview_status == PreviewStatus.READY_FOR_REVIEW
    assert p.selected_worker_id == "W1" and p.handoff_id != ""

def test_cli_valid_exit_0(tmp_path, capsys):
    f = tmp_path / "b.json"; f.write_text(json.dumps(_bundle()), encoding="utf-8")
    assert main([str(f)]) == 0
    out = capsys.readouterr().out
    assert '"can_execute": false' in out and '"can_dispatch": false' in out

def test_cli_invalid_exit_1(tmp_path, capsys):
    f = tmp_path / "b.json"; f.write_text("{not json", encoding="utf-8")
    assert main([str(f)]) == 1
    out = capsys.readouterr().out
    assert '"ok": false' in out and '"can_dispatch": false' in out

def test_stdout_success_flags_false(tmp_path, capsys):
    f = tmp_path / "b.json"; f.write_text(json.dumps(_bundle()), encoding="utf-8")
    main([str(f)]); out = capsys.readouterr().out
    d = json.loads(out); assert d["can_execute"] is False and d["can_dispatch"] is False

def test_no_files_written(tmp_path):
    f = tmp_path / "b.json"; f.write_text(json.dumps(_bundle()), encoding="utf-8")
    before = set(os.listdir(tmp_path))
    build_preview_from_bundle(load_bundle_from_path(str(f)))
    main([str(f)])
    assert set(os.listdir(tmp_path)) == before

def test_invalid_worker_not_recommended():
    b = load_bundle_from_dict(_bundle(workers=[_worker(status="DISABLED")]))
    p = build_preview_from_bundle(b)
    assert p.preview_status == PreviewStatus.BLOCKED and p.handoff_id == ""

def test_empty_workers_no_unsafe_fallback():
    p = build_preview_from_bundle(load_bundle_from_dict(_bundle(workers=[])))
    assert p.preview_status == PreviewStatus.NO_ELIGIBLE_WORKER
    assert p.selected_worker_id == "" and p.handoff_id == ""

def test_invalid_packet_fails_closed():
    p = build_preview_from_bundle(load_bundle_from_dict(_bundle(delegation_packet=_packet(objective=""))))
    assert p.preview_status == PreviewStatus.INVALID_INPUT

def test_unknown_fields_fail_by_default():
    with pytest.raises(OrchestrationBundleError):
        load_bundle_from_dict(_bundle(surprise="x"))

def test_allow_unknown_warns():
    res = validate_bundle_source(_bundle(surprise="x"), strict_unknown=False)
    assert any("unknown field" in w for w in res["warnings"])
    assert res["ok"] is True

def test_secret_like_content_fails_without_leak(tmp_path):
    b = _bundle(); b["audit_notes"] = "api_key=" + SECRET
    with pytest.raises(OrchestrationBundleError) as ei:
        load_bundle_from_dict(b)
    assert SECRET not in str(ei.value)
    res = validate_bundle_source(b)
    assert res["ok"] is False and SECRET not in json.dumps(res)

def test_raw_oversized_content_fails():
    b = _bundle(); b["audit_notes"] = "x" * 5000
    with pytest.raises(OrchestrationBundleError):
        load_bundle_from_dict(b)

def test_json_stable_and_normalize():
    p = build_preview_from_bundle(load_bundle_from_dict(_bundle()))
    s = normalize_preview_to_json(p); json.loads(s)
    assert '"can_execute": false' in s

def test_determinism():
    a = build_preview_from_bundle(load_bundle_from_dict(_bundle())).to_dict()
    b = build_preview_from_bundle(load_bundle_from_dict(_bundle())).to_dict()
    a.pop("created_at"); b.pop("created_at")
    assert a == b

def test_no_token_or_capability_minting():
    import assistant_os.mso.orchestration_preview_io as m
    for name in dir(m):
        assert "token" not in name.lower() and "mint" not in name.lower()

def test_nonexistent_path_fails_closed():
    with pytest.raises(OrchestrationBundleError):
        load_bundle_from_path("nope/does-not-exist.json")

def test_shipped_example_bundle_builds_preview():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ex = os.path.join(here, "docs", "mission", "examples", "orchestration-preview-bundle.example.json")
    b = load_bundle_from_path(ex)
    p = build_preview_from_bundle(b)
    assert p.can_dispatch is False and p.can_execute is False
    assert p.preview_status in (PreviewStatus.READY_FOR_REVIEW, PreviewStatus.NEEDS_HUMAN_REVIEW)
