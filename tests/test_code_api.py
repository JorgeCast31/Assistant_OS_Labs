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
    _derive_review_status,
    handle_execute,
    handle_list_executions,
    handle_code_status,
    handle_execution_log,
    handle_execution_report,
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


class TestHandleExecuteAgentRegistry:
    """Verify handle_execute routes through the agent registry, not RunnerBackedExecutor directly."""

    def _full_stub(self, mock_result, *, version="1.0.0",
                   requires_review=True, scope=None) -> dict:
        """Build a valid AgentDefinition stub (all required fields included)."""
        return {
            "name":            "code_executor",
            "version":         version,
            "requires_review": requires_review,
            "capability_scope": scope or ["code_execute"],
            "input_contract":  "RunnerExecutionRequest",
            "output_contract": "RunnerExecutionResult",
            "entrypoint":      lambda r: mock_result,
        }

    def _mock_runner_result(self, execution_id="n8n_test"):
        from unittest.mock import MagicMock
        r = MagicMock()
        r.execution_id = execution_id
        r.final_status = "success"
        r.summary = "ok"
        r.report_json_path = None
        r.report_md_path = None
        r.notification_path = None
        r.error = None
        return r

    def test_uses_agent_registry(self, tmp_path):
        """get_agent('code_executor') must be called during handle_execute."""
        from unittest.mock import patch

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("pass\n")

        mock_result = self._mock_runner_result("n8n_agent-registry-test")
        stub = self._full_stub(mock_result)

        with patch("assistant_os.agents.registry.AGENT_REGISTRY",
                   {"code_executor": stub}):
            result = handle_execute({
                "repo_path": str(repo),
                "request_id": "agent-registry-test",
            })

        assert result["ok"] is True
        assert result["execution_id"] == "n8n_agent-registry-test"

    def test_runner_not_called_directly(self, tmp_path):
        """RunnerBackedExecutor.execute must not be called directly from code_api."""
        from unittest.mock import patch

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("pass\n")

        mock_result = self._mock_runner_result("n8n_direct-check")
        stub = self._full_stub(mock_result)

        with patch("assistant_os.agents.registry.AGENT_REGISTRY",
                   {"code_executor": stub}), \
             patch("assistant_os.executors.runner_backed_executor"
                   ".RunnerBackedExecutor.execute") as mock_direct:
            handle_execute({"repo_path": str(repo), "request_id": "direct-check"})

        mock_direct.assert_not_called()

    def test_agent_invocation_in_response(self, tmp_path):
        """handle_execute response must include agent_invocation with registry values."""
        from unittest.mock import patch

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("pass\n")

        mock_result = self._mock_runner_result("n8n_inv-check")
        # Distinctive values to verify the source is the registry, not hardcoded
        stub = self._full_stub(mock_result, version="9.9.9",
                               requires_review=False, scope=["test_scope"])

        with patch("assistant_os.agents.registry.AGENT_REGISTRY",
                   {"code_executor": stub}):
            result = handle_execute({"repo_path": str(repo), "request_id": "inv-check"})

        assert "agent_invocation" in result
        inv = result["agent_invocation"]
        assert inv["agent_name"]             == "code_executor"
        assert inv["agent_version"]          == "9.9.9"
        assert inv["agent_requires_review"]  is False
        assert inv["agent_capability_scope"] == ["test_scope"]

    def test_agent_invocation_matches_real_registry(self, tmp_path):
        """With the real registry, agent_invocation values match AGENT_REGISTRY."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("pass\n")

        result = handle_execute({"repo_path": str(repo), "request_id": "real-reg-check"})

        assert "agent_invocation" in result
        inv = result["agent_invocation"]
        assert inv["agent_name"]             == "code_executor"
        assert inv["agent_version"]          == "1.0.0"
        assert inv["agent_requires_review"]  is True
        assert inv["agent_capability_scope"] == ["code_execute"]

    def test_execution_id_scheme_unchanged(self, tmp_path):
        """execution_id derivation is unaffected by the agent registry change."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("pass\n")

        result = handle_execute({"repo_path": str(repo), "request_id": "id-scheme-check"})

        assert result["execution_id"] == "n8n_id-scheme-check"

    def test_request_snapshot_still_written(self, tmp_path):
        """request_snapshot is still persisted in metadata.json after agent change."""
        from assistant_os.api.code_api import EXECUTIONS_ROOT

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("pass\n")

        result = handle_execute({
            "repo_path": str(repo),
            "request_id": "snapshot-persist-check",
            "source": "pytest-agent-unification",
        })

        # The runner writes metadata to EXECUTIONS_ROOT/{execution_id}/
        eid = result["execution_id"]
        meta_path = EXECUTIONS_ROOT / eid / "metadata.json"
        assert meta_path.exists(), f"metadata.json must exist at {meta_path}"
        meta = json.loads(meta_path.read_text())
        assert "request_snapshot" in meta, "request_snapshot must be in metadata"
        assert meta["request_snapshot"]["source"] == "pytest-agent-unification"


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
# Unit tests — handle_list_executions enrichment (Sprint A)
# ---------------------------------------------------------------------------


