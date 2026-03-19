"""
Tests para el módulo FIN de gastos (fin_expense.py).

Tests de extracción de:
- monto y moneda
- fecha
- responsable
- itbms
- categoría
- descripción
"""
import unittest
from datetime import date, timedelta

from assistant_os.fin_expense import (
    parse_expense,
    _extract_monto,
    _extract_fecha,
    _extract_responsable,
    _extract_itbms,
    _extract_categoria,
    _extract_descripcion,
    _get_panama_date,
    ExpenseRequest,
)


class TestExtractMonto(unittest.TestCase):
    """Tests para extracción de monto y moneda."""
    
    def test_dollar_sign_simple(self):
        """$50 => 50.0 USD."""
        monto, moneda = _extract_monto("Gasté $50 en comida")
        self.assertEqual(monto, 50.0)
        self.assertEqual(moneda, "USD")
    
    def test_dollar_sign_with_decimals(self):
        """$50.75 => 50.75 USD."""
        monto, moneda = _extract_monto("Pagué $50.75")
        self.assertEqual(monto, 50.75)
        self.assertEqual(moneda, "USD")
    
    def test_dollar_sign_with_space(self):
        """$ 100 => 100.0 USD."""
        monto, moneda = _extract_monto("Costo $ 100")
        self.assertEqual(monto, 100.0)
        self.assertEqual(moneda, "USD")
    
    def test_balboa_sign(self):
        """B/.50 => 50.0 PAB."""
        monto, moneda = _extract_monto("B/.50 en taxi")
        self.assertEqual(monto, 50.0)
        self.assertEqual(moneda, "PAB")
    
    def test_balboa_with_space(self):
        """B/. 12.35 => 12.35 PAB."""
        monto, moneda = _extract_monto("B/. 12.35 supermercado")
        self.assertEqual(monto, 12.35)
        self.assertEqual(moneda, "PAB")
    
    def test_usd_prefix(self):
        """USD 100 => 100.0 USD."""
        monto, moneda = _extract_monto("Me enviaron USD 100")
        self.assertEqual(monto, 100.0)
        self.assertEqual(moneda, "USD")
    
    def test_us_dollar_sign(self):
        """US$50 => 50.0 USD."""
        monto, moneda = _extract_monto("Costó US$50")
        self.assertEqual(monto, 50.0)
        self.assertEqual(moneda, "USD")
    
    def test_dolares_word(self):
        """50 dólares => 50.0 USD."""
        monto, moneda = _extract_monto("Pagué 50 dólares")
        self.assertEqual(monto, 50.0)
        self.assertEqual(moneda, "USD")
    
    def test_dolares_word_no_accent(self):
        """50 dolares => 50.0 USD."""
        monto, moneda = _extract_monto("Pagué 50 dolares")
        self.assertEqual(monto, 50.0)
        self.assertEqual(moneda, "USD")
    
    def test_balboas_word(self):
        """50 balboas => 50.0 PAB."""
        monto, moneda = _extract_monto("Tengo 50 balboas")
        self.assertEqual(monto, 50.0)
        self.assertEqual(moneda, "PAB")
    
    def test_comma_as_decimal(self):
        """$50,75 => 50.75 USD (coma como decimal)."""
        monto, moneda = _extract_monto("$50,75 en almuerzo")
        self.assertEqual(monto, 50.75)
        self.assertEqual(moneda, "USD")
    
    def test_no_amount(self):
        """Sin monto => None."""
        monto, moneda = _extract_monto("Algo sin número")
        # Debe retornar None para monto
        self.assertIsNone(monto)


