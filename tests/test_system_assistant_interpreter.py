"""Tests for assistant_os.system_assistant.interpreter.

Verifies:
1. healthy snapshot -> healthy interpretation
2. partial snapshot with warnings -> partial interpretation
3. unavailable snapshot -> unavailable interpretation
4. operational_mode None does not become NORMAL
5. warnings are preserved verbatim
6. interpretation has narrative=True
7. interpretation has no forbidden authority fields
8. interpretation does not include execution trigger / command / pipeline target
9. interpreter does not call observe_system automatically
10. interpreter is pure: same input -> same output
11. governance observations appear and carry correct qualifiers
"""

from __future__ import annotations

import unittest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _healthy_snapshot() -> dict:
    return {
        "generated_at": "2026-04-29T00:00:00+00:00",
        "status": "ok",
        "operational_mode": "RESTRICTED",
        "agents": [
            {"name": "code_executor", "domain": "CODE", "version": "1.0.0",
             "description": "Executes CODE proposals.", "capability_scope": ["code_execute"]},
        ],
        "capabilities": [
            {"action": "code_execute", "domain": "CODE", "mode": "allow", "allowed": True},
        ],
        "tasks_summary": {"active": 1, "completed": 3},
        "warnings": [],
    }


def _partial_snapshot() -> dict:
    return {
        "generated_at": "2026-04-29T00:00:00+00:00",
        "status": "partial",
        "operational_mode": None,
        "agents": [],
        "capabilities": [],
        "tasks_summary": {},
        "warnings": ["agents source unavailable: registry error"],
    }


def _unavailable_snapshot() -> dict:
    return {
        "generated_at": "2026-04-29T00:00:00+00:00",
        "status": "unavailable",
        "operational_mode": None,
        "agents": [],
        "capabilities": [],
        "tasks_summary": {},
        "warnings": [
            "operational_mode source unavailable: error",
            "agents source unavailable: error",
            "capabilities source unavailable: error",
            "tasks source unavailable: error",
        ],
    }


def _snapshot_with_governance() -> dict:
    return {
        "generated_at": "2026-05-01T00:00:00+00:00",
        "status": "ok",
        "operational_mode": "NORMAL",
        "agents": [],
        "capabilities": [],
        "tasks_summary": {},
        "warnings": [],
        "governance_status_summary": {
            "source": "mso_governance_status",
            "operational_mode": "NORMAL",
            "operational_mode_source": "derived",
            "hardened_domain_count": 1,
            "active_revocation_count": 0,
            "active_grant_count": 0,
            "recent_anomaly_count": 0,
            "ephemeral": True,
            "note": "Governance status is operational runtime state, not MSO activity or health.",
        },
        "recent_governance": [
            {
                "governance_ref": "G-001",
                "created_at": "2026-01-01T00:00:00+00:00",
                "action": "BLOCK",
                "target_domain": "ENERGY",
                "target_action": "COMMAND",
                "risk_level": "high",
                "operational_mode": "NORMAL",
                "effective_execution_mode": "blocked",
                "reason": "anomaly detected",
            }
        ],
    }


def _snapshot_no_governance() -> dict:
    return {
        "generated_at": "2026-05-01T00:00:00+00:00",
        "status": "ok",
        "operational_mode": "NORMAL",
        "agents": [],
        "capabilities": [],
        "tasks_summary": {},
        "warnings": [],
    }


def _snapshot_empty_recent_governance() -> dict:
    return {
        "generated_at": "2026-05-01T00:00:00+00:00",
        "status": "ok",
        "operational_mode": "NORMAL",
        "agents": [],
        "capabilities": [],
        "tasks_summary": {},
        "warnings": [],
        "governance_status_summary": {
            "source": "mso_governance_status",
            "operational_mode": "NORMAL",
            "operational_mode_source": "derived",
            "hardened_domain_count": 0,
            "active_revocation_count": 0,
            "active_grant_count": 0,
            "recent_anomaly_count": 0,
            "ephemeral": True,
            "note": "Governance status is operational runtime state, not MSO activity or health.",
        },
        "recent_governance": [],
    }


