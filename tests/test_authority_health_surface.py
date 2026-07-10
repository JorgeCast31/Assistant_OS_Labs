"""Tests for Authority/Health Surface v0.

Contract, safety and fail-soft guarantees. These tests use dependency
injection (``probes=``) so they never depend on external services and never
execute anything.
"""

import json

from assistant_os.mso import authority_health as ah


def _probe(name, status, detail="d", extra=None):
    def _fn():
        return ah._check(name, status, detail, extra=extra)
    _fn.__name__ = f"probe_{name}"
    return _fn


ALL_GO_CRITICALS = (
    _probe("police_available", ah.GO),
    _probe("policy_enforcement", ah.GO),
    _probe("capability_path", ah.GO),
)


def test_snapshot_is_json_serializable():
    snap = ah.get_authority_health_snapshot()
    json.dumps(snap)  # must not raise
    assert snap["surface"] == "authority_health"
    assert snap["version"] == "v0"
    assert "generated_at" in snap
    assert isinstance(snap["checks"], list)


def test_authority_and_execution_flags_are_hard_false():
    snap = ah.get_authority_health_snapshot()
    assert snap["can_execute_now"] is False
    assert snap["execution_allowed"] is False
    assert snap["authority_granted"] is False
    assert snap["read_only"] is True
    assert snap["observer"] is True
    assert snap["runner_available"] is False
    assert snap["durable_queue_present"] is False
    assert snap["backend_deploy_enabled"] is False


def test_every_check_status_is_in_vocabulary():
    snap = ah.get_authority_health_snapshot()
    for c in snap["checks"]:
        assert c["status"] in (ah.GO, ah.AMBER, ah.STOP, ah.NO_VERIFICADO), c


def test_all_go_criticals_plus_amber_yields_amber():
    probes = ALL_GO_CRITICALS + (_probe("runner_execution", ah.AMBER),)
    snap = ah.get_authority_health_snapshot(probes=probes)
    assert snap["overall"] == ah.AMBER


def test_all_go_yields_go():
    probes = ALL_GO_CRITICALS + (_probe("extra", ah.GO),)
    snap = ah.get_authority_health_snapshot(probes=probes)
    assert snap["overall"] == ah.GO


def test_missing_critical_is_never_reported_as_go():
    probes = (
        _probe("police_available", ah.STOP),
        _probe("policy_enforcement", ah.GO),
        _probe("capability_path", ah.GO),
    )
    snap = ah.get_authority_health_snapshot(probes=probes)
    assert snap["overall"] == ah.STOP
    assert snap["overall"] != ah.GO
    assert any(b["check"] == "police_available" for b in snap["blockers"])


def test_unverifiable_critical_degrades_to_no_verificado_not_go():
    probes = (
        _probe("police_available", ah.NO_VERIFICADO),
        _probe("policy_enforcement", ah.GO),
        _probe("capability_path", ah.GO),
    )
    snap = ah.get_authority_health_snapshot(probes=probes)
    assert snap["overall"] == ah.NO_VERIFICADO
    assert snap["overall"] != ah.GO


def test_stop_dominates_overall():
    probes = ALL_GO_CRITICALS + (_probe("something", ah.STOP),)
    snap = ah.get_authority_health_snapshot(probes=probes)
    assert snap["overall"] == ah.STOP


def test_genuine_no_verificado_still_dominates_over_amber():
    probes = ALL_GO_CRITICALS + (
        _probe("runner_execution", ah.AMBER),
        _probe("some_unprobeable", ah.NO_VERIFICADO),
    )
    snap = ah.get_authority_health_snapshot(probes=probes)
    assert snap["overall"] == ah.NO_VERIFICADO


def test_default_backend_identity_is_never_stop():
    row = ah.probe_backend_identity()
    assert row["status"] in (ah.GO, ah.AMBER)


def test_probe_exception_is_failsoft_and_marked_no_verificado():
    def boom():
        raise RuntimeError("kaboom")
    boom.__name__ = "probe_boom"
    snap = ah.get_authority_health_snapshot(probes=ALL_GO_CRITICALS + (boom,))
    rows = [c for c in snap["checks"] if c["check"] == "probe_boom"]
    assert rows and rows[0]["status"] == ah.NO_VERIFICADO


def test_malformed_probe_result_coerced_to_no_verificado():
    def bad():
        return {"no_status": True}
    bad.__name__ = "probe_bad"
    snap = ah.get_authority_health_snapshot(probes=ALL_GO_CRITICALS + (bad,))
    rows = [c for c in snap["checks"] if c["check"] == "probe_bad"]
    assert rows and rows[0]["status"] == ah.NO_VERIFICADO


def test_no_env_values_leak_into_snapshot(monkeypatch):
    sentinel = "SUPER_SECRET_VALUE_XYZ_should_never_appear"
    monkeypatch.setenv("ANTHROPIC_API_KEY", sentinel)
    monkeypatch.setenv("NOTION_TOKEN", sentinel)
    snap = ah.get_authority_health_snapshot()
    blob = json.dumps(snap)
    assert sentinel not in blob
    assert snap["env_presence"]["ANTHROPIC_API_KEY"] is True


def test_repeated_calls_are_structurally_identical():
    a = ah.get_authority_health_snapshot(probes=ALL_GO_CRITICALS)
    b = ah.get_authority_health_snapshot(probes=ALL_GO_CRITICALS)
    a.pop("generated_at")
    b.pop("generated_at")
    assert a == b
