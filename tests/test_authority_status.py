from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from assistant_os.mso.authority_status import get_authority_status


def _row(
    domain: str,
    action: str,
    mode: str,
    *,
    allowed: bool = True,
    notes: str = "",
):
    return type(
        "CapabilityRecordLike",
        (),
        {
            "domain": domain,
            "action": action,
            "mode": mode,
            "allowed": allowed,
            "notes": notes,
        },
    )()


def _grant(domain: str, action: str):
    return type("GrantLike", (), {"domain": domain, "action": action})()


def _revocation(domain: str, action: str):
    return type("RevocationLike", (), {"domain": domain, "action": action})()


def test_get_authority_status_has_expected_source() -> None:
    status = get_authority_status()
    assert status["source"] == "authority_status"


def test_get_authority_status_is_json_serializable() -> None:
    status = get_authority_status()
    json.dumps(status)


def test_includes_known_code_capabilities_from_registry() -> None:
    status = get_authority_status()
    assert any(row["domain"] == "CODE" for row in status["capabilities"])


def test_counts_total_allow_confirm_only_deny_blocked_from_mocked_data() -> None:
    mocked_caps = [
        _row("CODE", "CODE_EXPLAIN", "allow", allowed=True),
        _row("CODE", "CODE_FIX", "confirm_only", allowed=True),
        _row("WORK", "WORK_DELETE", "deny", allowed=False),
        _row("HOST", "HOST_X", "blocked", allowed=False),
    ]
    with (
        patch("assistant_os.mso.authority_status.list_registered_capabilities", return_value=mocked_caps),
        patch("assistant_os.mso.authority_status.list_temporary_grants", return_value=[]),
        patch("assistant_os.mso.authority_status.list_active_revocations", return_value=[]),
    ):
        status = get_authority_status()

    counts = status["counts"]
    assert counts["total"] == 4
    assert counts["allow"] == 1
    assert counts["confirm_only"] == 1
    assert counts["deny"] == 1
    assert counts["blocked"] == 2


def test_active_revocation_marks_row_revoked() -> None:
    mocked_caps = [_row("CODE", "CODE_FIX", "confirm_only", allowed=True)]
    with (
        patch("assistant_os.mso.authority_status.list_registered_capabilities", return_value=mocked_caps),
        patch("assistant_os.mso.authority_status.list_temporary_grants", return_value=[]),
        patch("assistant_os.mso.authority_status.list_active_revocations", return_value=[_revocation("CODE", "CODE_FIX")]),
    ):
        status = get_authority_status()

    row = status["capabilities"][0]
    assert row["active_revocation"] is True
    assert row["effective_posture"] == "revoked"


def test_active_grant_marks_temporarily_granted_unless_revoked() -> None:
    mocked_caps = [_row("CODE", "CODE_FIX", "confirm_only", allowed=True)]
    with (
        patch("assistant_os.mso.authority_status.list_registered_capabilities", return_value=mocked_caps),
        patch("assistant_os.mso.authority_status.list_temporary_grants", return_value=[_grant("CODE", "CODE_FIX")]),
        patch("assistant_os.mso.authority_status.list_active_revocations", return_value=[]),
    ):
        status = get_authority_status()

    row = status["capabilities"][0]
    assert row["active_grant"] is True
    assert row["effective_posture"] == "temporarily_granted"


def test_revocation_overrides_grant() -> None:
    mocked_caps = [_row("CODE", "CODE_FIX", "allow", allowed=True)]
    with (
        patch("assistant_os.mso.authority_status.list_registered_capabilities", return_value=mocked_caps),
        patch("assistant_os.mso.authority_status.list_temporary_grants", return_value=[_grant("CODE", "CODE_FIX")]),
        patch("assistant_os.mso.authority_status.list_active_revocations", return_value=[_revocation("CODE", "CODE_FIX")]),
    ):
        status = get_authority_status()

    assert status["capabilities"][0]["effective_posture"] == "revoked"


def test_confirm_only_maps_to_requires_confirmation() -> None:
    mocked_caps = [_row("WORK", "WORK_CREATE", "confirm_only", allowed=True)]
    with (
        patch("assistant_os.mso.authority_status.list_registered_capabilities", return_value=mocked_caps),
        patch("assistant_os.mso.authority_status.list_temporary_grants", return_value=[]),
        patch("assistant_os.mso.authority_status.list_active_revocations", return_value=[]),
    ):
        status = get_authority_status()

    assert status["capabilities"][0]["effective_posture"] == "requires_confirmation"


def test_allow_maps_to_allowed_by_registry() -> None:
    mocked_caps = [_row("WORK", "WORK_QUERY", "allow", allowed=True)]
    with (
        patch("assistant_os.mso.authority_status.list_registered_capabilities", return_value=mocked_caps),
        patch("assistant_os.mso.authority_status.list_temporary_grants", return_value=[]),
        patch("assistant_os.mso.authority_status.list_active_revocations", return_value=[]),
    ):
        status = get_authority_status()

    assert status["capabilities"][0]["effective_posture"] == "allowed_by_registry"


def test_denied_or_allowed_false_maps_to_blocked_by_registry() -> None:
    mocked_caps = [_row("UNKNOWN", "COMMAND", "deny", allowed=False)]
    with (
        patch("assistant_os.mso.authority_status.list_registered_capabilities", return_value=mocked_caps),
        patch("assistant_os.mso.authority_status.list_temporary_grants", return_value=[]),
        patch("assistant_os.mso.authority_status.list_active_revocations", return_value=[]),
    ):
        status = get_authority_status()

    assert status["capabilities"][0]["effective_posture"] == "blocked_by_registry"


def test_fail_soft_on_registry_read_exception() -> None:
    with patch("assistant_os.mso.authority_status.list_registered_capabilities", side_effect=RuntimeError("boom")):
        status = get_authority_status()

    assert status["source"] == "authority_status"
    assert status["capabilities"] == []
    assert status["counts"]["total"] == 0
    assert "error" in status
    assert "does not grant execution permission" in status["note"]


def test_does_not_call_governance_policy_orchestrator_runner_modules() -> None:
    source = Path("assistant_os/mso/authority_status.py").read_text(encoding="utf-8")
    for forbidden_module in (
        "governance_engine",
        "policy_engine",
        "orchestrator",
        "runner",
    ):
        assert forbidden_module not in source


def test_does_not_expose_forbidden_fields() -> None:
    status = get_authority_status()
    dumped = json.dumps(status).lower()
    for forbidden in (
        "execution_mode",
        "policy_decision",
        "governance_verdict",
        "approved",
        "authorized",
        "safe_to_apply",
        "ready_to_execute",
        "token",
        "signature",
    ):
        assert forbidden not in dumped


def test_does_not_mutate_registry_no_grant_or_revoke_calls() -> None:
    mocked_caps = [_row("WORK", "WORK_QUERY", "allow", allowed=True)]
    with (
        patch("assistant_os.mso.authority_status.list_registered_capabilities", return_value=mocked_caps),
        patch("assistant_os.mso.authority_status.list_temporary_grants", return_value=[]),
        patch("assistant_os.mso.authority_status.list_active_revocations", return_value=[]),
        patch("assistant_os.mso.capability_registry.grant_temporary_capability", side_effect=AssertionError("must not mutate grants")),
        patch("assistant_os.mso.capability_registry.revoke_capability", side_effect=AssertionError("must not mutate revocations")),
    ):
        status = get_authority_status()

    assert status["counts"]["total"] == 1
