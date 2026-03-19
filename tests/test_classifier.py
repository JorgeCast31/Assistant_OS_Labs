"""
Tests para el clasificador determinista.
"""
import unittest

from assistant_os.classifier import (
    classify_text,
    map_intent_to_prefix,
    build_routed_command,
    detect_operational_intent,
    PREFIX_CODE,
    PREFIX_DOC,
    DOMAIN_WORK,
    DOMAIN_PRO_DIAG,
    DOMAIN_FIN,
    DOMAIN_REL,
    DOMAIN_HEALTH,
    DOMAIN_EIPROTA,
    DOMAIN_ENERGY,
    TYPE_TAREA,
    TYPE_IDEA,
    TYPE_REFLEXION,
    TYPE_PROYECTO,
    IMPACT_ECONOMICO,
    IMPACT_EMOCIONAL,
    IMPACT_OPERATIVO,
    IMPACT_INTELECTUAL,
    IMPACT_ESTRUCTURAL,
)
from assistant_os.contracts import ClassifyRequest, OP_WORK_QUERY, OP_FIN_EXPENSE, OP_COMMAND


class TestClassifierDomains(unittest.TestCase):
    """Tests para clasificación de dominios."""
    
    def _classify(self, text: str) -> dict:
        """Helper to classify text."""
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    # -------------------------------------------------------------------------
    # FIN (Finanzas personales)
    # -------------------------------------------------------------------------
    
    def test_fin_gasto_con_monto(self):
        """Gasté $25 en comida => FIN, Tarea, Económico, conf alta."""
        result = self._classify("Gasté $25 en comida")
        
        self.assertEqual(result["domain"], DOMAIN_FIN)
        self.assertEqual(result["type"], TYPE_TAREA)  # empieza con verbo
        self.assertEqual(result["impact"], IMPACT_ECONOMICO)
        self.assertGreaterEqual(result["confidence"], 0.70)
        self.assertFalse(result["needs_confirmation"])
    
    def test_fin_presupuesto(self):
        """Mensaje sobre presupuesto => FIN."""
        result = self._classify("Revisar el presupuesto mensual")
        
        self.assertEqual(result["domain"], DOMAIN_FIN)
        self.assertEqual(result["impact"], IMPACT_ECONOMICO)
    
    def test_fin_dolares(self):
        """Mensaje con dólares => FIN."""
        result = self._classify("Tengo 500 dólares ahorrados")
        
        self.assertEqual(result["domain"], DOMAIN_FIN)
    
    def test_fin_deuda(self):
        """Mensaje sobre deuda => FIN."""
        result = self._classify("Pagar deuda de la tarjeta")
        
        self.assertEqual(result["domain"], DOMAIN_FIN)
    
    # -------------------------------------------------------------------------
    # ENERGY (Meta-sistema)
    # -------------------------------------------------------------------------
    
    def test_energy_saturado(self):
        """Estoy saturado, demasiados frentes abiertos => ENERGY."""
        result = self._classify("Estoy saturado, demasiados frentes abiertos")
        
        self.assertEqual(result["domain"], DOMAIN_ENERGY)
        self.assertEqual(result["impact"], IMPACT_ESTRUCTURAL)
    
    def test_energy_prioridad(self):
        """Mensaje sobre priorizar => ENERGY."""
        result = self._classify("Necesito priorizar mis tareas")
        
        self.assertEqual(result["domain"], DOMAIN_ENERGY)
    
    def test_energy_carga_cognitiva(self):
        """Mensaje sobre carga cognitiva => ENERGY."""
        result = self._classify("Mi carga cognitiva está muy alta")
        
        self.assertEqual(result["domain"], DOMAIN_ENERGY)
    
    def test_energy_modo_bajo(self):
        """Mensaje sobre modo bajo => ENERGY."""
        result = self._classify("Estoy en modo bajo hoy")
        
        self.assertEqual(result["domain"], DOMAIN_ENERGY)
    
    def test_energy_meta_sistema(self):
        """Mensaje sobre meta-sistema => ENERGY."""
        result = self._classify("Necesito revisar el meta-sistema")
        
        self.assertEqual(result["domain"], DOMAIN_ENERGY)
    
    # -------------------------------------------------------------------------
    # EIPROTA (TTI, filosofía, arte)
    # -------------------------------------------------------------------------
    
    def test_eiprota_tensores(self):
        """Necesito avanzar módulo de tensores TTI => EIPROTA."""
        result = self._classify("Necesito avanzar módulo de tensores TTI")
        
        self.assertEqual(result["domain"], DOMAIN_EIPROTA)
        self.assertEqual(result["impact"], IMPACT_INTELECTUAL)
    
    def test_eiprota_tti(self):
        """Mensaje sobre TTI => EIPROTA."""
        result = self._classify("Continuar desarrollo de TTI")
        
        self.assertEqual(result["domain"], DOMAIN_EIPROTA)
    
    def test_eiprota_filosofia(self):
        """Mensaje sobre filosofía => EIPROTA."""
        result = self._classify("Escribir ensayo de filosofía")
        
        self.assertEqual(result["domain"], DOMAIN_EIPROTA)
    
    def test_eiprota_ontologico(self):
        """Mensaje ontológico => EIPROTA."""
        result = self._classify("Modelo ontológico del campo")
        
        self.assertEqual(result["domain"], DOMAIN_EIPROTA)
    
    def test_eiprota_eiprota(self):
        """Mensaje sobre EiProta => EIPROTA."""
        result = self._classify("Revisar EiProta")
        
        self.assertEqual(result["domain"], DOMAIN_EIPROTA)
    
    # -------------------------------------------------------------------------
    # WORK (Trabajo institucional)
    # -------------------------------------------------------------------------
    
    def test_work_poe(self):
        """Actualizar POE incubadoras => WORK."""
        result = self._classify("Actualizar POE incubadoras")
        
        self.assertEqual(result["domain"], DOMAIN_WORK)
        self.assertEqual(result["impact"], IMPACT_ESTRUCTURAL)  # POE es proceso
    
    def test_work_cellab(self):
        """Mensaje sobre CELLAB => WORK."""
        result = self._classify("Reunión con equipo de CELLAB")
        
        self.assertEqual(result["domain"], DOMAIN_WORK)
    
    def test_work_calibracion(self):
        """Mensaje sobre calibración => WORK."""
        result = self._classify("Programar calibración de equipos")
        
        self.assertEqual(result["domain"], DOMAIN_WORK)
    
    def test_work_auditoria(self):
        """Mensaje sobre auditoría => WORK."""
        result = self._classify("Preparar documentos para auditoría ISO")
        
        self.assertEqual(result["domain"], DOMAIN_WORK)
    
    def test_work_incubadora(self):
        """Mensaje sobre incubadora => WORK."""
        result = self._classify("Revisar incubadoras del laboratorio")
        
        self.assertEqual(result["domain"], DOMAIN_WORK)
    
    # -------------------------------------------------------------------------
    # PRO_DIAG (Proyecto diagnóstico)
    # -------------------------------------------------------------------------
    
    def test_prodiag_saas_diagnostico(self):
        """Propuesta SaaS diagnóstico empresarial pricing => PRO_DIAG."""
        result = self._classify("Propuesta SaaS diagnóstico empresarial pricing")
        
        self.assertEqual(result["domain"], DOMAIN_PRO_DIAG)
    
    def test_prodiag_cliente(self):
        """Mensaje sobre cliente => PRO_DIAG."""
        result = self._classify("Enviar propuesta al cliente")
        
        self.assertEqual(result["domain"], DOMAIN_PRO_DIAG)
    
    def test_prodiag_consultoria(self):
        """Mensaje sobre consultoría => PRO_DIAG."""
        result = self._classify("Proyecto de consultoría empresarial")
        
        self.assertEqual(result["domain"], DOMAIN_PRO_DIAG)
    
    def test_prodiag_entregable(self):
        """Mensaje sobre entregable => PRO_DIAG."""
        result = self._classify("Preparar entregable para cliente")
        
        self.assertEqual(result["domain"], DOMAIN_PRO_DIAG)
    
    # -------------------------------------------------------------------------
    # REL (Relaciones)
    # -------------------------------------------------------------------------
    
    def test_rel_hablar_con_ana(self):
        """Hablar con Ana sobre X => REL."""
        result = self._classify("Hablar con Ana sobre la cena")
        
        self.assertEqual(result["domain"], DOMAIN_REL)
        self.assertEqual(result["impact"], IMPACT_EMOCIONAL)
    
    def test_rel_novia(self):
        """Mensaje sobre novia => REL."""
        result = self._classify("Planear algo con mi novia")
        
        self.assertEqual(result["domain"], DOMAIN_REL)
    
    def test_rel_mama(self):
        """Mensaje sobre mamá => REL."""
        result = self._classify("Llamar a mamá")
        
        self.assertEqual(result["domain"], DOMAIN_REL)
    
    def test_rel_amigo(self):
        """Mensaje sobre amigo => REL."""
        result = self._classify("Salir con amigos el viernes")
        
        self.assertEqual(result["domain"], DOMAIN_REL)
    
    def test_rel_familia(self):
        """Mensaje sobre familia => REL."""
        result = self._classify("Reunión familiar el domingo")
        
        self.assertEqual(result["domain"], DOMAIN_REL)
    
    # -------------------------------------------------------------------------
    # HEALTH (Salud)
    # -------------------------------------------------------------------------
    
    def test_health_dormir_mal(self):
        """Dormí mal, ansiedad => HEALTH."""
        result = self._classify("Dormí mal, ansiedad")
        
        self.assertEqual(result["domain"], DOMAIN_HEALTH)
        self.assertEqual(result["impact"], IMPACT_EMOCIONAL)
    
    def test_health_gym(self):
        """Mensaje sobre gym => HEALTH."""
        result = self._classify("Ir al gym hoy")
        
        self.assertEqual(result["domain"], DOMAIN_HEALTH)
    
    def test_health_terapia(self):
        """Mensaje sobre terapia => HEALTH."""
        result = self._classify("Agendar cita de terapia")
        
        self.assertEqual(result["domain"], DOMAIN_HEALTH)
    
    def test_health_sueno(self):
        """Mensaje sobre sueño => HEALTH."""
        result = self._classify("Mejorar calidad del sueño")
        
        self.assertEqual(result["domain"], DOMAIN_HEALTH)
    
    def test_health_rutina_operativo(self):
        """Mensaje sobre rutina => HEALTH con impacto operativo."""
        result = self._classify("Cambiar rutina de ejercicio")
        
        self.assertEqual(result["domain"], DOMAIN_HEALTH)
        self.assertEqual(result["impact"], IMPACT_OPERATIVO)


