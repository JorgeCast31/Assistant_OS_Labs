"""Static contracts for UI Police/Audit showroom DTO types."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
POLICE_TYPES = REPO_ROOT / "ui/lib/sovereign/police-types.ts"
SECURITY_VIEW = REPO_ROOT / "ui/components/sovereign/SecurityView.tsx"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _type_body(src: str, type_name: str) -> str:
    match = re.search(rf"\bexport\s+type\s+{type_name}\s*=\s*([^\n]+)", src)
    if not match:
        raise AssertionError(f"{type_name} type definition not found")
    return match.group(1)


def _interface_body(src: str, interface_name: str) -> str:
    match = re.search(
        rf"\bexport\s+interface\s+{interface_name}\s*\{{(?P<body>.*?)\n\}}",
        src,
        re.S,
    )
    if not match:
        raise AssertionError(f"{interface_name} interface definition not found")
    return match.group("body")


def _quoted_literals(text: str) -> set[str]:
    return set(re.findall(r"'([^']+)'", text))


class TestPoliceTypesContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _read(POLICE_TYPES)

    def test_police_evaluation_outcome_contains_all_three_literals(self) -> None:
        literals = _quoted_literals(_type_body(self.src, "PoliceEvaluationOutcome"))
        self.assertEqual(literals, {"ALLOW", "DENY", "REQUIRES_CONFIRMATION"})

    def test_police_evaluation_outcome_excludes_decision_vocabulary(self) -> None:
        literals = _quoted_literals(_type_body(self.src, "PoliceEvaluationOutcome"))
        self.assertFalse({"permitted", "deferred", "APPROVED", "AUTHORIZED"} & literals)

    def test_candidate_status_locked_to_pending_gate(self) -> None:
        literals = _quoted_literals(_type_body(self.src, "CandidateStatus"))
        self.assertEqual(literals, {"PENDING_GATE"})

    def test_police_evaluation_record_has_no_authorization_field(self) -> None:
        body = _interface_body(self.src, "PoliceEvaluationRecord")
        allowed_scope_fields = {
            "allowed_tools",
            "denied_tools",
            "allowed_environments",
            "denied_environments",
        }
        fields = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", body, re.M))
        forbidden = {
            "is_authorized",
            "authorized_at",
            "execution_enabled",
            "gate_passed",
            "authorize_execution",
        }
        self.assertFalse((fields - allowed_scope_fields) & forbidden)

    def test_police_decision_type_not_introduced(self) -> None:
        forbidden_type_names = (
            "PoliceDecisionOutcome",
            "PoliceDecisionRecord",
            "PoliceGateRequest",
            "TokenGateState",
            "TokenLifecycleState",
            "CandidateOrchestrationRequest",
            "PoliceOutcome",
        )
        for type_name in forbidden_type_names:
            self.assertIsNone(
                re.search(rf"\bexport\s+(?:type|interface)\s+{type_name}\b", self.src),
                f"{type_name} must not be introduced in police-types.ts",
            )

        forbidden_literals = (
            "permitted",
            "deferred",
            "APPROVED",
            "AUTHORIZED",
            "EXECUTION_READY",
            "GATE_PASSED",
        )
        literals = _quoted_literals(self.src)
        for literal in forbidden_literals:
            self.assertNotIn(literal, literals)

        forbidden_symbols = (
            "is_authorized",
            "authorized_at",
            "execution_enabled",
            "gate_passed",
            "authorize_execution",
            "launch",
            "runner",
            "pipeline",
            "machine_operator",
        )
        for symbol in forbidden_symbols:
            self.assertIsNone(
                re.search(rf"\b{symbol}\b", self.src),
                f"{symbol} must not appear in police-types.ts",
            )

    def test_agent_permission_profile_shape_no_execution_language(self) -> None:
        body = _interface_body(self.src, "AgentPermissionProfileShape")
        allowed_scope_fields = {"permitted_tools", "permitted_environments"}
        fields = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", body, re.M))
        forbidden_fields = {
            "launch",
            "runner",
            "pipeline",
            "machine_operator",
            "is_authorized",
            "authorized_at",
            "execution_enabled",
            "gate_passed",
            "authorize_execution",
        }
        self.assertFalse((fields - allowed_scope_fields) & forbidden_fields)


class TestSecurityViewRegression(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _read(SECURITY_VIEW)

    def test_security_view_not_modified(self) -> None:
        self.assertIn("AuthorityMatrixPanel", self.src)
        for panel_name in (
            "PoliceSurfacePanel",
            "PoliceEvaluationPanel",
            "MissionExecutionCandidatePanel",
            "CandidateAuditRecordPanel",
            "PoliceDecisionPanel",
        ):
            self.assertNotIn(panel_name, self.src)


if __name__ == "__main__":
    unittest.main()