class TestExtractFecha(unittest.TestCase):
    """Tests para extracción de fecha."""
    
    def test_default_today(self):
        """Sin fecha explícita => hoy (Panama timezone)."""
        fecha = _extract_fecha("Gasté $50")
        self.assertEqual(fecha, _get_panama_date().isoformat())
    
    def test_ayer(self):
        """'ayer' => fecha de ayer (Panama timezone)."""
        fecha = _extract_fecha("Ayer compré comida")
        expected = (_get_panama_date() - timedelta(days=1)).isoformat()
        self.assertEqual(fecha, expected)
    
    def test_date_format_slash(self):
        """24/02/2026 => 2026-02-24."""
        fecha = _extract_fecha("El 24/02/2026 pagué")
        self.assertEqual(fecha, "2026-02-24")
    
    def test_date_format_iso(self):
        """2026-02-24 => 2026-02-24."""
        fecha = _extract_fecha("Fecha 2026-02-24")
        self.assertEqual(fecha, "2026-02-24")


class TestExtractResponsable(unittest.TestCase):
    """Tests para extracción de responsable con alias y ambiguedad."""
    
    def test_ana(self):
        """'Ana' => Ana (canonical)."""
        resp, matches = _extract_responsable("pagué $50 cena, Ana")
        self.assertEqual(resp, "Ana")
        self.assertEqual(matches, ["Ana"])
    
    def test_jorge(self):
        """'Jorge' => Jorge."""
        resp, matches = _extract_responsable("Jorge pagó el taxi")
        self.assertEqual(resp, "Jorge")
        self.assertEqual(matches, ["Jorge"])
    
    def test_eiprota(self):
        """'eiprota' => eiProta (canonical case)."""
        resp, matches = _extract_responsable("eiprota software")
        self.assertEqual(resp, "eiProta")
        self.assertEqual(matches, ["eiProta"])
    
    def test_hogar(self):
        """'hogar' => Hogar."""
        resp, matches = _extract_responsable("compras hogar")
        self.assertEqual(resp, "Hogar")
        self.assertEqual(matches, ["Hogar"])
    
    def test_conejos(self):
        """'conejos' => Conejos."""
        resp, matches = _extract_responsable("comida conejos $15")
        self.assertEqual(resp, "Conejos")
        self.assertEqual(matches, ["Conejos"])
    
    def test_proyectos(self):
        """'proyectos' => Proyectos."""
        resp, matches = _extract_responsable("software proyectos $200")
        self.assertEqual(resp, "Proyectos")
        self.assertEqual(matches, ["Proyectos"])
    
    def test_unknown(self):
        """Sin responsable => unknown."""
        resp, matches = _extract_responsable("gasté $50")
        self.assertEqual(resp, "unknown")
        self.assertEqual(matches, [])
    
    def test_case_insensitive(self):
        """'ANA' => Ana (case insensitive)."""
        resp, matches = _extract_responsable("ANA pagó")
        self.assertEqual(resp, "Ana")
        self.assertEqual(matches, ["Ana"])
    
    # Alias tests
    def test_alias_yo_to_jorge(self):
        """'yo' => Jorge."""
        resp, matches = _extract_responsable("yo pagué $30")
        self.assertEqual(resp, "Jorge")
        self.assertEqual(matches, ["Jorge"])
    
    def test_alias_conejo_singular(self):
        """'conejo' => Conejos."""
        resp, matches = _extract_responsable("comida conejo")
        self.assertEqual(resp, "Conejos")
        self.assertEqual(matches, ["Conejos"])
    
    def test_alias_mascotas(self):
        """'mascotas' => Conejos."""
        resp, matches = _extract_responsable("veterinario mascotas $80")
        self.assertEqual(resp, "Conejos")
        self.assertEqual(matches, ["Conejos"])
    
    def test_alias_casa(self):
        """'casa' => Hogar."""
        resp, matches = _extract_responsable("limpieza casa $25")
        self.assertEqual(resp, "Hogar")
        self.assertEqual(matches, ["Hogar"])
    
    def test_alias_proyecto_singular(self):
        """'proyecto' => Proyectos."""
        resp, matches = _extract_responsable("gasto proyecto $150")
        self.assertEqual(resp, "Proyectos")
        self.assertEqual(matches, ["Proyectos"])
    
    def test_alias_prota(self):
        """'prota' => eiProta."""
        resp, matches = _extract_responsable("prota software")
        self.assertEqual(resp, "eiProta")
        self.assertEqual(matches, ["eiProta"])
    
    # Ambiguity tests
    def test_ambiguous_two_responsables(self):
        """'Ana y yo' => ambiguous (Ana and Jorge)."""
        resp, matches = _extract_responsable("Ana y yo pagamos $30")
        # First found is returned but all are in matches
        self.assertIn(resp, ["Ana", "Jorge"])
        self.assertEqual(len(matches), 2)
        self.assertIn("Ana", matches)
        self.assertIn("Jorge", matches)


