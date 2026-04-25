"""Tests for the Surface Behavior Layer.

Verifies that:
1. system_chat greetings return informational responses (no plan, no governance block)
2. system_chat capability queries surface operability data
3. mso_direct greetings return MSO-role responses (no plan, no governance block)
4. mso_direct executive requests pass through the orchestrator (not short-circuited)
5. Requests with no surface follow existing behavior (no regression)
"""
import http.client
import json
import time
import unittest
from unittest.mock import MagicMock

from assistant_os.config import WEBHOOK_TOKEN
from assistant_os.surface_behavior import (
    _normalize,
    _is_executive,
    get_surface_behavior_response,
    _SYSTEM_CHAT_CONVERSATIONAL,
    _MSO_DIRECT_CONVERSATIONAL,
)
from assistant_os.webhook_server import WebhookHTTPServer, start_server_thread


# ---------------------------------------------------------------------------
# Unit tests — surface_behavior module directly
# ---------------------------------------------------------------------------

class TestNormalize(unittest.TestCase):
    def test_strips_accents(self):
        self.assertEqual(_normalize("Hola"), "hola")
        self.assertEqual(_normalize("qué puedes hacer"), "que puedes hacer")
        self.assertEqual(_normalize("quién eres"), "quien eres")
        self.assertEqual(_normalize("cómo uso el MSO"), "como uso el mso")

    def test_strips_punctuation(self):
        self.assertEqual(_normalize("Hola!"), "hola")
        self.assertEqual(_normalize("que eres?"), "que eres")

    def test_empty(self):
        self.assertEqual(_normalize(""), "")
        self.assertEqual(_normalize("  "), "")


class TestIsExecutive(unittest.TestCase):
    def test_executive_verbs(self):
        for phrase in ("crea una tarea", "ejecuta el script", "abre la app",
                       "modifica el archivo", "haz esto", "borra el repo",
                       "aplica el cambio", "lanza el proceso"):
            with self.subTest(phrase=phrase):
                self.assertTrue(_is_executive(_normalize(phrase)))

    def test_non_executive(self):
        for phrase in ("hola", "quien eres", "que puedes hacer", "estado del sistema"):
            with self.subTest(phrase=phrase):
                self.assertFalse(_is_executive(_normalize(phrase)))


class TestPatternSets(unittest.TestCase):
    def test_system_chat_includes_required_patterns(self):
        required = [
            "hola", "que eres", "que puedes hacer",
            "quiero conversar", "conversa conmigo",
            "que agentes tienes", "estado del sistema",
            "como uso el mso", "como uso machine operator",
        ]
        for pattern in required:
            self.assertIn(pattern, _SYSTEM_CHAT_CONVERSATIONAL, msg=f"missing: {pattern}")

    def test_mso_direct_includes_required_patterns(self):
        required = ["hola", "quien eres", "que puedes hacer"]
        for pattern in required:
            self.assertIn(pattern, _MSO_DIRECT_CONVERSATIONAL, msg=f"missing: {pattern}")


