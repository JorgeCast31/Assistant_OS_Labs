"""
tests/test_mo_agent_registry.py

Validates that machine_operator is correctly registered in the agent registry
and that the registry endpoint projection includes it with required fields.
"""

import unittest


class TestMachineOperatorInRegistry(unittest.TestCase):
    """machine_operator must appear in AGENT_REGISTRY with correct structure."""

    def _get_registry(self):
        from assistant_os.agents.registry import AGENT_REGISTRY
        return AGENT_REGISTRY

    def _get_agent(self, name: str):
        from assistant_os.agents.registry import get_agent
        return get_agent(name)

    # ── Presence ──────────────────────────────────────────────────────────────

    def test_machine_operator_is_registered(self):
        registry = self._get_registry()
        self.assertIn(
            "machine_operator", registry,
            "machine_operator must be present in AGENT_REGISTRY",
        )

    def test_get_agent_returns_machine_operator(self):
        agent = self._get_agent("machine_operator")
        self.assertEqual(agent["name"], "machine_operator")

    # ── Required fields ───────────────────────────────────────────────────────

    def test_machine_operator_has_domain(self):
        agent = self._get_agent("machine_operator")
        self.assertEqual(agent["domain"], "MACHINE_OPERATOR")

    def test_machine_operator_has_capabilities(self):
        agent = self._get_agent("machine_operator")
        caps = agent.get("capability_scope", [])
        self.assertIsInstance(caps, list)
        self.assertGreater(len(caps), 0, "capability_scope must not be empty")

    def test_machine_operator_capability_scope_matches_allowed(self):
        from assistant_os.mso.contracts import MACHINE_OPERATOR_ALLOWED_CAPABILITIES
        agent = self._get_agent("machine_operator")
        for cap in agent["capability_scope"]:
            self.assertIn(
                cap,
                MACHINE_OPERATOR_ALLOWED_CAPABILITIES,
                f"capability {cap!r} not in MACHINE_OPERATOR_ALLOWED_CAPABILITIES",
            )

    def test_machine_operator_has_entrypoint(self):
        agent = self._get_agent("machine_operator")
        self.assertTrue(callable(agent["entrypoint"]))

    def test_machine_operator_passes_validation(self):
        from assistant_os.agents.registry import _validate_agent_definition
        agent = self._get_agent("machine_operator")
        # Should not raise
        _validate_agent_definition(agent, "machine_operator")

    def test_machine_operator_has_description(self):
        agent = self._get_agent("machine_operator")
        desc = agent.get("description", "")
        self.assertIsInstance(desc, str)
        self.assertGreater(len(desc), 10)

    # ── Registry projection (operability.py read model) ───────────────────────

    def test_registry_response_includes_machine_operator(self):
        from assistant_os.operability import build_agents_registry_response
        response = build_agents_registry_response()
        self.assertTrue(response["ok"])
        agent_ids = [a["id"] for a in response["agents"]]
        self.assertIn("machine_operator", agent_ids)

    def test_registry_response_machine_operator_has_capabilities(self):
        from assistant_os.operability import build_agents_registry_response
        response = build_agents_registry_response()
        mo = next(a for a in response["agents"] if a["id"] == "machine_operator")
        self.assertIsInstance(mo["capabilities"], list)
        self.assertGreater(len(mo["capabilities"]), 0)

    def test_registry_response_machine_operator_domain(self):
        from assistant_os.operability import build_agents_registry_response
        response = build_agents_registry_response()
        mo = next(a for a in response["agents"] if a["id"] == "machine_operator")
        self.assertEqual(mo["domain"], "MACHINE_OPERATOR")

    # ── Other agents not broken ───────────────────────────────────────────────

    def test_existing_agents_still_valid(self):
        from assistant_os.agents.registry import get_agent, AGENT_REGISTRY
        for name in AGENT_REGISTRY:
            with self.subTest(agent=name):
                agent = get_agent(name)
                self.assertEqual(agent["name"], name)
                self.assertTrue(callable(agent["entrypoint"]))

    def test_list_agents_includes_machine_operator(self):
        from assistant_os.agents.registry import list_agents
        names = [a["name"] for a in list_agents()]
        self.assertIn("machine_operator", names)

    def test_list_agents_returns_all_three(self):
        from assistant_os.agents.registry import list_agents
        agents = list_agents()
        self.assertGreaterEqual(len(agents), 3)
