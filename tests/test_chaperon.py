"""
Tests para el módulo Chaperón (chaperon.py).

Tests de:
- Detección de múltiples montos
- Fragmentos de continuación
- Confirmación requerida
- Herencia de contexto
- Generación de action_plan
"""
import unittest

from assistant_os.chaperon import (
    run_chaperon,
    confirm_action_plan,
    update_session_context,
    SessionContext,
    ActionPlan,
    FinItem,
    _extract_montos_with_positions,
    _segment_multi_expense,
    _is_continuation_fragment,
    _detect_responsable,
    _detect_categoria,
    _build_fin_item,
    _generate_confirmation_message,
)


class TestExtractMontosWithPositions(unittest.TestCase):
    """Tests para extracción de múltiples montos."""
    
    def test_single_dollar_amount(self):
        """Un solo monto en dólares."""
        montos = _extract_montos_with_positions("$25 en comida")
        self.assertEqual(len(montos), 1)
        self.assertEqual(montos[0][0], 25.0)
        self.assertEqual(montos[0][1], "USD")
    
    def test_two_dollar_amounts(self):
        """Dos montos en dólares."""
        montos = _extract_montos_with_positions("$25 en comida y $15 para conejos")
        self.assertEqual(len(montos), 2)
        self.assertEqual(montos[0][0], 25.0)
        self.assertEqual(montos[1][0], 15.0)
    
    def test_mixed_currencies(self):
        """Montos en diferentes monedas."""
        montos = _extract_montos_with_positions("$25 y B/.15")
        self.assertEqual(len(montos), 2)
        self.assertEqual(montos[0][1], "USD")
        self.assertEqual(montos[1][1], "PAB")
    
    def test_three_amounts(self):
        """Tres montos."""
        montos = _extract_montos_with_positions("$10 uber, $25 comida, $15 farmacia")
        self.assertEqual(len(montos), 3)
        self.assertEqual([m[0] for m in montos], [10.0, 25.0, 15.0])
    
    def test_decimal_amounts(self):
        """Montos con decimales."""
        montos = _extract_montos_with_positions("$25.50 y $15,75")
        self.assertEqual(len(montos), 2)
        self.assertEqual(montos[0][0], 25.50)
        self.assertEqual(montos[1][0], 15.75)
    
    def test_balboas_word(self):
        """Monto con palabra 'balboas'."""
        montos = _extract_montos_with_positions("50 balboas en taxi")
        self.assertEqual(len(montos), 1)
        self.assertEqual(montos[0][0], 50.0)
        self.assertEqual(montos[0][1], "PAB")


class TestSegmentMultiExpense(unittest.TestCase):
    """Tests para segmentación de múltiples gastos."""
    
    def test_single_expense(self):
        """Un solo gasto no se segmenta."""
        segments = _segment_multi_expense("$25 en comida")
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0], "$25 en comida")
    
    def test_two_expenses_with_y(self):
        """Dos gastos separados por 'y'."""
        segments = _segment_multi_expense("$25 en comida y $15 para conejos")
        self.assertEqual(len(segments), 2)
        self.assertIn("$25", segments[0])
        self.assertIn("$15", segments[1])
    
    def test_two_expenses_with_comma(self):
        """Dos gastos separados por coma."""
        segments = _segment_multi_expense("$25 comida, $15 farmacia")
        self.assertEqual(len(segments), 2)


class TestIsContinuationFragment(unittest.TestCase):
    """Tests para detección de fragmentos de continuación."""
    
    def test_starts_with_y(self):
        """'y 15 para conejos' es continuación."""
        self.assertTrue(_is_continuation_fragment("y 15 para los conejos"))
    
    def test_starts_with_y_monto(self):
        """'y $15' es continuación."""
        self.assertTrue(_is_continuation_fragment("y $15 para farmacia"))
    
    def test_starts_with_mas(self):
        """'más 20' es continuación."""
        self.assertTrue(_is_continuation_fragment("más 20 en taxi"))
    
    def test_starts_with_tambien(self):
        """'también 10' es continuación."""
        self.assertTrue(_is_continuation_fragment("también 10 para transporte"))
    
    def test_no_verb_but_amount(self):
        """'15 para conejos' sin verbo es continuación."""
        self.assertTrue(_is_continuation_fragment("15 para los conejos"))
    
    def test_has_verb_not_continuation(self):
        """'Gasté $25' con verbo NO es continuación."""
        self.assertFalse(_is_continuation_fragment("Gasté $25 en comida"))
    
    def test_full_sentence_not_continuation(self):
        """Oración completa NO es continuación."""
        self.assertFalse(_is_continuation_fragment("Compré $25 de comida para la casa"))