class TestExtractItbms(unittest.TestCase):
    """Tests para extracción de ITBMS."""
    
    def test_itbms_si(self):
        """'itbms si' => True, 7.0."""
        itbms, pct = _extract_itbms("pagué $50, itbms si")
        self.assertTrue(itbms)
        self.assertEqual(pct, 7.0)
    
    def test_con_itbms(self):
        """'con itbms' => True, 7.0."""
        itbms, pct = _extract_itbms("$50 con itbms")
        self.assertTrue(itbms)
        self.assertEqual(pct, 7.0)
    
    def test_itbms_percentage(self):
        """'itbms 10%' => True, 10.0."""
        itbms, pct = _extract_itbms("factura itbms 10%")
        self.assertTrue(itbms)
        self.assertEqual(pct, 10.0)
    
    def test_sin_itbms(self):
        """'sin itbms' => False, None."""
        itbms, pct = _extract_itbms("$50 sin itbms")
        self.assertFalse(itbms)
        self.assertIsNone(pct)
    
    def test_itbms_no(self):
        """'itbms no' => False, None."""
        itbms, pct = _extract_itbms("pago itbms no")
        self.assertFalse(itbms)
        self.assertIsNone(pct)
    
    def test_no_itbms_mention(self):
        """Sin mención => None, None (requiere confirmación)."""
        itbms, pct = _extract_itbms("pagué $50")
        self.assertIsNone(itbms)
        self.assertIsNone(pct)


class TestExtractCategoria(unittest.TestCase):
    """Tests para categorización automática - valores CANONICOS del dropdown."""
    
    def test_comida(self):
        """'cena' => Comida (canonical)."""
        cat = _extract_categoria("$50 cena")
        self.assertEqual(cat, "Comida")
    
    def test_restaurante(self):
        """'restaurante' => Comida."""
        cat = _extract_categoria("restaurante italiano")
        self.assertEqual(cat, "Comida")
    
    def test_supermercado(self):
        """'supermercado' => Comida (mapped in dropdown)."""
        cat = _extract_categoria("compras supermercado")
        self.assertEqual(cat, "Comida")
    
    def test_taxi(self):
        """'taxi' => Transporte."""
        cat = _extract_categoria("$10 taxi")
        self.assertEqual(cat, "Transporte")
    
    def test_uber(self):
        """'uber' => Transporte."""
        cat = _extract_categoria("uber al trabajo")
        self.assertEqual(cat, "Transporte")
    
    def test_software(self):
        """'software' => Software."""
        cat = _extract_categoria("licencia software")
        self.assertEqual(cat, "Software")
    
    def test_suscripcion(self):
        """'suscripción' => Software."""
        cat = _extract_categoria("suscripción mensual")
        self.assertEqual(cat, "Software")
    
    def test_otros(self):
        """Sin keyword => Otros."""
        cat = _extract_categoria("algo random")
        self.assertEqual(cat, "Otros")


class TestExtractDescripcion(unittest.TestCase):
    """Tests para extracción de descripción."""
    
    def test_removes_amount(self):
        """Quita el monto de la descripción."""
        desc = _extract_descripcion("$50 en cena")
        self.assertNotIn("$50", desc)
        self.assertIn("cena", desc)
    
    def test_removes_responsable(self):
        """Quita el responsable de la descripción."""
        desc = _extract_descripcion("$50 cena Ana")
        self.assertNotIn("Ana", desc.lower())
    
    def test_removes_itbms(self):
        """Quita ITBMS de la descripción."""
        desc = _extract_descripcion("$50 cena itbms si")
        self.assertNotIn("itbms", desc.lower())
    
    def test_removes_verb(self):
        """Quita verbos comunes."""
        desc = _extract_descripcion("pagué $50 en cena")
        self.assertNotIn("pagué", desc.lower())