class TestClassifierTypes(unittest.TestCase):
    """Tests para detección de tipo."""
    
    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    def test_type_tarea_crear(self):
        """Crear X => Tarea."""
        result = self._classify("Crear documento de requisitos")
        self.assertEqual(result["type"], TYPE_TAREA)
    
    def test_type_tarea_revisar(self):
        """Revisar X => Tarea."""
        result = self._classify("Revisar el código")
        self.assertEqual(result["type"], TYPE_TAREA)
    
    def test_type_tarea_actualizar(self):
        """Actualizar X => Tarea."""
        result = self._classify("Actualizar POE")
        self.assertEqual(result["type"], TYPE_TAREA)
    
    def test_type_proyecto(self):
        """Texto con proyecto => Proyecto."""
        result = self._classify("Definir el proyecto de consultoría")
        self.assertEqual(result["type"], TYPE_PROYECTO)
    
    def test_type_proyecto_roadmap(self):
        """Texto con roadmap => Proyecto."""
        result = self._classify("Crear roadmap del producto")
        self.assertEqual(result["type"], TYPE_PROYECTO)
    
    def test_type_reflexion(self):
        """Texto con pienso => Reflexión."""
        result = self._classify("Pienso que debería reorganizar")
        self.assertEqual(result["type"], TYPE_REFLEXION)
    
    def test_type_reflexion_me_pregunto(self):
        """Texto con me pregunto => Reflexión."""
        result = self._classify("Me pregunto si esto es correcto")
        self.assertEqual(result["type"], TYPE_REFLEXION)
    
    def test_type_idea_default(self):
        """Texto sin indicadores => Idea."""
        result = self._classify("Nueva funcionalidad para el sistema")
        self.assertEqual(result["type"], TYPE_IDEA)