class TestDetectResponsable(unittest.TestCase):
    """Tests para detección de responsable."""
    
    def test_para_hogar(self):
        """'para la casa' => Hogar."""
        resp = _detect_responsable("comida para la casa")
        self.assertEqual(resp, "Hogar")
    
    def test_para_conejos(self):
        """'para los conejos' => Conejos."""
        resp = _detect_responsable("comida para los conejos")
        self.assertEqual(resp, "Conejos")
    
    def test_responsable_label(self):
        """'Responsable: Jorge' => Jorge."""
        resp = _detect_responsable("gasto Responsable: Jorge")
        self.assertEqual(resp, "Jorge")
    
    def test_direct_mention(self):
        """Mención directa 'Ana' => Ana."""
        resp = _detect_responsable("gasto de Ana")
        self.assertEqual(resp, "Ana")
    
    def test_alias_mascotas(self):
        """'mascotas' => Conejos."""
        resp = _detect_responsable("comida mascotas")
        self.assertEqual(resp, "Conejos")
    
    def test_no_responsable(self):
        """Sin responsable => None."""
        resp = _detect_responsable("$25 en farmacia")
        self.assertIsNone(resp)


class TestDetectCategoria(unittest.TestCase):
    """Tests para detección de categoría."""
    
    def test_comida(self):
        """'comida' => Comida."""
        cat = _detect_categoria("$25 en comida")
        self.assertEqual(cat, "Comida")
    
    def test_farmacia_salud(self):
        """'farmacia' => Salud."""
        cat = _detect_categoria("$15 farmacia")
        self.assertEqual(cat, "Salud")
    
    def test_conejos_mascotas(self):
        """'conejos' => Mascotas."""
        cat = _detect_categoria("para los conejos")
        self.assertEqual(cat, "Mascotas")
    
    def test_uber_transporte(self):
        """'uber' => Transporte."""
        cat = _detect_categoria("$10 uber")
        self.assertEqual(cat, "Transporte")
    
    def test_supermercado_comida(self):
        """'supermercado' => Comida."""
        cat = _detect_categoria("compras supermercado")
        self.assertEqual(cat, "Comida")
    
    def test_no_categoria(self):
        """Sin keywords => None."""
        cat = _detect_categoria("algo random")
        self.assertIsNone(cat)


class TestBuildFinItem(unittest.TestCase):
    """Tests para construcción de FinItem."""
    
    def test_complete_item(self):
        """Item con monto, categoría y responsable."""
        item = _build_fin_item("$25 en comida para la casa")
        self.assertEqual(item["monto"], 25.0)
        self.assertEqual(item["moneda"], "USD")
        self.assertEqual(item["categoria"], "Comida")
        self.assertEqual(item["responsable"], "Hogar")
    
    def test_inherited_currency(self):
        """Item hereda moneda si no se especifica."""
        item = _build_fin_item("15 para conejos", inherited_moneda="PAB")
        self.assertEqual(item["monto"], 15.0)
        self.assertEqual(item["moneda"], "PAB")