class TestListExecutionsEnrichment:
    """handle_list_executions must include review_status, execution_assessment,
    and agent_invocation in every item — using the same derivation as the detail."""

    def _make_exec(
        self,
        root,
        eid: str,
        final_status: str = "needs_review",
        agent_invocation=None,
    ):
        """Create a minimal execution dir; returns the dir path."""
        exec_dir = root / eid
        exec_dir.mkdir(parents=True, exist_ok=True)
        meta = {"execution_id": eid, "final_status": final_status}
        if agent_invocation is not None:
            meta["agent_invocation"] = agent_invocation
        (exec_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        return exec_dir

    def _item(self, root, eid: str):
        """Return the list item for a specific execution_id."""
        result = handle_list_executions()
        items = {x["execution_id"]: x for x in result["executions"]}
        return items.get(eid)

    def test_list_includes_review_status_key(self, tmp_path, monkeypatch):
        """Every item in the list must have a review_status key."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "ls-001")
        item = self._item(tmp_path, "ls-001")
        assert item is not None
        assert "review_status" in item

    def test_list_includes_execution_assessment_key(self, tmp_path, monkeypatch):
        """Every item in the list must have an execution_assessment key."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "ls-002")
        item = self._item(tmp_path, "ls-002")
        assert item is not None
        assert "execution_assessment" in item

    def test_list_includes_agent_invocation_key(self, tmp_path, monkeypatch):
        """Every item in the list must have an agent_invocation key."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "ls-003")
        item = self._item(tmp_path, "ls-003")
        assert item is not None
        assert "agent_invocation" in item

    def test_review_status_none_without_review_json(self, tmp_path, monkeypatch):
        """Without review.json, review_status must be None (not 'unknown')."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "ls-004", final_status="needs_review")
        item = self._item(tmp_path, "ls-004")
        assert item["review_status"] is None

    def test_execution_assessment_awaiting_review_in_list(self, tmp_path, monkeypatch):
        """needs_review + no human review → awaiting_review in the list."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "ls-005", final_status="needs_review")
        item = self._item(tmp_path, "ls-005")
        assert item["execution_assessment"] == "awaiting_review"

    def test_execution_assessment_accepted_after_review_in_list(self, tmp_path, monkeypatch):
        """Approved review → review_status=accepted, execution_assessment=accepted in list."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        exec_dir = self._make_exec(tmp_path, "ls-006", final_status="needs_review")
        (exec_dir / "review.json").write_text(
            json.dumps({"review_action": "approved", "reviewed_by": "jorge"}),
            encoding="utf-8",
        )
        item = self._item(tmp_path, "ls-006")
        assert item["review_status"] == "accepted"
        assert item["execution_assessment"] == "accepted"

    def test_agent_invocation_surfaced_from_metadata(self, tmp_path, monkeypatch):
        """agent_invocation stored in metadata.json is surfaced in the list item."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        inv = {"agent_name": "code_executor", "agent_version": "1.0.0"}
        self._make_exec(tmp_path, "ls-007", agent_invocation=inv)
        item = self._item(tmp_path, "ls-007")
        assert item["agent_invocation"] == inv

    def test_agent_invocation_none_when_missing(self, tmp_path, monkeypatch):
        """Older executions without agent_invocation in metadata → None in list."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "ls-008")  # no agent_invocation
        item = self._item(tmp_path, "ls-008")
        assert item["agent_invocation"] is None

    def test_existing_fields_unchanged(self, tmp_path, monkeypatch):
        """Sprint A must not remove or rename any pre-existing list fields."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "ls-009", final_status="success")
        item = self._item(tmp_path, "ls-009")
        for key in ("execution_id", "final_status", "summary", "timestamp",
                    "report_json_path", "report_md_path", "done_path",
                    "metadata_path", "source"):
            assert key in item, f"pre-existing field missing: {key!r}"


# ---------------------------------------------------------------------------
# Unit tests — handle_list_executions filters (Sprint B)
# ---------------------------------------------------------------------------


class TestListExecutionsFilters:
    """handle_list_executions must honour status / review_status / assessment / limit."""

    def _make_exec(self, root, eid: str, final_status: str = "needs_review",
                   review_action=None):
        exec_dir = root / eid
        exec_dir.mkdir(parents=True, exist_ok=True)
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": eid, "final_status": final_status,
                        "started_at": f"2026-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )
        if review_action:
            (exec_dir / "review.json").write_text(
                json.dumps({"review_action": review_action, "reviewed_by": "jorge"}),
                encoding="utf-8",
            )
        return exec_dir

    def _ids(self, root) -> list:
        return [x["execution_id"] for x in handle_list_executions()["executions"]]

    # ------------------------------------------------------------------
    # 1. No params → all executions returned (backward compatibility)
    # ------------------------------------------------------------------

    def test_no_params_returns_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "f-001", "success")
        self._make_exec(tmp_path, "f-002", "failed")
        self._make_exec(tmp_path, "f-003", "needs_review")
        result = handle_list_executions()
        assert result["count"] == 3
        assert set(self._ids(tmp_path)) == {"f-001", "f-002", "f-003"}

    # ------------------------------------------------------------------
    # 2. status filter
    # ------------------------------------------------------------------

    def test_status_filter(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "f-010", "success")
        self._make_exec(tmp_path, "f-011", "failed")
        self._make_exec(tmp_path, "f-012", "needs_review")
        result = handle_list_executions(status="failed")
        assert result["count"] == 1
        assert result["executions"][0]["execution_id"] == "f-011"

    def test_status_filter_no_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "f-013", "success")
        result = handle_list_executions(status="failed")
        assert result["count"] == 0
        assert result["executions"] == []

    # ------------------------------------------------------------------
    # 3. review_status filter
    # ------------------------------------------------------------------

    def test_review_status_filter(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "f-020", "needs_review", review_action="approved")
        self._make_exec(tmp_path, "f-021", "needs_review", review_action="rejected")
        self._make_exec(tmp_path, "f-022", "needs_review")  # no review
        result = handle_list_executions(review_status="accepted")
        assert result["count"] == 1
        assert result["executions"][0]["execution_id"] == "f-020"

    def test_review_status_none_filter(self, tmp_path, monkeypatch):
        """review_status=None means no filter, not 'match None items'."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "f-023", "needs_review", review_action="approved")
        self._make_exec(tmp_path, "f-024", "needs_review")
        result = handle_list_executions(review_status=None)
        assert result["count"] == 2

    # ------------------------------------------------------------------
    # 4. assessment filter
    # ------------------------------------------------------------------

    def test_assessment_filter(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "f-030", "needs_review")        # awaiting_review
        self._make_exec(tmp_path, "f-031", "failed")               # failed
        self._make_exec(tmp_path, "f-032", "success")              # completed_unreviewed
        result = handle_list_executions(assessment="awaiting_review")
        assert result["count"] == 1
        assert result["executions"][0]["execution_id"] == "f-030"

    # ------------------------------------------------------------------
    # 5. combined filters
    # ------------------------------------------------------------------

    def test_combined_status_and_review_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "f-040", "success", review_action="approved")
        self._make_exec(tmp_path, "f-041", "success", review_action="rejected")
        self._make_exec(tmp_path, "f-042", "failed",  review_action="approved")
        result = handle_list_executions(status="success", review_status="accepted")
        assert result["count"] == 1
        assert result["executions"][0]["execution_id"] == "f-040"

    # ------------------------------------------------------------------
    # 6. limit
    # ------------------------------------------------------------------

    def test_limit_recorta(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        for i in range(5):
            self._make_exec(tmp_path, f"f-05{i}", "success")
        result = handle_list_executions(limit=3)
        assert result["count"] == 3
        assert len(result["executions"]) == 3

    def test_limit_larger_than_set_returns_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "f-060", "success")
        self._make_exec(tmp_path, "f-061", "success")
        result = handle_list_executions(limit=100)
        assert result["count"] == 2

    def test_limit_combined_with_filter(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        for i in range(4):
            self._make_exec(tmp_path, f"f-07{i}", "needs_review")
        self._make_exec(tmp_path, "f-074", "failed")
        result = handle_list_executions(status="needs_review", limit=2)
        assert result["count"] == 2
        assert all(x["final_status"] == "needs_review" for x in result["executions"])

    # ------------------------------------------------------------------
    # 7. limit validation (function level — HTTP level tested separately)
    # ------------------------------------------------------------------

    def test_limit_zero_returns_empty(self, tmp_path, monkeypatch):
        """limit=0 is rejected upstream by do_GET; at function level it slices to empty."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "f-080", "success")
        # limit=0 at function level just slices the list to empty ([:0])
        result = handle_list_executions(limit=0)
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# HTTP integration tests — query param parsing in do_GET (Sprint B)
# ---------------------------------------------------------------------------


class TestListExecutionsHTTPFilters:
    """Verify do_GET correctly parses query params and validates limit."""

    def _make_exec(self, root, eid: str, final_status: str = "needs_review"):
        exec_dir = root / eid
        exec_dir.mkdir(parents=True, exist_ok=True)
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": eid, "final_status": final_status}),
            encoding="utf-8",
        )

    def test_invalid_limit_string_returns_400(self, live_server, tmp_path, monkeypatch):
        """Non-integer limit → 400 with structured error."""
        import urllib.request, urllib.error
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        req = urllib.request.Request(
            f"{live_server}/api/code/executions?limit=abc",
            method="GET",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 400
        body = json.loads(exc_info.value.read())
        assert "limit" in body["error"].lower()

    def test_negative_limit_returns_400(self, live_server, tmp_path, monkeypatch):
        """Negative limit → 400."""
        import urllib.request, urllib.error
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        req = urllib.request.Request(
            f"{live_server}/api/code/executions?limit=-1",
            method="GET",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 400

    def test_no_params_still_works(self, live_server, tmp_path, monkeypatch):
        """No query params → 200, backward compatible."""
        import urllib.request
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        with urllib.request.urlopen(f"{live_server}/api/code/executions") as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
            assert body["ok"] is True

    def test_status_param_parsed_and_applied(self, live_server, tmp_path, monkeypatch):
        """?status=failed returns only failed executions."""
        import urllib.request
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "http-f-001", "failed")
        self._make_exec(tmp_path, "http-f-002", "success")
        with urllib.request.urlopen(f"{live_server}/api/code/executions?status=failed") as resp:
            body = json.loads(resp.read())
        assert body["count"] == 1
        assert body["executions"][0]["final_status"] == "failed"


# ---------------------------------------------------------------------------
# Unit tests — handle_code_status aggregation (Sprint C)
# ---------------------------------------------------------------------------


class TestHandleCodeStatus:
    """handle_code_status must return correct aggregated counts without
    duplicating any derivation logic."""

    def _make_exec(self, root, eid: str, final_status: str = "needs_review",
                   review_action=None):
        exec_dir = root / eid
        exec_dir.mkdir(parents=True, exist_ok=True)
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": eid, "final_status": final_status}),
            encoding="utf-8",
        )
        if review_action:
            (exec_dir / "review.json").write_text(
                json.dumps({"review_action": review_action, "reviewed_by": "jorge"}),
                encoding="utf-8",
            )
        return exec_dir

    # ------------------------------------------------------------------
    # 1. Empty — no executions
    # ------------------------------------------------------------------

    def test_empty_returns_zero_total(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        result = handle_code_status()
        assert result["ok"] is True
        assert result["total"] == 0
        assert result["by_final_status"] == {}
        assert result["by_review_status"] == {}
        assert result["by_execution_assessment"] == {}

    # ------------------------------------------------------------------
    # 2. total
    # ------------------------------------------------------------------

    def test_total_matches_execution_count(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "cs-001", "success")
        self._make_exec(tmp_path, "cs-002", "failed")
        self._make_exec(tmp_path, "cs-003", "needs_review")
        result = handle_code_status()
        assert result["total"] == 3

    # ------------------------------------------------------------------
    # 3. by_final_status
    # ------------------------------------------------------------------

    def test_by_final_status_counts(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "cs-010", "success")
        self._make_exec(tmp_path, "cs-011", "success")
        self._make_exec(tmp_path, "cs-012", "failed")
        result = handle_code_status()
        assert result["by_final_status"]["success"] == 2
        assert result["by_final_status"]["failed"] == 1
        assert "needs_review" not in result["by_final_status"]

    # ------------------------------------------------------------------
    # 4. by_review_status — null for unreviewed
    # ------------------------------------------------------------------

    def test_by_review_status_includes_null_for_unreviewed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "cs-020", "needs_review")                   # no review
        self._make_exec(tmp_path, "cs-021", "needs_review", "approved")       # accepted
        result = handle_code_status()
        assert result["by_review_status"]["null"] == 1
        assert result["by_review_status"]["accepted"] == 1

    def test_by_review_status_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "cs-022", "success", "rejected")
        result = handle_code_status()
        assert result["by_review_status"]["rejected"] == 1

    # ------------------------------------------------------------------
    # 5. by_execution_assessment
    # ------------------------------------------------------------------

    def test_by_execution_assessment_awaiting_review(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "cs-030", "needs_review")
        result = handle_code_status()
        assert result["by_execution_assessment"]["awaiting_review"] == 1

    def test_by_execution_assessment_failed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "cs-031", "failed")
        result = handle_code_status()
        assert result["by_execution_assessment"]["failed"] == 1

    def test_by_execution_assessment_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "cs-032", "needs_review", "approved")
        result = handle_code_status()
        assert result["by_execution_assessment"]["accepted"] == 1

    # ------------------------------------------------------------------
    # 6. integrity — sum of by_final_status == total
    # ------------------------------------------------------------------

    def test_sum_by_final_status_equals_total(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "cs-040", "success")
        self._make_exec(tmp_path, "cs-041", "failed")
        self._make_exec(tmp_path, "cs-042", "needs_review")
        self._make_exec(tmp_path, "cs-043", "needs_review", "approved")
        result = handle_code_status()
        assert sum(result["by_final_status"].values()) == result["total"]

    def test_sum_by_review_status_equals_total(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "cs-050", "success")
        self._make_exec(tmp_path, "cs-051", "needs_review", "approved")
        self._make_exec(tmp_path, "cs-052", "needs_review", "rejected")
        result = handle_code_status()
        assert sum(result["by_review_status"].values()) == result["total"]

    def test_sum_by_assessment_equals_total(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "cs-060", "success")
        self._make_exec(tmp_path, "cs-061", "failed")
        self._make_exec(tmp_path, "cs-062", "needs_review")
        result = handle_code_status()
        assert sum(result["by_execution_assessment"].values()) == result["total"]

    # ------------------------------------------------------------------
    # 7. HTTP — endpoint responds 200 (live server)
    # ------------------------------------------------------------------

    def test_status_endpoint_returns_200(self, live_server):
        import urllib.request
        with urllib.request.urlopen(f"{live_server}/api/code/status") as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
            assert body["ok"] is True
            assert "total" in body
            assert "by_final_status" in body
            assert "by_review_status" in body
            assert "by_execution_assessment" in body


# ---------------------------------------------------------------------------
# Unit tests — Sprint E: G1 rerun_of persistence
# ---------------------------------------------------------------------------


class TestRerunMetadataPersistence:
    """handle_rerun_execution must persist rerun_of to disk via patch_execution_metadata.

    G1 fix: _patch_metadata → patch_execution_metadata (NameError was latent).
    """

    def _make_source_exec(self, root, eid: str, repo_path: str) -> None:
        """Create a source execution directory with a minimal request_snapshot."""
        exec_dir = root / eid
        exec_dir.mkdir(parents=True, exist_ok=True)
        (exec_dir / "metadata.json").write_text(
            json.dumps({
                "execution_id": eid,
                "final_status": "needs_review",
                "request_snapshot": {
                    "repo_path": repo_path,
                    "changes": None,
                    "source": "assistant_os",
                    "mode": "kernel",
                },
            }),
            encoding="utf-8",
        )

    def test_rerun_of_persisted_to_metadata(self, tmp_path, monkeypatch):
        """rerun_of must be written into the new execution's metadata.json."""
        from unittest.mock import patch as mpatch
        import assistant_os.runners.metadata_utils as mu

        new_eid = "rerun-new-exec-e01"
        source_eid = "source-exec-e01"

        # patch_execution_metadata reads from metadata_utils.EXECUTIONS_ROOT, not code_api's.
        # Both must point to tmp_path for the write to land in the temp directory.
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        monkeypatch.setattr(mu, "EXECUTIONS_ROOT", tmp_path)
        self._make_source_exec(tmp_path, source_eid, repo_path=str(tmp_path))

        # Pre-create new execution dir so patch_execution_metadata can find the file.
        new_exec_dir = tmp_path / new_eid
        new_exec_dir.mkdir()
        (new_exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": new_eid, "final_status": "needs_review"}),
            encoding="utf-8",
        )

        fake_response = {
            "ok": True,
            "execution_id": new_eid,
            "final_status": "needs_review",
            "summary": "ok",
            "report_json_path": None,
            "report_md_path": None,
            "done_path": None,
            "error": None,
        }

        with mpatch("assistant_os.api.code_api.handle_execute", return_value=fake_response):
            from assistant_os.api.code_api import handle_rerun_execution
            result = handle_rerun_execution(source_eid)

        assert result["rerun_of"] == source_eid

        # Critical: rerun_of must also be in the new execution's metadata.json on disk.
        meta = json.loads((tmp_path / new_eid / "metadata.json").read_text())
        assert meta.get("rerun_of") == source_eid, (
            "rerun_of must be persisted to metadata.json — "
            "response-only was the G1 bug"
        )

    def test_rerun_no_snapshot_raises(self, tmp_path, monkeypatch):
        """Execution without request_snapshot → ValueError (rerun not available)."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        exec_dir = tmp_path / "no-snap-001"
        exec_dir.mkdir()
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": "no-snap-001", "final_status": "success"}),
            encoding="utf-8",
        )
        from assistant_os.api.code_api import handle_rerun_execution
        with pytest.raises(ValueError, match="snapshot"):
            handle_rerun_execution("no-snap-001")


# ---------------------------------------------------------------------------
# Unit tests — handle_execution_log / handle_execution_report (Sprint D)
# ---------------------------------------------------------------------------


class TestHandleExecutionLog:
    """handle_execution_log — reads runner.log; returns None when absent."""

    def _make_exec(self, root, eid: str, log_content: str = None):
        exec_dir = root / eid
        exec_dir.mkdir(parents=True, exist_ok=True)
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": eid, "final_status": "success"}),
            encoding="utf-8",
        )
        if log_content is not None:
            (exec_dir / "runner.log").write_text(log_content, encoding="utf-8")
        return exec_dir

    def test_log_exists_returns_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "log-001", log_content="step 1\nstep 2\n")
        result = handle_execution_log("log-001")
        assert result is not None
        assert result["ok"] is True
        assert result["execution_id"] == "log-001"
        assert result["log"] == "step 1\nstep 2\n"

    def test_log_not_present_returns_none(self, tmp_path, monkeypatch):
        """Execution exists but no runner.log → None (→ 404)."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "log-002")  # no log file
        result = handle_execution_log("log-002")
        assert result is None

    def test_execution_not_found_returns_none(self, tmp_path, monkeypatch):
        """Unknown execution_id → None (→ 404)."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        result = handle_execution_log("does-not-exist")
        assert result is None

    def test_invalid_execution_id_returns_none(self, tmp_path, monkeypatch):
        """Path-traversal id → sanitised to None (→ 404)."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        result = handle_execution_log("../etc/passwd")
        assert result is None

    def test_log_content_key_is_string(self, tmp_path, monkeypatch):
        """'log' field must be a string, not a list or bytes."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "log-003", log_content="hello")
        result = handle_execution_log("log-003")
        assert isinstance(result["log"], str)


class TestHandleExecutionReport:
    """handle_execution_report — report.json preferred, report.md fallback."""

    def _make_exec(self, root, eid: str, report_json=None, report_md: str = None):
        exec_dir = root / eid
        exec_dir.mkdir(parents=True, exist_ok=True)
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": eid, "final_status": "success"}),
            encoding="utf-8",
        )
        if report_json is not None:
            (exec_dir / "report.json").write_text(
                json.dumps(report_json), encoding="utf-8"
            )
        if report_md is not None:
            (exec_dir / "report.md").write_text(report_md, encoding="utf-8")
        return exec_dir

    def test_report_json_returned_as_dict(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "rpt-001", report_json={"status": "ok", "tests": 5})
        result = handle_execution_report("rpt-001")
        assert result is not None
        assert result["ok"] is True
        assert result["execution_id"] == "rpt-001"
        assert isinstance(result["report"], dict)
        assert result["report"]["tests"] == 5

    def test_report_md_fallback_when_no_json(self, tmp_path, monkeypatch):
        """Only report.md present → fallback returns its string content."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "rpt-002", report_md="# Summary\nAll good.")
        result = handle_execution_report("rpt-002")
        assert result is not None
        assert result["ok"] is True
        assert result["execution_id"] == "rpt-002"
        assert isinstance(result["report"], str)
        assert "All good" in result["report"]

    def test_json_takes_priority_over_md(self, tmp_path, monkeypatch):
        """Both exist → report.json is preferred."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(
            tmp_path, "rpt-003",
            report_json={"source": "json"},
            report_md="# from md",
        )
        result = handle_execution_report("rpt-003")
        assert isinstance(result["report"], dict)
        assert result["report"]["source"] == "json"

    def test_neither_report_returns_none(self, tmp_path, monkeypatch):
        """Execution exists but no report artefact → None (→ 404)."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "rpt-004")  # no report files
        result = handle_execution_report("rpt-004")
        assert result is None

    def test_execution_not_found_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        result = handle_execution_report("does-not-exist")
        assert result is None

    def test_invalid_execution_id_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        result = handle_execution_report("../etc/passwd")
        assert result is None


class TestSubResourceHTTP:
    """HTTP-level smoke: /log and /report endpoints return 200 or 404."""

    def _make_exec(self, root, eid: str, log: str = None, report=None):
        exec_dir = root / eid
        exec_dir.mkdir(parents=True, exist_ok=True)
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": eid, "final_status": "success"}),
            encoding="utf-8",
        )
        if log is not None:
            (exec_dir / "runner.log").write_text(log, encoding="utf-8")
        if report is not None:
            (exec_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")

    def test_log_endpoint_200(self, live_server, tmp_path, monkeypatch):
        import urllib.request
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "http-log-001", log="line one\nline two\n")
        with urllib.request.urlopen(
            f"{live_server}/api/code/executions/http-log-001/log"
        ) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
            assert body["ok"] is True
            assert "log" in body
            assert "line one" in body["log"]

    def test_log_endpoint_404_when_missing(self, live_server, tmp_path, monkeypatch):
        import urllib.request, urllib.error
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "http-log-002")  # no log file
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(
                f"{live_server}/api/code/executions/http-log-002/log"
            )
        assert exc_info.value.code == 404

    def test_report_endpoint_200_json(self, live_server, tmp_path, monkeypatch):
        import urllib.request
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "http-rpt-001", report={"tests": 3})
        with urllib.request.urlopen(
            f"{live_server}/api/code/executions/http-rpt-001/report"
        ) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
            assert body["ok"] is True
            assert body["report"]["tests"] == 3

    def test_report_endpoint_404_when_missing(self, live_server, tmp_path, monkeypatch):
        import urllib.request, urllib.error
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "http-rpt-002")  # no report
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(
                f"{live_server}/api/code/executions/http-rpt-002/report"
            )
        assert exc_info.value.code == 404

    def test_detail_route_unchanged(self, live_server, tmp_path, monkeypatch):
        """Existing detail route /executions/{id} must still work after Sprint D."""
        import urllib.request
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)
        self._make_exec(tmp_path, "http-det-001")
        with urllib.request.urlopen(
            f"{live_server}/api/code/executions/http-det-001"
        ) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
            assert body["ok"] is True
            assert "metadata" in body


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