# ---------------------------------------------------------------------------
# 1. healthy snapshot -> healthy interpretation
# ---------------------------------------------------------------------------

class TestHealthySnapshot(unittest.TestCase):
    def test_status_is_healthy(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_healthy_snapshot())
        self.assertEqual(result["status"], "healthy")

    def test_summary_is_non_empty_string(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_healthy_snapshot())
        self.assertIsInstance(result["summary"], str)
        self.assertGreater(len(result["summary"]), 0)

    def test_observations_is_list(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_healthy_snapshot())
        self.assertIsInstance(result["observations"], list)

    def test_warnings_empty_for_healthy(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_healthy_snapshot())
        self.assertEqual(result["warnings"], [])


# ---------------------------------------------------------------------------
# 2. partial snapshot with warnings -> partial interpretation
# ---------------------------------------------------------------------------

class TestPartialSnapshot(unittest.TestCase):
    def test_status_is_partial_when_snapshot_partial(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_partial_snapshot())
        self.assertEqual(result["status"], "partial")

    def test_status_is_partial_when_warnings_exist(self) -> None:
        """snapshot.status == 'ok' but has warnings -> interpretation is partial."""
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        snap = _healthy_snapshot()
        snap["warnings"] = ["something failed"]
        result = interpret_system_snapshot(snap)
        self.assertEqual(result["status"], "partial")

    def test_partial_snapshot_has_summary(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_partial_snapshot())
        self.assertIsInstance(result["summary"], str)
        self.assertGreater(len(result["summary"]), 0)


# ---------------------------------------------------------------------------
# 3. unavailable snapshot -> unavailable interpretation
# ---------------------------------------------------------------------------

class TestUnavailableSnapshot(unittest.TestCase):
    def test_status_is_unavailable(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_unavailable_snapshot())
        self.assertEqual(result["status"], "unavailable")

    def test_unavailable_has_summary(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_unavailable_snapshot())
        self.assertIsInstance(result["summary"], str)
        self.assertGreater(len(result["summary"]), 0)


# ---------------------------------------------------------------------------
# 4. operational_mode None does not become NORMAL
# ---------------------------------------------------------------------------