class TestRunChaperonMultiFin(unittest.TestCase):
    """Tests para detección de múltiples gastos."""
    
    def test_multi_expense_detected(self):
        """Múltiples montos => multi_fin."""
        response = run_chaperon(
            text="compre para la casa 25$ en comida y 15$ para los conejos",
            domain="FIN",
        )
        
        self.assertEqual(response["action_plan"]["type"], "multi_fin")
        self.assertEqual(len(response["action_plan"]["items"]), 2)
        self.assertTrue(response["action_plan"]["requires_confirmation"])
        self.assertFalse(response["should_execute"])
    
    def test_multi_expense_items(self):
        """Items de multi_fin tienen datos correctos."""
        response = run_chaperon(
            text="$25 en comida para la casa y $15 para los conejos",
            domain="FIN",
        )
        
        items = response["action_plan"]["items"]
        
        # First item
        self.assertEqual(items[0]["monto"], 25.0)
        self.assertEqual(items[0]["categoria"], "Comida")
        self.assertEqual(items[0]["responsable"], "Hogar")
        
        # Second item
        self.assertEqual(items[1]["monto"], 15.0)
        self.assertEqual(items[1]["categoria"], "Mascotas")
        self.assertEqual(items[1]["responsable"], "Conejos")
    
    def test_multi_expense_confirmation_message(self):
        """Multi_fin genera mensaje de confirmación."""
        response = run_chaperon(
            text="$25 comida y $15 farmacia",
            domain="FIN",
        )
        
        self.assertIsNotNone(response["confirmation_message"])
        self.assertIn("2 gastos", response["confirmation_message"])
        self.assertIn("USD 25", response["confirmation_message"])
        self.assertIn("USD 15", response["confirmation_message"])
    
    def test_three_expenses(self):
        """Tres gastos detectados."""
        response = run_chaperon(
            text="$10 uber, $25 almuerzo, $15 café",
            domain="FIN",
        )
        
        self.assertEqual(response["action_plan"]["type"], "multi_fin")
        self.assertEqual(len(response["action_plan"]["items"]), 3)


class TestRunChaperonContinuation(unittest.TestCase):
    """Tests para fragmentos de continuación."""
    
    def test_continuation_with_context(self):
        """Fragmento 'y 15 para conejos' con contexto FIN previo."""
        session = SessionContext(
            last_domain="FIN",
            last_moneda="USD",
            last_fecha="2026-02-25",
        )
        
        response = run_chaperon(
            text="y 15 para los conejos",
            domain="FIN",
            session_context=session,
        )
        
        self.assertEqual(response["action_plan"]["type"], "continuation")
        self.assertEqual(len(response["action_plan"]["items"]), 1)
        
        item = response["action_plan"]["items"][0]
        self.assertEqual(item["monto"], 15.0)
        self.assertEqual(item["moneda"], "USD")  # Inherited
        self.assertEqual(item["responsable"], "Conejos")
    
    def test_continuation_inherits_currency(self):
        """Continuación hereda moneda del contexto."""
        session = SessionContext(
            last_domain="FIN",
            last_moneda="PAB",
        )
        
        response = run_chaperon(
            text="y 20 más para farmacia",
            domain="FIN",
            session_context=session,
        )
        
        item = response["action_plan"]["items"][0]
        self.assertEqual(item["moneda"], "PAB")
    
    def test_continuation_without_context_is_passthrough(self):
        """Continuación sin contexto FIN previo pasa como single."""
        response = run_chaperon(
            text="y $15 para conejos",
            domain="FIN",
            session_context=None,
        )
        
        # Without prior FIN context, should detect as single expense
        self.assertIn(response["action_plan"]["type"], ["single_fin", "passthrough"])


class TestRunChaperonSingleFin(unittest.TestCase):
    """Tests para gastos únicos."""
    
    def test_single_expense_passthrough(self):
        """Gasto único => single_fin, ejecutar directamente."""
        response = run_chaperon(
            text="Gasté $25 en comida para la casa",
            domain="FIN",
        )
        
        self.assertEqual(response["action_plan"]["type"], "single_fin")
        self.assertTrue(response["should_execute"])
        self.assertFalse(response["action_plan"]["requires_confirmation"])
    
    def test_single_expense_updates_context(self):
        """Gasto único actualiza contexto de sesión."""
        response = run_chaperon(
            text="Gasté $25 en comida",
            domain="FIN",
        )
        
        context = response["action_plan"]["inherited_context"]
        self.assertEqual(context["last_domain"], "FIN")
        self.assertEqual(context["last_moneda"], "USD")