class TestClassifierConfidence(unittest.TestCase):
    """Tests para confidence y needs_confirmation."""
    
    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    def test_high_confidence_strong_match(self):
        """Match fuerte => confidence alto, no necesita confirmación."""
        result = self._classify("TTI tensores ontológico")
        
        self.assertGreaterEqual(result["confidence"], 0.80)
        self.assertFalse(result["needs_confirmation"])
    
    def test_low_confidence_ambiguous(self):
        """Texto ambiguo => confidence bajo, necesita confirmación."""
        result = self._classify("Algo nuevo")
        
        self.assertLessEqual(result["confidence"], 0.70)
        self.assertTrue(result["needs_confirmation"])
    
    def test_alternatives_present(self):
        """Debe incluir alternativas cuando hay múltiples matches."""
        result = self._classify("Gasté dinero en gym")
        
        # Should have alternatives
        self.assertIsInstance(result["alternatives"], list)
        
        # If has alternatives, check structure
        if result["alternatives"]:
            alt = result["alternatives"][0]
            self.assertIn("domain", alt)
            self.assertIn("confidence", alt)


class TestClassifierTiebreakers(unittest.TestCase):
    """Tests para reglas de tiebreaker."""
    
    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    def test_fin_wins_with_money(self):
        """FIN gana cuando hay monto aunque haya emoción."""
        result = self._classify("Me siento mal por haber gastado $50")
        
        self.assertEqual(result["domain"], DOMAIN_FIN)
    
    def test_energy_wins_meta_system(self):
        """ENERGY gana cuando es reflexión meta sobre el sistema."""
        result = self._classify("El orquestador necesita más priorización")
        
        self.assertEqual(result["domain"], DOMAIN_ENERGY)
    
    def test_eiprota_vs_energy(self):
        """EIPROTA gana para TTI/arte si no es meta-sistema."""
        result = self._classify("Módulo de tensores TTI campo")
        
        self.assertEqual(result["domain"], DOMAIN_EIPROTA)