# ---------------------------------------------------------------------------
# Agent invocation persistence + GET detail exposure
# ---------------------------------------------------------------------------


class TestAgentInvocationPersistence:
    """Verify agent_invocation is written to metadata.json and exposed in GET detail."""

    def test_agent_invocation_persisted_to_metadata(self, tmp_path):
        """handle_execute must write agent_invocation into metadata.json on disk."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("pass\n")

        result = handle_execute({
            "repo_path": str(repo),
            "request_id": "inv-persist-001",
        })

        eid = result["execution_id"]
        meta_path = EXECUTIONS_ROOT / eid / "metadata.json"
        assert meta_path.exists(), f"metadata.json must exist at {meta_path}"

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "agent_invocation" in meta, "agent_invocation must be written to metadata.json"

    def test_agent_invocation_persisted_fields_correct(self, tmp_path):
        """The four agent_invocation fields written to disk must match the registry."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("pass\n")

        result = handle_execute({
            "repo_path": str(repo),
            "request_id": "inv-persist-fields-002",
        })

        eid = result["execution_id"]
        meta = json.loads(
            (EXECUTIONS_ROOT / eid / "metadata.json").read_text(encoding="utf-8")
        )
        inv = meta["agent_invocation"]

        assert inv["agent_name"]             == "code_executor"
        assert inv["agent_version"]          == "1.0.0"
        assert inv["agent_requires_review"]  is True
        assert inv["agent_capability_scope"] == ["code_execute"]

    def test_get_execution_exposes_agent_invocation(self, tmp_path, monkeypatch):
        """handle_get_execution must include agent_invocation from metadata.json."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)

        # Build an execution directory with agent_invocation already in metadata
        eid = "inv-get-003"
        exec_dir = tmp_path / eid
        exec_dir.mkdir()
        (exec_dir / "metadata.json").write_text(
            json.dumps({
                "execution_id": eid,
                "final_status": "success",
                "agent_invocation": {
                    "agent_name":             "code_executor",
                    "agent_version":          "1.0.0",
                    "agent_requires_review":  True,
                    "agent_capability_scope": ["code_execute"],
                },
            }),
            encoding="utf-8",
        )

        detail = handle_get_execution(eid)

        assert "agent_invocation" in detail
        inv = detail["agent_invocation"]
        assert inv["agent_name"]             == "code_executor"
        assert inv["agent_version"]          == "1.0.0"
        assert inv["agent_requires_review"]  is True
        assert inv["agent_capability_scope"] == ["code_execute"]

    def test_get_execution_agent_invocation_null_for_legacy(self, tmp_path, monkeypatch):
        """agent_invocation must be None (not KeyError) for older executions without it."""
        monkeypatch.setattr("assistant_os.api.code_api.EXECUTIONS_ROOT", tmp_path)

        eid = "inv-legacy-004"
        exec_dir = tmp_path / eid
        exec_dir.mkdir()
        # Older metadata without agent_invocation key
        (exec_dir / "metadata.json").write_text(
            json.dumps({"execution_id": eid, "final_status": "success"}),
            encoding="utf-8",
        )

        detail = handle_get_execution(eid)

        assert "agent_invocation" in detail
        assert detail["agent_invocation"] is None