class TestRunChaperonNonFin(unittest.TestCase):
    """Tests para dominios no-FIN."""
    
    def test_non_fin_passthrough(self):
        """Dominio no-FIN => passthrough."""
        response = run_chaperon(
            text="Tengo reunión mañana",
            domain="WORK",
        )
        
        self.assertEqual(response["action_plan"]["type"], "passthrough")
        self.assertTrue(response["should_execute"])
    
    def test_energy_domain_passthrough(self):
        """Dominio ENERGY => passthrough."""
        response = run_chaperon(
            text="Estoy cansado",
            domain="ENERGY",
        )
        
        self.assertEqual(response["action_plan"]["type"], "passthrough")


class TestConfirmActionPlan(unittest.TestCase):
    """Tests para confirmación de action_plan."""
    
    def test_confirm_sets_responsable(self):
        """Confirmación puede fijar responsable."""
        plan = ActionPlan(
            type="multi_fin",
            items=[
                FinItem(monto=25.0, moneda="USD", categoria="Comida", responsable=None, descripcion=None, raw_segment="$25 comida"),
            ],
            requires_confirmation=True,
            clarification_questions=[],
            inherited_context={},
            summary_text="",
        )
        
        confirmed = confirm_action_plan(plan, {"responsable_0": "Jorge"})
        
        self.assertEqual(confirmed["items"][0]["responsable"], "Jorge")
        self.assertFalse(confirmed["requires_confirmation"])
    
    def test_confirm_clears_questions(self):
        """Confirmación limpia clarification_questions."""
        plan = ActionPlan(
            type="continuation",
            items=[FinItem(monto=15.0, moneda="USD", categoria=None, responsable=None, descripcion=None, raw_segment="15")],
            requires_confirmation=True,
            clarification_questions=[{"field": "responsable", "question": "¿Quién?", "options": []}],
            inherited_context={},
            summary_text="",
        )
        
        confirmed = confirm_action_plan(plan, {"responsable_0": "Ana"})
        
        self.assertEqual(len(confirmed["clarification_questions"]), 0)


class TestUpdateSessionContext(unittest.TestCase):
    """Tests para actualización de contexto de sesión."""
    
    def test_updates_last_domain(self):
        """El contexto actualiza last_domain."""
        response = run_chaperon("$25 comida", domain="FIN")
        
        new_context = update_session_context(None, response)
        
        self.assertEqual(new_context["last_domain"], "FIN")
    
    def test_preserves_fecha_from_previous(self):
        """El contexto preserva fecha del contexto anterior."""
        old_context = SessionContext(
            last_domain="FIN",
            last_moneda="USD",
            last_fecha="2026-02-24",
        )
        
        response = run_chaperon("$25 comida", domain="FIN")
        
        new_context = update_session_context(old_context, response)
        
        self.assertEqual(new_context["last_fecha"], "2026-02-24")


class TestGenerateConfirmationMessage(unittest.TestCase):
    """Tests para generación de mensaje de confirmación."""
    
    def test_single_item_message(self):
        """Mensaje para un item."""
        items = [FinItem(monto=25.0, moneda="USD", categoria="Comida", responsable="Hogar", descripcion=None, raw_segment="")]
        
        msg = _generate_confirmation_message(items)
        
        self.assertIn("1 gasto", msg)
        self.assertIn("USD 25.00", msg)
        self.assertIn("Comida", msg)
        self.assertIn("Hogar", msg)
    
    def test_multi_item_message(self):
        """Mensaje para múltiples items."""
        items = [
            FinItem(monto=25.0, moneda="USD", categoria="Comida", responsable="Hogar", descripcion=None, raw_segment=""),
            FinItem(monto=15.0, moneda="USD", categoria="Mascotas", responsable="Conejos", descripcion=None, raw_segment=""),
        ]
        
        msg = _generate_confirmation_message(items)
        
        self.assertIn("2 gastos", msg)
        self.assertIn("1)", msg)
        self.assertIn("2)", msg)
        self.assertIn("Confirmar?", msg)
    
    def test_missing_fields_shown_as_question_mark(self):
        """Campos faltantes se muestran como '?'."""
        items = [FinItem(monto=25.0, moneda="USD", categoria=None, responsable=None, descripcion=None, raw_segment="")]
        
        msg = _generate_confirmation_message(items)
        
        self.assertIn("?", msg)


if __name__ == "__main__":
    unittest.main()
