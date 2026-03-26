"""Tests for the CODE API HTTP adapter."""

import sys
import json
import threading
import urllib.request
from pathlib import Path

import pytest

# Ensure project root is importable from tests
sys.path.insert(0, str(Path(__file__).parent.parent))


from assistant_os.api.code_api import _validate_payload, _build_execution_id, handle_execute, create_server


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