class TestParseExpense(unittest.TestCase):
    """Tests para parse_expense completo."""
    
    def test_complete_expense(self):
        """Gasto completo: pagué $50 cena, Ana, itbms si."""
        req: ExpenseRequest = {"text": "pagué $50 cena, Ana, itbms si"}
        result = parse_expense(req)
        
        self.assertTrue(result["ok"])
        self.assertFalse(result["needs_confirmation"])
        self.assertEqual(result["missing_fields"], [])
        
        exp = result["expense"]
        assert exp is not None
        self.assertEqual(exp["monto"], 50.0)
        self.assertEqual(exp["moneda"], "USD")
        self.assertEqual(exp["responsable"], "Ana")
        self.assertTrue(exp["itbms"])
        self.assertEqual(exp["categoria"], "Comida")  # Canonical
    
    def test_balboa_expense(self):
        """B/. 12.35 supermercado hogar."""
        req: ExpenseRequest = {"text": "B/. 12.35 supermercado hogar"}
        result = parse_expense(req)
        
        self.assertTrue(result["ok"])
        # Note: needs_confirmation is True if itbms is None
        
        exp = result["expense"]
        assert exp is not None
        self.assertEqual(exp["monto"], 12.35)
        self.assertEqual(exp["moneda"], "PAB")
        self.assertEqual(exp["responsable"], "Hogar")
        self.assertEqual(exp["categoria"], "Comida")  # supermercado maps to Comida
    
    def test_missing_responsable(self):
        """Sin responsable => needs_confirmation."""
        req: ExpenseRequest = {"text": "$50 cena"}
        result = parse_expense(req)
        
        self.assertTrue(result["ok"])
        self.assertTrue(result["needs_confirmation"])
        self.assertIn("responsable", result["missing_fields"])
    
    def test_missing_monto(self):
        """Sin monto => needs_confirmation."""
        req: ExpenseRequest = {"text": "cena con Ana"}
        result = parse_expense(req)
        
        self.assertTrue(result["ok"])
        self.assertTrue(result["needs_confirmation"])
        self.assertIn("monto", result["missing_fields"])
    
    def test_override_responsable(self):
        """Override puede fijar responsable."""
        req: ExpenseRequest = {
            "text": "$50 cena itbms no",  # Add itbms to avoid missing field
            "override": {"responsable": "Jorge"}
        }
        result = parse_expense(req)
        
        self.assertTrue(result["ok"])
        self.assertFalse(result["needs_confirmation"])
        exp = result["expense"]
        assert exp is not None
        self.assertEqual(exp["responsable"], "Jorge")
    
    def test_empty_text(self):
        """Texto vacío => ok=False."""
        req: ExpenseRequest = {"text": ""}
        result = parse_expense(req)
        
        self.assertFalse(result["ok"])
        self.assertIn("text", result["missing_fields"])


