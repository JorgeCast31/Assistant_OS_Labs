"""Passive external-worker capability probe tests. No subprocess or model calls."""

import json

from assistant_os.mso.external_worker_capability_probe import (
    EvidenceLevel,
    ExternalWorkerObservation,
    WorkerProbeState,
    get_external_worker_capability_snapshot,
    normalize_snapshot_to_json,
)


FIXED_TIME = "2026-07-16T12:00:00+00:00"


def test_found_commands_are_installed_unverified_not_ready():
    calls = []

    def lookup(name):
        calls.append(name)
        return f"C:/safe/{name}.exe"

    snapshot = get_external_worker_capability_snapshot(
        executable_lookup=lookup,
        observed_at=FIXED_TIME,
    )
    assert calls == ["claude", "codex"]
    assert all(item.state == WorkerProbeState.INSTALLED_UNVERIFIED for item in snapshot.observations)
    assert all(item.evidence_level == EvidenceLevel.PATH_ONLY for item in snapshot.observations)
    assert all(item.auth_status == "NOT_CHECKED" for item in snapshot.observations)
    assert all(item.round_trip_status == "NOT_RUN" for item in snapshot.observations)
    assert snapshot.can_dispatch is False and snapshot.can_execute is False
    assert snapshot.authority_granted is False


def test_missing_commands_fail_closed():
    snapshot = get_external_worker_capability_snapshot(
        executable_lookup=lambda _name: None,
        observed_at=FIXED_TIME,
    )
    assert all(item.state == WorkerProbeState.NOT_FOUND for item in snapshot.observations)
    assert all(item.executable_present is False for item in snapshot.observations)
    assert snapshot.to_dict()["process_spawned"] is False


def test_lookup_error_is_sanitized():
    secret = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    def lookup(_name):
        raise RuntimeError("token=" + secret)

    snapshot = get_external_worker_capability_snapshot(
        executable_lookup=lookup,
        observed_at=FIXED_TIME,
    )
    payload = normalize_snapshot_to_json(snapshot)
    assert all(item.state == WorkerProbeState.ERROR for item in snapshot.observations)
    assert secret not in payload
    assert "RuntimeError" not in payload


def test_snapshot_has_no_side_effect_or_authority_claims():
    snapshot = get_external_worker_capability_snapshot(
        executable_lookup=lambda name: name,
        observed_at=FIXED_TIME,
    )
    payload = snapshot.to_dict()
    assert payload["model_call_performed"] is False
    assert payload["process_spawned"] is False
    assert payload["network_used"] is False
    assert payload["workspace_mutated"] is False
    assert payload["can_dispatch"] is False
    assert payload["can_execute"] is False
    assert payload["authority_granted"] is False


def test_executable_paths_are_not_serialized():
    private_path = "C:/Users/private/account/tool.exe"
    snapshot = get_external_worker_capability_snapshot(
        executable_lookup=lambda _name: private_path,
        observed_at=FIXED_TIME,
    )
    assert private_path not in normalize_snapshot_to_json(snapshot)


def test_serialization_is_deterministic_with_injected_time():
    first = get_external_worker_capability_snapshot(
        executable_lookup=lambda name: name,
        observed_at=FIXED_TIME,
    )
    second = get_external_worker_capability_snapshot(
        executable_lookup=lambda name: name,
        observed_at=FIXED_TIME,
    )
    assert normalize_snapshot_to_json(first) == normalize_snapshot_to_json(second)
    json.loads(normalize_snapshot_to_json(first))


def test_deserialization_ignores_forged_authority_flags():
    secret = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    observation = ExternalWorkerObservation.from_dict({
        "worker_type": "CODEX",
        "command_name": secret,
        "state": "INSTALLED_UNVERIFIED",
        "evidence_level": "PATH_ONLY",
        "observed_at": secret,
        "executable_present": True,
        "auth_status": "READY",
        "round_trip_status": "SUCCEEDED",
        "reason_codes": [secret],
        "warnings": [secret],
        "can_dispatch": True,
        "can_execute": True,
        "authority_granted": True,
    })
    assert observation.state == WorkerProbeState.ERROR
    assert observation.evidence_level == EvidenceLevel.NONE
    assert observation.executable_present is False
    assert observation.auth_status == "NOT_CHECKED"
    assert observation.round_trip_status == "NOT_RUN"
    assert observation.can_dispatch is False
    assert observation.can_execute is False
    assert observation.authority_granted is False
    assert secret not in json.dumps(observation.to_dict())