class TestGetSurfaceBehaviorResponse(unittest.TestCase):
    def _mock_identity(self):
        m = MagicMock()
        m.to_audit_dict.return_value = {"principal": "anon"}
        return m

    def _mock_guard(self):
        m = MagicMock()
        m.to_audit_dict.return_value = {"decision": "allow"}
        return m

    def _call(self, surface, text):
        return get_surface_behavior_response(
            surface=surface,
            text=text,
            context_id="ctx-test-001",
            identity=self._mock_identity(),
            guard_result=self._mock_guard(),
        )

    # --- system_chat ---

    def test_system_chat_greeting_returns_response(self):
        resp = self._call("system_chat", "Hola")
        self.assertIsNotNone(resp)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["domain"], "SYSTEM")
        self.assertEqual(resp["intent"], "informational_response")
        self.assertEqual(resp["plan"], [])
        self.assertFalse(resp["needs_confirmation"])
        self.assertEqual(resp["audit"]["surface"], "system_chat")
        self.assertEqual(resp["audit"]["result_type"], "surface_response")
        self.assertFalse(resp["audit"]["mso_decided"])

    def test_system_chat_greeting_accented(self):
        # "Hola" with no accent — still a greeting
        resp = self._call("system_chat", "hola!")
        self.assertIsNotNone(resp)
        self.assertEqual(resp["domain"], "SYSTEM")

    def test_system_chat_capabilities(self):
        resp = self._call("system_chat", "qué puedes hacer")
        self.assertIsNotNone(resp)
        self.assertEqual(resp["domain"], "SYSTEM")
        self.assertEqual(resp["audit"]["surface"], "system_chat")
        self.assertIsInstance(resp["message"], str)
        self.assertGreater(len(resp["message"]), 10)
        self.assertEqual(resp["plan"], [])

    def test_system_chat_agents(self):
        resp = self._call("system_chat", "qué agentes tienes")
        self.assertIsNotNone(resp)
        self.assertIsInstance(resp["message"], str)

    def test_system_chat_system_state(self):
        resp = self._call("system_chat", "estado del sistema")
        self.assertIsNotNone(resp)
        self.assertIn("operacional", resp["message"].lower())

    def test_system_chat_mso_usage(self):
        resp = self._call("system_chat", "cómo uso el MSO")
        self.assertIsNotNone(resp)
        self.assertIn("mso", resp["message"].lower())

    def test_system_chat_unknown_text_returns_none(self):
        # Not in conversational set → None (goes to orchestrator)
        resp = self._call("system_chat", "necesito que borres todos los archivos")
        self.assertIsNone(resp)

    # --- mso_direct ---

    def test_mso_direct_greeting_returns_response(self):
        resp = self._call("mso_direct", "Hola")
        self.assertIsNotNone(resp)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["domain"], "MSO")
        self.assertEqual(resp["intent"], "informational_response")
        self.assertEqual(resp["plan"], [])
        self.assertFalse(resp["needs_confirmation"])
        self.assertEqual(resp["audit"]["surface"], "mso_direct")
        self.assertFalse(resp["audit"]["mso_decided"])

    def test_mso_direct_identity_question(self):
        resp = self._call("mso_direct", "quién eres")
        self.assertIsNotNone(resp)
        self.assertEqual(resp["domain"], "MSO")
        # Message should explain MSO role
        self.assertIn("mso", resp["message"].lower())

    def test_mso_direct_capabilities(self):
        resp = self._call("mso_direct", "qué puedes hacer")
        self.assertIsNotNone(resp)
        self.assertEqual(resp["domain"], "MSO")
        self.assertEqual(resp["plan"], [])

    def test_mso_direct_executive_returns_none(self):
        # Executive requests must NOT be short-circuited
        for phrase in ("crea una tarea", "ejecuta el script", "abre la app",
                       "borra el archivo", "lanza el proceso"):
            with self.subTest(phrase=phrase):
                resp = self._call("mso_direct", phrase)
                self.assertIsNone(resp, msg=f"'{phrase}' should not be short-circuited")

    def test_mso_direct_unknown_text_returns_none(self):
        resp = self._call("mso_direct", "necesito análisis completo de arquitectura")
        self.assertIsNone(resp)

    # --- no surface / other surface ---

    def test_no_surface_returns_none(self):
        resp = self._call("", "Hola")
        self.assertIsNone(resp)

    def test_unknown_surface_returns_none(self):
        resp = self._call("agent_direct", "Hola")
        self.assertIsNone(resp)

    def test_none_surface_returns_none(self):
        resp = get_surface_behavior_response(
            surface="",
            text="Hola",
            context_id="ctx-test",
            identity=self._mock_identity(),
            guard_result=self._mock_guard(),
        )
        self.assertIsNone(resp)

    # --- Response shape integrity ---

    def test_response_has_all_required_fields(self):
        resp = self._call("system_chat", "hola")
        required = [
            "ok", "message", "trace_id", "domain", "intent", "mode",
            "needs_confirmation", "missing_fields", "plan", "ui_actions",
            "session", "audit", "identity", "guard",
        ]
        for field in required:
            self.assertIn(field, resp, msg=f"missing field: {field}")

    def test_response_session_has_context_id(self):
        resp = self._call("system_chat", "hola")
        self.assertEqual(resp["session"]["context_id"], "ctx-test-001")
        self.assertEqual(resp["session"]["last_domain"], "SYSTEM")

    def test_response_mode_is_chat(self):
        resp = self._call("mso_direct", "hola")
        self.assertEqual(resp["mode"], "chat")