class TestClassifierNextAction(unittest.TestCase):
    """Tests para next_action."""
    
    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    def test_next_action_not_empty(self):
        """next_action nunca debe estar vacío."""
        result = self._classify("Hacer algo")
        
        self.assertIsInstance(result["next_action"], str)
        self.assertTrue(len(result["next_action"]) > 0)
    
    def test_next_action_fin(self):
        """FIN tiene next_action relacionado a tracker."""
        result = self._classify("Gasté $25")
        
        self.assertIn("financiero", result["next_action"].lower())


class TestClassifierCognitiveLoad(unittest.TestCase):
    """Tests para carga cognitiva."""
    
    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    def test_cognitive_alta_complex(self):
        """Texto complejo con tensores => Alta."""
        result = self._classify("Desarrollar modelo de tensores ontológicos")
        
        self.assertEqual(result["cognitive_load"], "Alta")
    
    def test_cognitive_baja_simple(self):
        """Texto simple corto => Baja."""
        result = self._classify("Gym")
        
        self.assertEqual(result["cognitive_load"], "Baja")


class TestClassifierReason(unittest.TestCase):
    """Tests para reason (debug info)."""
    
    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    def test_reason_present(self):
        """reason siempre debe estar presente."""
        result = self._classify("Test")
        
        self.assertIn("reason", result)
        self.assertIsInstance(result["reason"], str)


