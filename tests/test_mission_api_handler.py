import json
import threading
import urllib.error
import urllib.request

import pytest

from assistant_os.api.mission_api import MissionAPIHandler, create_server
from assistant_os.missions.service import MissionRegistry


def _registry_with_mission() -> tuple[MissionRegistry, str]:
    registry = MissionRegistry()
    mission = registry.open_mission(
        macro_goal="Serve mission state.",
        title="HTTP Mission",
        created_by="test",
        source_surface="unit",
    )
    return registry, mission.mission_id


@pytest.fixture
def mission_api() -> tuple[str, str]:
    registry, mission_id = _registry_with_mission()
    server = create_server(port=0, store=registry.store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", mission_id
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _get_json(base_url: str, path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(f"{base_url}{path}", timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_handler_has_no_non_get_http_methods() -> None:
    for method_name in ("do_POST", "do_PUT", "do_PATCH", "do_DELETE"):
        assert method_name not in MissionAPIHandler.__dict__


def test_health_returns_service(mission_api: tuple[str, str]) -> None:
    base_url, _mission_id = mission_api

    status, body = _get_json(base_url, "/health")

    assert status == 200
    assert body["service"] == "mission_api"


def test_list_missions_returns_missions(mission_api: tuple[str, str]) -> None:
    base_url, _mission_id = mission_api

    status, body = _get_json(base_url, "/api/missions")

    assert status == 200
    assert body["ok"] is True
    assert len(body["missions"]) == 1


def test_get_known_mission_returns_mission(mission_api: tuple[str, str]) -> None:
    base_url, mission_id = mission_api

    status, body = _get_json(base_url, f"/api/missions/{mission_id}")

    assert status == 200
    assert body["mission"]["mission_id"] == mission_id


def test_get_known_mission_events_returns_events(mission_api: tuple[str, str]) -> None:
    base_url, mission_id = mission_api

    status, body = _get_json(base_url, f"/api/missions/{mission_id}/events")

    assert status == 200
    assert body["mission_id"] == mission_id
    assert body["count"] == 1


def test_get_unknown_mission_returns_404(mission_api: tuple[str, str]) -> None:
    base_url, _mission_id = mission_api

    status, body = _get_json(base_url, "/api/missions/unknown")

    assert status == 404
    assert body["ok"] is False


def test_get_unknown_mission_events_returns_404(mission_api: tuple[str, str]) -> None:
    base_url, _mission_id = mission_api

    status, body = _get_json(base_url, "/api/missions/unknown/events")

    assert status == 404
    assert body["ok"] is False


def test_unknown_path_returns_404(mission_api: tuple[str, str]) -> None:
    base_url, _mission_id = mission_api

    status, body = _get_json(base_url, "/api/nope")

    assert status == 404
    assert body["ok"] is False


def test_non_get_methods_not_implemented_by_handler_class() -> None:
    method_names = {name for name in MissionAPIHandler.__dict__ if name.startswith("do_")}

    assert method_names == {"do_GET"}


def test_create_server_requires_explicit_store() -> None:
    with pytest.raises(TypeError):
        create_server(port=0)  # type: ignore[call-arg]
