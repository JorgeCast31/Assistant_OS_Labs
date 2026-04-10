"""Tests for the CODE API HTTP adapter."""

import sys
import json
import threading
import urllib.request
from pathlib import Path

import pytest

# Ensure project root is importable from tests
sys.path.insert(0, str(Path(__file__).parent.parent))


from assistant_os.api.code_api import (
    _validate_payload,
    _build_execution_id,
    _derive_execution_assessment,
    handle_execute,
    handle_review_execution,
    handle_get_execution,
    create_server,
    EXECUTIONS_ROOT,
)


# ---------------------------------------------------------------------------
# Unit tests — no server required
# ---------------------------------------------------------------------------


class TestValidatePayload:
    def test_valid_minimal(self, tmp_path):
        assert _validate_payload({"repo_path": str(tmp_path)}) is None

    def test_missing_repo_path(self):
        err = _validate_payload({})
        assert err is not None
        assert "repo_path" in err.lower()

    def test_empty_repo_path(self):
        err = _validate_payload({"repo_path": "   "})
        assert err is not None

    def test_invalid_test_spec_type(self, tmp_path):
        err = _validate_payload({"repo_path": str(tmp_path), "test_spec": "pytest"})
        assert err is not None
        assert "test_spec" in err.lower()

    def test_test_spec_missing_command(self, tmp_path):
        err = _validate_payload({"repo_path": str(tmp_path), "test_spec": {}})
        assert err is not None
        assert "command" in err.lower()

    def test_valid_with_test_spec(self, tmp_path):
        payload = {
            "repo_path": str(tmp_path),
            "test_spec": {"command": ["pytest", "-q"]},
        }
        assert _validate_payload(payload) is None


class TestBuildExecutionId:
    def test_uses_request_id(self):
        eid = _build_execution_id({"request_id": "wf-123"})
        assert "wf-123" in eid
        assert eid.startswith("n8n_")

    def test_generates_id_without_request_id(self):
        eid = _build_execution_id({})
        assert eid.startswith("n8n_")
        assert len(eid) > 5

    def test_sanitises_slashes(self):
        eid = _build_execution_id({"request_id": "a/b\\c"})
        assert "/" not in eid
        assert "\\" not in eid

    def test_sanitises_dotdot(self):
        eid = _build_execution_id({"request_id": "../escape"})
        assert ".." not in eid


class TestHandleExecute:
    """Tests handle_execute() — invokes the real Runner on tmp repos."""

    def test_missing_repo_path_returns_failed(self):
        result = handle_execute({})
        assert result["final_status"] == "failed"
        assert result["error"] is not None

    def test_nonexistent_repo_returns_failed(self):
        result = handle_execute({"repo_path": "/does/not/exist/at/all"})
        assert result["final_status"] == "failed"

    def test_valid_workspace_only_returns_needs_review(self, tmp_path):
        """A real empty repo with no changes or tests → needs_review."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("pass\n")

        result = handle_execute({"repo_path": str(repo)})

        # No test_spec, no changes → workspace ready → needs_review
        assert result["final_status"] in ("needs_review", "success", "failed")
        assert "execution_id" in result
        assert result["execution_id"].startswith("n8n_")

    def test_execution_id_in_response(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("pass\n")

        result = handle_execute({
            "repo_path": str(repo),
            "request_id": "smoke-001",
        })

        assert "smoke-001" in result["execution_id"]

    def test_result_has_all_required_fields(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "x.py").write_text("pass\n")

        result = handle_execute({"repo_path": str(repo)})

        for key in ("execution_id", "final_status", "summary",
                    "report_json_path", "report_md_path", "done_path", "error"):
            assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# HTTP integration tests — starts a real server on a random port
# ---------------------------------------------------------------------------


def _get_free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    """Start a real HTTP server on a free port; tear it down after the module."""
    port = _get_free_port()
    server = create_server(port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{port}"
    server.shutdown()


def _post(base_url: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base_url}/api/code/execute",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_health_endpoint(live_server):
    with urllib.request.urlopen(f"{live_server}/health") as resp:
        data = json.loads(resp.read())
    assert data["status"] == "ok"


def test_post_missing_repo_path_returns_200_failed(live_server):
    status, data = _post(live_server, {})
    assert status == 200
    assert data["final_status"] == "failed"


def test_post_invalid_json_returns_400(live_server):
    req = urllib.request.Request(
        f"{live_server}/api/code/execute",
        data=b"not json{{{",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 400


def test_post_unknown_endpoint_returns_404(live_server):
    req = urllib.request.Request(
        f"{live_server}/api/unknown",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 404


def test_post_real_execution(live_server, tmp_path):
    """Full HTTP round-trip: POST → Runner → JSON response."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("pass\n")

    payload = {
        "request_id": "http-test-001",
        "source": "pytest",
        "repo_path": str(repo),
    }

    status, data = _post(live_server, payload)

    assert status == 200
    assert data["execution_id"] == "n8n_http-test-001"
    assert data["final_status"] in ("success", "failed", "needs_review")
    assert data["report_json_path"] is not None
    assert Path(data["report_json_path"]).exists()