class TestOperationalModeNone(unittest.TestCase):
    def test_none_mode_not_reported_as_normal(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        snap = _partial_snapshot()  # mode is None
        result = interpret_system_snapshot(snap)
        # observations and summary must not claim mode is NORMAL
        all_text = " ".join(result.get("observations", [])) + " " + result.get("summary", "")
        # Should not assert NORMAL when mode is None
        self.assertNotIn("NORMAL", all_text.upper().replace("ABNORMAL", ""))

    def test_none_mode_produces_unknown_or_not_set_observation(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        snap = _partial_snapshot()  # mode is None
        result = interpret_system_snapshot(snap)
        all_text = " ".join(result.get("observations", [])) + " " + result.get("summary", "")
        # Some form of "not set", "unknown", "no override", "unavailable" should appear
        lower = all_text.lower()
        self.assertTrue(
            any(word in lower for word in ("not set", "unknown", "no override", "unavailable", "not overridden")),
            f"Expected indication that mode is unknown/not set, got: {all_text!r}",
        )

    def test_known_mode_appears_in_observation(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        snap = _healthy_snapshot()  # mode is "RESTRICTED"
        result = interpret_system_snapshot(snap)
        all_text = " ".join(result.get("observations", [])) + " " + result.get("summary", "")
        self.assertIn("RESTRICTED", all_text)


# ---------------------------------------------------------------------------
# 5. warnings preserved verbatim
# ---------------------------------------------------------------------------

class TestWarningsPreserved(unittest.TestCase):
    def test_warnings_passed_through_verbatim(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        snap = _partial_snapshot()
        result = interpret_system_snapshot(snap)
        self.assertEqual(result["warnings"], snap["warnings"])

    def test_multiple_warnings_all_preserved(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        snap = _unavailable_snapshot()
        result = interpret_system_snapshot(snap)
        self.assertEqual(result["warnings"], snap["warnings"])


# ---------------------------------------------------------------------------
# 6. narrative=True
# ---------------------------------------------------------------------------

class TestNarrativeFlag(unittest.TestCase):
    def test_narrative_is_true(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        for snap in (_healthy_snapshot(), _partial_snapshot(), _unavailable_snapshot()):
            with self.subTest(status=snap["status"]):
                result = interpret_system_snapshot(snap)
                self.assertIs(result["narrative"], True)


# ---------------------------------------------------------------------------
# 7. source and execution_status fields
# ---------------------------------------------------------------------------

class TestRequiredMetaFields(unittest.TestCase):
    def test_source_is_system_assistant(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_healthy_snapshot())
        self.assertEqual(result["source"], "system_assistant")

    def test_execution_status_is_none(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_healthy_snapshot())
        self.assertIsNone(result["execution_status"])


# ---------------------------------------------------------------------------
# 7b. No forbidden authority fields
# ---------------------------------------------------------------------------

class TestNoForbiddenAuthorityFields(unittest.TestCase):
    FORBIDDEN_KEYS = (
        "execution_mode",
        "GovernanceVerdict",
        "governance_verdict",
        "PolicyDecision",
        "policy_decision",
    )

    def test_no_forbidden_keys_in_result(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        for snap in (_healthy_snapshot(), _partial_snapshot(), _unavailable_snapshot()):
            with self.subTest(status=snap["status"]):
                result = interpret_system_snapshot(snap)
                for key in self.FORBIDDEN_KEYS:
                    self.assertNotIn(key, result, f"Forbidden key {key!r} found in interpretation")


# ---------------------------------------------------------------------------
# 8. No execution trigger / command / pipeline target in result
# ---------------------------------------------------------------------------

class TestNoExecutionTrigger(unittest.TestCase):
    FORBIDDEN_KEYS = ("pipeline_target", "command", "callable", "authorization_recommendation")

    def test_no_execution_trigger_keys(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_healthy_snapshot())
        for key in self.FORBIDDEN_KEYS:
            self.assertNotIn(key, result, f"Forbidden execution key {key!r} found in interpretation")


# ---------------------------------------------------------------------------
# 9. Interpreter does not call observe_system automatically
# ---------------------------------------------------------------------------

class TestInterpreterDoesNotCallObserver(unittest.TestCase):
    def test_observe_system_not_called(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        with patch("assistant_os.system_assistant.observer.observe_system") as obs_mock:
            interpret_system_snapshot(_healthy_snapshot())
        obs_mock.assert_not_called()


# ---------------------------------------------------------------------------
# 10. Interpreter is pure: same input -> same output
# ---------------------------------------------------------------------------

class TestInterpreterIsPure(unittest.TestCase):
    def test_same_input_same_output(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        snap = _healthy_snapshot()
        result_a = interpret_system_snapshot(snap)
        result_b = interpret_system_snapshot(snap)
        self.assertEqual(result_a, result_b)

    def test_does_not_mutate_input_snapshot(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        snap = _healthy_snapshot()
        import copy
        snap_copy = copy.deepcopy(snap)
        interpret_system_snapshot(snap)
        self.assertEqual(snap, snap_copy)


# ---------------------------------------------------------------------------
# Additional: agents/capabilities/tasks exposed as counts only
# ---------------------------------------------------------------------------

class TestCountsOnly(unittest.TestCase):
    def test_agents_not_copied_verbatim_into_observations(self) -> None:
        """Observations must summarise as counts, not echo raw agent dicts."""
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_healthy_snapshot())
        for obs in result.get("observations", []):
            self.assertNotIsInstance(obs, dict)

    def test_observations_are_strings(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_healthy_snapshot())
        for obs in result.get("observations", []):
            self.assertIsInstance(obs, str)


# ---------------------------------------------------------------------------
# 11. Governance observations
# ---------------------------------------------------------------------------

class TestGovernanceObservations(unittest.TestCase):
    def test_governance_status_observation_appears(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_snapshot_with_governance())
        all_text = " ".join(result["observations"])
        self.assertIn("Governance status:", all_text)
        self.assertIn("NORMAL", all_text)
        self.assertIn("derived", all_text)

    def test_governance_status_observation_contains_qualifier(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_snapshot_with_governance())
        all_text = " ".join(result["observations"])
        self.assertIn("not MSO activity or health", all_text)

    def test_governance_no_summary_does_not_crash(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_snapshot_no_governance())
        self.assertIsInstance(result["observations"], list)

    def test_governance_absent_does_not_add_observation(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_snapshot_no_governance())
        all_text = " ".join(result["observations"])
        self.assertNotIn("Governance status:", all_text)
        self.assertNotIn("Recent governance:", all_text)

    def test_recent_governance_empty_observation_appears(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_snapshot_empty_recent_governance())
        all_text = " ".join(result["observations"])
        self.assertIn("Recent governance:", all_text)
        self.assertIn("does not imply MSO inactivity", all_text)

    def test_recent_governance_empty_does_not_claim_mso_inactive(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_snapshot_empty_recent_governance())
        all_text = " ".join(result["observations"])
        self.assertNotIn("MSO inactive", all_text)

    def test_recent_governance_latest_decision_observation_appears(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_snapshot_with_governance())
        all_text = " ".join(result["observations"])
        self.assertIn("Recent governance:", all_text)
        self.assertIn("BLOCK", all_text)
        self.assertIn("ENERGY", all_text)
        self.assertIn("anomaly detected", all_text)

    def test_no_mso_active_in_observations(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        result = interpret_system_snapshot(_snapshot_with_governance())
        all_text = " ".join(result["observations"]) + " " + result["summary"]
        self.assertNotIn("MSO ACTIVE", all_text)
        self.assertNotIn("MSO HEALTHY", all_text)
        self.assertNotIn("system safe", all_text.lower())
        self.assertNotIn("system unsafe", all_text.lower())
        self.assertNotIn("governance working perfectly", all_text.lower())

    def test_interpreter_remains_pure_with_governance(self) -> None:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        snap = _snapshot_with_governance()
        result_a = interpret_system_snapshot(snap)
        result_b = interpret_system_snapshot(snap)
        self.assertEqual(result_a, result_b)

    def test_interpreter_does_not_call_governance_surface(self) -> None:
        """Interpreter reads from snapshot dict only — never calls governance_surface."""
        from unittest.mock import patch
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        with patch(
            "assistant_os.mso.governance_surface.get_governance_summary"
        ) as gs_mock:
            interpret_system_snapshot(_snapshot_with_governance())
        gs_mock.assert_not_called()


# ---------------------------------------------------------------------------
# 12. Summary effective mode wording
# ---------------------------------------------------------------------------

class TestSummaryEffectiveModeWording(unittest.TestCase):
    def _summary(self, snap: dict) -> str:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        return interpret_system_snapshot(snap)["summary"]

    def test_manual_override_takes_priority_over_governance(self) -> None:
        snap = {
            "generated_at": "2026-05-01T00:00:00+00:00",
            "status": "ok",
            "operational_mode": "FROZEN",
            "agents": [], "capabilities": [], "tasks_summary": {}, "warnings": [],
            "governance_status_summary": {
                "operational_mode": "NORMAL",
                "operational_mode_source": "derived",
                "hardened_domain_count": 0, "active_revocation_count": 0,
                "active_grant_count": 0, "recent_anomaly_count": 0,
            },
        }
        summary = self._summary(snap)
        self.assertIn("manual operational override FROZEN", summary)
        self.assertNotIn("effective governance mode", summary)

    def test_governance_effective_mode_used_when_no_override(self) -> None:
        snap = {
            "generated_at": "2026-05-01T00:00:00+00:00",
            "status": "ok",
            "operational_mode": None,
            "agents": [], "capabilities": [], "tasks_summary": {}, "warnings": [],
            "governance_status_summary": {
                "operational_mode": "NORMAL",
                "operational_mode_source": "derived",
                "hardened_domain_count": 0, "active_revocation_count": 0,
                "active_grant_count": 0, "recent_anomaly_count": 0,
            },
        }
        summary = self._summary(snap)
        self.assertIn("effective governance mode NORMAL (source derived)", summary)

    def test_unknown_fallback_when_no_override_and_no_governance(self) -> None:
        snap = {
            "generated_at": "2026-05-01T00:00:00+00:00",
            "status": "ok",
            "operational_mode": None,
            "agents": [], "capabilities": [], "tasks_summary": {}, "warnings": [],
        }
        summary = self._summary(snap)
        self.assertIn("mode unknown (no override set)", summary)
        self.assertNotIn("NORMAL", summary)

    def test_unknown_fallback_when_governance_status_summary_none(self) -> None:
        snap = {
            "generated_at": "2026-05-01T00:00:00+00:00",
            "status": "ok",
            "operational_mode": None,
            "agents": [], "capabilities": [], "tasks_summary": {}, "warnings": [],
            "governance_status_summary": None,
        }
        summary = self._summary(snap)
        self.assertIn("mode unknown (no override set)", summary)

    def test_partial_summary_uses_effective_governance_mode(self) -> None:
        snap = {
            "generated_at": "2026-05-01T00:00:00+00:00",
            "status": "partial",
            "operational_mode": None,
            "agents": [], "capabilities": [], "tasks_summary": {},
            "warnings": ["agents source unavailable: error"],
            "governance_status_summary": {
                "operational_mode": "NORMAL",
                "operational_mode_source": "derived",
                "hardened_domain_count": 0, "active_revocation_count": 0,
                "active_grant_count": 0, "recent_anomaly_count": 0,
            },
        }
        summary = self._summary(snap)
        self.assertIn("System observation partial", summary)
        self.assertIn("effective governance mode NORMAL (source derived)", summary)

    def test_derived_frozen_appears_correctly(self) -> None:
        snap = {
            "generated_at": "2026-05-01T00:00:00+00:00",
            "status": "ok",
            "operational_mode": None,
            "agents": [], "capabilities": [], "tasks_summary": {}, "warnings": [],
            "governance_status_summary": {
                "operational_mode": "FROZEN",
                "operational_mode_source": "derived",
                "hardened_domain_count": 2, "active_revocation_count": 1,
                "active_grant_count": 0, "recent_anomaly_count": 3,
            },
        }
        summary = self._summary(snap)
        self.assertIn("effective governance mode FROZEN (source derived)", summary)

    def test_no_mso_active_or_healthy_in_summary(self) -> None:
        for snap in (
            _snapshot_with_governance(),
            _snapshot_no_governance(),
            _snapshot_empty_recent_governance(),
        ):
            with self.subTest(status=snap["status"]):
                summary = self._summary(snap)
                self.assertNotIn("MSO ACTIVE", summary)
                self.assertNotIn("MSO HEALTHY", summary)


# ---------------------------------------------------------------------------
# S-CODE-READINESS-01C — interpreter must observe CODE readiness passively.
# ---------------------------------------------------------------------------


def _snapshot_with_code_readiness(*, reachable: bool = True,
                                   apply_mode: str = "stub",
                                   allowed: int = 2,
                                   confirm: int = 2,
                                   blocked: int = 0,
                                   runner_probed: bool = False,
                                   runner_available: object = None) -> dict:
    return {
        "status": "ok",
        "operational_mode": None,
        "agents": [],
        "capabilities": [],
        "tasks_summary": {},
        "warnings": [],
        "code_readiness_summary": {
            "source": "code_readiness",
            "domain": "CODE",
            "feature_enabled": True,
            "code_api_reachable": reachable,
            "apply_execution_mode": apply_mode,
            "apply_real_enabled": apply_mode == "real",
            "runner_backend_probed": runner_probed,
            "runner_backend_available": runner_available,
            "code_capability_allowed_count": allowed,
            "code_capability_confirm_only_count": confirm,
            "code_capability_blocked_count": blocked,
            "note": "Readiness is not authority.",
        },
    }


def _snapshot_without_code_readiness() -> dict:
    return {
        "status": "ok",
        "operational_mode": None,
        "agents": [],
        "capabilities": [],
        "tasks_summary": {},
        "warnings": [],
        "code_readiness_summary": None,
    }


class TestCodeReadinessObservations(unittest.TestCase):
    """Interpreter must surface CODE readiness with passive wording only."""

    def _observations(self, snapshot: dict) -> list[str]:
        from assistant_os.system_assistant.interpreter import interpret_system_snapshot
        return interpret_system_snapshot(snapshot)["observations"]

    def test_observation_appears_when_present(self) -> None:
        snap = _snapshot_with_code_readiness()
        joined = " || ".join(self._observations(snap))
        self.assertIn("CODE readiness", joined)
        self.assertIn("API reachable", joined)
        self.assertIn("apply mode stub", joined)
        self.assertIn("2 allow", joined)
        self.assertIn("not execution authority", joined.lower())

    def test_api_unreachable_phrased_as_unavailable(self) -> None:
        snap = _snapshot_with_code_readiness(reachable=False)
        joined = " || ".join(self._observations(snap))
        self.assertIn("API unavailable", joined)

    def test_runner_probed_available(self) -> None:
        snap = _snapshot_with_code_readiness(
            apply_mode="real", runner_probed=True, runner_available=True,
        )
        joined = " || ".join(self._observations(snap))
        self.assertIn("runner backend available", joined)

    def test_runner_probed_unavailable(self) -> None:
        snap = _snapshot_with_code_readiness(
            apply_mode="real", runner_probed=True, runner_available=False,
        )
        joined = " || ".join(self._observations(snap))
        self.assertIn("runner backend unavailable", joined)

    def test_unavailable_when_summary_none(self) -> None:
        snap = _snapshot_without_code_readiness()
        joined = " || ".join(self._observations(snap))
        self.assertIn("CODE readiness: unavailable", joined)
        self.assertIn("does not imply CODE authority", joined)

    def test_no_forbidden_authority_wording(self) -> None:
        for snap in (
            _snapshot_with_code_readiness(),
            _snapshot_with_code_readiness(reachable=False),
            _snapshot_with_code_readiness(apply_mode="real",
                                          runner_probed=True,
                                          runner_available=True),
            _snapshot_without_code_readiness(),
        ):
            with self.subTest():
                joined = " || ".join(self._observations(snap))
                lowered = joined.lower()
                for forbidden in (
                    "ready to execute",
                    "safe to apply",
                    "authorized",
                    "execution enabled",
                    "runner authorized",
                    "mso active",
                    "mso healthy",
                    "healthy because online",
                ):
                    self.assertNotIn(
                        forbidden, lowered,
                        f"Forbidden authority wording leaked: {forbidden!r}",
                    )

    def test_interpreter_does_not_import_codeops(self) -> None:
        """Interpreter must remain pure — no I/O, no codeops/readiness import."""
        import inspect
        from assistant_os.system_assistant import interpreter as _interp
        src = inspect.getsource(_interp)
        # Must NOT import codeops.readiness directly — relies on snapshot only.
        self.assertNotIn("from assistant_os.codeops.readiness", src)
        self.assertNotIn("from ..codeops", src)
        self.assertNotIn("from .codeops", src)


if __name__ == "__main__":
    unittest.main()