class TestParseExpenseEndToEnd(unittest.TestCase):
    """Tests end-to-end con casos reales."""
    
    def test_user_story_1(self):
        """pagué $50 cena, Ana, itbms si => FIN correcto."""
        req: ExpenseRequest = {"text": "pagué $50 cena, Ana, itbms si"}
        result = parse_expense(req)
        
        self.assertTrue(result["ok"])
        exp = result["expense"]
        assert exp is not None
        self.assertEqual(exp["monto"], 50.0)
        self.assertEqual(exp["moneda"], "USD")
        self.assertEqual(exp["responsable"], "Ana")
        self.assertTrue(exp["itbms"])
    
    def test_user_story_2(self):
        """B/. 12.35 supermercado hogar => moneda PAB."""
        req: ExpenseRequest = {"text": "B/. 12.35 supermercado hogar"}
        result = parse_expense(req)
        
        self.assertTrue(result["ok"])
        exp = result["expense"]
        assert exp is not None
        self.assertEqual(exp["moneda"], "PAB")
        self.assertEqual(exp["monto"], 12.35)
        self.assertEqual(exp["responsable"], "Hogar")
    
    def test_user_story_3_complete_expense(self):
        """Complete expense with all fields: Compras del hogar B/. 15.00 supermercado Responsable Hogar ITBMS Sí Yappy."""
        req: ExpenseRequest = {
            "text": "Compras del hogar B/. 15.00 en supermercado. Responsable: Hogar. Moneda PAB. ITBMS: Sí. Método de Pago: Yappy."
        }
        result = parse_expense(req)
        
        self.assertTrue(result["ok"])
        self.assertFalse(result["needs_confirmation"])  # Should NOT need confirmation
        
        exp = result["expense"]
        assert exp is not None
        self.assertEqual(exp["monto"], 15.0)
        self.assertEqual(exp["moneda"], "PAB")
        self.assertEqual(exp["responsable"], "Hogar")
        self.assertTrue(exp["itbms"])
        self.assertEqual(exp["categoria"], "Comida")  # supermercado => Comida (canonical)
        # Verify fecha is a valid ISO date (YYYY-MM-DD format)
        self.assertRegex(exp["fecha"], r"^\d{4}-\d{2}-\d{2}$")


class TestITBMSParsing(unittest.TestCase):
    """Tests específicos para parsing de ITBMS con formatos variados."""
    
    def test_itbms_colon_si(self):
        """ITBMS: Sí => True."""
        itbms, _ = _extract_itbms("algo ITBMS: Sí")
        self.assertTrue(itbms)
    
    def test_itbms_colon_no(self):
        """ITBMS: No => False."""
        itbms, _ = _extract_itbms("algo ITBMS: No")
        self.assertFalse(itbms)
    
    def test_itbms_colon_no_with_period(self):
        """ITBMS: No. => False."""
        itbms, _ = _extract_itbms("algo ITBMS: No.")
        self.assertFalse(itbms)
    
    def test_case_insensitive_itbms_no(self):
        """itbms: no (lowercase) => False."""
        itbms, _ = _extract_itbms("itbms: no algo")
        self.assertFalse(itbms)
    
    def test_full_expense_itbms_no(self):
        """Full expense with ITBMS: No."""
        req: ExpenseRequest = {
            "text": "Gasto B/. 23.50 en farmacia. Responsable: Jorge. Moneda: PAB. ITBMS: No. Método: Tarjeta."
        }
        result = parse_expense(req)
        exp = result["expense"]
        assert exp is not None
        self.assertFalse(exp["itbms"], "ITBMS debería ser False con 'ITBMS: No'")
    
    def test_full_expense_itbms_si(self):
        """Full expense with ITBMS: Sí."""
        req: ExpenseRequest = {
            "text": "Compras del hogar B/. 15.00 en supermercado. Responsable: Hogar. Moneda PAB. ITBMS: Sí. Método de Pago: Yappy."
        }
        result = parse_expense(req)
        exp = result["expense"]
        assert exp is not None
        self.assertTrue(exp["itbms"], "ITBMS debería ser True con 'ITBMS: Sí'")