# ---------------------------------------------------------------------------
# Review System tests
# ---------------------------------------------------------------------------


def _make_exec_dir(executions_root, execution_id: str):
    """Create a minimal execution directory with metadata.json for testing."""
    exec_dir = executions_root / execution_id
    exec_dir.mkdir(parents=True, exist_ok=True)
    (exec_dir / "metadata.json").write_text(
        json.dumps({"execution_id": execution_id, "final_status": "needs_review"}),
        encoding="utf-8",
    )
    return exec_dir


class TestHandleReviewExecution:
    """Unit tests for handle_review_execution — no HTTP server needed."""

    def test_create_valid_review(self, tmp_path, monkeypatch):
        """Test 1: create a valid review → ok=True, review saved."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "exec-001")

        result = handle_review_execution(
            "exec-001",
            {"review_action": "approved", "reviewed_by": "jorge", "review_notes": "LGTM"},
        )

        assert result is not None
        assert result["ok"] is True
        review = result["review"]
        assert review["execution_id"] == "exec-001"
        assert review["review_action"] == "approved"
        assert review["reviewed_by"] == "jorge"
        assert review["review_notes"] == "LGTM"
        assert review["reviewed_at"]

        # Persisted on disk
        saved = json.loads((tmp_path / "exec-001" / "review.json").read_text())
        assert saved["review_action"] == "approved"
        assert saved["reviewed_by"] == "jorge"

    def test_overwrite_existing_review(self, tmp_path, monkeypatch):
        """Test 2: posting a second review overwrites the first."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "exec-002")

        handle_review_execution(
            "exec-002",
            {"review_action": "approved", "reviewed_by": "jorge"},
        )
        handle_review_execution(
            "exec-002",
            {"review_action": "rejected", "reviewed_by": "jorge", "review_notes": "needs work"},
        )

        saved = json.loads((tmp_path / "exec-002" / "review.json").read_text())
        assert saved["review_action"] == "rejected"
        assert saved["review_notes"] == "needs work"

    def test_nonexistent_execution_returns_none(self, tmp_path, monkeypatch):
        """Test 3: execution_id not found → returns None (→ 404)."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)

        result = handle_review_execution(
            "does-not-exist",
            {"review_action": "approved", "reviewed_by": "jorge"},
        )
        assert result is None

    def test_invalid_review_action_raises(self, tmp_path, monkeypatch):
        """Test 4: invalid review_action → ValueError (→ 400)."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "exec-003")

        with pytest.raises(ValueError, match="review_action"):
            handle_review_execution(
                "exec-003",
                {"review_action": "yolo", "reviewed_by": "jorge"},
            )

    def test_missing_reviewed_by_raises(self, tmp_path, monkeypatch):
        """reviewed_by is required → ValueError (→ 400)."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "exec-004")

        with pytest.raises(ValueError, match="reviewed_by"):
            handle_review_execution(
                "exec-004",
                {"review_action": "approved"},
            )

    def test_missing_review_action_raises(self, tmp_path, monkeypatch):
        """review_action is required → ValueError (→ 400)."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "exec-005")

        with pytest.raises(ValueError, match="review_action"):
            handle_review_execution(
                "exec-005",
                {"reviewed_by": "jorge"},
            )

    def test_needs_followup_action_valid(self, tmp_path, monkeypatch):
        """needs_followup is a valid review_action."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "exec-006")

        result = handle_review_execution(
            "exec-006",
            {"review_action": "needs_followup", "reviewed_by": "jorge"},
        )
        assert result["review"]["review_action"] == "needs_followup"


class TestGetExecutionReview:
    """Unit tests for handle_get_execution — review field integration."""

    def test_get_detail_includes_review_when_exists(self, tmp_path, monkeypatch):
        """Test 5: GET detail after review → review object included."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "exec-r01")

        handle_review_execution(
            "exec-r01",
            {"review_action": "approved", "reviewed_by": "jorge", "review_notes": "ok"},
        )

        detail = handle_get_execution("exec-r01")
        assert detail is not None
        assert detail["review"] is not None
        assert detail["review"]["review_action"] == "approved"
        assert detail["review"]["reviewed_by"] == "jorge"
        assert detail["review"]["review_notes"] == "ok"
        assert detail["review"]["execution_id"] == "exec-r01"

    def test_get_detail_review_null_when_no_review(self, tmp_path, monkeypatch):
        """Test 6: GET detail without any review → review: null."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "exec-r02")

        detail = handle_get_execution("exec-r02")
        assert detail is not None
        assert detail["review"] is None


class TestReviewStatus:
    """review_status is derived from review_action — separate from final_status."""

    def test_approved_maps_to_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "rs-001")
        handle_review_execution("rs-001", {"review_action": "approved", "reviewed_by": "jorge"})

        detail = handle_get_execution("rs-001")
        assert detail["review_status"] == "accepted"

    def test_rejected_maps_to_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "rs-002")
        handle_review_execution("rs-002", {"review_action": "rejected", "reviewed_by": "jorge"})

        detail = handle_get_execution("rs-002")
        assert detail["review_status"] == "rejected"

    def test_needs_followup_maps_to_pending_followup(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "rs-003")
        handle_review_execution("rs-003", {"review_action": "needs_followup", "reviewed_by": "jorge"})

        detail = handle_get_execution("rs-003")
        assert detail["review_status"] == "pending_followup"

    def test_no_review_gives_null_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "rs-004")

        detail = handle_get_execution("rs-004")
        assert detail["review_status"] is None

    def test_review_object_still_intact(self, tmp_path, monkeypatch):
        """review_status must not replace or alter the original review object."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        _make_exec_dir(tmp_path, "rs-005")
        handle_review_execution(
            "rs-005",
            {"review_action": "approved", "reviewed_by": "jorge", "review_notes": "looks good"},
        )

        detail = handle_get_execution("rs-005")
        assert detail["review_status"] == "accepted"
        # Original review object must be untouched
        assert detail["review"]["review_action"] == "approved"
        assert detail["review"]["reviewed_by"] == "jorge"
        assert detail["review"]["review_notes"] == "looks good"
        assert detail["review"]["execution_id"] == "rs-005"

    def test_final_status_unaffected_by_review(self, tmp_path, monkeypatch):
        """final_status in metadata is independent of review_status."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        exec_dir = _make_exec_dir(tmp_path, "rs-006")
        # Override metadata with an explicit final_status
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": "rs-006", "final_status": "needs_review"}),
            encoding="utf-8",
        )
        handle_review_execution("rs-006", {"review_action": "rejected", "reviewed_by": "jorge"})

        detail = handle_get_execution("rs-006")
        # System status is untouched
        assert detail["metadata"]["final_status"] == "needs_review"
        # Human decision is independent
        assert detail["review_status"] == "rejected"


class TestDeriveExecutionAssessment:
    """Unit tests for the pure _derive_execution_assessment helper."""

    # --- sprint-specified cases ---

    def test_success_accepted(self):
        assert _derive_execution_assessment("success", "accepted") == "accepted"

    def test_success_rejected(self):
        assert _derive_execution_assessment("success", "rejected") == "rejected_after_review"

    def test_success_pending_followup(self):
        assert _derive_execution_assessment("success", "pending_followup") == "awaiting_followup"

    def test_needs_review_no_review(self):
        assert _derive_execution_assessment("needs_review", None) == "awaiting_review"

    def test_failed_returns_failed(self):
        assert _derive_execution_assessment("failed", None) == "failed"

    def test_success_no_review(self):
        assert _derive_execution_assessment("success", None) == "completed_unreviewed"

    # --- failed overrides human decision ---

    def test_failed_with_accepted_still_failed(self):
        """System failure overrides human review — failed is terminal."""
        assert _derive_execution_assessment("failed", "accepted") == "failed"

    def test_failed_with_rejected_still_failed(self):
        assert _derive_execution_assessment("failed", "rejected") == "failed"

    # --- edge cases ---

    def test_needs_review_with_accepted(self):
        """Human accepted a needs_review run — assessment follows human decision."""
        assert _derive_execution_assessment("needs_review", "accepted") == "accepted"

    def test_needs_review_with_rejected(self):
        assert _derive_execution_assessment("needs_review", "rejected") == "rejected_after_review"

    def test_unknown_final_status(self):
        assert _derive_execution_assessment("unknown_status", None) == "unknown"

    def test_none_final_status(self):
        assert _derive_execution_assessment(None, None) == "unknown"

    def test_none_final_status_with_review(self):
        """If final_status is missing but human reviewed, human decision wins."""
        assert _derive_execution_assessment(None, "accepted") == "accepted"


class TestExecutionAssessmentInDetail:
    """Integration tests: execution_assessment in handle_get_execution output."""

    def _make_dir_with_status(self, root, eid: str, final_status: str):
        exec_dir = _make_exec_dir(root, eid)
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": eid, "final_status": final_status}),
            encoding="utf-8",
        )
        return exec_dir

    def test_success_accepted_in_detail(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_dir_with_status(tmp_path, "ea-001", "success")
        handle_review_execution("ea-001", {"review_action": "approved", "reviewed_by": "jorge"})
        detail = handle_get_execution("ea-001")
        assert detail["execution_assessment"] == "accepted"

    def test_success_rejected_in_detail(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_dir_with_status(tmp_path, "ea-002", "success")
        handle_review_execution("ea-002", {"review_action": "rejected", "reviewed_by": "jorge"})
        detail = handle_get_execution("ea-002")
        assert detail["execution_assessment"] == "rejected_after_review"

    def test_success_pending_followup_in_detail(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_dir_with_status(tmp_path, "ea-003", "success")
        handle_review_execution("ea-003", {"review_action": "needs_followup", "reviewed_by": "jorge"})
        detail = handle_get_execution("ea-003")
        assert detail["execution_assessment"] == "awaiting_followup"

    def test_needs_review_no_review_in_detail(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_dir_with_status(tmp_path, "ea-004", "needs_review")
        detail = handle_get_execution("ea-004")
        assert detail["execution_assessment"] == "awaiting_review"

    def test_failed_in_detail(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_dir_with_status(tmp_path, "ea-005", "failed")
        detail = handle_get_execution("ea-005")
        assert detail["execution_assessment"] == "failed"

    def test_success_no_review_in_detail(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_dir_with_status(tmp_path, "ea-006", "success")
        detail = handle_get_execution("ea-006")
        assert detail["execution_assessment"] == "completed_unreviewed"

    def test_review_status_still_intact(self, tmp_path, monkeypatch):
        """execution_assessment does not replace review_status."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_dir_with_status(tmp_path, "ea-007", "success")
        handle_review_execution("ea-007", {"review_action": "approved", "reviewed_by": "jorge"})
        detail = handle_get_execution("ea-007")
        assert detail["review_status"] == "accepted"
        assert detail["execution_assessment"] == "accepted"

    def test_final_status_still_intact(self, tmp_path, monkeypatch):
        """execution_assessment does not replace metadata.final_status."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_dir_with_status(tmp_path, "ea-008", "needs_review")
        handle_review_execution("ea-008", {"review_action": "rejected", "reviewed_by": "jorge"})
        detail = handle_get_execution("ea-008")
        assert detail["metadata"]["final_status"] == "needs_review"
        assert detail["review_status"] == "rejected"
        assert detail["execution_assessment"] == "rejected_after_review"


# ---------------------------------------------------------------------------
# HTTP integration tests for review endpoints
# ---------------------------------------------------------------------------


def _post_review(base_url: str, execution_id: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base_url}/api/code/executions/{execution_id}/review",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _get_detail(base_url: str, execution_id: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{base_url}/api/code/executions/{execution_id}",
        method="GET",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_http_review_not_found_returns_404(live_server):
    """POST review for non-existent execution → 404."""
    status, data = _post_review(
        live_server,
        "definitely-does-not-exist-zzz",
        {"review_action": "approved", "reviewed_by": "jorge"},
    )
    assert status == 404


def test_http_review_invalid_action_returns_400(live_server, tmp_path):
    """POST review with invalid review_action → 400."""
    import unittest.mock as mock
    # We need a real execution on disk — run one first
    repo = tmp_path / "rrepo"
    repo.mkdir()
    (repo / "main.py").write_text("pass\n")
    _, exec_data = _post(live_server, {"repo_path": str(repo), "request_id": "rev-bad-action"})
    eid = exec_data["execution_id"]

    status, data = _post_review(
        live_server, eid,
        {"review_action": "INVALID", "reviewed_by": "jorge"},
    )
    assert status == 400
    assert "error" in data


def test_http_review_create_and_get(live_server, tmp_path):
    """Create a review via HTTP then verify it appears in GET detail."""
    repo = tmp_path / "rrepo2"
    repo.mkdir()
    (repo / "main.py").write_text("pass\n")
    _, exec_data = _post(live_server, {"repo_path": str(repo), "request_id": "rev-integration"})
    eid = exec_data["execution_id"]

    # POST review
    status, rev_data = _post_review(
        live_server, eid,
        {"review_action": "needs_followup", "reviewed_by": "jorge", "review_notes": "check again"},
    )
    assert status == 200
    assert rev_data["ok"] is True
    assert rev_data["review"]["review_action"] == "needs_followup"
    assert rev_data["review"]["reviewed_by"] == "jorge"

    # GET detail — review should be present
    status2, detail = _get_detail(live_server, eid)
    assert status2 == 200
    assert detail["review"] is not None
    assert detail["review"]["review_action"] == "needs_followup"