class TestMoneyOverride(unittest.TestCase):
    """Tests para override de FIN por indicadores monetarios."""
    
    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    def test_gasto_50_software_tti_goes_to_fin(self):
        """gasto $50 en software para TTI => FIN (dinero gana sobre TTI)."""
        result = self._classify("gasto $50 en software para TTI")
        
        self.assertEqual(result["domain"], DOMAIN_FIN)
        self.assertGreaterEqual(result["confidence"], 0.95)
        self.assertIn("override:money->FIN", result["reason"])
    
    def test_balboa_currency(self):
        """B/.25 => FIN."""
        result = self._classify("Pagué B/.25 en el taxi")
        
        self.assertEqual(result["domain"], DOMAIN_FIN)
        self.assertGreaterEqual(result["confidence"], 0.95)
    
    def test_usd_currency(self):
        """USD 100 => FIN."""
        result = self._classify("Me enviaron USD 100")
        
        self.assertEqual(result["domain"], DOMAIN_FIN)
        self.assertGreaterEqual(result["confidence"], 0.95)
    
    def test_us_dollar_sign(self):
        """US$50 => FIN."""
        result = self._classify("Costó US$50 el libro")
        
        self.assertEqual(result["domain"], DOMAIN_FIN)
        self.assertGreaterEqual(result["confidence"], 0.95)
    
    def test_dolar_word(self):
        """dólares => FIN."""
        result = self._classify("Necesito 200 dólares para el viaje")
        
        self.assertEqual(result["domain"], DOMAIN_FIN)
        self.assertGreaterEqual(result["confidence"], 0.95)
    
    def test_balboa_word(self):
        """balboas => FIN."""
        result = self._classify("Tengo 50 balboas en efectivo")
        
        self.assertEqual(result["domain"], DOMAIN_FIN)
        self.assertGreaterEqual(result["confidence"], 0.95)
    
    def test_shell_variable_excluded(self):
        """$PATH no debe activar FIN override."""
        result = self._classify("Revisar el $PATH del sistema")
        
        self.assertNotEqual(result["domain"], DOMAIN_FIN)
    
    def test_powershell_excluded(self):
        """PowerShell context excluido."""
        result = self._classify("Abrir PowerShell y escribir $env:HOME")
        
        self.assertNotEqual(result["domain"], DOMAIN_FIN)
    
    def test_bash_excluded(self):
        """bash context excluido."""
        result = self._classify("En bash usar export $VAR")
        
        self.assertNotEqual(result["domain"], DOMAIN_FIN)
    
    def test_shell_variable_uppercase(self):
        """$HOME es variable de shell, no dinero."""
        result = self._classify("Configurar $HOME en el terminal")
        
        self.assertNotEqual(result["domain"], DOMAIN_FIN)


class TestTTIAttractor(unittest.TestCase):
    """Tests para atractor TTI/EIPROTA."""
    
    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    def test_avanzar_tensores_tti(self):
        """avanzar tensores TTI => EIPROTA."""
        result = self._classify("avanzar tensores TTI")
        
        self.assertEqual(result["domain"], DOMAIN_EIPROTA)
        self.assertGreaterEqual(result["confidence"], 0.90)
        self.assertIn("override:tti->EIPROTA", result["reason"])
    
    def test_campos_ontologicos(self):
        """campos ontológicos => EIPROTA."""
        result = self._classify("Modelar los campos ontológicos del sistema")
        
        self.assertEqual(result["domain"], DOMAIN_EIPROTA)
        self.assertGreaterEqual(result["confidence"], 0.90)
    
    def test_tensor_de_intencion(self):
        """Tensor de Intención => EIPROTA."""
        result = self._classify("Trabajar en el Tensor de Intención")
        
        self.assertEqual(result["domain"], DOMAIN_EIPROTA)
        self.assertGreaterEqual(result["confidence"], 0.90)
    
    def test_eiprota_keyword(self):
        """EiProta => EIPROTA."""
        result = self._classify("Avanzar el proyecto EiProta")
        
        self.assertEqual(result["domain"], DOMAIN_EIPROTA)
        self.assertGreaterEqual(result["confidence"], 0.90)
    
    def test_espacio_tensorial(self):
        """espacio tensorial => EIPROTA."""
        result = self._classify("Definir el espacio tensorial del modelo")
        
        self.assertEqual(result["domain"], DOMAIN_EIPROTA)
        self.assertGreaterEqual(result["confidence"], 0.90)
    
    def test_money_beats_tti(self):
        """Dinero gana sobre TTI."""
        result = self._classify("Invertir $500 en el proyecto TTI")
        
        self.assertEqual(result["domain"], DOMAIN_FIN)
        self.assertIn("override:money->FIN", result["reason"])


