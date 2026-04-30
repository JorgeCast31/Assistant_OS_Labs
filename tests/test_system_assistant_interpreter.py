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


if __name__ == "__main__":
    unittest.main()