# ---------------------------------------------------------------------------
# Integration tests — via HTTP webhook server
# ---------------------------------------------------------------------------

class TestSurfaceBehaviorHTTP(unittest.TestCase):
    server: WebhookHTTPServer
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.port = start_server_thread("127.0.0.1", 0)
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        from assistant_os.mso.system_state import clear_operational_mode_override
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.trace_aggregator import reset_trace_aggregator
        from assistant_os.storage.mso_store import clear_mso_store

        reset_dynamic_capabilities()
        clear_operational_mode_override()
        reset_task_registry()
        reset_trace_aggregator()
        clear_mso_store()

    def _post_chat(self, text: str, surface: str = "") -> tuple[int, dict]:
        body: dict = {"text": text}
        if surface:
            body["surface"] = surface

        headers = {
            "X-Assistant-Token": WEBHOOK_TOKEN,
            "Content-Type": "application/json",
        }
        payload = json.dumps(body).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/chat/process", body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        conn.close()
        return response.status, json.loads(raw)

    # Case 1: system_chat greeting
    def test_system_chat_greeting_http(self):
        status, body = self._post_chat("Hola", surface="system_chat")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["domain"], "SYSTEM")
        self.assertEqual(body["plan"], [])
        self.assertFalse(body["needs_confirmation"])
        self.assertIsInstance(body["message"], str)
        self.assertGreater(len(body["message"]), 5)
        self.assertEqual(body["audit"]["surface"], "system_chat")
        self.assertEqual(body["audit"]["result_type"], "surface_response")

    # Case 2: system_chat capabilities
    def test_system_chat_capabilities_http(self):
        status, body = self._post_chat("qué puedes hacer", surface="system_chat")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["plan"], [])
        self.assertFalse(body["needs_confirmation"])
        self.assertEqual(body["audit"]["surface"], "system_chat")

    # Case 3: mso_direct greeting
    def test_mso_direct_greeting_http(self):
        status, body = self._post_chat("Hola", surface="mso_direct")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["domain"], "MSO")
        self.assertEqual(body["plan"], [])
        self.assertFalse(body["needs_confirmation"])
        self.assertEqual(body["audit"]["surface"], "mso_direct")
        self.assertEqual(body["audit"]["result_type"], "surface_response")
        # Message must explain MSO sovereign role
        self.assertIn("mso", body["message"].lower())

    # Case 4: mso_direct executive request still goes through orchestrator
    def test_mso_direct_executive_governed_http(self):
        status, body = self._post_chat("crea una tarea nueva", surface="mso_direct")
        self.assertEqual(status, 200)
        # Must NOT be a surface_response — must have gone through orchestrator
        audit = body.get("audit", {})
        self.assertNotEqual(
            audit.get("result_type"), "surface_response",
            msg="Executive mso_direct request must not be handled as surface_response",
        )

    # Case 5: no surface — existing behavior preserved
    def test_no_surface_existing_behavior_preserved(self):
        status, body = self._post_chat("Hola")
        self.assertEqual(status, 200)
        # Must NOT be a surface_response (no surface provided)
        audit = body.get("audit", {})
        self.assertNotEqual(
            audit.get("result_type"), "surface_response",
            msg="Request with no surface must follow normal path",
        )


# ---------------------------------------------------------------------------
# v2 tests — expanded patterns (all observed failing phrases)
# ---------------------------------------------------------------------------