class TestIntentToPrefix(unittest.TestCase):
    """Tests para mapeo de intención a prefijo de comando."""
    
    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    def test_fin_maps_to_doc(self):
        """FIN domain => DOC prefix."""
        text = "Gasté $50 en comida"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_FIN)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_DOC)
    
    def test_rel_maps_to_doc(self):
        """REL domain => DOC prefix."""
        text = "Llamar a mi mamá"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_REL)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_DOC)
    
    def test_health_maps_to_doc(self):
        """HEALTH domain => DOC prefix."""
        text = "Ir al gym mañana"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_HEALTH)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_DOC)
    
    def test_energy_maps_to_doc(self):
        """ENERGY domain => DOC prefix."""
        text = "Revisar frentes abiertos y priorizar"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_ENERGY)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_DOC)
    
    def test_eiprota_modulo_maps_to_code(self):
        """EIPROTA with 'módulo' => CODE prefix."""
        text = "Crear módulo de tensores TTI"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_EIPROTA)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_CODE)
    
    def test_eiprota_implementar_maps_to_code(self):
        """EIPROTA with 'implementar' => CODE prefix."""
        text = "Implementar el modelo de tensores TTI"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_EIPROTA)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_CODE)
    
    def test_eiprota_programar_maps_to_code(self):
        """EIPROTA with 'programar' => CODE prefix."""
        text = "Programar simulación de tensores"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_EIPROTA)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_CODE)
    
    def test_eiprota_simular_maps_to_code(self):
        """EIPROTA with 'simular' => CODE prefix."""
        text = "Simular campos ontológicos"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_EIPROTA)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_CODE)
    
    def test_eiprota_no_code_keyword_maps_to_doc(self):
        """EIPROTA without code keywords => DOC prefix."""
        text = "Reflexionar sobre el TTI y la ontología"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_EIPROTA)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_DOC)
    
    def test_work_script_maps_to_code(self):
        """WORK with 'script' => CODE prefix."""
        text = "Crear script para el laboratorio"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_WORK)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_CODE)
    
    def test_work_automatizar_maps_to_code(self):
        """WORK with 'automatizar' => CODE prefix."""
        text = "Automatizar proceso del QC en laboratorio"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_WORK)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_CODE)
    
    def test_work_python_maps_to_code(self):
        """WORK with 'python' => CODE prefix."""
        text = "Hacer script en python para la incubadora"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_WORK)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_CODE)
    
    def test_work_no_code_keyword_maps_to_doc(self):
        """WORK without code keywords => DOC prefix."""
        text = "Revisar el POE del laboratorio"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_WORK)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_DOC)
    
    def test_pro_diag_api_maps_to_code(self):
        """PRO_DIAG with 'api' => CODE prefix."""
        text = "Crear API para el cliente SaaS"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_PRO_DIAG)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_CODE)
    
    def test_pro_diag_no_code_keyword_maps_to_doc(self):
        """PRO_DIAG without code keywords => DOC prefix."""
        text = "Preparar propuesta para el cliente"
        intent = self._classify(text)
        
        self.assertEqual(intent["domain"], DOMAIN_PRO_DIAG)
        self.assertEqual(map_intent_to_prefix(text, intent), PREFIX_DOC)
    
    def test_none_intent_maps_to_doc(self):
        """None intent => DOC prefix."""
        result = map_intent_to_prefix("cualquier texto", None)
        
        self.assertEqual(result, PREFIX_DOC)