class TestMetodoPagoNormalization(unittest.TestCase):
    """Tests para normalización de método de pago - valores CANONICOS del dropdown."""
    
    def test_yappy_stays_yappy(self):
        """Yappy debe quedar como 'Yappy' (canonical)."""
        from assistant_os.fin_expense import _extract_metodo_pago
        metodo = _extract_metodo_pago("Pagué con Yappy")
        self.assertEqual(metodo, "Yappy")
    
    def test_nequi_maps_to_transferencia(self):
        """Nequi => Transferencia (dropdown doesn't have Nequi)."""
        from assistant_os.fin_expense import _extract_metodo_pago
        metodo = _extract_metodo_pago("Por Nequi")
        self.assertEqual(metodo, "Transferencia")
    
    def test_ach_maps_to_transferencia(self):
        """ACH => Transferencia (dropdown doesn't have ACH)."""
        from assistant_os.fin_expense import _extract_metodo_pago
        metodo = _extract_metodo_pago("Pago por ACH")
        self.assertEqual(metodo, "Transferencia")
    
    def test_efectivo(self):
        """Efectivo => Efectivo (canonical)."""
        from assistant_os.fin_expense import _extract_metodo_pago
        metodo = _extract_metodo_pago("Pago en efectivo")
        self.assertEqual(metodo, "Efectivo")
    
    def test_tarjeta_credito(self):
        """Tarjeta/crédito => Tarjeta."""
        from assistant_os.fin_expense import _extract_metodo_pago
        metodo = _extract_metodo_pago("Con tarjeta de crédito")
        self.assertEqual(metodo, "Tarjeta")
    
    def test_full_expense_yappy(self):
        """Full expense con Yappy => metodo_pago='Yappy'."""
        req: ExpenseRequest = {
            "text": "Compras B/. 15 supermercado. Responsable: Hogar. ITBMS: Sí. Método de Pago: Yappy."
        }
        result = parse_expense(req)
        exp = result["expense"]
        assert exp is not None
        self.assertEqual(exp["metodo_pago"], "Yappy", "Yappy debe quedar como 'Yappy'")


class TestDescripcionCleaning(unittest.TestCase):
    """Tests para limpieza de descripción."""
    
    def test_no_responsable_label(self):
        """Descripción no debe contener 'Responsable:'."""
        desc = _extract_descripcion("Gasto en farmacia. Responsable: Jorge. Moneda: PAB.")
        self.assertNotIn("Responsable:", desc)
        self.assertNotIn("responsable:", desc.lower())
    
    def test_no_moneda_label(self):
        """Descripción no debe contener 'Moneda:'."""
        desc = _extract_descripcion("Compra de víveres. Moneda: USD. ITBMS: No.")
        self.assertNotIn("Moneda:", desc)
        self.assertNotIn("moneda:", desc.lower())
    
    def test_no_itbms_label(self):
        """Descripción no debe contener 'ITBMS:'."""
        desc = _extract_descripcion("Taxi al trabajo. ITBMS: Sí. Método: Efectivo.")
        self.assertNotIn("ITBMS:", desc)
        self.assertNotIn("itbms:", desc.lower())
    
    def test_no_metodo_label(self):
        """Descripción no debe contener 'Método:'."""
        desc = _extract_descripcion("Almuerzo en restaurante. Método: Tarjeta.")
        self.assertNotIn("Método:", desc)
        self.assertNotIn("metodo:", desc.lower())
    
    def test_full_expense_clean_description(self):
        """Full expense debe tener descripción limpia."""
        req: ExpenseRequest = {
            "text": "Gasto B/. 23.50 en farmacia. Responsable: Jorge. Moneda: PAB. ITBMS: No. Método: Tarjeta."
        }
        result = parse_expense(req)
        exp = result["expense"]
        assert exp is not None
        desc = exp["descripcion"]
        # Should be clean, containing only the concept
        self.assertNotIn("Responsable:", desc)
        self.assertNotIn("Moneda:", desc)
        self.assertNotIn("ITBMS:", desc)
        self.assertNotIn("Método:", desc)
        # Should contain the actual expense concept
        self.assertIn("farmacia", desc.lower())


class TestMesCalculation(unittest.TestCase):
    """Tests para cálculo de mes (YYYY-MM)."""
    
    def test_mes_from_fecha(self):
        """Mes debe derivarse de fecha."""
        req: ExpenseRequest = {
            "text": "Gasto $50 en comida. Responsable: Jorge."
        }
        result = parse_expense(req)
        exp = result["expense"]
        assert exp is not None
        # Fecha should be today
        fecha = exp["fecha"]
        mes = exp["mes"]
        # Mes should be first 7 chars of fecha
        self.assertEqual(mes, fecha[:7])
        self.assertEqual(len(mes), 7)  # YYYY-MM
        self.assertIn("-", mes)