class TestNormalizeV2(unittest.TestCase):
    """_normalize must collapse internal ?!¿¡ so multi-clause inputs match cleanly."""

    def test_internal_question_mark_collapsed(self):
        self.assertEqual(_normalize("Machine operator? Cuéntame más."), "machine operator cuentame mas")

    def test_internal_exclamation_collapsed(self):
        self.assertEqual(_normalize("Hola! cómo estás"), "hola como estas")

    def test_trailing_period_stripped(self):
        self.assertEqual(_normalize("Conversemos."), "conversemos")

    def test_trailing_question_stripped(self):
        self.assertEqual(_normalize("Está activo?"), "esta activo")

    def test_multiple_internal_marks(self):
        # "hola? que tal!" -> "hola que tal"
        result = _normalize("hola? que tal!")
        self.assertEqual(result, "hola que tal")


class TestIsExecutiveV2(unittest.TestCase):
    def test_corre_is_executive(self):
        self.assertTrue(_is_executive(_normalize("Corre código")))

    def test_corre_codigo_is_executive(self):
        self.assertTrue(_is_executive("corre codigo"))

    def test_correr_is_executive(self):
        self.assertTrue(_is_executive(_normalize("Correr el script")))

    def test_non_executive_machine_operator(self):
        self.assertFalse(_is_executive(_normalize("Tienes machine operator?")))

    def test_non_executive_esta_activo(self):
        self.assertFalse(_is_executive(_normalize("Está activo?")))


class TestPatternSetsV2(unittest.TestCase):
    """All observed failing phrases must be in the correct pattern set after normalization."""

    SYSTEM_CHAT_REQUIRED = [
        "como funciona el sistema",
        "tienes machine operator",
        "machine operator cuentame mas",
        "esta activo",
        "que capacidades tienes ahora",
        "que esta corriendo",
        "analiza tus capacidades",
        "conversemos",
        # existing patterns still present
        "hola",
        "que eres",
        "que puedes hacer",
        "que agentes tienes",
        "estado del sistema",
        "como uso el mso",
    ]

    MSO_DIRECT_REQUIRED = [
        "tienes machine operator",
        "esta activo",
        "tienes acceso a las ultimas acciones del sistema",
        "puedes leer esta conversacion",
        "que agentes estan disponibles",
        "que puedes delegar",
        # existing patterns still present
        "hola",
        "quien eres",
        "que puedes hacer",
    ]

    def test_system_chat_v2_patterns_present(self):
        for pattern in self.SYSTEM_CHAT_REQUIRED:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, _SYSTEM_CHAT_CONVERSATIONAL, msg=f"missing: {pattern}")

    def test_mso_direct_v2_patterns_present(self):
        for pattern in self.MSO_DIRECT_REQUIRED:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, _MSO_DIRECT_CONVERSATIONAL, msg=f"missing: {pattern}")


class TestSystemChatV2(unittest.TestCase):
    """Every observed failing phrase for system_chat must now return a surface response."""

    def _mock_identity(self):
        m = MagicMock()
        m.to_audit_dict.return_value = {"principal": "anon"}
        return m

    def _mock_guard(self):
        m = MagicMock()
        m.to_audit_dict.return_value = {"decision": "allow"}
        return m

    def _call(self, text):
        return get_surface_behavior_response(
            surface="system_chat",
            text=text,
            context_id="ctx-v2-sys",
            identity=self._mock_identity(),
            guard_result=self._mock_guard(),
        )

    def _assert_informational(self, text, *, contains=None):
        resp = self._call(text)
        self.assertIsNotNone(resp, msg=f"'{text}' should be handled as surface_response")
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["domain"], "SYSTEM")
        self.assertEqual(resp["plan"], [])
        self.assertFalse(resp["needs_confirmation"])
        self.assertEqual(resp["audit"]["result_type"], "surface_response")
        self.assertIsInstance(resp["message"], str)
        self.assertGreater(len(resp["message"]), 5)
        if contains:
            self.assertIn(contains, resp["message"].lower(),
                          msg=f"'{text}' response should contain '{contains}'")
        return resp

    def test_como_funciona_el_sistema(self):
        self._assert_informational("Cómo funciona el sistema?")

    def test_tienes_machine_operator(self):
        resp = self._assert_informational("Tienes machine operator?")
        self.assertIn("machine operator", resp["message"].lower())

    def test_machine_operator_cuentame_mas(self):
        resp = self._assert_informational("Machine operator? Cuéntame más.")
        self.assertIn("machine operator", resp["message"].lower())

    def test_esta_activo(self):
        self._assert_informational("Está activo?")

    def test_que_capacidades_tienes_ahora(self):
        self._assert_informational("Qué capacidades tienes ahora?")

    def test_que_esta_corriendo(self):
        self._assert_informational("Qué está corriendo?")

    def test_analiza_tus_capacidades(self):
        self._assert_informational("Analiza tus capacidades.")

    def test_conversemos(self):
        self._assert_informational("Conversemos.")

    # Regression: existing phrases still work
    def test_hola_still_works(self):
        self._assert_informational("Hola")

    def test_que_puedes_hacer_still_works(self):
        self._assert_informational("qué puedes hacer")

    def test_que_agentes_tienes_still_works(self):
        self._assert_informational("qué agentes tienes")

    def test_estado_del_sistema_still_works(self):
        self._assert_informational("estado del sistema", contains="operacional")