class TestBuildRoutedCommand(unittest.TestCase):
    """Tests para construcción de comando enrutado."""
    
    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    def test_fin_builds_doc_command(self):
        """FIN => DOC: prefix."""
        text = "Gasté $50 en comida"
        intent = self._classify(text)
        
        result = build_routed_command(text, intent)
        
        self.assertEqual(result, f"DOC: {text}")
    
    def test_eiprota_code_builds_code_command(self):
        """EIPROTA + código => CODE: prefix."""
        text = "Implementar módulo de tensores TTI"
        intent = self._classify(text)
        
        result = build_routed_command(text, intent)
        
        self.assertEqual(result, f"CODE: {text}")
    
    def test_eiprota_doc_builds_doc_command(self):
        """EIPROTA sin código => DOC: prefix."""
        text = "Reflexionar sobre el TTI"
        intent = self._classify(text)
        
        result = build_routed_command(text, intent)
        
        self.assertEqual(result, f"DOC: {text}")


# ---------------------------------------------------------------------------
# OPERATIONAL INTENT TESTS (new architecture)
# ---------------------------------------------------------------------------

class TestOperationalIntentDetection(unittest.TestCase):
    """Tests for operational intent detection layer (routing priority)."""
    
    def _classify(self, text: str) -> dict:
        """Helper to classify text."""
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    def test_tareas_de_consultoria_returns_work_query(self):
        """'tareas de consultoria?' => operation=WORK_QUERY (not FIN_EXPENSE)."""
        result = self._classify("tareas de consultoria?")
        
        self.assertEqual(result["operation"], "WORK_QUERY")
        # Semantic domain may be PRO_DIAG but operation should be WORK_QUERY
        self.assertIn(result["domain"], [DOMAIN_PRO_DIAG, DOMAIN_WORK])
    
    def test_estado_sobre_tareas_returns_work_query(self):
        """'estado sobre tareas de consultoría' => WORK_QUERY."""
        result = self._classify("estado sobre tareas de consultoría")
        
        self.assertEqual(result["operation"], "WORK_QUERY")
    
    def test_que_tengo_pendiente_returns_work_query(self):
        """'qué tengo pendiente' => WORK_QUERY."""
        result = self._classify("qué tengo pendiente")
        
        self.assertEqual(result["operation"], "WORK_QUERY")
    
    def test_tareas_eiprota_returns_work_query(self):
        """'tareas eiprota' => WORK_QUERY (not confused with EIPROTA domain)."""
        result = self._classify("tareas eiprota")
        
        self.assertEqual(result["operation"], "WORK_QUERY")
    
    def test_gasto_5_en_metro_returns_fin_expense(self):
        """'gasto 5 en metro' => FIN_EXPENSE (not WORK_QUERY)."""
        result = self._classify("gasto 5 en metro")
        
        self.assertEqual(result["operation"], "FIN_EXPENSE")
        self.assertEqual(result["domain"], DOMAIN_FIN)
    
    def test_idea_sobre_consultoria_returns_command(self):
        """'idea sobre consultoria digital' => COMMAND (not WORK_QUERY)."""
        result = self._classify("idea sobre consultoria digital")
        
        self.assertEqual(result["operation"], "COMMAND")
        # Should classify as PRO_DIAG
        self.assertEqual(result["domain"], DOMAIN_PRO_DIAG)
    
    def test_inbox_returns_work_query(self):
        """'inbox' => WORK_QUERY."""
        result = self._classify("inbox")
        
        self.assertEqual(result["operation"], "WORK_QUERY")
    
    def test_next_returns_work_query(self):
        """'next' => WORK_QUERY."""
        result = self._classify("next")
        
        self.assertEqual(result["operation"], "WORK_QUERY")
    
    def test_urgentes_returns_work_query(self):
        """'urgentes' => WORK_QUERY."""
        result = self._classify("urgentes")
        
        self.assertEqual(result["operation"], "WORK_QUERY")
    
    def test_pague_50_returns_fin_expense(self):
        """'pagué 50 pesos' => FIN_EXPENSE."""
        result = self._classify("pagué 50 pesos")
        
        self.assertEqual(result["operation"], "FIN_EXPENSE")
    
    def test_reflexion_tti_returns_command(self):
        """'reflexionar sobre el TTI' => COMMAND (no task/expense patterns)."""
        result = self._classify("reflexionar sobre el TTI")
        
        self.assertEqual(result["operation"], "COMMAND")