class TestMissingFieldsValidation(unittest.TestCase):
    """Tests para validación de campos faltantes."""
    
    def test_missing_responsable(self):
        """Falta responsable => needs_confirmation True."""
        req: ExpenseRequest = {"text": "Gasté $25 en comida"}
        result = parse_expense(req)
        
        self.assertTrue(result["needs_confirmation"])
        self.assertIn("responsable", result["missing_fields"])
        self.assertEqual(result["status"], "needs_confirmation")
    
    def test_missing_monto(self):
        """Falta monto => needs_confirmation True."""
        req: ExpenseRequest = {"text": "Comida para Jorge"}
        result = parse_expense(req)
        
        self.assertTrue(result["needs_confirmation"])
        self.assertIn("monto", result["missing_fields"])
    
    def test_complete_expense_no_confirmation(self):
        """Expense completo (con ITBMS especificado) => needs_confirmation False."""
        req: ExpenseRequest = {
            "text": "Gasté $50 en comida. Responsable: Jorge. ITBMS: No."
        }
        result = parse_expense(req)
        
        self.assertFalse(result["needs_confirmation"])
        self.assertEqual(len(result["missing_fields"]), 0)


class TestNewExpenseFields(unittest.TestCase):
    """Tests para nuevos campos de ParsedExpense."""
    
    def test_expense_has_mes_field(self):
        """ParsedExpense debe tener campo 'mes'."""
        req: ExpenseRequest = {"text": "Gasto $50 comida Jorge"}
        result = parse_expense(req)
        exp = result["expense"]
        assert exp is not None
        self.assertIn("mes", exp)
    
    def test_expense_has_factura_field(self):
        """ParsedExpense debe tener campo 'factura' (vacío por defecto)."""
        req: ExpenseRequest = {"text": "Gasto $50 comida Jorge"}
        result = parse_expense(req)
        exp = result["expense"]
        assert exp is not None
        self.assertIn("factura", exp)
        self.assertEqual(exp["factura"], "")
    
    def test_expense_has_fuente_field(self):
        """ParsedExpense debe tener campo 'fuente' = 'chat'."""
        req: ExpenseRequest = {"text": "Gasto $50 comida Jorge"}
        result = parse_expense(req)
        exp = result["expense"]
        assert exp is not None
        self.assertIn("fuente", exp)
        self.assertEqual(exp["fuente"], "chat")
    
    def test_expense_has_link_archivo_field(self):
        """ParsedExpense debe tener campo 'link_archivo' (vacío)."""
        req: ExpenseRequest = {"text": "Gasto $50 comida Jorge"}
        result = parse_expense(req)
        exp = result["expense"]
        assert exp is not None
        self.assertIn("link_archivo", exp)
        self.assertEqual(exp["link_archivo"], "")


class TestResponseFields(unittest.TestCase):
    """Tests para campos de ExpenseResponse."""
    
    def test_response_has_stored_field(self):
        """ExpenseResponse debe tener campo 'stored'."""
        req: ExpenseRequest = {"text": "Gasto $50 comida Jorge"}
        result = parse_expense(req)
        self.assertIn("stored", result)
    
    def test_response_has_status_field(self):
        """ExpenseResponse debe tener campo 'status'."""
        req: ExpenseRequest = {"text": "Gasto $50 comida Jorge"}
        result = parse_expense(req)
        self.assertIn("status", result)
    
    def test_response_has_sheets_available_field(self):
        """ExpenseResponse debe tener campo 'sheets_available'."""
        req: ExpenseRequest = {"text": "Gasto $50 comida Jorge"}
        result = parse_expense(req)
        self.assertIn("sheets_available", result)
    
    def test_response_has_row_number_field(self):
        """ExpenseResponse debe tener campo 'row_number'."""
        req: ExpenseRequest = {"text": "Gasto $50 comida Jorge"}
        result = parse_expense(req)
        self.assertIn("row_number", result)
    
    def test_response_has_tab_name_field(self):
        """ExpenseResponse debe tener campo 'tab_name'."""
        req: ExpenseRequest = {"text": "Gasto $50 comida Jorge"}
        result = parse_expense(req)
        self.assertIn("tab_name", result)