class TestMSODirectV2(unittest.TestCase):
    """Every observed failing phrase for mso_direct must now return a surface response."""

    def _mock_identity(self):
        m = MagicMock()
        m.to_audit_dict.return_value = {"principal": "anon"}
        return m

    def _mock_guard(self):
        m = MagicMock()
        m.to_audit_dict.return_value = {"decision": "allow"}
        return m

    def _call(self, text):
        return get_surface_behavior_response(
            surface="mso_direct",
            text=text,
            context_id="ctx-v2-mso",
            identity=self._mock_identity(),
            guard_result=self._mock_guard(),
        )

    def _assert_informational(self, text, *, contains=None):
        resp = self._call(text)
        self.assertIsNotNone(resp, msg=f"'{text}' should be handled as surface_response")
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["domain"], "MSO")
        self.assertEqual(resp["plan"], [])
        self.assertFalse(resp["needs_confirmation"])
        self.assertEqual(resp["audit"]["result_type"], "surface_response")
        self.assertIsInstance(resp["message"], str)
        self.assertGreater(len(resp["message"]), 5)
        if contains:
            self.assertIn(contains, resp["message"].lower(),
                          msg=f"'{text}' response should contain '{contains}'")
        return resp

    def test_tienes_machine_operator(self):
        resp = self._assert_informational("Tienes machine operator?")
        self.assertIn("machine operator", resp["message"].lower())

    def test_esta_activo(self):
        self._assert_informational("Está activo?")

    def test_tienes_acceso_ultimas_acciones(self):
        self._assert_informational("Tienes acceso a las últimas acciones del sistema?")

    def test_puedes_leer_esta_conversacion(self):
        self._assert_informational("Puedes leer esta conversación?")

    def test_que_agentes_estan_disponibles(self):
        self._assert_informational("Qué agentes están disponibles?")

    def test_que_puedes_delegar(self):
        self._assert_informational("Qué puedes delegar?")

    # Regression: existing phrases still work
    def test_hola_still_works(self):
        resp = self._assert_informational("Hola")
        self.assertIn("mso", resp["message"].lower())

    def test_que_puedes_hacer_still_works(self):
        self._assert_informational("qué puedes hacer")

    def test_quien_eres_still_works(self):
        resp = self._assert_informational("quién eres")
        self.assertIn("mso", resp["message"].lower())

    # Executive phrases must still pass through (None)
    def test_crea_una_tarea_is_executive(self):
        self.assertIsNone(self._call("Crea una tarea"))

    def test_ejecuta_algo_is_executive(self):
        self.assertIsNone(self._call("Ejecuta algo"))

    def test_corre_codigo_is_executive(self):
        self.assertIsNone(self._call("Corre código"))

    def test_abre_navegador_is_executive(self):
        self.assertIsNone(self._call("Abre navegador"))

    def test_borra_algo_is_executive(self):
        self.assertIsNone(self._call("Borra algo"))


if __name__ == "__main__":
    unittest.main()
