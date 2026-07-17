"""Tests for Mission Inbox / Preview Index v0. Read-only; no execution/writes/moves."""
import json, os
import pytest
from assistant_os.mso.mission_inbox_index import (
    MissionInboxError, InboxRecordStatus, scan_inbox, scan_bundle_file,
    normalize_index_to_json, index_to_dict, main)

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

def _write(tmp, name, obj):
    p = tmp / name
    p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")
    return p

def test_valid_inbox_produces_index(tmp_path):
    _write(tmp_path, "a.preview-bundle.json", _bundle())
    idx = scan_inbox(str(tmp_path))
    assert idx.total_files == 1 and idx.valid_bundles == 1 and idx.invalid_bundles == 0
    assert idx.records[0].status == InboxRecordStatus.VALID_PREVIEW
    assert idx.records[0].recommended_worker_id == "W1"

def test_cli_stdout_parses_json(tmp_path, capsys):
    _write(tmp_path, "a.preview-bundle.json", _bundle())
    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.lstrip().startswith("{")
    d = json.loads(out)
    assert d["can_execute"] is False and d["can_dispatch"] is False

def test_flags_false_in_index_and_records(tmp_path):
    _write(tmp_path, "a.preview-bundle.json", _bundle())
    idx = scan_inbox(str(tmp_path)); d = idx.to_dict()
    assert d["can_execute"] is False and d["can_dispatch"] is False
    assert all(r["can_execute"] is False and r["can_dispatch"] is False for r in d["records"])

def test_nonexistent_path_exit_1(tmp_path, capsys):
    assert main([str(tmp_path / "nope")]) == 1
    d = json.loads(capsys.readouterr().out)
    assert d["ok"] is False and d["can_dispatch"] is False

def test_scan_inbox_raises_on_bad_path():
    with pytest.raises(MissionInboxError):
        scan_inbox("this/does/not/exist-xyz")

def test_invalid_file_does_not_break_index(tmp_path):
    _write(tmp_path, "a.preview-bundle.json", _bundle())
    _write(tmp_path, "b.preview-bundle.json", "{not json")
    idx = scan_inbox(str(tmp_path))
    statuses = {r.source_path.split(os.sep)[-1]: r.status for r in idx.records}
    assert statuses["a.preview-bundle.json"] == InboxRecordStatus.VALID_PREVIEW
    assert statuses["b.preview-bundle.json"] == InboxRecordStatus.INVALID_BUNDLE
    assert idx.valid_bundles == 1 and idx.invalid_bundles == 1

def test_empty_workers_no_unsafe_fallback(tmp_path):
    _write(tmp_path, "a.preview-bundle.json", _bundle(workers=[]))
    idx = scan_inbox(str(tmp_path))
    assert idx.records[0].status == InboxRecordStatus.NO_ELIGIBLE_WORKER
    assert idx.records[0].recommended_worker_id == ""

def test_explicit_target_reaches_inbox_without_cross_worker_fallback(tmp_path):
    packet = _packet(target_worker="CLAUDE_CODE")
    codex = _worker(worker_id="A-CODEX", worker_type="CODEX")
    claude = _worker(worker_id="Z-CLAUDE", worker_type="CLAUDE_CODE")
    _write(tmp_path, "a.preview-bundle.json", _bundle(
        delegation_packet=packet, workers=[codex, claude]))
    idx = scan_inbox(str(tmp_path))
    assert idx.records[0].recommended_worker_id == "Z-CLAUDE"

    _write(tmp_path, "a.preview-bundle.json", _bundle(
        delegation_packet=packet, workers=[codex]))
    idx = scan_inbox(str(tmp_path))
    assert idx.records[0].status == InboxRecordStatus.NO_ELIGIBLE_WORKER
    assert idx.records[0].recommended_worker_id == ""

def test_invalid_worker_not_eligible(tmp_path):
    _write(tmp_path, "a.preview-bundle.json", _bundle(workers=[_worker(status="DISABLED")]))
    idx = scan_inbox(str(tmp_path))
    assert idx.records[0].status == InboxRecordStatus.BLOCKED

def test_secret_content_fails_without_leak(tmp_path):
    b = _bundle(); b["audit_notes"] = "api_key=" + SECRET
    _write(tmp_path, "a.preview-bundle.json", b)
    idx = scan_inbox(str(tmp_path))
    assert idx.records[0].status == InboxRecordStatus.INVALID_BUNDLE
    assert SECRET not in normalize_index_to_json(idx)

def test_unsupported_file_skipped(tmp_path):
    _write(tmp_path, "a.preview-bundle.json", _bundle())
    _write(tmp_path, "notes.txt", "hello")
    _write(tmp_path, "plain.json", _bundle())
    idx = scan_inbox(str(tmp_path))
    skipped = [r for r in idx.records if r.status == InboxRecordStatus.SKIPPED_UNSUPPORTED_FILE]
    names = {r.source_path.split(os.sep)[-1] for r in skipped}
    assert names == {"notes.txt", "plain.json"}
    assert idx.total_files == 3 and idx.valid_bundles == 1

def test_deterministic_order_by_filename(tmp_path):
    _write(tmp_path, "b.preview-bundle.json", _bundle(bundle_id="BB"))
    _write(tmp_path, "a.preview-bundle.json", _bundle(bundle_id="AA"))
    idx = scan_inbox(str(tmp_path))
    order = [r.source_path.split(os.sep)[-1] for r in idx.records]
    assert order == ["a.preview-bundle.json", "b.preview-bundle.json"]

def test_no_writes_or_moves(tmp_path):
    _write(tmp_path, "a.preview-bundle.json", _bundle())
    before = sorted(os.listdir(tmp_path))
    scan_inbox(str(tmp_path)); main([str(tmp_path)])
    assert sorted(os.listdir(tmp_path)) == before

def test_json_stable_roundtrip(tmp_path):
    _write(tmp_path, "a.preview-bundle.json", _bundle())
    idx = scan_inbox(str(tmp_path))
    s = normalize_index_to_json(idx); json.loads(s)
    assert index_to_dict(idx) == idx.to_dict()

def test_allow_unknown_flag(tmp_path):
    b = _bundle(); b["surprise"] = "x"
    _write(tmp_path, "a.preview-bundle.json", b)
    strict = scan_inbox(str(tmp_path))
    assert strict.records[0].status == InboxRecordStatus.INVALID_BUNDLE
    lax = scan_inbox(str(tmp_path), strict_unknown=False)
    assert lax.records[0].status in (InboxRecordStatus.VALID_PREVIEW, InboxRecordStatus.NEEDS_HUMAN_REVIEW)

def test_no_token_or_capability_minting():
    import assistant_os.mso.mission_inbox_index as m
    for name in dir(m):
        assert "token" not in name.lower() and "mint" not in name.lower()

def test_shipped_example_inbox(tmp_path):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    inbox = os.path.join(here, "docs", "mission", "inbox")
    idx = scan_inbox(inbox)
    assert idx.can_execute is False and idx.can_dispatch is False
    assert idx.total_files >= 1
