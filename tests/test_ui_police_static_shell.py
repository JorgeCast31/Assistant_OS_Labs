"""Static contracts for unmounted Police showroom shell panels."""

from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
SOVEREIGN_ROOT = REPO_ROOT / "ui/components/sovereign"
POLICE_ROOT = SOVEREIGN_ROOT / "police"

PANEL_FILES = {
    "PoliceEvaluationPanel": POLICE_ROOT / "PoliceEvaluationPanel.tsx",
    "MissionExecutionCandidatePanel": POLICE_ROOT / "MissionExecutionCandidatePanel.tsx",
    "CandidateAuditRecordPanel": POLICE_ROOT / "CandidateAuditRecordPanel.tsx",
    "AgentPermissionProfilePanel": POLICE_ROOT / "AgentPermissionProfilePanel.tsx",
}

REQUIRED_COPY = {
    "PoliceEvaluationPanel": (
        "PoliceEvaluation.ALLOW is observational and not execution authorization."
    ),
    "MissionExecutionCandidatePanel": (
        "pending_gate is a neutral waiting state and does not grant execution permission."
    ),
    "CandidateAuditRecordPanel": (
        "CandidateAuditRecord is observational evidence, not authority."
    ),
    "AgentPermissionProfilePanel": (
        "AgentPermissionProfile is scope-only and does not grant execution permission."
    ),
}

READ_ONLY_COPY = "Read-only surface. No mutation controls."


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _line_with(src: str, token: str) -> str:
    for line in src.splitlines():
        if token in line:
            return line
    raise AssertionError(f"line containing {token!r} not found")


def _lines_with_any(src: str, tokens: tuple[str, ...]) -> list[str]:
    lowered_tokens = tuple(token.lower() for token in tokens)
    return [
        line
        for line in src.splitlines()
        if any(token in line.lower() for token in lowered_tokens)
    ]


class TestStaticPoliceShowroomShell(unittest.TestCase):
    def test_all_panel_files_exist(self) -> None:
        for path in PANEL_FILES.values():
            self.assertTrue(path.exists(), f"{path} must exist")

    def test_old_root_level_panel_files_do_not_remain(self) -> None:
        for panel_name in PANEL_FILES:
            self.assertFalse((SOVEREIGN_ROOT / f"{panel_name}.tsx").exists())

    def test_security_view_does_not_import_or_mount_panels(self) -> None:
        src = _read(SOVEREIGN_ROOT / "SecurityView.tsx")
        for panel_name in PANEL_FILES:
            self.assertNotIn(panel_name, src)
            self.assertNotIn(f"<{panel_name}", src)

    def test_police_decision_panel_does_not_exist(self) -> None:
        self.assertFalse((SOVEREIGN_ROOT / "PoliceDecisionPanel.tsx").exists())

    def test_panels_have_no_mutation_or_action_affordances(self) -> None:
        forbidden = (
            "button",
            "onClick",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "approve",
            "deny",
            "execute",
            "launch",
            "PoliceDecision",
            "TokenGate",
            "<form",
            "fetch(",
            "useEffect",
            "useState",
            "useStore",
            "/api/",
        )
        for path in PANEL_FILES.values():
            src = _read(path)
            for token in forbidden:
                self.assertNotIn(token, src, f"{path.name} contains {token}")

    def test_required_non_authority_copy_exists(self) -> None:
        for panel_name, path in PANEL_FILES.items():
            src = _read(path)
            self.assertIn(REQUIRED_COPY[panel_name], src)
            self.assertIn(READ_ONLY_COPY, src)

    def test_agent_permission_profile_uses_real_scope_fields(self) -> None:
        src = _read(PANEL_FILES["AgentPermissionProfilePanel"])
        self.assertIn("permitted_tools:", src)
        self.assertIn("permitted_environments:", src)
        self.assertIn("profile.declared_capabilities", src)
        self.assertIn("profile.permitted_tools", src)
        self.assertIn("profile.permitted_environments", src)
        self.assertNotIn("['per' + 'mitted_tools']", src)
        self.assertNotIn("['per' + 'mitted_environments']", src)

    def test_allow_line_is_neutral(self) -> None:
        src = _read(PANEL_FILES["PoliceEvaluationPanel"])
        lines = [
            _line_with(src, "PoliceEvaluation.ALLOW"),
            _line_with(src, "record.outcome"),
        ]
        forbidden = (
            "authorized",
            "approved",
            "execution enabled",
            "ready to execute",
            "safe to execute",
            "gate passed",
            "success",
            "green",
        )
        for line in lines:
            lowered = line.lower()
            for token in forbidden:
                self.assertNotIn(token, lowered)
        self.assertIn("not execution authorization", lines[0])

    def test_pending_gate_lines_are_neutral(self) -> None:
        src = _read(PANEL_FILES["MissionExecutionCandidatePanel"])
        lines = [
            line
            for line in src.splitlines()
            if "PENDING_GATE" in line or "pending_gate" in line or "candidate_status" in line
        ]
        self.assertTrue(lines)
        forbidden = (
            "authorized",
            "approved",
            "execution enabled",
            "ready to execute",
            "safe to execute",
            "gate passed",
            "success",
            "green",
        )
        for line in lines:
            lowered = line.lower()
            for token in forbidden:
                self.assertNotIn(token, lowered)
        self.assertIn("does not grant execution permission", "\n".join(lines))

    def test_candidate_audit_record_line_is_observational(self) -> None:
        src = _read(PANEL_FILES["CandidateAuditRecordPanel"])
        line = _line_with(src, "CandidateAuditRecord")
        forbidden = (
            "authorized",
            "approved",
            "execution enabled",
            "ready to execute",
            "safe to execute",
            "gate passed",
            "launch",
            "execute now",
        )
        lowered = line.lower()
        for token in forbidden:
            self.assertNotIn(token, lowered)

    def test_agent_permission_profile_line_is_scope_only(self) -> None:
        src = _read(PANEL_FILES["AgentPermissionProfilePanel"])
        lines = _lines_with_any(
            src,
            ("AgentPermissionProfile", "permitted_tools", "permitted_environments"),
        )
        self.assertTrue(lines)
        forbidden = (
            "runner",
            "pipeline",
            "Machine Operator",
            "launch",
            "authorized",
            "approved",
            "execution enabled",
            "ready to execute",
            "safe to execute",
            "gate passed",
            "execute now",
        )
        for line in lines:
            lowered = line.lower()
            for token in forbidden:
                self.assertNotIn(token.lower(), lowered)

        scope_lines = "\n".join(lines)
        self.assertIn("permitted_tools", scope_lines)
        self.assertIn("permitted_environments", scope_lines)


if __name__ == "__main__":
    unittest.main()