class TestOperationalIntentReason(unittest.TestCase):
    """Tests that operation is included in reason field for debugging."""
    
    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)
    
    def test_work_query_in_reason(self):
        """operation=WORK_QUERY should appear in reason."""
        result = self._classify("tareas de consultoria?")
        
        self.assertIn("op:WORK_QUERY", result["reason"])
    
    def test_fin_expense_in_reason(self):
        """operation=FIN_EXPENSE should appear in reason."""
        result = self._classify("gasto 10 en café")
        
        self.assertIn("op:FIN_EXPENSE", result["reason"])
    
    def test_command_not_in_reason(self):
        """operation=COMMAND (default) should NOT appear in reason."""
        result = self._classify("reflexionar sobre el TTI")
        
        self.assertNotIn("op:COMMAND", result["reason"])


class TestFinOperationDomainOverride(unittest.TestCase):
    """
    Regression tests — FIN_EXPENSE operation must force domain=FIN even when
    the input has no currency symbol ($, B/., USD, etc.).
    """

    def _classify(self, text: str) -> dict:
        req: ClassifyRequest = {"text": text}
        return classify_text(req)

    def test_compre_cafe_efectivo_routes_fin(self):
        """'compré café en efectivo' → domain=FIN, operation=FIN_EXPENSE, needs_confirmation=False."""
        result = self._classify("compré café en efectivo")
        self.assertEqual(result["domain"], "FIN")
        self.assertEqual(result["operation"], "FIN_EXPENSE")
        self.assertFalse(result["needs_confirmation"],
                         "FIN_EXPENSE must not show confirmation panel")

    def test_compre_almuerzo_tarjeta_routes_fin(self):
        """'compré almuerzo con tarjeta' → domain=FIN, operation=FIN_EXPENSE."""
        result = self._classify("compré almuerzo con tarjeta")
        self.assertEqual(result["domain"], "FIN")
        self.assertEqual(result["operation"], "FIN_EXPENSE")
        self.assertFalse(result["needs_confirmation"])

    def test_compre_pan_routes_fin(self):
        """'compré pan con tarjeta' → domain=FIN."""
        result = self._classify("compré pan con tarjeta")
        self.assertEqual(result["domain"], "FIN")

    def test_confidence_high_after_fin_op_override(self):
        """FIN_EXPENSE operation override must yield confidence >= 0.90."""
        result = self._classify("compré café en efectivo")
        self.assertGreaterEqual(result["confidence"], 0.90)

    def test_fin_op_override_in_reason(self):
        """Reason string must include override:fin_op->FIN for purchase verbs."""
        result = self._classify("compré café en efectivo")
        self.assertIn("override:fin_op->FIN", result["reason"])

    def test_gaste_sin_simbolo_routes_fin(self):
        """'gasté en taxi' (no $ symbol) → domain=FIN, no confirmation."""
        result = self._classify("gasté en taxi")
        self.assertEqual(result["domain"], "FIN")
        self.assertEqual(result["operation"], "FIN_EXPENSE")
        self.assertFalse(result["needs_confirmation"])

    def test_money_symbol_still_routes_fin(self):
        """Inputs with $ already routed to FIN must not be broken by the new override."""
        result = self._classify("$25 en almuerzo")
        self.assertEqual(result["domain"], "FIN")
        self.assertEqual(result["operation"], "FIN_EXPENSE")


if __name__ == "__main__":
    unittest.main()
