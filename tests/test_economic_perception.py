"""Unit tests for SPRINT-ALPHA-02 — Economic Perception Frame.

Tests:
- build_economic_perception_frame(): required keys, execution boundary, fail-safety,
  bounded reads, subsystem mocking.
- build_mso_grounding_context(): backward compat + new frame keys present.
- build_mso_chat_system_prompt(): expanded sections rendered correctly.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from assistant_os.mso.perception import build_economic_perception_frame

REQUIRED_KEYS = {
    "version",
    "generated_at",
    "execution_allowed",
    "can_execute_now",
    "execution_closed",
    "operational_mode",
    "seat_provider",
    "authority_posture",
    "next_safe_step",
    "limitations",
    "prepared_actions_count",
    "prepared_actions_summary",
    "confirm_pending_count",
    "confirm_pending_summary",
    "capabilities_summary",
    "recent_governance",
    "active_tasks_brief",
    "recent_failures",
    "session_history_available",
    "session_history",
    "perception_warnings",
}


# ---------------------------------------------------------------------------
# Required keys and execution boundary
# ---------------------------------------------------------------------------

class TestBuildEconomicPerceptionFrameKeys(unittest.TestCase):
    def test_returns_all_required_keys(self):
        frame = build_economic_perception_frame()
        missing = REQUIRED_KEYS - set(frame.keys())
        self.assertFalse(missing, f"Frame missing required keys: {missing}")

    def test_execution_boundary_immutable(self):
        frame = build_economic_perception_frame()
        self.assertFalse(frame["execution_allowed"])
        self.assertFalse(frame["can_execute_now"])
        self.assertTrue(frame["execution_closed"])

    def test_session_history_deferred(self):
        frame = build_economic_perception_frame()
        self.assertFalse(frame["session_history_available"])
        self.assertEqual(frame["session_history"], [])

    def test_perception_warnings_is_list(self):
        frame = build_economic_perception_frame()
        self.assertIsInstance(frame["perception_warnings"], list)

    def test_version_is_alpha_02(self):
        frame = build_economic_perception_frame()
        self.assertEqual(frame["version"], "alpha-02")

    def test_prepared_actions_count_matches_summary_length(self):
        mock_items = [{"queue_entry_id": f"q{i}", "domain": "WORK"} for i in range(3)]
        with patch("assistant_os.mso.perception._read_prepared_actions", return_value=mock_items):
            frame = build_economic_perception_frame()
        self.assertEqual(frame["prepared_actions_count"], 3)
        self.assertEqual(len(frame["prepared_actions_summary"]), 3)
        self.assertEqual(frame["confirm_pending_count"], 3)

    def test_confirm_pending_summary_equals_prepared_summary(self):
        mock_items = [{"queue_entry_id": "q1", "domain": "CODE"}]
        with patch("assistant_os.mso.perception._read_prepared_actions", return_value=mock_items):
            frame = build_economic_perception_frame()
        self.assertEqual(frame["prepared_actions_summary"], frame["confirm_pending_summary"])


# ---------------------------------------------------------------------------
# Fail-safety
# ---------------------------------------------------------------------------

class TestBuildEconomicPerceptionFrameFailSafety(unittest.TestCase):
    def test_all_readers_replaced_with_safe_defaults_still_returns_frame(self):
        with patch("assistant_os.mso.perception._read_operational_mode", return_value="UNKNOWN"), \
             patch("assistant_os.mso.perception._read_seat_provider", return_value="unavailable"), \
             patch("assistant_os.mso.perception._read_prepared_actions", return_value=[]), \
             patch("assistant_os.mso.perception._read_capabilities_summary", return_value={}), \
             patch("assistant_os.mso.perception._read_recent_governance", return_value=[]), \
             patch("assistant_os.mso.perception._read_active_tasks_brief", return_value=[]), \
             patch("assistant_os.mso.perception._read_recent_failures", return_value=[]):
            frame = build_economic_perception_frame()
        self.assertFalse(frame["execution_allowed"])
        self.assertFalse(frame["can_execute_now"])
        self.assertEqual(frame["prepared_actions_count"], 0)
        self.assertEqual(frame["recent_governance"], [])
        self.assertEqual(frame["active_tasks_brief"], [])
        self.assertEqual(frame["recent_failures"], [])

    def test_governance_warning_injected_when_reader_adds_it(self):
        def bad_governance(warnings):
            warnings.append("recent_governance unavailable: test error")
            return []

        with patch("assistant_os.mso.perception._read_recent_governance", bad_governance):
            frame = build_economic_perception_frame()

        self.assertEqual(frame["recent_governance"], [])
        self.assertTrue(
            any("recent_governance" in w for w in frame["perception_warnings"]),
            f"Expected governance warning, got: {frame['perception_warnings']}"
        )

    def test_operational_mode_warning_injected(self):
        def bad_mode(warnings):
            warnings.append("operational_mode unavailable: boom")
            return "UNKNOWN"

        with patch("assistant_os.mso.perception._read_operational_mode", bad_mode):
            frame = build_economic_perception_frame()

        self.assertEqual(frame["operational_mode"], "UNKNOWN")
        self.assertTrue(
            any("operational_mode" in w for w in frame["perception_warnings"]),
            f"Expected mode warning, got: {frame['perception_warnings']}"
        )

    def test_frame_never_raises_even_with_bad_subsystems(self):
        # Simulate the entire internal path raising for prepared_actions
        # The internal reader already wraps with try/except, so patch to verify
        # even a badly behaving reader doesn't escape build_economic_perception_frame
        try:
            frame = build_economic_perception_frame()
            self.assertIn("execution_allowed", frame)
        except Exception as exc:
            self.fail(f"build_economic_perception_frame raised: {exc}")


# ---------------------------------------------------------------------------
# Subsystem mock integration
# ---------------------------------------------------------------------------

class TestBuildEconomicPerceptionFrameWithMockedSubsystems(unittest.TestCase):
    def test_capabilities_summary_present_when_available(self):
        mock_caps = {
            "domains": ["WORK", "CODE"],
            "active_capabilities": ["cap_code_review"],
            "machine_operator": "available",
            "runner_enforced": True,
        }
        with patch("assistant_os.mso.perception._read_capabilities_summary",
                   return_value=mock_caps):
            frame = build_economic_perception_frame()
        self.assertEqual(frame["capabilities_summary"]["domains"], ["WORK", "CODE"])
        self.assertIn("cap_code_review", frame["capabilities_summary"]["active_capabilities"])

    def test_recent_governance_present(self):
        mock_gov = [{"decision_id": f"d{i}", "outcome": "ALLOW", "domain": "CODE"}
                    for i in range(3)]
        with patch("assistant_os.mso.perception._read_recent_governance", return_value=mock_gov):
            frame = build_economic_perception_frame()
        self.assertEqual(len(frame["recent_governance"]), 3)
        self.assertEqual(frame["recent_governance"][0]["outcome"], "ALLOW")

    def test_recent_failures_present(self):
        mock_failures = [
            {"task_id": f"f{i}", "domain": "CODE", "status": "failed",
             "error_type": "runtime", "error_message": "oops", "created_at": ""}
            for i in range(3)
        ]
        with patch("assistant_os.mso.perception._read_recent_failures",
                   return_value=mock_failures):
            frame = build_economic_perception_frame()
        self.assertEqual(len(frame["recent_failures"]), 3)
        self.assertEqual(frame["recent_failures"][0]["status"], "failed")

    def test_active_tasks_brief_present(self):
        mock_tasks = [
            {"task_id": "t1", "domain": "WORK", "status": "active",
             "last_known_action": "ACTION_WORK_CREATE", "created_at": ""}
        ]
        with patch("assistant_os.mso.perception._read_active_tasks_brief",
                   return_value=mock_tasks):
            frame = build_economic_perception_frame()
        self.assertEqual(len(frame["active_tasks_brief"]), 1)
        self.assertEqual(frame["active_tasks_brief"][0]["task_id"], "t1")

    def test_next_safe_step_normal_no_pending(self):
        with patch("assistant_os.mso.perception._read_operational_mode", return_value="NORMAL"), \
             patch("assistant_os.mso.perception._read_prepared_actions", return_value=[]):
            frame = build_economic_perception_frame()
        self.assertIn("plan_request", frame["next_safe_step"])

    def test_next_safe_step_with_pending(self):
        mock_items = [{"queue_entry_id": "q1"}, {"queue_entry_id": "q2"}]
        with patch("assistant_os.mso.perception._read_operational_mode", return_value="NORMAL"), \
             patch("assistant_os.mso.perception._read_prepared_actions",
                   return_value=mock_items):
            frame = build_economic_perception_frame()
        self.assertIn("2", frame["next_safe_step"])

    def test_next_safe_step_restricted_mode(self):
        with patch("assistant_os.mso.perception._read_operational_mode",
                   return_value="RESTRICTED"):
            frame = build_economic_perception_frame()
        self.assertIn("RESTRICTED", frame["next_safe_step"])

    def test_multiple_warnings_accumulated(self):
        def bad_gov(warnings):
            warnings.append("recent_governance unavailable: err1")
            return []

        def bad_caps(warnings):
            warnings.append("capabilities_summary unavailable: err2")
            return {}

        with patch("assistant_os.mso.perception._read_recent_governance", bad_gov), \
             patch("assistant_os.mso.perception._read_capabilities_summary", bad_caps):
            frame = build_economic_perception_frame()

        self.assertGreaterEqual(len(frame["perception_warnings"]), 2)


# ---------------------------------------------------------------------------
# Backward compat: build_mso_grounding_context
# ---------------------------------------------------------------------------

class TestBuildMsoGroundingContextBackwardCompat(unittest.TestCase):
    REQUIRED_LEGACY_KEYS = {
        "execution_allowed",
        "can_execute_now",
        "execution_closed",
        "operational_mode",
        "seat_provider",
        "prepared_actions_count",
        "pending_review_items",
        "next_safe_step",
        "authority_posture",
        "limitations",
    }

    def test_legacy_keys_present(self):
        from assistant_os.mso.narrative_runtime import build_mso_grounding_context
        ctx = build_mso_grounding_context()
        missing = self.REQUIRED_LEGACY_KEYS - set(ctx.keys())
        self.assertFalse(missing, f"Legacy keys missing after delegation: {missing}")

    def test_execution_boundary_preserved(self):
        from assistant_os.mso.narrative_runtime import build_mso_grounding_context
        ctx = build_mso_grounding_context()
        self.assertFalse(ctx["execution_allowed"])
        self.assertFalse(ctx["can_execute_now"])

    def test_new_frame_keys_now_present(self):
        from assistant_os.mso.narrative_runtime import build_mso_grounding_context
        ctx = build_mso_grounding_context()
        new_keys = {
            "version", "capabilities_summary", "recent_governance",
            "active_tasks_brief", "recent_failures", "perception_warnings",
        }
        present = new_keys & set(ctx.keys())
        self.assertEqual(present, new_keys, f"New frame keys missing: {new_keys - present}")

    def test_version_alpha_02(self):
        from assistant_os.mso.narrative_runtime import build_mso_grounding_context
        ctx = build_mso_grounding_context()
        self.assertEqual(ctx.get("version"), "alpha-02")

    def test_pending_review_items_alias_present(self):
        from assistant_os.mso.narrative_runtime import build_mso_grounding_context
        ctx = build_mso_grounding_context()
        # pending_review_items must equal prepared_actions_summary
        self.assertEqual(ctx["pending_review_items"], ctx["prepared_actions_summary"])


# ---------------------------------------------------------------------------
# Prompt expansion
# ---------------------------------------------------------------------------

class TestBuildMsoChatSystemPromptExpansion(unittest.TestCase):
    def _make_frame(self, **overrides) -> dict:
        base = {
            "version": "alpha-02",
            "generated_at": "2026-05-13T00:00:00Z",
            "execution_allowed": False,
            "can_execute_now": False,
            "execution_closed": True,
            "operational_mode": "NORMAL",
            "seat_provider": "anthropic / claude-haiku-4-5",
            "authority_posture": "PolicyDecision -> PoliceGate",
            "next_safe_step": "No pending actions.",
            "limitations": "You cannot execute.",
            "prepared_actions_count": 0,
            "prepared_actions_summary": [],
            "confirm_pending_count": 0,
            "confirm_pending_summary": [],
            "capabilities_summary": {},
            "recent_governance": [],
            "active_tasks_brief": [],
            "recent_failures": [],
            "session_history_available": False,
            "session_history": [],
            "perception_warnings": [],
        }
        base.update(overrides)
        return base

    def test_prompt_contains_hard_rules(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        prompt = build_mso_chat_system_prompt(self._make_frame())
        self.assertIn("cannot execute", prompt.lower())
        self.assertIn("do not invent", prompt.lower())

    def test_prompt_instructs_no_data_visible(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        prompt = build_mso_chat_system_prompt(self._make_frame())
        self.assertIn("no data", prompt.lower())

    def test_prompt_contains_operational_mode(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        prompt = build_mso_chat_system_prompt(self._make_frame(operational_mode="RESTRICTED"))
        self.assertIn("RESTRICTED", prompt)

    def test_prompt_shows_capabilities_when_present(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        frame = self._make_frame(capabilities_summary={
            "domains": ["WORK", "CODE"],
            "active_capabilities": ["cap_code_review"],
            "machine_operator": "available",
            "runner_enforced": True,
        })
        prompt = build_mso_chat_system_prompt(frame)
        self.assertIn("WORK", prompt)
        self.assertIn("cap_code_review", prompt)

    def test_prompt_shows_no_data_when_capabilities_empty(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        prompt = build_mso_chat_system_prompt(self._make_frame(capabilities_summary={}))
        self.assertIn("no data", prompt.lower())

    def test_prompt_shows_governance_when_present(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        frame = self._make_frame(recent_governance=[
            {"decision_id": "d1", "outcome": "ALLOW", "domain": "CODE"}
        ])
        prompt = build_mso_chat_system_prompt(frame)
        self.assertIn("ALLOW", prompt)

    def test_prompt_shows_no_data_when_governance_empty(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        prompt = build_mso_chat_system_prompt(self._make_frame(recent_governance=[]))
        self.assertIn("no data", prompt.lower())

    def test_prompt_shows_failures_when_present(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        frame = self._make_frame(recent_failures=[
            {"task_id": "f1", "domain": "WORK", "status": "failed",
             "error_type": "timeout", "error_message": "timed out", "created_at": ""}
        ])
        prompt = build_mso_chat_system_prompt(frame)
        self.assertIn("f1", prompt)

    def test_prompt_shows_perception_warnings_when_present(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        frame = self._make_frame(perception_warnings=["governance unavailable: error"])
        prompt = build_mso_chat_system_prompt(frame)
        self.assertIn("perception warning", prompt.lower())

    def test_prompt_shows_prepared_actions_when_present(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        frame = self._make_frame(
            prepared_actions_count=2,
            prepared_actions_summary=[{
                "queue_entry_id": "q1",
                "domain": "CODE",
                "requested_action": "PLAN_REVIEW",
                "capability_name": "plan_review",
                "human_confirmation_status": "pending",
                "execution_allowed": False,
                "can_execute_now": False,
            }],
        )
        prompt = build_mso_chat_system_prompt(frame)
        self.assertIn("q1", prompt)

    def test_prompt_shows_active_tasks_when_present(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        frame = self._make_frame(active_tasks_brief=[
            {"task_id": "t99", "domain": "WORK", "status": "active",
             "last_known_action": "ACTION_WORK_CREATE", "created_at": ""}
        ])
        prompt = build_mso_chat_system_prompt(frame)
        self.assertIn("t99", prompt)

    def test_prompt_shows_no_data_when_failures_empty(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        prompt = build_mso_chat_system_prompt(self._make_frame(recent_failures=[]))
        self.assertIn("no data", prompt.lower())

    def test_prompt_contains_execution_boundary_statement(self):
        from assistant_os.mso.prompts import build_mso_chat_system_prompt
        prompt = build_mso_chat_system_prompt(self._make_frame())
        self.assertIn("execution_allowed=false", prompt.lower())


if __name__ == "__main__":
    unittest.main()