class TestDropdownNormalization(unittest.TestCase):
    """Tests para normalización a valores EXACTOS del dropdown de Google Sheets.
    
    Dropdowns:
    - Responsable: Ana, Conejos, Jorge, eiProta, Proyectos, Hogar
    - Categoría: Comida, Transporte, Software, Salud, Hogar, Mascotas, Educación, Servicios, Entretenimiento, Otros
    - Método de Pago: Efectivo, Tarjeta, Transferencia, Yappy, Otro
    """
    
    def test_responsable_hogar_lowercase(self):
        """'responsable: hogar' => 'Hogar' (canonical)."""
        req: ExpenseRequest = {"text": "$50 gasto Responsable: hogar ITBMS: No"}
        result = parse_expense(req)
        exp = result["expense"]
        assert exp is not None
        self.assertEqual(exp["responsable"], "Hogar")
    
    def test_responsable_jorge_case_insensitive(self):
        """'JORGE' => 'Jorge'."""
        req: ExpenseRequest = {"text": "$50 cena JORGE ITBMS: Si"}
        result = parse_expense(req)
        exp = result["expense"]
        assert exp is not None
        self.assertEqual(exp["responsable"], "Jorge")
    
    def test_metodo_yappy_canonical(self):
        """'metodo: yappy' => 'Yappy'."""
        from assistant_os.fin_expense import _extract_metodo_pago
        metodo = _extract_metodo_pago("pagué con yappy")
        self.assertEqual(metodo, "Yappy")
    
    def test_categoria_supermercado_to_comida(self):
        """'supermercado' => 'Comida' (dropdown mapping)."""
        cat = _extract_categoria("compras en supermercado")
        self.assertEqual(cat, "Comida")
    
    def test_categoria_farmacia_to_salud(self):
        """'farmacia' => 'Salud'."""
        cat = _extract_categoria("gasto farmacia")
        self.assertEqual(cat, "Salud")
    
    def test_itbms_no_explicit(self):
        """'ITBMS: No' => itbms=False."""
        itbms, _ = _extract_itbms("algo ITBMS: No")
        self.assertFalse(itbms)
    
    def test_itbms_sin_to_false(self):
        """'sin itbms' => itbms=False."""
        itbms, _ = _extract_itbms("gasto sin itbms")
        self.assertFalse(itbms)
    
    def test_itbms_missing_triggers_confirmation(self):
        """Si no menciona ITBMS => needs_confirmation=True, 'itbms' in missing_fields."""
        req: ExpenseRequest = {"text": "$50 cena Jorge"}
        result = parse_expense(req)
        
        self.assertTrue(result["needs_confirmation"])
        self.assertIn("itbms", result["missing_fields"])
    
    def test_unknown_responsable_blocks_storage(self):
        """Responsable desconocido => needs_confirmation=True, no se escribe a sheets."""
        req: ExpenseRequest = {"text": "$50 cena Responsable: PedroPicaPiedra ITBMS: No"}
        result = parse_expense(req)
        
        self.assertTrue(result["needs_confirmation"])
        self.assertIn("responsable", result["missing_fields"])
        self.assertFalse(result["stored"])  # No debe escribirse
    
    def test_full_canonical_expense(self):
        """Gasto completo con todos los campos canonizados correctamente."""
        req: ExpenseRequest = {
            "text": "B/. 25.50 supermercado. Responsable: hogar. ITBMS: Sí. Método: yappy."
        }
        result = parse_expense(req)
        
        self.assertFalse(result["needs_confirmation"])
        exp = result["expense"]
        assert exp is not None
        self.assertEqual(exp["responsable"], "Hogar")
        self.assertEqual(exp["categoria"], "Comida")
        self.assertEqual(exp["metodo_pago"], "Yappy")
        self.assertTrue(exp["itbms"])


if __name__ == "__main__":
    unittest.main()
